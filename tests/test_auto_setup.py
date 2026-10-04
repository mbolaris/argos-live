from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, starter
spec = importlib.util.spec_from_file_location('argos_auto_fixture', ROOT / 'runtime/argos.py')
argos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(argos)


class AutoSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.models = self.root / 'public-data/ArgosLive/Models/catalog'
        self.state = self.home / '.config/argos-live/state.json'
        self.config = self.home / '.openclaw/openclaw.json'
        self.seed = {'tag': starter.TAG, 'manifest_digest': 'sha256:' + 'a' * 64, 'verified_bytes': 42}

    def configure(self, active=False, **options):
        return auto_setup.configure(self.home,
            planner=lambda budget: {'path': str(self.models), 'kind': 'ram' if not active else 'disk',
                                    'encrypted': None if not active else False, 'volume_uuid': None},
            verify_seed=lambda: self.seed,
            probe_persistence=lambda: {'active': active, 'encrypted': True if active else None}, **options)

    def test_try_and_persistent_setup_are_questionless_and_keep_weights_in_image(self):
        for active in (False, True):
            with self.subTest(active=active):
                # A separate fixture per mode; no owner files or network.
                self.home = self.root / ('persistent' if active else 'try')
                self.home.mkdir()
                self.models = self.root / ('disk-models' if active else 'ram-models')
                self.state = self.home / '.config/argos-live/state.json'
                self.config = self.home / '.openclaw/openclaw.json'
                events = []
                with patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
                    result = self.configure(active, progress=events.append)
                self.assertEqual(result['mode'], 'persistent' if active else 'try')
                self.assertEqual(result['model_source'], 'bundled')
                self.assertEqual(result['storage_encrypted'], False if active else None)
                self.assertEqual(result['persistence_encrypted'], True if active else None)
                self.assertEqual([path.name for path in self.models.iterdir()], ['.argos-storage-id'])
                state = json.loads(self.state.read_text())
                config = json.loads(self.config.read_text())
                self.assertEqual(state['storage_id'], (self.models / '.argos-storage-id').read_text().strip())
                self.assertEqual(config['gateway']['bind'], 'loopback')
                self.assertEqual(len(config['gateway']['auth']['token']), 64)
                self.assertFalse(config['tools']['elevated']['enabled'])
                self.assertEqual(config['tools']['profile'], 'minimal')
                self.assertIn('group:fs', config['tools']['deny'])
                self.assertFalse(config['commands']['bash'])
                self.assertNotIn('token', json.dumps(result))
                self.assertEqual(events[-1]['phase'], 'configured')
                if os.name != 'nt':
                    self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(self.config.parent.stat().st_mode & 0o777, 0o700)

    def test_existing_state_and_owner_permissions_reused_byte_for_byte(self):
        self.configure()
        value = json.loads(self.config.read_text())
        value['tools']['elevated']['enabled'] = True  # Fictional owner-selected policy.
        self.config.write_text(json.dumps(value))
        before = self.state.read_bytes(), self.config.read_bytes()
        with patch('builtins.input', side_effect=AssertionError('prompt')):
            result = self.configure()
        self.assertEqual(result['status'], 'existing')
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), before)
        (self.models / '.argos-storage-id').write_text('wrong identity')
        with self.assertRaises(ValueError):
            self.configure()
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), before)

    def test_owner_config_without_state_and_nonempty_model_location_are_not_adopted(self):
        self.config.parent.mkdir()
        self.config.write_bytes(b'owner configuration')
        with self.assertRaisesRegex(ValueError, 'will not replace'):
            self.configure()
        self.assertEqual(self.config.read_bytes(), b'owner configuration')
        self.assertFalse(self.models.exists())
        self.config.unlink()
        self.models.mkdir(parents=True)
        (self.models / 'owner-model').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'will not adopt'):
            self.configure()
        self.assertEqual((self.models / 'owner-model').read_bytes(), b'keep')
        self.assertFalse(self.state.exists())

    def test_integrity_storage_and_unknown_persistence_fail_before_writes(self):
        for key in ('verify_seed', 'planner', 'probe_persistence'):
            options = {'planner': lambda _: {'path': str(self.models), 'kind': 'ram'},
                       'verify_seed': lambda: self.seed,
                       'probe_persistence': lambda: {'active': False}}
            def failure(*args):
                raise ValueError('fixture unavailable')
            options[key] = failure
            with self.assertRaises(ValueError):
                auto_setup.configure(self.home, **options)
            self.assertEqual(list(self.home.iterdir()), [])
            self.assertFalse(self.models.exists())

    def test_failed_publication_removes_own_files_but_keeps_changed_owner_config(self):
        original = auto_setup.publish_new
        def fail_state(path, value, journal):
            if path == self.state:
                self.config.write_bytes(b'owner changed this during setup')
                raise OSError('fixture disk full')
            return original(path, value, journal)
        with patch('argoslive.auto_setup.publish_new', fail_state):
            with self.assertRaises(OSError):
                self.configure()
        self.assertEqual(self.config.read_bytes(), b'owner changed this during setup')
        self.assertFalse(self.state.exists())
        self.assertFalse((self.models / '.argos-storage-id').exists())
        self.assertEqual(list(self.home.rglob('.setup-*')), [])

    def test_racing_owner_file_is_not_replaced(self):
        original = auto_setup.os.link
        def race(source, destination):
            if destination == self.config:
                destination.write_bytes(b'owner racing configuration')
            return original(source, destination)
        with patch('argoslive.auto_setup.os.link', race):
            with self.assertRaises(FileExistsError):
                self.configure()
        self.assertEqual(self.config.read_bytes(), b'owner racing configuration')
        self.assertFalse(self.state.exists())
        self.assertFalse((self.models / '.argos-storage-id').exists())

    def test_cli_auto_json_has_no_prompt_or_generated_credentials(self):
        result = {'status': 'created', 'model': starter.TAG, 'mode': 'try'}
        output = io.StringIO()
        with patch('argoslive.auto_setup.configure', return_value=result), redirect_stdout(output), \
                patch('builtins.input', side_effect=AssertionError('prompt')):
            self.assertEqual(argos.main(['setup', '--auto', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), result)
        args = argos.command_parser().parse_args(['setup', '--auto'])
        self.assertTrue(args.auto)

    def test_bundled_server_points_to_image_not_selected_download_store(self):
        from contextlib import nullcontext
        with patch.object(argos, 'request', side_effect=[OSError('not running'), nullcontext()]), \
                patch.object(argos.subprocess, 'Popen') as spawn, \
                patch('argoslive.starter.read_only') as verify:
            spawn.return_value.poll.return_value = None
            argos.server({'storage': str(self.models), 'model_source': 'bundled', 'model': starter.TAG})
        verify.assert_called_once_with(argos.SEED)
        self.assertEqual(spawn.call_args.kwargs['env']['OLLAMA_MODELS'], str(argos.SEED))
        self.assertEqual(spawn.call_args.kwargs['env']['OLLAMA_NOPRUNE'], '1')
        self.assertFalse(self.models.exists())


if __name__ == '__main__':
    unittest.main()
