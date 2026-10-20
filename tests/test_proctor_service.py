import json
import hashlib
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
        runtime_root = self.home / '.local/state/argos-live'
        if os.name != 'nt':
            self.assertEqual(runtime_root.stat().st_mode & 0o077, 0)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(config['agents']['defaults']['model']['temperature'], 0)
        model = config['models']['providers']['ollama']['models'][0]
        self.assertEqual(model['params'], {'think': True, 'temperature': 0})
        self.assertIs(model['reasoning'], True)
        self.assertEqual(config['tools']['alsoAllow'], proctor_service.PROCTOR_TOOL_NAMES)
        self.assertIn('exec', config['tools']['deny'])
        self.assertIn('process', config['tools']['deny'])
        self.assertNotIn('group:runtime', config['tools']['deny'])
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

    def test_campaign_profile_uses_canonical_workspace_and_only_managed_tools(self):
        (self.home / '.openclaw/workspace').mkdir(parents=True)
        root, workspace, config_path, _digest = proctor_service.private_profile(
            self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
            owner_config_path=self.owner_config, purpose='campaign')
        config = json.loads(config_path.read_text())
        self.assertEqual(workspace, (self.home / '.openclaw/workspace').resolve())
        self.assertEqual(config['tools']['alsoAllow'], proctor_service.CAMPAIGN_TOOL_NAMES)
        self.assertIn('argos_audit_instructions', config['tools']['alsoAllow'])
        self.assertIn('group:fs', config['tools']['deny'])
        self.assertIn('exec', config['tools']['deny'])
        self.assertNotIn('argos_proctor_start', config['tools']['alsoAllow'])
        self.assertEqual(config['agents']['defaults']['model']['temperature'], 0)

    def test_improvement_campaign_starts_only_after_completed_practice(self):
        state_path = self.home / '.config/argos-live/state.json'
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({'model': 'qwen3.8:27b'}))
        feedback = {'state': 'COMPLETED', 'correct': 3, 'total': 4}
        campaign = {'status': 'completed', 'saved_evaluation_ids': ['run-1']}
        events = []
        with patch.object(proctor_service, 'run_practice', return_value={
                'status': 'completed', 'result': feedback, 'transcript_id': 'transcript-1'}) as practice, \
             patch.object(proctor_service.startup, 'source', return_value=(self.home / 'Models', 'qwen3.8:27b')), \
             patch.object(proctor_service, 'run_campaign', side_effect=lambda *args, **kwargs:
                          events.append(('campaign', args[3])) or campaign):
            result = proctor_service.run_improvement(self.home, executable='openclaw')
        practice.assert_called_once()
        self.assertEqual(events, [('campaign', feedback)])
        self.assertEqual(result['campaign'], campaign)
        self.assertIs(result['practice_is_improvement_evidence'], False)

    def test_incomplete_practice_never_starts_campaign(self):
        with patch.object(proctor_service, 'run_practice', return_value={
                'status': 'completed', 'result': {'state': 'INCOMPLETE'}}), \
             patch.object(proctor_service, 'run_campaign') as campaign:
            with self.assertRaisesRegex(ValueError, 'Practice did not complete'):
                proctor_service.run_improvement(self.home)
        campaign.assert_not_called()

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

    def test_session_subject_binds_verified_model_receipt_and_can_start_exam(self):
        original_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.as_posix() == '/proc/sys/kernel/random/boot_id':
                return 'synthetic-boot'
            return original_read_text(path, *args, **kwargs)

        def create_test_key(path, executable='openssl'):
            Path(path).write_bytes(b'test signing key placeholder')

        class TestSigner:
            def __init__(self, *_args, **_kwargs):
                pass

        cartridge = proctor_service.default_cartridge(self.home)
        with patch.object(Path, 'read_text', read_text), \
             patch.object(proctor_service, 'generate_key', create_test_key), \
             patch.object(proctor_service, 'Ed25519Signer', TestSigner):
            model_identity = {
                'schema': 'argos-verified-model/1', 'tag': 'fixture:latest',
                'catalog_manifest_digest': 'sha256:' + 'a' * 64,
                'local_manifest_sha256': hashlib.sha256(
                    b'synthetic fixture model manifest\n').hexdigest(),
                'artifacts': [{'digest': 'sha256:' + 'b' * 64, 'size': 7,
                               'media_type': 'application/vnd.ollama.image.model'}],
                'verified_bytes': 7,
                'verification': 'catalog manifest and every declared model blob SHA-256 verified',
            }
            model_identity['sha256'] = hashlib.sha256(json.dumps(
                model_identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            bad_identity = dict(model_identity, sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'checksum is invalid'):
                proctor_service.make_session(
                    self.home, cartridge, 'pilot-a', 'fixture:latest', 'b' * 64,
                    model_identity=bad_identity)
            incomplete_identity = dict(model_identity, verified_bytes=6)
            unsigned_identity = {key: value for key, value in incomplete_identity.items() if key != 'sha256'}
            incomplete_identity['sha256'] = hashlib.sha256(json.dumps(
                unsigned_identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            with self.assertRaisesRegex(ValueError, 'complete blob verification'):
                proctor_service.make_session(
                    self.home, cartridge, 'pilot-a', 'fixture:latest', 'b' * 64,
                    model_identity=incomplete_identity)
            self.assertFalse((self.home / '.local/state/argos-live/proctor/caller.token').exists())
            db, exam, _cart = proctor_service.make_session(
                self.home, cartridge, 'pilot-a', 'fixture:latest', 'b' * 64,
                model_identity=model_identity)
        try:
            status = exam.start('start-operation')
            self.assertEqual(status['state'], 'ACTIVE')
            row = db.execute('SELECT subject_json FROM sessions WHERE session_id=?',
                             (exam.session_id,)).fetchone()
            subject = json.loads(row['subject_json'])
            self.assertEqual(subject['model_tag'], 'fixture:latest')
            self.assertEqual(subject['model_digest'], model_identity['sha256'])
            self.assertEqual(subject['model_identity'], model_identity)
            self.assertEqual(subject['configuration']['profile_sha256'], 'b' * 64)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
