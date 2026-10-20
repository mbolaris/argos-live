import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import evaluation_context as ec
from argoslive.assistant_trial import OpenClawRunner


class EvaluationIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.workspace = self.home / '.openclaw/workspace'
        self.workspace.mkdir(parents=True)
        (self.workspace / 'AGENTS.md').write_text('Owner campaign instructions', encoding='utf-8')
        (self.workspace / 'IMPROVEMENT-LOG.md').write_text('Private campaign history')
        (self.workspace / 'tools').mkdir()
        (self.workspace / 'tools/control.py').write_text('dangerous controller')
        self.config = self.home / '.openclaw/openclaw.json'
        self.value = {
            'agents': {'defaults': {'workspace': str(self.workspace), 'model': {'primary': 'ollama/fixture'}}},
            'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434',
                'apiKey': 'owner-secret', 'models': [{'id': 'fixture', 'name': 'fixture',
                    'agentRuntime': {'id': 'external-harness'}}]}}},
            'plugins': {'entries': {'argos-live': {'enabled': True}}},
            'gateway': {'auth': {'token': 'private-gateway-token'}},
            'env': {'SECRET': 'never-copy'},
        }
        self.config.write_text(json.dumps(self.value))

    def test_inputs_copied_but_tools_sessions_and_credentials_are_not(self):
        original = self.config.read_bytes()
        with ec.isolated(self.home, self.workspace) as (home, config, workspace):
            self.assertNotEqual(home, self.home)
            self.assertEqual((workspace / 'AGENTS.md').read_bytes(), (self.workspace / 'AGENTS.md').read_bytes())
            self.assertFalse((workspace / 'tools').exists())
            self.assertFalse((workspace / 'IMPROVEMENT-LOG.md').exists())
            value = json.loads(config.read_bytes())
            self.assertEqual(value['tools'], {'deny': ['*'], 'toolSearch': False})
            self.assertEqual(value['plugins']['allow'], ['ollama'])
            self.assertEqual(value['plugins']['entries'], {'ollama': {'enabled': True}})
            self.assertEqual(value['plugins']['slots']['memory'], 'none')
            self.assertEqual(value['agents']['defaults']['heartbeat']['every'], '0m')
            self.assertEqual(value['agents']['defaults']['models']['ollama/fixture']['agentRuntime']['id'], 'openclaw')
            raw = config.read_text()
            for secret in ('owner-secret', 'private-gateway-token', 'never-copy', 'external-harness'):
                self.assertNotIn(secret, raw)
            (workspace / 'AGENTS.md').write_text('Modified evaluation copy')
        self.assertFalse(home.exists())
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual((self.workspace / 'AGENTS.md').read_text(), 'Owner campaign instructions')

    def test_cli_is_local_with_ephemeral_environment_and_cwd(self):
        observed = []
        original_embedded = OpenClawRunner._embedded_turn
        def embedded(runner, text, timeout, home, config, workspace):
            # Exercise the actual CLI assembly and reply parsing while inspecting
            # policy at launch time, before the temporary state is cleaned up.
            with patch('argoslive.assistant_trial.subprocess.Popen') as spawn:
                process = spawn.return_value.__enter__.return_value
                process.returncode = 0
                def communicate(timeout):
                    command = spawn.call_args.args[0]
                    sid = command[command.index('--session-id') + 1]
                    return json.dumps({'result': {'payloads': [{'text': 'C'}], 'meta': {
                        'agentMeta': {'sessionId': sid, 'provider': 'ollama', 'model': 'fixture'}}}}).encode(), b''
                process.communicate.side_effect = communicate
                answer = original_embedded(runner, text, timeout, home, config, workspace)
                command, options = spawn.call_args.args[0], spawn.call_args.kwargs
                self.assertIn('--local', command)
                self.assertEqual(options['env']['HOME'], str(home))
                self.assertEqual(options['env']['OPENCLAW_STATE_DIR'], str(config.parent))
                self.assertEqual(options['cwd'], workspace)
                observed.append(home)
                return answer
        with patch.object(OpenClawRunner, '_embedded_turn', embedded):
            runner = OpenClawRunner(self.home, executable='openclaw')
            self.assertEqual(runner.turn('Which planet?')['text'], 'C')
            self.assertEqual(runner.turn('Which planet?')['text'], 'C')
        self.assertNotEqual(observed[0], observed[1])
        self.assertTrue(all(not home.exists() for home in observed))
        self.assertFalse((self.home / '.openclaw/agents').exists())

    def test_generation_scopes_and_main_selection_survive_isolation(self):
        defaults = self.value['agents']['defaults']
        defaults['model'] = {'primary': 'ollama/unused'}
        defaults['params'] = {'temperature': 0.2}
        defaults['models'] = {'ollama/fixture': {'params': {'topP': 0.7}}}
        self.value['agents']['list'] = [{'id': 'main', 'model': 'ollama/fixture',
            'params': {'temperature': 0.3}, 'models': {'ollama/fixture': {'params': {'thinking': 'low'}}}}]
        self.value['models']['providers']['ollama']['models'][0]['params'] = {'num_ctx': 8192}
        self.config.write_text(json.dumps(self.value))
        receipt = ec.configuration_receipt(self.home)
        with ec.isolated(self.home, self.workspace) as (_, path, _):
            copied = json.loads(path.read_bytes())
            self.assertEqual(copied['agents']['defaults']['model']['primary'], 'ollama/fixture')
            self.assertEqual(copied['agents']['defaults']['params'], {'temperature': 0.2})
            self.assertEqual(copied['agents']['entries']['main']['params'], {'temperature': 0.3})
            self.assertEqual(copied['models']['providers']['ollama']['models'][0]['params'], {'num_ctx': 8192})
        self.assertEqual(receipt['configured_generation']['agent_model_params'], {'thinking': 'low'})

    def test_canonical_roster_is_used_for_model_and_workspace_selection(self):
        self.value['agents']['entries'] = {'main': {'workspace': str(self.workspace), 'model': 'ollama/fixture',
                                                   'params': {'temperature': 0.4}}}
        self.value['agents']['list'] = [{'id': 'main', 'model': 'ollama/absent'}]
        self.config.write_text(json.dumps(self.value))
        config = ec.configuration(self.home)
        self.assertNotIn('list', config['agents'])
        self.assertEqual(config['agents']['entries']['main']['params'], {'temperature': 0.4})

    def test_private_parameter_values_are_digested_and_changes_are_detected(self):
        self.value['agents']['defaults']['params'] = {'stop': ['private-stop-canary'],
            'format': {'private-schema-canary': {'type': 'string'}}}
        self.config.write_text(json.dumps(self.value))
        first = ec.configuration_receipt(self.home)
        self.assertNotIn('private-stop-canary', json.dumps(first))
        self.assertNotIn('private-schema-canary', json.dumps(first))
        self.value['agents']['defaults']['params']['stop'] = ['changed']
        self.config.write_text(json.dumps(self.value))
        self.assertNotEqual(first['sha256'], ec.configuration_receipt(self.home)['sha256'])
        for params in ({'headers': {'Authorization': 'secret'}}, {'temperature': True},
                       {'topP': float('inf')}, {'thinking': 'invented'}):
            with self.assertRaises(ValueError):
                ec.parameters(params)

    def test_remote_provider_is_rejected_before_launch(self):
        self.value['models']['providers']['ollama']['baseUrl'] = 'https://example.com'
        self.config.write_text(json.dumps(self.value))
        with patch('argoslive.assistant_trial.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'localhost'):
                OpenClawRunner(self.home, executable='openclaw').turn('task')
            spawn.assert_not_called()

    def test_linked_workspace_input_is_refused(self):
        with patch.object(ec.storage, 'safe_local', side_effect=lambda p: (_ for _ in ()).throw(ValueError('link'))
                          if p.name == 'AGENTS.md' else p):
            with self.assertRaisesRegex(ValueError, 'link'):
                with ec.isolated(self.home, self.workspace):
                    self.fail('linked input accepted')

    def test_missing_model_selection_preserves_both_files_without_prompt(self):
        spec = importlib.util.spec_from_file_location('argos_selection_cli', ROOT / 'runtime/argos.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        state_path = self.home / 'state.json'
        state = {'model': 'fixture', 'storage': str(self.home / 'models')}
        state_path.write_text(json.dumps(state))
        before = (state_path.read_bytes(), self.config.read_bytes())
        with patch.object(cli, 'load', return_value=state), patch.object(cli, 'STATE', state_path), \
                patch.object(cli, 'OC', self.config.parent), patch('builtins.input') as prompt:
            with self.assertRaisesRegex(ValueError, 'before selecting'):
                cli.select_model('qwen3:30b')
            prompt.assert_not_called()
        self.assertEqual((state_path.read_bytes(), self.config.read_bytes()), before)

    def test_pending_legacy_trial_blocks_gateway_without_rewriting_database(self):
        path = self.home / '.openclaw/agents/main/agent/openclaw-agent.sqlite'
        path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE session_nodes(session_key TEXT,status TEXT)')
            db.execute('INSERT INTO session_nodes VALUES (?,?)', ('agent:main:argos-trial-old', 'running'))
        before = path.read_bytes()
        with patch('argoslive.owned_gateway.sys.platform', 'linux'), patch('subprocess.Popen') as spawn:
            from argoslive.owned_gateway import owned
            with self.assertRaisesRegex(ValueError, 'legacy evaluation'):
                with owned(self.home):
                    self.fail('gateway launched over legacy work')
            spawn.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE session_nodes SET status='done'")
        ec.require_no_legacy_trials(self.home)

    def test_unreadable_legacy_session_database_fails_closed(self):
        path = self.home / '.openclaw/agents/main/agent/openclaw-agent.sqlite'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'not a SQLite database')
        with self.assertRaisesRegex(ValueError, 'owner review'):
            ec.require_no_legacy_trials(self.home)


if __name__ == '__main__':
    unittest.main()
