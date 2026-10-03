import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('welcome', Path(__file__).parents[1] / 'runtime/welcome.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

class WelcomeTests(unittest.TestCase):
    def test_liveness_is_not_readiness(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok":true,"status":"live"}'
        with patch.object(w, 'urlopen', return_value=response):
            self.assertFalse(w.ready('http://127.0.0.1:18789'))
        response.read.return_value = b'{"ready":true}'
        with patch.object(w, 'urlopen', return_value=response):
            self.assertTrue(w.ready('http://127.0.0.1:18789'))

    def test_unavailable_gateway(self):
        with patch.object(w, 'urlopen', side_effect=OSError('offline')):
            self.assertFalse(w.ready('http://127.0.0.1:18789'))

    def test_nonlocal_gateway_rejected(self):
        with self.assertRaisesRegex(ValueError, 'local-only'):
            w.gateway_url({'gateway': {'bind': 'lan'}})

    def test_offline_does_not_require_internet(self):
        with patch.object(w.subprocess, 'run', return_value=Mock(stdout='[]')):
            self.assertIn('local chat still works', w.network_status())

    def test_route_does_not_claim_internet(self):
        with patch.object(w.subprocess, 'run', return_value=Mock(stdout='[{"dst":"default"}]')):
            self.assertEqual('Connected to a network', w.network_status())

    def test_model_manifest_requires_every_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'manifests/registry.ollama.ai/library/qwen3/0.6b'
            manifest.parent.mkdir(parents=True)
            digest = 'sha256:' + 'a' * 64
            manifest.write_text(json.dumps({'config': {'digest': digest, 'size': 3}, 'layers': []}))
            state = {'model': 'qwen3:0.6b', 'storage': directory}
            self.assertFalse(w.model_available(state))
            (root / 'blobs').mkdir()
            blob = root / 'blobs' / digest.replace(':', '-')
            blob.write_bytes(b'abc')
            self.assertTrue(w.model_available(state))
            blob.write_bytes(b'a')
            self.assertFalse(w.model_available(state))

    def test_persistence_encryption_not_assumed(self):
        with patch.object(w.subprocess, 'run', return_value=Mock(stdout='')):
            self.assertIn('Temporary session', w.persistence_status())

    def test_setup_explicit_permissions_required(self):
        argos = w.runtime()
        with tempfile.TemporaryDirectory() as directory:
            argos.STATE = Path(directory) / 'state.json'
            with patch.object(argos, 'persistence_present', return_value=True):
                with self.assertRaisesRegex(ValueError, 'cancelled'):
                    argos.setup(ask=lambda prompt: 'no')
            self.assertFalse(argos.STATE.exists())

    def test_temporary_setup_requires_explicit_acceptance(self):
        argos = w.runtime()
        with tempfile.TemporaryDirectory() as directory:
            argos.STATE = Path(directory) / 'state.json'
            with patch.object(argos, 'persistence_present', return_value=False):
                argos.setup(ask=lambda prompt: 'no')
            self.assertFalse(argos.STATE.exists())

class LaunchTests(unittest.TestCase):
    def test_existing_ready_assistant_opens_browser_without_second_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'openclaw.json'
            config.write_text(json.dumps({'gateway': {'bind': 'loopback', 'auth': {'token': 'private-test-token'}}}))
            app = w.Welcome.__new__(w.Welcome)
            app.argos = Mock(OC=root)
            app.argos.load.return_value = {'storage': str(root), 'model': 'qwen3:0.6b'}
            app.events = w.queue.Queue()
            app.log_path = root / 'startup.log'
            app.owns_process = False
            app.process = None
            with patch.object(w, 'model_available', return_value=True), patch.object(w, 'ready', return_value=True), patch.object(w.shutil, 'which', return_value='/usr/bin/firefox-esr'), patch.object(w.subprocess, 'Popen') as launch:
                app.start_worker(False, '', False)
                self.assertEqual(launch.call_count, 1)
                args = launch.call_args.args[0]
                self.assertEqual(args[0], '/usr/bin/firefox-esr')
                self.assertIn('/chat#token=', args[1])
            events = list(app.events.queue)
            self.assertIn('done', [kind for kind, value in events])
            self.assertNotIn('private-test-token', str(events))
            self.assertFalse(app.owns_process)

    def test_failed_start_does_not_open_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openclaw.json').write_text(json.dumps({'gateway': {'auth': {'token': 'private-test-token'}}}))
            app = w.Welcome.__new__(w.Welcome)
            app.argos = Mock(OC=root)
            app.argos.load.return_value = {'storage': str(root), 'model': 'qwen3:0.6b'}
            app.events = w.queue.Queue()
            app.log_path = root / 'startup.log'
            app.owns_process = False
            daemon = Mock()
            daemon.poll.return_value = 1
            with patch.object(w, 'model_available', return_value=True), patch.object(w, 'ready', return_value=False), patch.object(w.subprocess, 'Popen', return_value=daemon) as launch:
                app.start_worker(False, '', False)
                self.assertEqual(launch.call_count, 1)
                self.assertEqual(launch.call_args.args[0][-1], 'start')
            self.assertIn('error', [kind for kind, value in app.events.queue])

class FirstSetupTests(unittest.TestCase):
    def test_graphical_worker_sets_up_verified_seed_and_limited_policy(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / 'seed'
            manifest = seed / 'manifests/registry.ollama.ai/library/qwen3/0.6b'
            manifest.parent.mkdir(parents=True)
            blob = b'unit-test-model-artifact'
            digest = 'sha256:' + hashlib.sha256(blob).hexdigest()
            manifest.write_text(json.dumps({'config': {'digest': digest, 'size': len(blob)}, 'layers': []}))
            (seed / 'blobs').mkdir()
            (seed / 'blobs' / digest.replace(':', '-')).write_bytes(blob)
            storage = root / 'models'
            storage.mkdir()
            app = w.Welcome.__new__(w.Welcome)
            app.argos = w.runtime()
            app.argos.SEED = seed
            app.argos.STATE = root / 'config/state.json'
            app.argos.OC = root / 'openclaw'
            app.events = w.queue.Queue()
            app.log_path = root / 'logs/startup.log'
            app.owns_process = False
            app.process = None
            with patch.object(app.argos, 'persistence_present', return_value=True), patch.object(w, 'ready', return_value=True), patch.object(w.shutil, 'which', return_value='/usr/bin/firefox-esr'), patch.object(w.subprocess, 'Popen') as browser:
                app.start_worker(True, str(storage), False)
                self.assertEqual(browser.call_count, 1)
            events = list(app.events.queue)
            self.assertIn('done', [kind for kind, value in events], events)
            state = app.argos.load()
            self.assertTrue(w.model_available(state))
            config = json.loads((app.argos.OC / 'openclaw.json').read_text())
            self.assertEqual(config['tools']['profile'], 'minimal')
            self.assertIn('group:fs', config['tools']['deny'])
            self.assertFalse(config['tools']['elevated']['enabled'])
            self.assertNotIn(config['gateway']['auth']['token'], str(events))

if __name__ == '__main__':
    unittest.main()
