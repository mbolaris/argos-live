import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_chat', ROOT / 'scripts/smoke-native-chat.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeChatTests(unittest.TestCase):
    def setUp(self):
        self.reply = {'payloads': [{'text': 'Hello from the local fixture.'}],
            'meta': {'agentMeta': {'provider': 'ollama', 'model': 'qwen3:0.6b'}}}

    def test_accepts_native_local_reply_and_only_exports_readiness_metadata(self):
        for result in (self.reply, {'result': self.reply}):
            report = module.summary(json.dumps(result).encode())
            self.assertTrue(report['reply_verified'])
            self.assertEqual(report['reply_bytes'], len(self.reply['payloads'][0]['text']))
            self.assertFalse(report['effective_tool_denial_verified'])
            self.assertNotIn('Hello', json.dumps(report))

    def test_failure_identity_missing_text_and_invalid_shapes_are_not_ready(self):
        cases = [[], {'result': None}, {'result': []}, {'meta': False},
                 {'meta': {'agentMeta': []}}, {'ok': False, **self.reply},
                 {'status': 'timeout', **self.reply}]
        for path, value in ((('meta', 'agentMeta', 'provider'), 'cloud-fixture'),
                            (('meta', 'agentMeta', 'model'), 'unexpected-model'),
                            (('meta', 'error'), {'message': 'fictional failure'}),
                            (('payloads',), []), (('payloads',), [None]),
                            (('payloads',), [{'text': ''}]), (('payloads',), [{'text': 42}])):
            result = copy.deepcopy(self.reply)
            node = result
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            cases.append(result)
        for result in cases:
            with self.subTest(result=result), self.assertRaises(ValueError):
                module.summary(json.dumps(result).encode())
        with self.assertRaises(ValueError):
            module.summary(b' ' * (1024**2 + 1))

    def test_disposable_child_cannot_inherit_owner_credentials_or_state(self):
        with patch.dict(module.os.environ, {'PATH': 'fixture-bin', 'HOME': 'owner-home',
                'OPENAI_API_KEY': 'fictional', 'GITHUB_TOKEN': 'fictional',
                'HTTPS_PROXY': 'fictional', 'OLLAMA_HOST': 'owner-host',
                'OPENCLAW_CONFIG_PATH': 'owner-config'}, clear=True):
            env = module.child_environment(Path('/disposable/fixture'))
        self.assertEqual(env['PATH'], 'fixture-bin')
        self.assertEqual(env['HOME'], str(Path('/disposable/fixture')))
        self.assertEqual(env['OPENCLAW_CONFIG_PATH'], str(Path('/disposable/fixture/.openclaw/openclaw.json')))
        self.assertTrue(set(env).isdisjoint({'OPENAI_API_KEY', 'GITHUB_TOKEN', 'HTTPS_PROXY', 'OLLAMA_HOST'}))
