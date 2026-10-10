import http.client
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import doc_trial, replay
from argoslive.results import Store
from argoslive.web.benchmarks import View
from argoslive.web.server import DashboardServer
from test_doc_trial import DocBackend
from test_results import ability_result


def run(mode='reference'):
    return doc_trial.run(DocBackend(mode), 'fixture:latest', hardware=lambda: {})


class ReplayTests(unittest.TestCase):
    def test_every_response_in_suite_order_with_saved_verdicts(self):
        saved = run()
        value = replay.build(saved)
        self.assertEqual(len(value['items']), 32)
        self.assertEqual(value['run']['unscored'], 8)
        self.assertEqual((value['run']['correct'], value['run']['total']), (24, 24))
        first = value['items'][:4]
        self.assertEqual([i['category'] for i in first], ['answer', 'quote', 'not_stated', 'summary'])
        self.assertEqual(len({i['passage_id'] for i in first}), 1)
        # Suite order survives the sorted keys of a saved run.
        stored = json.loads(json.dumps(saved, sort_keys=True))
        self.assertEqual([i['item_id'] for i in replay.build(stored)['items'][:4]],
                         ['answer-01', 'quote-01', 'missing-01', 'summary-01'])
        self.assertEqual(first[3]['outcome'], 'unscored')
        self.assertTrue(all(i['passage_id'] in value['passages'] for i in value['items']))
        quote = first[1]
        self.assertTrue(quote['quote_in_passage'])
        self.assertTrue(quote['reason'].startswith('Correct'))
        # Verdicts are the saved ones; replay never rescored.
        saved_outcomes = {i['item_id']: i['outcome'] for i in saved['items']}
        for item in value['items']:
            if item['outcome'] != 'unscored':
                self.assertEqual(item['outcome'], saved_outcomes[item['item_id']])

    def test_reasons_explain_misses_with_the_scorers_own_parsing(self):
        wrong = {i['category']: i for i in replay.build(run('wrong'))['items'] if i['passage_id'] == 'ferry'}
        self.assertTrue(wrong['answer']['reason'].startswith('Wrong: expected “'))
        # The quote fixture keeps the right answer but quotes a sentence that is not in the passage.
        self.assertIn('isn’t copied exactly from the passage', wrong['quote']['reason'])
        self.assertFalse(wrong['quote']['quote_in_passage'])
        self.assertIn('answered anyway', wrong['not_stated']['reason'])
        broken = replay.build(run('malformed'))['items'][0]
        self.assertEqual(broken['outcome'], 'format_error')
        self.assertTrue(broken['reason'].startswith('Not scorable'))

    def test_only_document_runs_replay(self):
        with self.assertRaises(ValueError):
            replay.build(ability_result())

    def test_route_is_authenticated_bounded_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            saved = run()
            store.save(saved)
            other = ability_result()
            store.save(other)
            with DashboardServer(port=0, benchmarks=View(store)) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()

                def request(path, headers=None):
                    with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                        connection.request('GET', path, headers=headers or {})
                        reply = connection.getresponse()
                        return reply.status, reply.read()
                auth = {'X-Argos-Token': server.token}
                try:
                    self.assertEqual(request('/api/benchmarks/replay/' + saved['id'])[0], 403)
                    code, body = request('/api/benchmarks/replay/' + saved['id'], auth)
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body)['schema'], 'argos-replay/1')
                    for path in ('/api/benchmarks/replay/' + other['id'], '/api/benchmarks/replay/../../private'):
                        code, body = request(path, auth)
                        self.assertEqual(code, 409)
                        self.assertNotIn(temp.encode(), body)
                    self.assertEqual(store.load(saved['id']), saved)
                finally:
                    server.shutdown(); worker.join(timeout=5)


# Real receipts from Toronado (public suite documents/short/1.0.0), audited in docs/DOCUMENT-MISS-AUDIT.md.
RECEIPTS = [
    # (item, saved outcome, model output, expected diagnosis)
    ('quote-05', 'wrong_answer', '{"status": "answered", "answer": "to protect nesting birds", "quote": "the lookout at the '
     'halfway point is closed to dogs from March to June to protect nesting birds"}', 'wording'),
    ('quote-07', 'wrong_answer', '{"status": "answered", "answer": "Markdown export", "quote": "The release removes the old '
     'plain-text export; users should choose Markdown export instead."}', 'wording'),
    ('answer-07', 'wrong_answer', '{"status": "answered", "answer": "Android 10 or newer", "quote": "Version 3.2 requires '
     'Android 10 or newer."}', 'wording'),
    ('quote-06', 'wrong_answer', '{"status": "answered", "answer": "The exhibit shows how coastal towns traded salt across the '
     'bay in the nineteenth century.", "quote": "The exhibit follows how coastal towns traded salt across the bay in the '
     'nineteenth century."}', 'long_answer'),
    ('quote-08', 'wrong_answer', '{"status": "answered", "answer": "Unsold bread is donated to the Eastside Pantry every evening '
     'at closing.", "quote": "Unsold bread is donated to the Eastside Pantry every evening at closing."}', 'long_answer'),
    ('quote-07', 'wrong_answer', '```json\n{"status": "answered", "answer": "Markdown export", "quote": "A bug that duplicated '
     'checklist items after a sync conflict is fixed."}\n```', 'unsupported_quote'),
    ('answer-03', 'wrong_answer', '```json\n{"status": "answered", "answer": "30", "quote": "Exchanges for a different size are '
     'handled by phone, and the exchange window is 30 days."}\n```', 'wrong'),
    ('quote-02', 'wrong_answer', '{"status": "answered", "answer": "a short answer, or an empty string", "quote": "The project is '
     'funded by a $1.2 million bond approved by voters last November."}', 'instruction_echo'),
    ('missing-08', 'wrong_answer', '{"status": "answered", "answer": "a short answer, or an empty string", "quote": "The bakery '
     'is closed on Mondays."}', 'answered_missing'),
]


class AuditTests(unittest.TestCase):
    """Diagnostic labels for real misses: answer acceptance and quote validity are judged separately."""

    def setUp(self):
        data = doc_trial.load()
        self.rules = {i['id']: i for i in data['items']}

    def diagnose(self, item_id, outcome, output):
        suite_item = self.rules[item_id]
        saved = {'item_id': item_id, 'category': suite_item['category'], 'outcome': outcome, 'output': output}
        return replay.diagnose(saved, suite_item['scorer'], suite_item['scorer'].get('passage'))

    def test_real_receipts_get_the_audited_diagnosis(self):
        for item_id, outcome, output, kind in RECEIPTS:
            with self.subTest(item_id=item_id, kind=kind):
                # Diagnosis explains the saved score; the scorer still rejects every one of these.
                suite_item = self.rules[item_id]
                self.assertEqual(doc_trial.score(suite_item, output)['outcome'], outcome)
                self.assertEqual(self.diagnose(item_id, outcome, output)['diagnosis']['kind'], kind)

    def test_answer_and_quote_are_checked_separately(self):
        wording = self.diagnose(*RECEIPTS[0][:3])
        self.assertEqual(wording['checks'], {'answer_accepted': False, 'answer_contains_accepted': True,
                                             'answer_words': 4, 'quote_exact': True, 'quote_supports': True})
        unsupported = self.diagnose(*RECEIPTS[5][:3])
        self.assertTrue(unsupported['checks']['quote_exact'])
        self.assertFalse(unsupported['checks']['quote_supports'])

    def test_an_exact_quote_alone_is_not_treated_as_correct(self):
        # The quote is copied exactly and contains "30", but the answer is the wrong fact.
        value = self.diagnose(*RECEIPTS[6][:3])
        self.assertEqual(value['diagnosis']['group'], 'wrong')
        negated = self.diagnose('quote-07', 'wrong_answer', '{"status": "answered", "answer": "not markdown", '
                                '"quote": "The release removes the old plain-text export; users should choose Markdown export instead."}')
        self.assertEqual(negated['diagnosis']['kind'], 'wrong')

    def test_correct_answers_and_summaries_get_no_diagnosis(self):
        item = self.rules['quote-05']
        self.assertNotIn('diagnosis', replay.diagnose({'item_id': 'quote-05', 'category': 'quote', 'outcome': 'pass',
                                                       'output': item['reference']}, item['scorer'], item['scorer']['passage']))
        self.assertNotIn('diagnosis', replay.diagnose({'item_id': 'summary-01', 'category': 'summary'}, None, None))

    def test_combined_quote_check_is_renamed_for_display_only(self):
        from argoslive import mission_report
        saved = run('wrong')
        check = next(c for c in saved['qualification']['checks'] if c['name'] == 'quote')
        self.assertEqual(check['label'], 'Supported quotations')  # historical label preserved in saved runs
        shown = mission_report.summarize([saved])['ability']
        label = next(c['label'] for c in shown['checks'] if c['name'] == 'quote')
        self.assertEqual(label, 'Correct answers with a supporting quote')
        self.assertEqual(next(c['label'] for c in shown['categories'] if c['id'] == 'quote'), 'Answer with a supporting quote')
        self.assertEqual(shown['correct'], saved['summary']['correct'])

    def test_replay_counts_diagnoses_without_changing_scores(self):
        value = replay.build(run('wrong'))
        self.assertEqual(value['run']['correct'], 0)
        self.assertEqual(sum(value['run']['diagnoses'].values()), 24)


if __name__ == '__main__':
    unittest.main()
