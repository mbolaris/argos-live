import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.web import status
from argoslive.ollama import NotRunning


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.openclaw/openclaw.json'
        self.config.parent.mkdir()
        self.hardware = lambda dirs: {'cpu': {'model': None, 'threads': None},
            'ram': {'total_bytes': None, 'available_bytes': None}, 'gpus': None,
            'model_directories': [{'free_bytes': 42}] if dirs else []}
        self.client = Mock()
        self.client.version.return_value = '0.35.0'
        self.client.ps.return_value = {'models': [{'name': 'qwen3:0.6b', 'size': 100, 'size_vram': 0}]}

    def snapshot(self, **kw):
        return status.snapshot(self.home, hardware=self.hardware, client=self.client,
                               run=lambda args: '[]' if args[0] == 'ip' else None,
                               proc=self.home / 'absent-proc', **kw)

    def test_unknown_persistence_and_offline_cpu_backend(self):
        result = self.snapshot()
        self.assertIsNone(result['persistence']['active'])
        self.assertFalse(result['network']['default_route'])
        self.assertFalse(result['network']['internet_verified'])
        self.assertTrue(result['ollama']['reachable'])
        self.assertFalse(result['ollama']['ownership_verified'])
        self.assertEqual(result['ollama']['loaded_models'][0]['backend']['mode'], 'CPU')
        self.assertIsNone(result['hardware']['ram']['total_bytes'])

    def test_gateway_config_whitelist_and_no_secrets_in_status(self):
        self.config.write_text(json.dumps({'gateway': {'mode': 'local', 'bind': 'loopback',
                               'auth': {'mode': 'token', 'token': 'fictional-secret'}}}))
        result = self.snapshot(ready=lambda origin: True)
        self.assertEqual(result['assistant'], 'ready')
        self.assertTrue(result['chat_available'])
        self.assertNotIn('fictional-secret', json.dumps(result))

    def test_network_gateway_rejected_without_probe(self):
        self.config.write_text(json.dumps({'gateway': {'bind': 'lan'}}))
        ready = Mock()
        result = self.snapshot(ready=ready)
        self.assertEqual(result['assistant'], 'configuration-needs-attention')
        self.assertFalse(result['chat_available'])
        ready.assert_not_called()

    def test_model_storage_marker_read_only_and_no_fallback(self):
        models = self.home / 'models'
        models.mkdir()
        (models / '.argos-storage-id').write_text('fixture-owner')
        configured = self.home / '.config/argos-live/state.json'
        configured.parent.mkdir(parents=True)
        configured.write_text(json.dumps({'storage': str(models), 'storage_id': 'fixture-owner', 'model': 'qwen3:0.6b'}))
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result = self.snapshot()
        self.assertEqual(result['model_storage']['state'], 'available')
        self.assertEqual(result['model_storage']['free_bytes'], 42)
        self.assertIsNone(result['model_storage']['encrypted'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        (models / '.argos-storage-id').unlink()
        result = self.snapshot()
        self.assertEqual(result['model_storage']['state'], 'needs-attention')
        self.assertIsNone(result['model_storage']['path'])

    def test_persistence_encryption_from_block_ancestry(self):
        mount = {'target': '/run/live/persistence/fixture', 'device': '253:0', 'source': '/dev/dm-0'}
        blocks = {'253:0': {'name': '/dev/dm-0', 'encrypted_paths': [True]}}
        with patch.object(Path, 'is_file', return_value=True):
            result = status.persistence([mount], blocks)
        self.assertTrue(result['active'])
        self.assertTrue(result['encrypted'])
        blocks['253:0']['encrypted_paths'] = [True, False]
        self.assertIsNone(status.encryption(mount, blocks))

    def test_failed_service_is_not_ready(self):
        self.client.version.side_effect = NotRunning('private-path-never-returned')
        self.config.write_text(json.dumps({'gateway': {'auth': {'token': 'fictional-secret'}}}))
        result = self.snapshot(ready=lambda origin: False)
        self.assertFalse(result['ollama']['reachable'])
        self.assertEqual(result['assistant'], 'not-ready')
        self.assertFalse(result['chat_available'])
        self.assertNotIn('private-path', json.dumps(result))

    def test_failed_loaded_model_probe_is_unknown_not_empty(self):
        self.client.ps.side_effect = NotRunning('fixture failure')
        result = self.snapshot()
        self.assertTrue(result['ollama']['reachable'])
        self.assertIsNone(result['ollama']['loaded_models'])

    def test_liveness_is_not_gateway_readiness(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok":true}'
        with patch.object(status, 'build_opener', return_value=Mock(open=Mock(return_value=response))):
            self.assertFalse(status.gateway_ready('http://127.0.0.1:18789'))
            response.read.return_value = b'{"ready":true}'
            self.assertTrue(status.gateway_ready('http://127.0.0.1:18789'))

    def test_chat_requires_local_ready_token_mode_and_uses_fragment(self):
        self.config.write_text(json.dumps({'gateway': {'auth': {'token': 'fixture/secret'}}}))
        url = status.chat_url(self.config, ready=lambda origin: True)
        self.assertEqual(url, 'http://127.0.0.1:18789/chat#token=fixture%2Fsecret')
        with self.assertRaisesRegex(ValueError, 'not ready'):
            status.chat_url(self.config, ready=lambda origin: False)
        self.config.write_text(json.dumps({'gateway': {'auth': {'mode': 'password', 'password': 'fixture'}}}))
        with self.assertRaisesRegex(ValueError, 'not configured'):
            status.chat_url(self.config, ready=lambda origin: True)

    def test_bound_configuration_read(self):
        self.config.write_bytes(b' ' * (1024**2 + 1))
        with self.assertRaisesRegex(ValueError, 'too large'):
            status.read_json(self.config)
