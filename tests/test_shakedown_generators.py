import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))

from argoslive import ability
from argoslive.shakedown import diagnose, fault
from argoslive.shakedown import generators


def choice_generator(seed, tier):
    """Small deterministic test generator with a distinct planted wrong answer."""
    offset = int(hashlib.sha256(seed.encode('utf-8')).hexdigest()[:2], 16) % 4
    choices = 'ABCD'
    expected = choices[offset]
    wrong = choices[(offset + 1) % len(choices)]
    return ({'id': 'generator-must-not-choose-id',
             'prompt': f'Choose the supported record for sample {seed}.',
             'scorer': {'kind': 'choice', 'expected': expected},
             'reference': expected, 'wrong': wrong, 'malformed': 'Record ' + expected + '.'},
            {'item': 'generator-must-not-choose-item', 'partition': 'sealed',
             'family': 'altered-record', 'console': 'evidence',
             'tier': 3,
             'display': {'family': 'Altered record', 'brief': 'A test record has one changed value.'},
             'diagnostics': [{'code': 'evidence.wrong-source', 'when': {'choice-is': wrong}}]})


def recipe(rows=None):
    return {'schema': generators.SCHEMA, 'suite': 'relay-check', 'version': '1.0.0',
            'items': rows if rows is not None else [
                {'generator': 'test-choice', 'seed': 'sample-a', 'tier': 1, 'partition': 'practice'},
                {'generator': 'test-choice', 'seed': 'sample-b', 'tier': 2, 'partition': 'sealed'}]}


class ShakedownGeneratorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = 'test-choice'
        generators.register(cls.name, '1.2.3', choice_generator)

    @classmethod
    def tearDownClass(cls):
        generators.GENERATORS.pop(cls.name, None)

    def test_registered_names_are_sorted_and_duplicate_registration_is_refused(self):
        self.assertEqual(tuple(sorted(generators.names())), generators.names())
        with self.assertRaisesRegex(ValueError, 'already registered'):
            generators.register(self.name, '1.2.4', choice_generator)

    def test_registration_rejects_invalid_names_versions_and_functions(self):
        for args in (("Bad Name", '1.0.0', choice_generator),
                     ('bad-name', '1', choice_generator),
                     ('bad-name', '1.0.0', None)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                generators.register(*args)

    def test_generate_returns_detached_data_and_records_generator_identity(self):
        item, card = generators.generate(self.name, 'sample-a', 2)
        self.assertEqual(item['id'] if 'id' in item else None, None)
        self.assertEqual(card['generator'], {'name': self.name, 'version': '1.2.3', 'seed': 'sample-a'})
        self.assertNotIn('item', card)
        self.assertNotIn('partition', card)
        item['prompt'] = 'changed by caller'
        card['display']['brief'] = 'changed by caller'
        again_item, again_card = generators.generate(self.name, 'sample-a', 2)
        self.assertIn('sample-a', again_item['prompt'])
        self.assertIn('test record', again_card['display']['brief'])

    def test_generate_rejects_unhashable_or_invalid_names_seeds_and_tiers(self):
        for name, seed, tier in (([], 'x', 1), ('Bad Name', 'x', 1),
                                 (self.name, '', 1), (self.name, ' x ', 1),
                                 (self.name, 'x' * 129, 1), (self.name, 'x', True),
                                 (self.name, 'x', 4)):
            with self.subTest(name=name, seed=seed, tier=tier), self.assertRaises(ValueError):
                generators.generate(name, seed, tier)

    def test_generate_rejects_unknown_generator_and_nondeterministic_output(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            generators.generate('missing', 'seed', 1)

        count = 0
        def flaky(seed, tier):
            nonlocal count
            count += 1
            item, card = choice_generator(seed + str(count), tier)
            return item, card

        generators.register('flaky', '1.0.0', flaky)
        try:
            with self.assertRaisesRegex(ValueError, 'not deterministic'):
                generators.generate('flaky', 'seed', 1)
        finally:
            generators.GENERATORS.pop('flaky', None)

    def test_generate_rejects_bad_return_shapes(self):
        generators.register('bad-shape', '1.0.0', lambda seed, tier: [None, None])
        try:
            with self.assertRaisesRegex(ValueError, 'must return'):
                generators.generate('bad-shape', 'seed', 1)
        finally:
            generators.GENERATORS.pop('bad-shape', None)

    def test_recipe_assigns_ids_partitions_and_tiers_over_generator_values(self):
        form, sidecar = generators.build_form(recipe())
        self.assertEqual([item['id'] for item in form['items']], ['practice-01', 'heldout-02'])
        self.assertEqual([card['item'] for card in sidecar['cards']], ['practice-01', 'heldout-02'])
        self.assertEqual([card['partition'] for card in sidecar['cards']], ['practice', 'sealed'])
        self.assertEqual([card['tier'] for card in sidecar['cards']], [1, 2])
        self.assertEqual([card['generator']['seed'] for card in sidecar['cards']], ['sample-a', 'sample-b'])
        fault.validate(sidecar, form)

    def test_seeded_output_scores_reference_wrong_and_malformed_and_routes_diagnosis(self):
        form, sidecar = generators.build_form(recipe())
        cards = {card['item']: card for card in sidecar['cards']}
        for item in form['items']:
            card = cards[item['id']]
            self.assertEqual(ability.score(item, item['reference'])['outcome'], 'pass')
            self.assertEqual(ability.score(item, item['wrong'])['outcome'], 'wrong_answer')
            self.assertEqual(ability.score(item, item['malformed'])['outcome'], 'format_error')
            self.assertEqual(diagnose.diagnose(card, item, {'outcome': 'wrong_answer', 'output': item['wrong']}),
                             ['evidence.wrong-source'])
            self.assertEqual(diagnose.diagnose(card, item, {'outcome': 'pass', 'output': item['wrong']}), [])

    def test_two_hundred_seeds_across_all_tiers_remain_valid_and_reproducible(self):
        rows = [{'generator': self.name, 'seed': f'seed-{index:03d}', 'tier': index % 3 + 1,
                 'partition': 'practice' if index % 2 == 0 else 'sealed'}
                for index in range(200)]
        form, sidecar = generators.build_form(recipe(rows))
        again, again_sidecar = generators.build_form(recipe(rows))
        self.assertEqual(generators._json_bytes(form), generators._json_bytes(again))
        self.assertEqual(generators._json_bytes(sidecar), generators._json_bytes(again_sidecar))
        self.assertEqual(len(form['items']), 200)
        fault.validate(sidecar, form)

    def test_build_bytes_has_stable_serialization_and_hashes(self):
        built = generators.build_bytes(recipe())
        repeated = generators.build_bytes(recipe())
        self.assertEqual(built, repeated)
        self.assertEqual(hashlib.sha256(built['form']).hexdigest(), built['form_sha256'])
        self.assertEqual(hashlib.sha256(built['sidecar']).hexdigest(), built['sidecar_sha256'])
        self.assertTrue(built['form'].endswith(b'\n'))
        self.assertTrue(built['sidecar'].endswith(b'\n'))

    def test_recipe_rejects_unknown_fields_empty_lists_bad_rows_and_bad_values(self):
        bad = []
        extra = recipe(); extra['extra'] = True; bad.append(extra)
        missing = recipe(); del missing['version']; bad.append(missing)
        for update in ({'tier': True}, {'tier': 4}, {'partition': 'heldout'},
                       {'seed': ''}, {'seed': ' x '}, {'seed': 'x' * 129},
                       {'generator': 'Bad Name'}):
            row = recipe()['items'][0] | update
            bad.append(recipe([row]))
        bad.extend((recipe([]), recipe([None])))
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                generators.build_form(value)

    def test_invalid_scorer_fixtures_and_unclassified_wrong_answers_are_rejected(self):
        def wrong_reference(seed, tier):
            item, card = choice_generator(seed, tier)
            item['reference'] = item['wrong']
            return item, card
        generators.register('wrong-reference', '1.0.0', wrong_reference)
        try:
            rows = [{'generator': 'wrong-reference', 'seed': 'bad', 'tier': 1, 'partition': 'practice'}]
            with self.assertRaisesRegex(ValueError, 'invalid reference fixture'):
                generators.build_form(recipe(rows))
        finally:
            generators.GENERATORS.pop('wrong-reference', None)

        def unmatched(seed, tier):
            item, card = choice_generator(seed, tier)
            card['diagnostics'] = []
            return item, card
        generators.register('unmatched', '1.0.0', unmatched)
        try:
            rows = [{'generator': 'unmatched', 'seed': 'bad', 'tier': 1, 'partition': 'practice'}]
            with self.assertRaisesRegex(ValueError, 'wrong fixture'):
                generators.build_form(recipe(rows))
        finally:
            generators.GENERATORS.pop('unmatched', None)

    def test_builder_cli_output_and_check_mode_compare_exact_bytes(self):
        script_path = ROOT / 'scripts' / 'shakedown-build-form.py'
        spec = importlib.util.spec_from_file_location('shakedown_build_form', script_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe_path = root / 'recipe.json'
            recipe_path.write_text(json.dumps(recipe()), encoding='utf-8')
            output = root / 'built'
            original_root = builder.ROOT
            builder.ROOT = root
            try:
                with mock.patch.object(sys, 'argv', ['shakedown-build-form.py', '--recipe', str(recipe_path),
                                                      '--output-dir', str(output)]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(builder.main(), 0)
                expected_form = output / 'relay-check-1.0.0.json'
                expected_sidecar = output / 'relay-check-1.0.0.sidecar.json'
                form_path = root / 'runtime/argoslive/data/ability/relay-check-1.0.0.json'
                sidecar_path = root / 'runtime/argoslive/data/shakedown/sidecars/relay-check-1.0.0.json'
                form_path.parent.mkdir(parents=True)
                sidecar_path.parent.mkdir(parents=True)
                form_path.write_bytes(expected_form.read_bytes())
                sidecar_path.write_bytes(expected_sidecar.read_bytes())
                with mock.patch.object(sys, 'argv', ['shakedown-build-form.py', '--recipe', str(recipe_path),
                                                      '--check']), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(builder.main(), 0)
                sidecar_path.write_text('{}', encoding='utf-8')
                with mock.patch.object(sys, 'argv', ['shakedown-build-form.py', '--recipe', str(recipe_path),
                                                      '--check']), \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(builder.main(), 2)
            finally:
                builder.ROOT = original_root


if __name__ == '__main__':
    unittest.main()
