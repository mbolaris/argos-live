import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive.results import Store
from argoslive.shakedown.queue import QueueController
from argoslive.shakedown.scorecard import View as ShakedownView
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer
from test_bench_openclaw import configure_fake
from test_shakedown_scorecard import ability_run


MODEL = 'qwen3:4b-instruct-2507-q4_K_M'


class Inventory:
    def list(self):
        return {'models': [{'name': MODEL}]}


class SerialJobs:
    def __init__(self, _home):
        self.calls = []
        self.active = 0
        self.maximum_active = 0

    def start(self, suite, **options):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        if self.active > 1:
            raise AssertionError('queue started overlapping evaluations')
        self.calls.append((suite, options))
        return {'status': 'running', 'job_id': str(len(self.calls))}

    def wait(self, job_id, **_options):
        self.active -= 1
        return {'status': 'completed', 'job_id': job_id,
                'result': {'id': 'f' * 32, 'state': 'completed'}}

    def cancel_owner(self, _job_id):
        raise AssertionError('unexpected cancellation')


class DashboardQueueFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.workspace = self.home / '.openclaw/workspace'
        self.workspace.mkdir(parents=True)
        (self.workspace / 'AGENTS.md').write_text('deployed instructions', encoding='utf-8')
        configure_fake(self.home, self.workspace)
        self.config = self.home / '.openclaw/openclaw.json'
        self.original_config = self.config.read_bytes()
        self.original_instructions = (self.workspace / 'AGENTS.md').read_bytes()
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.store.save(ability_run('a' * 32, 'ollama/' + MODEL, [1] * 8))
        self.jobs = None

        def jobs_factory(home):
            self.jobs = SerialJobs(home)
            return self.jobs
        self.queue = QueueController(self.home, self.store, jobs_factory=jobs_factory,
                                     model_client_factory=Inventory)
        self.server = DashboardServer(port=0, benchmarks=BenchmarkView(self.store),
                                      shakedown=ShakedownView(self.store, home=self.home),
                                      queue_controller=self.queue)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None):
        headers = {'X-Argos-Token': self.server.token}
        encoded = None
        if body is not None:
            encoded = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_three_entry_queue_through_dashboard_fixture_runs_one_job_at_a_time(self):
        loadout_id = self.queue.choices()[0]['id']
        status, started = self.request('POST', '/api/shakedown/queue/start', {'entries': [
            {'loadout_id': loadout_id, 'size': 'quick'},
            {'loadout_id': loadout_id, 'size': 'standard'},
            {'loadout_id': loadout_id, 'size': 'full'}]})
        self.assertEqual(status, 202)
        for _ in range(300):
            status, snapshot = self.request('GET', '/api/shakedown/queue')
            if snapshot['state'] not in ('running', 'cancelling'):
                break
            time.sleep(.01)
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['state'], 'completed')
        self.assertEqual(snapshot['position'], 3)
        self.assertEqual(len(snapshot['entries']), 3)
        self.assertIn('3 completed', snapshot['notice'])
        self.assertEqual(self.jobs.maximum_active, 1)
        self.assertEqual(len(self.jobs.calls), 21)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual((self.workspace / 'AGENTS.md').read_bytes(), self.original_instructions)


if __name__ == '__main__':
    unittest.main()
