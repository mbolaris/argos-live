import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from argoslive import auto_climb
from argoslive.web.server import DashboardServer


class FakeStartup:
    def __init__(self, home):
        self.home = home
        self.lock = threading.RLock()
        self.lab_active = False
        self.active = True

    def snapshot(self):
        return {'active': self.active, 'phase': 'ready', 'model': 'test-model'}

    def stop(self):
        self.active = False

    def start(self, *, _reserved=False):
        self.active = True


class FakeRunner:
    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.cancel_event = None

    def turn(self, prompt):
        while not self.gate.is_set():
            if self.cancel_event and self.cancel_event.is_set():
                raise auto_climb.assistant_trial.TrialTurnError('cancelled')
            self.gate.wait(timeout=0.05)
        return 'Test response.'


class TestAutoClimbAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        ws = self.home / '.openclaw/workspace'
        ws.mkdir(parents=True)
        (self.home / '.openclaw/openclaw.json').write_text(
            json.dumps({'agents': {'defaults': {'workspace': str(ws)}}})
        )
        (self.home / '.config/argos-live').mkdir(parents=True)
        (self.home / '.config/argos-live/state.json').write_text('{"model": "test-model"}')
        (ws / 'AGENTS.md').write_text('# Operating notes\n')
        for name in ('SOUL.md', 'IDENTITY.md', 'USER.md'):
            (ws / name).write_text(f'{name} content\n')

        self.startup = FakeStartup(self.home)
        self.runner = FakeRunner()
        self.controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            sleep_fn=lambda s: None,
        )
        self.server = DashboardServer(port=0, auto_climb=self.controller)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.controller.close()
        self.temp.cleanup()

    def request(self, path, method='GET', data=None):
        url = f'{self.server.origin}{path}'
        headers = {'X-Argos-Token': self.server.token}
        payload = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            payload = json.dumps(data).encode('utf-8')
        req = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except HTTPError as err:
            try:
                return err.code, json.loads(err.read().decode('utf-8'))
            finally:
                err.close()

    def test_get_auto_climb_snapshot(self):
        status, body = self.request('/api/auto-climb')
        self.assertEqual(status, 200)
        self.assertTrue(body['available'])
        self.assertEqual(body['phase'], 'idle')
        self.assertTrue(body['can_start'])

    def test_start_pause_resume_stop_flow(self):
        # Gate the runner turn so the worker is paused inside assess
        self.runner.gate.clear()
        try:
            # Start session
            status, body = self.request('/api/auto-climb/start', method='POST', data={'envelope': {'max_experiments': 2}})
            self.assertEqual(status, 200)
            self.assertIsNotNone(body['session_id'])

            # Duplicate start returns 409
            status, err = self.request('/api/auto-climb/start', method='POST')
            self.assertEqual(status, 409)

            # Pause
            status, paused = self.request('/api/auto-climb/pause', method='POST')
            self.assertEqual(status, 200)
            self.assertEqual(paused['phase'], 'paused')

            # Resume
            status, resumed = self.request('/api/auto-climb/resume', method='POST')
            self.assertEqual(status, 200)
            self.assertEqual(resumed['phase'], 'assess')
        finally:
            self.runner.gate.set()

        # Stop
        status, stopped = self.request('/api/auto-climb/stop', method='POST')
        self.assertEqual(status, 200)
        self.assertEqual(stopped['phase'], 'stopped')


if __name__ == '__main__':
    unittest.main()
