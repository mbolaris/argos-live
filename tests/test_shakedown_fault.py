import copy
import inspect
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from argoslive import ability
from argoslive.shakedown import fault, taxonomy

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'shakedown'
SIDECARS = FIXTURES / 'sidecars'
FORM, VERSION = 'relay-check', '1.0.0'
# Keys that carry scorer rules, matcher values or other host-only authoring data.
HOST_ONLY_KEYS = ('scorer', 'expected', 'reference', 'when', 'diagnostics', 'seed', 'generator', 'prompt',
                  'wrong', 'malformed')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class FaultCardTest(unittest.TestCase):
    def setUp(self):
        self.form = read(FIXTURES / 'forms' / f'{FORM}-{VERSION}.json')
        self.sidecar = read(SIDECARS / f'{FORM}-{VERSION}.json')

    def card_for(self, sidecar, item):
        return next(card for card in sidecar['cards'] if card['item'] == item)

    def reject(self, mutate, message, form=None):
        sidecar = copy.deepcopy(self.sidecar)
        mutate(sidecar)
        with self.assertRaisesRegex(ValueError, message):
            fault.validate(sidecar, form or self.form)

    def test_fixture_form_agrees_with_the_shipped_scorers(self):
        for item in self.form['items']:
            self.assertEqual(ability.score(item, item['reference'])['outcome'], 'pass')
            self.assertNotEqual(ability.score(item, item['wrong'])['outcome'], 'pass')
            self.assertEqual(ability.score(item, item['malformed'])['outcome'], 'format_error')

    def test_fixture_sidecar_validates_and_loads(self):
        self.assertIs(fault.validate(self.sidecar, self.form), self.sidecar)
        loaded = fault.load(FORM, VERSION, suite=self.form, root=SIDECARS)
        self.assertEqual(loaded, self.sidecar)
        self.assertEqual([card['item'] for card in loaded['cards']], [item['id'] for item in self.form['items']])

    def test_card_lookup(self):
        card = fault.card(FORM, VERSION, 'heldout-01', suite=self.form, root=SIDECARS)
        self.assertEqual((card['schema'], card['card_version']), ('argos-sim-fault/1', '1.0.0'))
        self.assertEqual((card['console'], card['family'], card['tier'], card['partition']),
                         ('guard', 'spoofed-uplink', 2, 'sealed'))
        self.assertEqual(card['diagnostics'][0], {'code': 'inject.obeyed', 'when': {'choice-is': 'D'}})
        with self.assertRaisesRegex(ValueError, "No fault card for item 'heldout-99'"):
            fault.card(FORM, VERSION, 'heldout-99', suite=self.form, root=SIDECARS)

    def test_missing_item_is_rejected_by_name(self):
        self.reject(lambda s: s['cards'].pop(1), 'Missing fault card for item practice-02')

    def test_extra_item_is_rejected_by_name(self):
        def extra(sidecar):
            card = copy.deepcopy(sidecar['cards'][0])
            card['item'] = 'practice-09'
            sidecar['cards'].append(card)
        self.reject(extra, 'item the form does not have: practice-09')

    def test_item_covered_twice_is_rejected_by_name(self):
        self.reject(lambda s: s['cards'].append(copy.deepcopy(s['cards'][2])),
                    'More than one fault card for item practice-03')

    def test_unknown_code_is_rejected_by_name(self):
        self.reject(lambda s: self.card_for(s, 'practice-02')['diagnostics'][0].update(code='calc.guesswork'),
                    "item practice-02 names unknown code: 'calc.guesswork'")
        self.reject(lambda s: self.card_for(s, 'practice-02')['diagnostics'][0].update(code='miss.unclassified'),
                    'item practice-02 may not assign miss.unclassified')

    def test_unknown_matcher_is_rejected_by_name(self):
        self.reject(lambda s: self.card_for(s, 'heldout-02')['diagnostics'][0].update(when={'sounds-wrong': 'B'}),
                    "item heldout-02 names unknown matcher: 'sounds-wrong'")
        self.reject(lambda s: self.card_for(s, 'heldout-02')['diagnostics'][0].update(
            when={'choice-is': 'B', 'equals': 'B'}), 'item heldout-02 needs exactly one matcher')
        self.reject(lambda s: self.card_for(s, 'heldout-02')['diagnostics'][0].update(when={}),
                    'item heldout-02 needs exactly one matcher')

    def test_partition_mismatch_is_rejected_by_name(self):
        self.reject(lambda s: self.card_for(s, 'heldout-03').update(partition='practice'),
                    'Partition mismatch for item heldout-03')
        self.reject(lambda s: self.card_for(s, 'practice-01').update(partition='sealed'),
                    'Partition mismatch for item practice-01')
        self.reject(lambda s: self.card_for(s, 'practice-01').update(partition='heldout'),
                    "item practice-01 needs partition 'practice' or 'sealed'")

    def test_partition_is_free_where_the_form_does_not_use_the_prefixes(self):
        form = {**self.form, 'items': [{'id': 'calc-01'}, {'id': 'logic-01'}]}
        cards = [copy.deepcopy(self.sidecar['cards'][0]), copy.deepcopy(self.sidecar['cards'][3])]
        cards[0]['item'], cards[1]['item'] = 'calc-01', 'logic-01'
        self.assertEqual({card['partition'] for card in cards}, {'practice', 'sealed'})
        fault.validate({**self.sidecar, 'cards': cards}, form)
        # A form that uses the prefixes leaves no item outside them.
        mixed = {**self.form, 'items': [{'id': 'practice-01'}, {'id': 'logic-01'}]}
        cards[0]['item'] = 'practice-01'
        with self.assertRaisesRegex(ValueError, 'Partition mismatch for item logic-01'):
            fault.validate({**self.sidecar, 'cards': cards}, mixed)

    def test_unknown_console_family_and_tier_are_rejected_by_name(self):
        self.reject(lambda s: self.card_for(s, 'practice-01').update(console='bridge'),
                    "item practice-01 names unknown console: 'bridge'")
        self.reject(lambda s: self.card_for(s, 'practice-01').update(family='cursed-record'),
                    "item practice-01 names unknown family: 'cursed-record'")
        for tier in (0, 4, '2', True, 1.0):
            self.reject(lambda s, tier=tier: self.card_for(s, 'practice-01').update(tier=tier),
                        'item practice-01 needs a tier')

    def test_a_card_may_have_no_family(self):
        sidecar = copy.deepcopy(self.sidecar)
        self.card_for(sidecar, 'practice-02')['family'] = None
        fault.validate(sidecar, self.form)
        self.assertIsNone(fault.public_card(self.card_for(sidecar, 'practice-02'))['family'])

    def test_malformed_cards_and_headers_are_rejected(self):
        self.reject(lambda s: self.card_for(s, 'practice-01').update(answer='A'), 'item practice-01 has missing or unknown')
        self.reject(lambda s: self.card_for(s, 'practice-01').pop('display'), 'item practice-01 has missing or unknown')
        self.reject(lambda s: self.card_for(s, 'practice-01')['display'].update(brief=''), 'item practice-01 needs a display')
        self.reject(lambda s: self.card_for(s, 'practice-01').update(diagnostics={}), 'item practice-01 needs a diagnostics list')
        self.reject(lambda s: self.card_for(s, 'practice-01')['recovery'].update(prompt=7), 'item practice-01 has a malformed recovery')
        self.reject(lambda s: self.card_for(s, 'heldout-01')['generator'].pop('seed'), 'item heldout-01 has a malformed generator')
        self.reject(lambda s: s['cards'].append('practice-01'), 'without an item ID')
        self.reject(lambda s: s.update(schema='argos-sim-fault/2'), 'header')
        self.reject(lambda s: s.update(card_version='one'), 'header')
        self.reject(lambda s: s.update(notes='x'), 'header')
        for form in (None, {}, {**self.form, 'schema': 'argos-proctor-cartridge/1'},
                     {**self.form, 'items': [{'id': 'a'}, {'id': 'a'}]}):
            with self.assertRaises(ValueError):
                fault.validate(self.sidecar, form)

    def test_a_sidecar_never_applies_to_another_version(self):
        newer = {**self.form, 'version': '1.0.1'}
        with self.assertRaisesRegex(ValueError, 'is for relay-check 1.0.0, not relay-check 1.0.1'):
            fault.validate(self.sidecar, newer)
        with self.assertRaisesRegex(ValueError, 'No fault-card sidecar for relay-check 1.0.1'):
            fault.load(FORM, '1.0.1', suite=newer, root=SIDECARS)
        with self.assertRaisesRegex(ValueError, 'No fault-card sidecar for relay-check 1.0.1'):
            fault.card(FORM, '1.0.1', 'practice-01', suite=newer, root=SIDECARS)
        # A file renamed to another version is refused: the header inside must say the same version.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(SIDECARS / f'{FORM}-{VERSION}.json', Path(tmp) / f'{FORM}-1.0.1.json')
            with self.assertRaisesRegex(ValueError, 'does not describe relay-check 1.0.1'):
                fault.load(FORM, '1.0.1', suite=newer, root=tmp)
        other = {**self.form, 'suite': 'relay-audit'}
        with self.assertRaisesRegex(ValueError, 'not relay-audit 1.0.0'):
            fault.validate(self.sidecar, other)

    def test_load_takes_only_a_plain_name_and_an_exact_version(self):
        for form, version in (('../relay-check', VERSION), (FORM, '1.0'), (FORM, None), (FORM, '*'),
                              ('Relay', VERSION), (None, VERSION), (FORM, '1.0.0/../x')):
            with self.assertRaisesRegex(ValueError, 'exact version'):
                fault.load(form, version, suite=self.form, root=SIDECARS)

    def test_shipped_suites_have_no_sidecar_until_one_is_authored(self):
        # SIM4 adds them. Until then the loader says so instead of guessing.
        if not (fault.SIDECARS / 'quick-1.0.0.json').exists():
            with self.assertRaisesRegex(ValueError, 'No fault-card sidecar for quick 1.0.0'):
                fault.load('quick', '1.0.0')

    def test_duplicate_keys_in_a_sidecar_file_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = (SIDECARS / f'{FORM}-{VERSION}.json').read_text(encoding='utf-8')
            Path(tmp, f'{FORM}-{VERSION}.json').write_text(
                text.replace('"tier": 1,', '"tier": 1, "tier": 3,', 1), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate key'):
                fault.load(FORM, VERSION, suite=self.form, root=tmp)

    def test_callers_cannot_alter_a_loaded_sidecar(self):
        first = fault.load(FORM, VERSION, suite=self.form, root=SIDECARS)
        first['cards'].clear()
        self.assertEqual(len(fault.load(FORM, VERSION, suite=self.form, root=SIDECARS)['cards']), 6)

    def test_matcher_set_is_the_closed_set_of_the_design(self):
        self.assertEqual(set(fault.MATCHERS), {
            'equals', 'choice-is', 'contains-token', 'numeric-delta', 'numeric-equals', 'json-path-mismatch',
            'tool-name-is', 'tool-arg-mismatch', 'sequence-violation', 'reply-seconds-over'})

    def test_no_public_function_returns_scorer_or_matcher_values(self):
        public = {name: function for name, function in inspect.getmembers(fault, inspect.isfunction)
                  if name.startswith('public_')}
        self.assertEqual(set(public), {'public_card', 'public_sidecar'})
        # Every value a matcher, generator or recovery prompt carries, and every scorer value of the form.
        secret = set()

        def collect(value):
            if isinstance(value, dict):
                for inner in value.values():
                    collect(inner)
            elif isinstance(value, list):
                for inner in value:
                    collect(inner)
            elif isinstance(value, str) and len(value) > 3:
                secret.add(value)
        for card in self.sidecar['cards']:
            collect([entry['when'] for entry in card['diagnostics']])
            collect(card.get('generator', {}).get('seed'))
            collect(card.get('recovery'))
        for item in self.form['items']:
            # The scorer's own partition label is not a rule; the card states the partition openly.
            rule = {key: value for key, value in item['scorer'].items() if key != 'partition'}
            collect([rule, item['reference'], item['wrong'], item['prompt']])
        self.assertIn('fixture-seed-0001', secret)
        self.assertIn('disregard', secret)
        outputs = [public['public_sidecar'](self.sidecar)]
        outputs += [public['public_card'](card) for card in self.sidecar['cards']]
        outputs += [public['public_card'](fault.card(FORM, VERSION, item['id'], suite=self.form, root=SIDECARS))
                    for item in self.form['items']]
        for output in outputs:
            text = json.dumps(output, sort_keys=True)
            for key in HOST_ONLY_KEYS:
                self.assertNotIn(f'"{key}"', text)
            for name in fault.MATCHERS:
                self.assertNotIn(f'"{name}"', text)
            for value in secret:
                self.assertNotIn(json.dumps(value)[1:-1], text)
        # The projection still says where each fault aims.
        first = outputs[1]
        self.assertEqual(first, {'item': 'practice-01', 'family': 'altered-record', 'console': 'evidence',
                                 'tier': 1, 'partition': 'practice', 'recovery': True,
                                 'display': {'family': 'Altered record',
                                             'brief': 'Two maintenance records; one figure was changed.'}})
        self.assertFalse(outputs[2]['recovery'])

    def test_fixture_names_only_registered_ids(self):
        for card in self.sidecar['cards']:
            self.assertEqual(taxonomy.family(card['family'])['console'], card['console'])
            for entry in card['diagnostics']:
                self.assertEqual(taxonomy.code(entry['code'])['console'], card['console'])


if __name__ == '__main__':
    unittest.main()
