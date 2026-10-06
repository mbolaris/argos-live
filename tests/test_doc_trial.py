import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import doc_trial as dt, results
from test_bench_speed import Backend


class DocBackend(Backend):
    """Answers each prompt from the suite's own reference, wrong or malformed fixtures."""
    def __init__(self, mode='reference', **kwargs):
        super().__init__(**kwargs)
        self.mode = mode
        self.answers = {item['prompt']: item for item in dt.load()['items']}

    def generate(self, model, prompt, **kwargs):
        result = super().generate(model, prompt, **kwargs)
        if prompt in self.answers:
            item = self.answers[prompt]
            result['text'] = ('A short summary.' if not item['scored'] else
                              item[self.mode] if isinstance(self.mode, str) else self.mode(item))
        return result


def run(backend, **kwargs):
    return dt.run(backend, 'fixture:latest', hardware=lambda: {}, **kwargs)


class SuiteTests(unittest.TestCase):
    def test_suite_loads_and_every_fixture_matches_its_scorer(self):
        data = dt.load()
        self.assertEqual(data['version'], '1.0.0')
        counts = {c: sum(1 for i in data['items'] if i['category'] == c) for c in (*dt.CATEGORIES, 'summary')}
        self.assertEqual(counts, {'answer': 8, 'quote': 8, 'not_stated': 8, 'summary': 8})
        self.assertEqual(data['omitted_categories'], ['long-documents', 'file-reading'])

    def test_checked_in_suite_matches_the_generator(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build-document-suite.py')],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = subprocess.run(['git', 'diff', '--quiet', '--', 'runtime/argoslive/data/documents/short.json'],
                                cwd=ROOT)
        self.assertEqual(status.returncode, 0, 'Regenerating the suite changed it; bump the suite version')

    def test_prompts_fit_the_tested_context_with_room_to_answer(self):
        # Four characters per token is a coarse upper bound for English; the suite uses far less.
        longest = max(len(i['prompt']) for i in dt.load()['items'])
        self.assertLess(longest / 3, dt.CONTEXT / 2)

    def test_invalid_suites_are_rejected(self):
        base = dt.load()
        def mutated(change):
            data = copy.deepcopy(base)
            change(data)
            with self.assertRaises(ValueError):
                dt.validate(data)
        mutated(lambda d: d['criteria']['min_correct'].update(answer=99))
        mutated(lambda d: d['criteria']['min_correct'].pop('quote'))
        mutated(lambda d: d.update(context=2048))
        mutated(lambda d: d['items'][1]['scorer'].update(reference_quote='Not in the passage at all.'))
        mutated(lambda d: d['items'][0]['scorer'].update(accepted=['']))
        mutated(lambda d: d['items'][0].update(reference='{"status": "answered", "answer": "no", "quote": ""}'))
        mutated(lambda d: d['items'].pop())
        mutated(lambda d: d['items'][0].update(id=d['items'][1]['id']))


class ScorerTests(unittest.TestCase):
    def setUp(self):
        self.items = {i['id']: i for i in dt.load()['items']}

    def outcome(self, item_id, text):
        return dt.score(self.items[item_id], text)['outcome']

    def test_answer_accepts_listed_variants_and_fenced_json(self):
        item = self.items['answer-01']
        self.assertEqual(self.outcome('answer-01', dt.reply('answered', '240 passengers')), 'pass')
        self.assertEqual(self.outcome('answer-01', '```json\n' + dt.reply('answered', ' 240. ') + '\n```'), 'pass')
        self.assertEqual(self.outcome('answer-01', dt.reply('answered', '180')), 'wrong_answer')
        self.assertEqual(self.outcome('answer-01', dt.reply('not_stated')), 'wrong_answer')
        self.assertTrue(item['scored'])

    def test_quote_must_be_verbatim_short_and_contain_the_answer(self):
        rule = self.items['quote-01']['scorer']
        good = rule['reference_quote']
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '35 minutes', good)), 'pass')
        # Whitespace differences are tolerated; wording changes are not.
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '35 minutes', good.replace(' ', '  '))), 'pass')
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '35 minutes', 'Crossings last 35 minutes.')), 'wrong_answer')
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '35 minutes', '')), 'wrong_answer')
        # A real sentence that does not support the answer is not supporting evidence.
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '35 minutes',
                         'The Marigold carries up to 240 passengers and 18 cars, while the Heron carries 180 passengers and no cars.')),
                         'wrong_answer')
        # Copying the whole passage is not a supporting quotation.
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '35 minutes', rule['passage'])), 'wrong_answer')
        # A right quote with a wrong answer still fails.
        self.assertEqual(self.outcome('quote-01', dt.reply('answered', '45 minutes', good)), 'wrong_answer')

    def test_not_stated_requires_status_and_empty_fields(self):
        self.assertEqual(self.outcome('missing-01', dt.reply('not_stated')), 'pass')
        self.assertEqual(self.outcome('missing-01', dt.reply('answered', '$4')), 'wrong_answer')
        self.assertEqual(self.outcome('missing-01', dt.reply('not_stated', 'maybe $4')), 'wrong_answer')

    def test_format_errors_are_separate_from_wrong_answers(self):
        for text in ('plain prose', '{"status": "answered"}', '{"status": "maybe", "answer": "", "quote": ""}',
                     '{"status": "answered", "answer": 240, "quote": ""}',
                     '{"status": "answered", "answer": "240", "answer": "240", "quote": ""}',
                     '{"status": "answered", "answer": "240", "quote": "", "extra": 1}', '', '[]', 'x' * 70000):
            self.assertEqual(self.outcome('answer-01', text), 'format_error', text[:40])
        self.assertIsNone(dt.score(self.items['summary-01'], 'anything'))
        self.assertEqual(dt.score(self.items['answer-01'], None)['outcome'], 'format_error')


class RunTests(unittest.TestCase):
    def test_reference_answers_qualify_with_context_and_scope_recorded(self):
        backend = DocBackend()
        result = run(backend)
        self.assertEqual(result['suite_version'], 'documents/short/1.0.0')
        self.assertEqual(result['settings']['context'], 4096)
        self.assertEqual(result['coverage'], {'completed': 24, 'total': 24, 'complete': True})
        self.assertEqual(result['summary']['correct'], 24)
        self.assertEqual(len(result['unscored']), 8)
        self.assertTrue(result['qualification']['qualified'])
        self.assertIn('longer documents', result['qualification']['scope'])
        self.assertEqual(result['document_context']['context'], 4096)
        self.assertTrue(result['restoration']['succeeded'])
        self.assertEqual(backend.loaded[0]['name'], 'previous:fixture')
        for call in backend.calls:
            if call[0] == 'generate' and call[2]:
                self.assertEqual(call[3]['options']['num_ctx'], 4096)
                self.assertEqual(call[3]['options']['temperature'], 0)

    def test_wrong_and_malformed_runs_do_not_qualify(self):
        wrong = run(DocBackend('wrong'))
        self.assertFalse(wrong['qualification']['qualified'])
        self.assertEqual(wrong['summary']['correct'], 0)
        self.assertEqual(wrong['summary']['format_errors'], 0)
        broken = run(DocBackend('malformed'))
        self.assertFalse(broken['qualification']['qualified'])
        self.assertEqual(broken['summary']['format_errors'], 24)

    def test_thresholds_are_exact_and_independent_of_any_baseline(self):
        data = dt.load()
        criteria = data['criteria']
        def run_with(skip_per_category):
            seen = {}
            def mode(item):
                cat = item['category']
                seen[cat] = seen.get(cat, 0) + 1
                return item['wrong'] if seen[cat] <= skip_per_category.get(cat, 0) else item['reference']
            return run(DocBackend(mode))['qualification']
        self.assertTrue(run_with({'quote': 2})['qualified'])
        near = run_with({'quote': 3})
        self.assertFalse(near['qualified'])
        self.assertEqual([c['met'] for c in near['checks']], [True, False, True, True])
        self.assertFalse(run_with({'answer': 2})['qualified'])
        self.assertFalse(run_with({'not_stated': 2})['qualified'])
        # A weak baseline cannot lower the bar: criteria come only from the suite file.
        self.assertEqual(near['criteria_version'], criteria['version'])
        self.assertEqual({c['name']: c['required'] for c in near['checks']},
                         {'answer': 7, 'quote': 6, 'not_stated': 7, 'format_errors': 2})

    def test_format_error_budget_and_incomplete_runs(self):
        two = [0]
        def mode(item):
            if item['category'] == 'answer' and two[0] < 2:
                two[0] += 1
                return item['malformed']
            return item['reference']
        result = run(DocBackend(mode))
        self.assertEqual(result['summary']['format_errors'], 2)
        self.assertFalse([c for c in result['qualification']['checks'] if c['name'] == 'format_errors'][0]['met'] is False)
        event = threading.Event()
        def progress(value):
            if value['completed'] == 5:
                event.set()
        partial = run(DocBackend(), cancel=event, progress=progress)
        self.assertEqual(partial['state'], 'cancelled')
        self.assertFalse(partial['qualification']['qualified'])
        self.assertFalse(partial['qualification']['complete'])

    def test_context_must_be_advertised(self):
        with self.assertRaisesRegex(ValueError, 'at least 4096'):
            run(DocBackend(context=2048))

    def test_results_round_trip_and_matched_comparison(self):
        first, second = run(DocBackend()), run(DocBackend('wrong'))
        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(Path(temp) / 'results')
            store.save(first)
            store.save(second)
            loaded = store.load(first['id'])
            self.assertEqual(loaded['qualification'], first['qualification'])
            comparison = results.compare([store.load(first['id']), store.load(second['id'])])
            accuracy = {row['id']: row['value'] for row in comparison['rows']}
            self.assertEqual(accuracy[first['id']], 1.0)
            self.assertEqual(accuracy[second['id']], 0.0)

    def test_document_results_do_not_compare_with_quick_ability(self):
        from test_results import ability_result
        with self.assertRaisesRegex(ValueError, 'same benchmark kind'):
            results.compare([run(DocBackend()), ability_result()])


if __name__ == '__main__':
    unittest.main()
