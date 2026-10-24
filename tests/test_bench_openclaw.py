import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, auto_setup, bench_openclaw, results
from argoslive.assistant_trial import TrialTurnError


class FakeOpenClaw:
    def __init__(self, fail_at=None, suite='quick'):
        self.tasks = {item['prompt']: item for item in ability.load(suite)['items']}
        self.calls = 0
        self.fail_at = fail_at

    def turn(self, prompt):
        self.calls += 1
        if self.calls == self.fail_at:
            raise TrialTurnError('assistant-error')
        item = self.tasks[prompt]
        return {'text': item['reference'], 'elapsed_seconds': 0.1,
                'session_id': f'session-{self.calls}', 'provider': 'ollama',
                'model': 'qwen3:4b-instruct-2507-q4_K_M'}


def configure_fake(home, workspace):
    (home / '.openclaw').mkdir(parents=True, exist_ok=True)
    (home / '.openclaw/openclaw.json').write_text(json.dumps(auto_setup.conversation_config(
        'qwen3:4b-instruct-2507-q4_K_M', workspace)), encoding='utf-8')


class OpenClawBenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        (home / '.openclaw/workspace').mkdir(parents=True)
        configure_fake(home, home / '.openclaw/workspace')
        patcher = patch.object(Path, 'home', return_value=Path(temporary.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_records_suite_and_workspace_instruction_fingerprints(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            instructions = workspace / 'AGENTS.md'
            instructions.write_text('Original instructions\n', encoding='utf-8')
            config = home / '.openclaw/openclaw.json'
            configure_fake(home, workspace)
            result = bench_openclaw.run(home=home, runner=FakeOpenClaw())
            suite_path = ability.DATA / 'quick.json'
            self.assertEqual(result['settings']['suite_sha256'], hashlib.sha256(suite_path.read_bytes()).hexdigest())
            self.assertEqual(result['prompt_fingerprint']['workspace_agents_sha256'],
                             hashlib.sha256(instructions.read_bytes()).hexdigest())
            self.assertEqual(len(result['prompt_fingerprint']['workspace_context_sha256']), 64)

    def test_challenge_form_is_a_distinct_saved_suite_with_full_coverage(self):
        result = bench_openclaw.run(suite='challenge', runner=FakeOpenClaw(suite='challenge'))
        self.assertEqual(result['suite'], 'openclaw-challenge')
        self.assertEqual(result['suite_version'], 'argos-openclaw-ability/challenge/1.0.0')
        self.assertEqual(result['coverage'], {'completed': 40, 'total': 40, 'complete': True})
        self.assertEqual(result['summary']['correct'], 40)
        self.assertEqual(len(result['settings']['suite_sha256']), 64)

    def test_tool_schema_form_records_partition_scores_and_full_coverage(self):
        result = bench_openclaw.run(suite='tool-schema', runner=FakeOpenClaw(suite='tool-schema'))
        self.assertEqual(result['suite'], 'openclaw-tool-schema')
        self.assertEqual(result['suite_version'], 'argos-openclaw-ability/tool-schema/1.0.0')
        self.assertEqual(result['coverage'], {'completed': 40, 'total': 40, 'complete': True})
        self.assertEqual(result['summary']['partitions']['practice']['correct'], 20)
        self.assertEqual(result['summary']['partitions']['heldout']['correct'], 20)
        self.assertTrue(all(item.get('partition') in ('practice', 'heldout') for item in result['items']))

    def test_copied_context_presence_and_changes_invalidate_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            (workspace / 'AGENTS.md').write_text('Guide\n', encoding='utf-8')
            configure_fake(home, workspace)

            class AddingPersona(FakeOpenClaw):
                def turn(self, prompt):
                    answer = super().turn(prompt)
                    if self.calls == 2:
                        (workspace / 'SOUL.md').write_text('New persona\n', encoding='utf-8')
                    return answer

            result = bench_openclaw.run(home=home, runner=AddingPersona())
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(result['failure_code'], 'workspace-changed-during-run')
            self.assertEqual((workspace / 'SOUL.md').read_text(encoding='utf-8'), 'New persona\n')

    def test_no_answer_is_scored_wrong_and_the_run_continues(self):
        class SilentOnce(FakeOpenClaw):
            def turn(self, prompt):
                if self.calls == 16:
                    self.calls += 1
                    raise TrialTurnError('empty-reply')
                return super().turn(prompt)

        result = bench_openclaw.run(runner=SilentOnce())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['coverage'], {'completed': 20, 'total': 20, 'complete': True})
        silent = result['items'][16]
        self.assertTrue(silent['no_reply'])
        self.assertEqual((silent['score'], silent['outcome']), (0, 'format_error'))
        self.assertEqual(result['summary']['correct'], 19)

    def test_infrastructure_errors_still_stop_the_run(self):
        result = bench_openclaw.run(runner=FakeOpenClaw(fail_at=3))
        self.assertEqual((result['state'], result['failure_code']), ('failed', 'assistant-error'))

    def test_concurrent_workspace_additions_are_preserved_and_invalidate_run(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            (workspace / 'AGENTS.md').write_text('Instructions\n', encoding='utf-8')
            (workspace / 'IMPROVEMENT-LOG.md').write_text('# Log\n', encoding='utf-8')
            configure_fake(home, workspace)

            class Littering(FakeOpenClaw):
                def turn(self, prompt):
                    if self.calls == 2:
                        (workspace / 'OUTPUT.txt').write_text('scratch', encoding='utf-8')
                    return super().turn(prompt)

            result = bench_openclaw.run(home=home, runner=Littering())
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(result['workspace_side_effects']['added_entries'], ['OUTPUT.txt'])
            self.assertEqual((workspace / 'OUTPUT.txt').read_text(encoding='utf-8'), 'scratch')

    def test_instruction_edits_are_preserved_and_stop_the_run(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            (workspace / 'tools').mkdir(parents=True)
            guide = workspace / 'AGENTS.md'
            guide.write_text('Real guidebook\n', encoding='utf-8')
            (workspace / 'tools/argos-control.py').write_text('print(1)\n', encoding='utf-8')
            configure_fake(home, workspace)
            seen = []

            class Overwriting(FakeOpenClaw):
                def turn(self, prompt):
                    seen.append(guide.read_text(encoding='utf-8'))
                    answer = super().turn(prompt)
                    if self.calls == 5:
                        guide.write_text('storage optimization', encoding='utf-8')
                        (workspace / 'tools/argos-control.py').unlink()
                    return answer

            result = bench_openclaw.run(home=home, runner=Overwriting())
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(set(seen), {'Real guidebook\n'})
            self.assertEqual(guide.read_text(encoding='utf-8'), 'storage optimization')
            self.assertFalse((workspace / 'tools/argos-control.py').exists())
            self.assertEqual(result['workspace_changed']['files'], ['AGENTS.md', 'tools/argos-control.py'])

    def test_config_edits_invalidate_without_overwriting_the_edit(self):
        home = Path.home()
        path = home / '.openclaw/openclaw.json'
        class Changing(FakeOpenClaw):
            def turn(self, prompt):
                value = json.loads(path.read_bytes())
                value['agents']['defaults']['params'] = {'temperature': 0.123}
                path.write_text(json.dumps(value))
                return super().turn(prompt)
        value = bench_openclaw.run(home=home, runner=Changing())
        self.assertEqual(value['state'], 'failed')
        self.assertEqual(value['failure_code'], 'configuration-changed-during-run')
        self.assertEqual(json.loads(path.read_bytes())['agents']['defaults']['params'], {'temperature': 0.123})

    def test_configuration_comparison_requires_one_change_and_labels_evidence(self):
        import copy
        first = bench_openclaw.run(runner=FakeOpenClaw())
        second = copy.deepcopy(first)
        second['id'] = 'a' * 32
        second['settings']['configured_generation']['model_params']['temperature'] = 0.2
        second['prompt_fingerprint']['evaluation_config_sha256'] = 'b' * 64
        compared = results.compare([first, second])
        self.assertIn('configured settings', compared['configuration_changes'][1]['evidence'])
        second['prompt_fingerprint']['workspace_context_sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'more than one'):
            results.compare([first, second])
        second['prompt_fingerprint']['workspace_context_sha256'] = first['prompt_fingerprint']['workspace_context_sha256']
        second['settings']['configured_generation']['model_params']['topP'] = 0.8
        with self.assertRaisesRegex(ValueError, 'more than one'):
            results.compare([first, second])
        del second['settings']['configured_generation']['model_params']['topP']
        second['settings']['model']['metadata']['reasoning'] = True
        with self.assertRaisesRegex(ValueError, 'more than one'):
            results.compare([first, second])

    def test_failed_turn_saves_partial_evidence_but_cannot_be_compared(self):
        complete = bench_openclaw.run(runner=FakeOpenClaw())
        partial = bench_openclaw.run(runner=FakeOpenClaw(fail_at=6))
        self.assertEqual(partial['state'], 'failed')
        self.assertEqual(partial['failure_code'], 'assistant-error')
        self.assertEqual(partial['coverage'], {'completed': 5, 'total': 20, 'complete': False})

        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(Path(temp) / 'runs')
            partial_path = store.save(partial)
            saved = store.load(partial['id'])
            self.assertTrue(partial_path.is_file())
            self.assertEqual(saved['failure_code'], 'assistant-error')
            with self.assertRaisesRegex(ValueError, 'partial or cancelled'):
                results.compare([saved, complete])

    def test_old_gateway_runs_are_not_compared_to_isolated_runs(self):
        old = bench_openclaw.run(runner=FakeOpenClaw())
        old['settings']['execution_path'] = 'openclaw gateway; fresh session per task'
        current = bench_openclaw.run(runner=FakeOpenClaw())
        with self.assertRaisesRegex(ValueError, 'non-model settings'):
            results.compare([old, current])

    def test_cancellation_keeps_partial_evidence_and_blocks_comparison(self):
        cancel = threading.Event()
        class Cancelling(FakeOpenClaw):
            def turn(self, prompt):
                if self.calls == 3:
                    cancel.set()
                    raise TrialTurnError('cancelled')
                return super().turn(prompt)
        value = bench_openclaw.run(runner=Cancelling(), cancel=cancel)
        self.assertEqual((value['state'], value['failure_code']), ('cancelled', 'cancelled'))
        self.assertEqual(value['coverage'], {'completed': 3, 'total': 20, 'complete': False})
        results.validate(value)

    def test_already_cancelled_run_never_calls_the_model(self):
        cancel = threading.Event()
        cancel.set()
        runner = FakeOpenClaw()
        value = bench_openclaw.run(runner=runner, cancel=cancel)
        self.assertEqual(runner.calls, 0)
        self.assertEqual(value['state'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
