import contextlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import lab, startup, bench_speed
from argoslive.results import Store
from argoslive.ollama import Cancelled
from argoslive.web.server import DashboardServer
from test_bench_speed import Backend
from test_results import ability_result


class Assistant:
    def __init__(self, home, active=True):
        self.home, self.active = home, active
        self.lock = threading.RLock()
        self.lab_active = False
        self.calls = []
        self.chat_claimed = False
    def snapshot(self):
        return {'active': self.active}
    def stop(self):
        self.calls.append('pause')
        self.active = False
    def start(self):
        assert not self.lab_active
        self.calls.append('resume')
        self.active = True
    def resolve_source(self, home):
        self.calls.append('resolve')
        return home / 'models', 'fixture:latest'
    @contextlib.contextmanager
    def backend(self, target, **options):
        self.calls.append('backend-start')
        try:
            yield Backend()
        finally:
            self.calls.append('backend-stop')


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.assistant = Assistant(Path(self.temp.name))
        self.store = Store(Path(self.temp.name) / 'results')
        self.lab = lab.Controller(self.assistant, store=self.store,
            speed=lambda client, model, **kw: bench_speed.run(client, model, hardware=lambda: {}, **kw),
            ability=lambda *args, **kw: ability_result())
        self.addCleanup(self.lab.close)
    def finish(self):
        self.lab.worker.join(timeout=5)
        self.assertFalse(self.lab.worker.is_alive())
    def test_pause_owned_backend_save_then_resume_in_order(self):
        self.lab.start()
        self.finish()
        self.assertEqual(self.assistant.calls, ['pause', 'resolve', 'backend-start', 'backend-stop', 'resume'])
        value = self.lab.snapshot()
        self.assertEqual(value['phase'], 'completed')
        self.assertTrue(value['resume_requested'])
        self.assertEqual(len(value['runs']), 2)
        speed = self.store.load(value['runs'][0])
        self.assertEqual(speed['settings']['prompt_sizes'], ['short'])
        self.assertEqual(len(speed['prompts'][0]['runs']), 3)
        self.assertTrue(self.assistant.chat_claimed)
    def test_inactive_assistant_stays_inactive(self):
        self.assistant.active = False
        self.lab.start()
        self.finish()
        self.assertNotIn('resume', self.assistant.calls)
    def test_cancel_and_duplicate_start_during_stream_then_cleanup(self):
        entered = threading.Event()
        def speed(*args, cancel, **kw):
            entered.set()
            self.assertTrue(cancel.wait(3))
            raise Cancelled('Fixture stopped')
        self.lab.speed = speed
        self.lab.start()
        self.assertTrue(entered.wait(3))
        with self.assertRaises(ValueError): self.lab.start()
        self.assertTrue(self.assistant.lab_active)
        self.lab.cancel()
        self.finish()
        self.assertEqual(self.lab.snapshot()['phase'], 'cancelled')
        self.assertFalse(self.assistant.lab_active)
        self.assertLess(self.assistant.calls.index('backend-stop'), self.assistant.calls.index('resume'))
        self.assertEqual(self.store.list()['runs'], [])
    def test_failed_ability_retains_speed_and_does_not_export_error(self):
        def failed(*args, **kw): raise ValueError('PRIVATE token configuration-path')
        self.lab.ability = failed
        self.lab.start()
        self.finish()
        self.assertEqual(self.lab.snapshot()['phase'], 'failed')
        self.assertNotIn('PRIVATE', str(self.lab.snapshot()))
        self.assertEqual(len(self.lab.snapshot()['runs']), 1)
        self.assertEqual(self.assistant.calls[-2:], ['backend-stop', 'resume'])
    def test_close_cancels_without_restarting_or_accepting_new_jobs(self):
        entered = threading.Event()
        def speed(*args, cancel, **kw):
            entered.set()
            self.assertTrue(cancel.wait(3))
            raise Cancelled('Fixture closed')
        self.lab.speed = speed
        self.lab.start()
        self.assertTrue(entered.wait(3))
        self.lab.close()
        self.assertFalse(self.lab.worker.is_alive())
        self.assertNotIn('resume', self.assistant.calls)
        self.assertFalse(self.lab.snapshot()['available'])
        with self.assertRaises(ValueError): self.lab.start()
    def test_chat_start_rejected_while_lab_reserved(self):
        controller = startup.Controller(Path(self.temp.name))
        controller.lab_active = True
        self.assertFalse(controller.snapshot()['can_start'])
        with self.assertRaises(ValueError): controller.start()
    def test_lab_http_requires_header_and_empty_body(self):
        import http.client
        with DashboardServer(port=0, lab=self.lab) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            def request(path, body=None, headers=None):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                try:
                    conn.request('POST', path, body=body, headers=headers or {})
                    result = conn.getresponse()
                    result.read()
                    return result.status
                finally: conn.close()
            try:
                self.assertEqual(request('/api/lab/start?token=' + server.token), 403)
                auth = {'X-Argos-Token': server.token}
                self.assertEqual(request('/api/lab/start', body='{"model":"other"}', headers=auth), 400)
                self.assertEqual(request('/api/lab/start', headers=auth), 200)
                self.finish()
            finally:
                server.shutdown()
                worker.join(3)
