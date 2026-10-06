import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import lab, model_controls
from argoslive.web.server import DashboardServer
from argoslive.model_onboarding import OnboardingQueue
from test_lab import Assistant


class Queue:
    def __init__(self, gate=None):
        self.calls, self.gate, self.action = [], gate, 'run'
        self.job = {'id': 'a' * 32, 'tag': 'qwen3:0.6b', 'state': 'paused'}
    def create(self, tag):
        self.calls.append('create')
        return dict(self.job, tag=tag, state='queued')
    def get(self, job):
        if job != self.job['id']: raise ValueError('Unknown ID')
        return self.job
    def check(self, job):
        pass
    def retry(self, job):
        self.calls.append('retry')
        return self.job
    def request(self, job, action):
        self.action = action
    def run_verified(self, job, *, backend, callback, assistant_stopped, cancel):
        assert assistant_stopped
        with backend(Path('/public-fixture')):
            callback({'state': 'downloading', 'progress': {'bytes_done': 10, 'bytes_total': 100,
                'recent_mib_per_second': 1.5, 'eta_seconds': 60, 'private': 'PRIVATE'}})
            if self.gate:
                self.gate.set()
                assert cancel.__self__.wait(3)
            return {'state': 'paused' if self.action == 'pause' else 'cancelled' if cancel() else 'ready',
                    'reply_test': {'text_reply_verified': not cancel(), 'eval_count': 9,
                        'eval_duration': 1000000000, 'private': 'PRIVATE'}}


class ModelControlsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.assistant = Assistant(Path(temp.name))
        self.queue = Queue()
        self.controller = model_controls.Controller(self.assistant, queue_factory=lambda _: self.queue, storage_gate=lambda home: None)
        self.addCleanup(self.controller.close)
    def finish(self):
        self.controller.worker.join(5)
        self.assertFalse(self.controller.worker.is_alive())
    def test_verified_pipeline_cleanup_and_prior_assistant_restart(self):
        self.controller.start(tag='qwen3:0.6b')
        self.finish()
        value = self.controller.snapshot()
        self.assertEqual(value['phase'], 'completed')
        self.assertTrue(value['resume_requested'])
        self.assertTrue(value['reply_test']['text_reply_verified'])
        self.assertNotIn('PRIVATE', str(value))
        self.assertEqual(self.assistant.calls, ['pause', 'resolve', 'backend-start', 'backend-stop', 'resume'])
    def test_unconfirmed_or_failing_storage_stops_download_before_any_job(self):
        for failure in (ValueError('Choose where models are stored before downloading'), OSError('read-only')):
            def gate(home, failure=failure):
                raise failure
            controller = model_controls.Controller(self.assistant, queue_factory=lambda _: self.queue, storage_gate=gate)
            self.addCleanup(controller.close)
            with self.assertRaises(type(failure)):
                controller.start(tag='qwen3:0.6b')
            self.assertEqual(self.queue.calls, [])
            self.assertEqual(self.assistant.calls, [])
            self.assertIsNone(controller.worker)
    def test_gate_receives_the_desktop_home(self):
        seen = []
        controller = model_controls.Controller(self.assistant, queue_factory=lambda _: self.queue,
                                               storage_gate=seen.append)
        self.addCleanup(controller.close)
        controller.start(tag='qwen3:0.6b')
        controller.worker.join(5)
        self.assertEqual(seen, [self.assistant.home])
    def test_explicit_retry_uses_same_durable_job(self):
        self.controller.start(job='a' * 32)
        self.finish()
        self.assertEqual(self.queue.calls, ['retry'])
        self.assertEqual(self.controller.snapshot()['job_id'], 'a' * 32)
    def test_download_and_benchmark_cannot_overlap_pause_is_durable(self):
        gate = threading.Event()
        self.queue.gate = gate
        self.controller.start(tag='qwen3:0.6b')
        self.assertTrue(gate.wait(3))
        other = lab.Controller(self.assistant)
        with self.assertRaises(ValueError): other.start()
        original_request = self.queue.request
        def durable_first(job, action):
            self.assertFalse(self.controller.cancel_event.is_set())
            original_request(job, action)
        self.queue.request = durable_first
        self.controller.cancel('pause')
        self.finish()
        self.assertEqual(self.controller.snapshot()['phase'], 'paused')
        self.assertEqual(self.queue.action, 'pause')
        self.assertFalse(self.assistant.lab_active)
    def test_unknown_models_and_ambiguous_inputs_never_pause(self):
        for choice in ({'tag': 'unknown:model'}, {'tag': 'qwen3:0.6b', 'job': 'a' * 32}, {}):
            with self.assertRaises(ValueError): self.controller.start(**choice)
        self.assertEqual(self.assistant.calls, [])
    def test_cancel_while_waiting_for_chat_records_terminal_receipt(self):
        root = self.assistant.home / 'jobs'
        OnboardingQueue.initialize(root)
        models = self.assistant.home / 'models'
        models.mkdir()
        queue = OnboardingQueue(root, {'storage_id': 'fixture'}, validate=lambda _: models)
        self.controller.queue_factory = lambda _: queue
        self.assistant.stop = lambda: self.assistant.calls.append('pause')
        self.controller.start(tag='qwen3:0.6b')
        self.controller.cancel()
        self.finish()
        job = queue.get(self.controller.job_id)
        self.assertEqual(job['state'], 'cancelled')
        self.assertNotIn('backend-start', self.assistant.calls)
        with self.assertRaises(ValueError): queue.retry(job['id'])
    def test_http_bounded_choices_and_authentication(self):
        with DashboardServer(port=0, downloads=self.controller) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            def request(raw, auth=True, path='/api/models/download', length=None):
                headers = {'Content-Type': 'application/json'}
                if length is not None: headers['Content-Length'] = str(length)
                if auth: headers['X-Argos-Token'] = server.token
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    conn.request('POST', path, body=raw, headers=headers)
                    reply = conn.getresponse()
                    reply.read()
                    return reply.status
                finally: conn.close()
            try:
                self.assertEqual(request(None, auth=False,
                    path='/api/models/download?token=' + server.token), 403)
                self.assertEqual(request(None, length=513), 400)
                for raw in ('{"tag":"qwen3:0.6b","tag":"qwen3:0.6b"}', '{"command":"shell"}', '[]'):
                    self.assertEqual(request(raw), 409)
                self.assertEqual(self.assistant.calls, [])
                self.assertEqual(request(json.dumps({'tag': 'qwen3:0.6b'})), 200)
                self.finish()
            finally:
                server.shutdown()
                worker.join(3)
