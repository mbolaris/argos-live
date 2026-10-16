import copy
from contextlib import closing
import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_chat', ROOT / 'scripts/smoke-native-chat.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeChatTests(unittest.TestCase):
    def test_native_budget_requires_observed_request_not_catalog_metadata(self):
        module.verify_request_budget({'body_inspected': True, 'num_predict': 32})
        for value in ({}, {'num_predict': 32}, {'body_inspected': True},
                      {'body_inspected': True, 'num_predict': 4096},
                      {'body_inspected': True, 'num_predict': -1}):
            with self.assertRaises(ValueError):
                module.verify_request_budget(value)

    def test_request_report_is_revalidated_before_export(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'
            path.write_text(json.dumps({'num_predict': 32, 'num_ctx': 32768,
                'think': False, 'body_inspected': True, 'request_count': True,
                'message_chars': 'private-canary', 'secret': 'private-canary'}))
            report = module.request_metrics({'ARGOS_NATIVE_REQUEST_REPORT': str(path)})
            self.assertEqual(report, {'num_predict': 32, 'num_ctx': 32768,
                                      'think': False, 'body_inspected': True})
            path.write_text('x' * 32769)
            self.assertEqual(module.request_metrics({'ARGOS_NATIVE_REQUEST_REPORT': str(path)}), {})

    def test_failure_metadata_only_exports_finite_allowlisted_numbers(self):
        secret = 'fictional-private-text'
        raw = {'meta': {'durationMs': 180000, 'aborted': True,
            'agentMeta': {'promptTokens': 9000, 'usage': {'input': 9000, 'output': 33,
                'total': float('inf'), 'cacheRead': True, secret: 123}, 'sessionId': secret},
            'systemPromptReport': {'systemPrompt': {'chars': 34000, 'text': secret},
                'tools': {'schemaChars': 8000, 'promptChars': secret}}, 'error': secret}}
        report = module.failure_diagnostics({}, json.dumps(raw).encode())
        self.assertTrue(report['aborted'])
        self.assertEqual(report['numeric_metadata'], {'duration_ms': 180000,
            'prompt_tokens': 9000, 'usage_input': 9000, 'usage_output': 33,
            'systemPrompt_chars': 34000, 'tools_schemaChars': 8000})
        self.assertNotIn(secret, json.dumps(report))
        for value in ([], {'result': None}, {'meta': None}, {'meta': {'agentMeta': []}},
                      {'meta': {'systemPromptReport': None}}):
            report = module.failure_diagnostics({}, json.dumps(value).encode())
            self.assertEqual(report['numeric_metadata'], {})

    def test_failure_diagnostics_are_bounded_read_only_and_do_not_export_content(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            path = state / 'agents/main/agent/openclaw-agent.sqlite'
            path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('CREATE TABLE transcript_events (created_at INTEGER, event_json TEXT)')
                secret = 'fictional-private-content'
                event = {'message': {'role': 'assistant', 'content': [
                    {'type': 'thinking', 'thinking': secret},
                    {'type': 'toolCall', 'name': 'exec', 'arguments': {'command': secret}},
                    {'type': 'toolCall', 'name': secret}]}}
                connection.executemany('INSERT INTO transcript_events VALUES (?, ?)',
                    [(i, json.dumps(event)) for i in range(70)] +
                    [(71, 'bad json'), (72, 'x' * (1048576 + 1))])
                connection.commit()
            before = path.read_bytes()
            report = module.failure_diagnostics({'OPENCLAW_STATE_DIR': str(state)},
                                                secret.encode(), secret.encode())
            self.assertEqual(report['scanned_events'], 64)
            self.assertEqual(report['skipped_events'], 2)
            self.assertEqual(report['tool_calls']['exec'], 62)
            self.assertEqual(report['tool_calls']['other'], 62)
            self.assertNotIn(secret, json.dumps(report))
            self.assertEqual(path.read_bytes(), before)

    def test_missing_or_unreadable_diagnostics_do_not_mask_command_failure(self):
        self.assertEqual(module.failure_diagnostics({})['transcript_scan'], 'unavailable')
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(module.failure_diagnostics({'OPENCLAW_STATE_DIR': temp})
                             ['transcript_scan'], 'absent')

    def test_outer_timeout_exports_counters_and_still_cleans_process(self):
        process = MagicMock()
        process.communicate.side_effect = module.subprocess.TimeoutExpired(
            ['private-command'], 1, output=b'private-reply', stderr=b'private-token')
        with patch.object(module.subprocess, 'Popen', return_value=process), \
                patch.object(module, 'stop_group') as stop:
            with self.assertRaises(ValueError) as failure:
                module.command('fixture-cli', [], {}, timeout=1)
        text = str(failure.exception)
        self.assertIn('outer deadline exceeded', text)
        self.assertIn('stdout_bytes', text)
        self.assertNotIn('private', text)
        stop.assert_called_once_with(process)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

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
