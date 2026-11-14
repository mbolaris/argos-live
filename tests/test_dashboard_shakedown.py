import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.results import Store
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer
from argoslive.shakedown.scorecard import View as ShakedownView


class ShakedownApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        store = Store(self.home / '.local/share/argos-live/results')
        self.server = DashboardServer(port=0, benchmarks=BenchmarkView(store),
                                      shakedown=ShakedownView(store, home=self.home))
        self.server.shakedown.home = self.home
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, path, *, token=None, header=True, method='GET', body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {}
        if token is not None and header:
            headers['X-Argos-Token'] = token
        if body is not None:
            import json
            body = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_scorecard_requires_session_token_and_returns_empty_state(self):
        self.assertEqual(self.request('/api/shakedown/scorecard')[0], 403)
        status, body = self.request('/api/shakedown/scorecard', token=self.server.token)
        self.assertEqual(status, 200)
        self.assertTrue(__import__('json').loads(body)['empty'])

    def test_scorecard_rejects_unknown_query_parameters_and_bad_loadout_ids(self):
        status, _ = self.request('/api/shakedown/scorecard?other=1', token=self.server.token)
        self.assertEqual(status, 400)
        status, _ = self.request('/api/shakedown/scorecard?loadouts=bad', token=self.server.token)
        self.assertEqual(status, 400)

    def test_comparison_requires_session_token_and_returns_first_build_message(self):
        self.assertEqual(self.request('/api/shakedown/comparison')[0], 403)
        status, body = self.request('/api/shakedown/comparison', token=self.server.token)
        self.assertEqual(status, 200)
        value = __import__('json').loads(body)
        self.assertFalse(value['has_comparison'])
        self.assertIn('Run this again later', value['headline'])

    def test_comparison_rejects_invalid_previous_loadout(self):
        status, _ = self.request('/api/shakedown/comparison?previous=bad', token=self.server.token)
        self.assertEqual(status, 400)

    def test_shakedown_page_embeds_session_token_only_in_asset_urls(self):
        status, body = self.request('/shakedown?token=' + quote(self.server.token), header=False)
        self.assertEqual(status, 200)
        self.assertIn(b'/shakedown.js?token=' + quote(self.server.token).encode(), body)
        self.assertNotIn(b'__SESSION_TOKEN__', body)

    def test_queue_snapshot_and_choices_require_session_token(self):
        self.assertEqual(self.request('/api/shakedown/queue')[0], 403)
        status, body = self.request('/api/shakedown/queue', token=self.server.token)
        self.assertEqual(status, 200)
        self.assertEqual(__import__('json').loads(body)['state'], 'idle')
        status, body = self.request('/api/shakedown/queue/choices', token=self.server.token)
        self.assertEqual(status, 200)
        self.assertEqual(__import__('json').loads(body)['entries'], [])

    def test_queue_start_requires_owner_token_before_reading_body(self):
        status, _ = self.request('/api/shakedown/queue/start', method='POST',
                                 body={'entries': []})
        self.assertEqual(status, 403)

    def test_export_saves_local_files_and_requires_session_authorization(self):
        self.assertEqual(self.request('/api/shakedown/export', method='POST', body={})[0], 403)
        status, body = self.request('/api/shakedown/export', token=self.server.token,
                                    method='POST', body={})
        self.assertEqual(status, 201)
        result = __import__('json').loads(body)
        self.assertIn('json', result['files'])
        self.assertIn('svg', result['files'])
        status, svg = self.request('/api/shakedown/exports/' + result['export_id'] + '.svg',
                                   token=self.server.token)
        self.assertEqual(status, 200)
        self.assertIn(b'Argos Shakedown scorecard', svg)


if __name__ == '__main__':
    unittest.main()
