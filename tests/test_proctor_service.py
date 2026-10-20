import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, proctor_service


class ProctorServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.owner_config = self.home / '.openclaw/openclaw.json'
        self.owner_config.parent.mkdir(parents=True)
        workspace = self.home / '.openclaw/workspace'
        owner = auto_setup.conversation_config('qwen3.8:27b', workspace, plugin_root='/opt/argos/plugins')
        owner['agents']['defaults']['model']['temperature'] = 0
        owner['models']['providers']['ollama']['models'][0].update(
            reasoning=True, params={'think': True, 'temperature': 0})
        self.owner_config.write_text(json.dumps(owner))

    def test_profile_is_persistent_restricted_and_preserves_model_controls(self):
        root, workspace, config_path, first_hash = proctor_service.private_profile(
            self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
            owner_config_path=self.owner_config)
        config = json.loads(config_path.read_text())
        self.assertEqual(root, self.home / '.local/state/argos-live/proctor')
        self.assertTrue(workspace.is_dir())
        self.assertEqual(config['agents']['defaults']['model']['temperature'], 0)
        model = config['models']['providers']['ollama']['models'][0]
        self.assertEqual(model['params'], {'think': True, 'temperature': 0})
        self.assertIs(model['reasoning'], True)
        self.assertEqual(config['tools']['alsoAllow'], proctor_service.PROCTOR_TOOL_NAMES)
        self.assertIn('exec', config['tools']['deny'])
        self.assertIn('group:runtime', config['tools']['deny'])
        self.assertNotIn('group:fs', config['tools']['alsoAllow'])
        self.assertEqual(config['plugins']['allow'], ['argos-improve'])
        self.assertIs(config['plugins']['entries']['argos-improve']['config']['hostAdmission'], True)
        self.assertIs(config['plugins']['entries']['argos-improve']['hooks']['allowConversationAccess'], True)
        second = proctor_service.private_profile(self.home, 'qwen3.8:27b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        self.assertEqual(second[2], config_path)
        self.assertEqual(second[3], first_hash)
        self.assertEqual(json.loads(config_path.read_text()), config)

    def test_model_specific_profile_does_not_overwrite_prior_snapshot(self):
        first = proctor_service.private_profile(self.home, 'qwen3.8:27b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        other_config = json.loads(self.owner_config.read_text())
        other_config['agents']['defaults']['model']['primary'] = 'ollama/qwen3:14b'
        other_config['models']['providers']['ollama']['models'].append(
            {'id': 'qwen3:14b', 'name': 'qwen3:14b', 'input': ['text'], 'reasoning': False})
        self.owner_config.write_text(json.dumps(other_config))
        second = proctor_service.private_profile(self.home, 'qwen3:14b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        self.assertNotEqual(first[2], second[2])
        self.assertTrue(first[2].is_file())
        self.assertTrue(second[2].is_file())

    def test_remote_or_unmatched_owner_model_profile_is_rejected(self):
        owner = json.loads(self.owner_config.read_text())
        owner['models']['providers']['ollama']['baseUrl'] = 'https://example.invalid'
        self.owner_config.write_text(json.dumps(owner))
        with self.assertRaisesRegex(ValueError, 'needs review'):
            proctor_service.private_profile(self.home, 'qwen3.8:27b',
                plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)

    def test_existing_gateway_is_refused_before_any_proctor_reservation(self):
        _root, _workspace, config_path, _digest = proctor_service.private_profile(
            self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
            owner_config_path=self.owner_config)
        with patch('argoslive.proctor_service.socket.create_connection') as connect:
            connect.return_value.__enter__.return_value = object()
            with self.assertRaisesRegex(ValueError, 'Stop the existing OpenClaw gateway'):
                proctor_service.refuse_live_gateway(config_path)
        with patch('argoslive.proctor_service.socket.create_connection', side_effect=OSError):
            proctor_service.refuse_live_gateway(config_path)

    def test_existing_backend_is_refused_and_absent_backend_is_allowed(self):
        with patch('argoslive.proctor_service.socket.create_connection') as connect:
            connect.return_value.__enter__.return_value = object()
            with self.assertRaisesRegex(ValueError, 'Stop the existing Ollama service'):
                proctor_service.refuse_live_backend()
        with patch('argoslive.proctor_service.socket.create_connection', side_effect=OSError):
            proctor_service.refuse_live_backend()

    def test_private_service_secret_is_reused_and_never_overwritten(self):
        path = self.home / 'secret'
        first = proctor_service._secret(path)
        second = proctor_service._secret(path)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_bundled_pilot_is_content_addressed_and_explicitly_uncalibrated(self):
        first = proctor_service.default_cartridge(self.home)
        second = proctor_service.default_cartridge(self.home)
        self.assertEqual(first, second)
        cartridge = proctor_service.proctor.Cartridge(first)
        self.assertEqual(cartridge.manifest['calibration_status'], 'uncalibrated')
        self.assertEqual(cartridge.manifest['cartridge_id'], 'argos-practice-pilot')
        self.assertIn('pilot-a', cartridge.forms)
        self.assertEqual(len(cartridge.items), 4)


if __name__ == '__main__':
    unittest.main()
