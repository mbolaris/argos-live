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
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive import lab as lab_module
from argoslive.results import Store
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer
from test_doc_trial import DocBackend
from test_lab import Assistant


class JourneyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir(parents=True)
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.assistant = Assistant(self.home)
        self.lab = lab_module.Controller(self.assistant, store=self.store)
        self.server = DashboardServer(
            port=0,
            lab=self.lab,
            benchmarks=BenchmarkView(self.store),
        )
        self.server.__enter__()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.lab.close()
        try:
            self.server.shutdown()
        except Exception:
            pass
        self.thread.join(timeout=2)
        self.server.__exit__(None, None, None)
        self.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None, token=True):
        hdrs = dict(headers or {})
        if token:
            hdrs['X-Argos-Token'] = self.server.token
        if body is not None and 'Content-Type' not in hdrs:
            hdrs['Content-Type'] = 'application/json'
        payload = json.dumps(body).encode('utf-8') if body is not None else None
        if payload is not None:
            hdrs['Content-Length'] = str(len(payload))
        with closing(http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)) as conn:
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            data = None
            if resp.getheader('Content-Type', '').startswith('application/json'):
                try:
                    data = json.loads(raw.decode('utf-8'))
                except Exception:
                    pass
            return resp.status, data

    def test_recipe_select_requires_auth(self):
        status, data = self.request('/api/lab/recipe/select', method='POST', body={'preset': 'concise'}, token=False)
        self.assertEqual(status, 403)

    def test_recipe_select_and_verify_state(self):
        # Initial state: standard (None)
        status, data = self.request('/api/lab/recipes')
        self.assertEqual(status, 200)
        self.assertIsNone(data.get('selected'))

        # Select concise recipe
        status, data = self.request('/api/lab/recipe/select', method='POST', body={'preset': 'concise'})
        self.assertEqual(status, 200)
        self.assertEqual(data.get('selected_recipe', {}).get('preset'), 'concise')

        # Verify through /api/lab/recipes
        status, data = self.request('/api/lab/recipes')
        self.assertEqual(status, 200)
        self.assertIsNotNone(data.get('selected'))
        self.assertEqual(data['selected']['preset'], 'concise')

        # Restore recipe
        status, data = self.request('/api/lab/recipe/restore', method='POST', headers={'Content-Length': '0'})
        self.assertEqual(status, 200)
        self.assertIsNone(data.get('selected_recipe'))

        # Verify restored to standard
        status, data = self.request('/api/lab/recipes')
        self.assertEqual(status, 200)
        self.assertIsNone(data.get('selected'))

    def test_recipe_select_and_restore_conflict_when_trial_active(self):
        # Fake active worker with blocking event
        event = threading.Event()
        fake_worker = threading.Thread(target=event.wait)
        fake_worker.start()
        with self.lab.lock:
            self.lab.worker = fake_worker

        try:
            # POST /api/lab/recipe/select returns 409
            status, data = self.request('/api/lab/recipe/select', method='POST', body={'preset': 'concise'})
            self.assertEqual(status, 409)
            self.assertIn('error', data)

            # POST /api/lab/recipe/restore returns 409
            status, data = self.request('/api/lab/recipe/restore', method='POST', headers={'Content-Length': '0'})
            self.assertEqual(status, 409)
            self.assertIn('error', data)
            self.assertIn('active', data['error'].lower())

            # POST /api/lab/start-documents returns 409
            status, data = self.request('/api/lab/start-documents', method='POST', headers={'Content-Length': '0'})
            self.assertEqual(status, 409)
            self.assertIn('error', data)
        finally:
            event.set()
            fake_worker.join(timeout=1)
            with self.lab.lock:
                self.lab.worker = None

    def test_experiment_comparison_409_refusal(self):
        from test_results import ability_result
        run = ability_result()
        self.store.save(run)

        # Identical pair comparison returns 409 Conflict
        status, data = self.request(f'/api/benchmarks/experiment?baseline={run["id"]}&candidate={run["id"]}')
        self.assertEqual(status, 409)
        self.assertIn('error', data)
        self.assertIn('distinct', data['error'].lower())


if __name__ == '__main__':
    unittest.main()
