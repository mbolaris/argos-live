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

    def test_wording_miss_with_an_exact_quote_says_so(self):
        # Seen on Toronado: right evidence, answer phrased differently from every accepted form.
        def mode(item):
            if item['id'] != 'quote-01':
                return item['reference']
            value = json.loads(item['reference'])
            value['answer'] = 'about ' + value['answer']
            return json.dumps(value)
        item = next(i for i in replay.build(run(mode))['items'] if i['item_id'] == 'quote-01')
        self.assertEqual(item['outcome'], 'wrong_answer')
        self.assertTrue(item['quote_in_passage'])
        self.assertIn('the quote was copied exactly, but the answer “about', item['reason'])
        self.assertIn('word for word', item['reason'])

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


if __name__ == '__main__':
    unittest.main()
