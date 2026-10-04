from contextlib import contextmanager
import copy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, startup
from argoslive.web.server import DashboardServer


class Client:
    def __init__(self, gate=None):
        self.gate = gate
        self.generations = 0
    def generate(self, model, prompt, **options):
        self.generations += 1
        if self.gate:
            while not self.gate.wait(0.01):
                if options['cancel']():
                    raise ValueError('fixture cancelled')
        return {'text': 'Hello public fixture', 'time_to_first_token_seconds': .25,
            'elapsed_seconds': .5, 'final': {'eval_count': 4, 'eval_duration': 1000000000}}
    def ps(self):
        return {'models': [{'name': 'qwen3:0.6b', 'size': 123, 'size_vram': 0}]}
    def unload(self, model):
        pass


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.calls = []
        self.client = Client()

    @contextmanager
    def backend(self, target, **options):
        self.calls.append('backend-start')
        try:
            yield self.client
        finally:
            self.calls.append('backend-stop')

    @contextmanager
    def gateway(self, home, **options):
        self.calls.append('gateway-start')
        try:
            yield 'http://127.0.0.1:18789'
        finally:
            self.calls.append('gateway-stop')

    def controller(self, **options):
        defaults = {'configure': lambda home, **kw: self.calls.append('setup'),
            'resolve_source': lambda home: (home / 'read-only-image', 'qwen3:0.6b'),
            'backend': self.backend, 'gateway': self.gateway, 'ready': lambda origin: True,
            'conversation': lambda path, **kw: 'http://127.0.0.1:18789/chat#token=fictional'}
        value = startup.Controller(self.home, **dict(defaults, **options))
        self.addCleanup(value.close)
        return value

    def wait(self, controller, phase):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if controller.snapshot()['phase'] == phase:
                return
            time.sleep(.01)
        self.fail('Startup did not reach ' + phase + ': ' + json.dumps(controller.snapshot()))

    def test_one_worker_measured_reply_once_handoff_and_ordered_owned_cleanup(self):
        value = self.controller()
        value.start()
        self.wait(value, 'ready')
        for _ in range(3):
            value.start()
        report = value.snapshot()
        self.assertTrue(report['model_reply_verified'])
        self.assertEqual(report['metrics']['generation_tokens_per_second'], 4)
        self.assertEqual(report['metrics']['backend']['mode'], 'CPU')
        self.assertTrue(report['auto_open_chat'])
        self.assertNotIn('Hello', json.dumps(report))
        self.assertEqual(value.claim_chat(), 'http://127.0.0.1:18789/chat#token=fictional')
        self.assertFalse(value.snapshot()['auto_open_chat'])
        with self.assertRaises(ValueError):
            value.claim_chat()
        value.close()
        self.wait(value, 'stopped')
        self.assertEqual(self.calls, ['setup', 'backend-start', 'gateway-start', 'gateway-stop', 'backend-stop'])
        self.assertEqual(self.client.generations, 1)

    def test_stop_during_warmup_never_starts_gateway_and_releases_backend(self):
        self.client = Client(threading.Event())
        value = self.controller()
        value.start()
        self.wait(value, 'first-reply')
        value.close()
        self.wait(value, 'stopped')
        self.assertNotIn('gateway-start', self.calls)
        self.assertEqual(self.calls[-1], 'backend-stop')
        self.assertFalse(value.snapshot()['model_reply_verified'])

    def test_complete_auto_setup_progress_can_reach_gateway(self):
        def configure(home, progress):
            for phase in ('verify-starter', 'select-storage', 'write-configuration', 'configured'):
                progress({'phase': phase})
        value = self.controller(configure=configure)
        value.start()
        self.wait(value, 'ready')
        value.close()
        self.wait(value, 'stopped')

    def test_failure_keeps_owner_files_and_public_error_omits_details(self):
        owner = self.home / 'owner-config'
        owner.write_bytes(b'owner bytes')
        def failed(home, **options):
            raise ValueError('fictional-private-token-and-path')
        value = self.controller(configure=failed)
        value.start()
        self.wait(value, 'failed')
        value.close()
        report = value.snapshot()
        self.assertTrue(report['can_start'])
        self.assertNotIn('fictional-private', json.dumps(report))
        self.assertEqual(owner.read_bytes(), b'owner bytes')
        self.assertEqual(self.calls, [])

    def test_managed_source_requires_current_identity_and_retains_reviewed_policy(self):
        state = {'model': 'qwen3:0.6b', 'model_source': 'managed', 'storage': str(self.home / 'models')}
        config = auto_setup.conversation_config(state['model'], self.home / 'workspace')
        original = copy.deepcopy(config)
        with patch('argoslive.startup.read_json', side_effect=[state, config]), \
                patch('argoslive.startup.storage.validate_configured', return_value=self.home / 'models'), \
                patch('argoslive.startup.model_verify.verify') as verify:
            target, tag = startup.source(self.home)
        self.assertEqual(target, self.home / 'models')
        self.assertEqual(tag, state['model'])
        verify.assert_called_once()
        self.assertEqual(config, original)
        for change in ('policy', 'shell', 'provider', 'channels', 'source'):
            proposed = copy.deepcopy(config)
            altered = copy.deepcopy(state)
            if change == 'policy': proposed['tools']['profile'] = 'full'
            if change == 'shell': proposed['commands']['bash'] = True
            if change == 'provider': proposed['models']['providers']['ollama']['baseUrl'] = 'http://remote.invalid'
            if change == 'channels': proposed['channels'] = {'fixture': {'enabled': True}}
            if change == 'source': altered['model_source'] = 'unknown'
            with patch('argoslive.startup.read_json', side_effect=[altered, proposed]), \
                    patch('argoslive.startup.storage.validate_configured', return_value=target), \
                    patch('argoslive.startup.model_verify.verify') as verify:
                with self.subTest(change=change), self.assertRaises(ValueError): startup.source(self.home)
                verify.assert_not_called()


class StartupHTTPTests(unittest.TestCase):
    def test_only_authenticated_same_origin_empty_post_can_control_owned_startup(self):
        class Fixture:
            calls = 0
            def snapshot(self): return {'schema': 'argos-startup/1', 'phase': 'idle'}
            def start(self): self.calls += 1; return self.snapshot()
            stop = start
            def claim_chat(self): raise ValueError('fictional-private-details')
        fixture = Fixture()
        with DashboardServer(port=0, startup=fixture) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            def request(method, headers=None, body=None, path='/api/startup/start'):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    connection.request(method, path, body=body, headers=headers or {})
                    response = connection.getresponse()
                    return response.status, response.read()
                finally:
                    connection.close()
            try:
                auth = {'X-Argos-Token': server.token, 'Origin': server.origin}
                self.assertEqual(request('POST')[0], 403)
                self.assertEqual(request('POST', path='/api/startup/start?token=' + server.token)[0], 403)
                self.assertEqual(request('POST', dict(auth, Origin='https://foreign.invalid'))[0], 403)
                self.assertEqual(request('POST', auth, b'{}')[0], 400)
                self.assertEqual(request('PUT', auth)[0], 405)
                self.assertEqual(request('DELETE', auth)[0], 405)
                self.assertEqual(fixture.calls, 0)
                self.assertEqual(request('POST', auth)[0], 200)
                self.assertEqual(fixture.calls, 1)
                code, body = request('POST', auth, path='/api/startup/chat')
                self.assertEqual(code, 409)
                self.assertNotIn(b'fictional-private', body)
            finally:
                server.shutdown()
                worker.join(timeout=5)
