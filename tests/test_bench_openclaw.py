import sys
import tempfile
import unittest
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, bench_openclaw, results
from argoslive.assistant_trial import TrialTurnError


class FakeOpenClaw:
    def __init__(self, fail_at=None):
        self.tasks = {item['prompt']: item for item in ability.load('quick')['items']}
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


class OpenClawBenchmarkTests(unittest.TestCase):
    def test_records_suite_and_workspace_instruction_fingerprints(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            instructions = workspace / 'AGENTS.md'
            instructions.write_text('Original instructions\n', encoding='utf-8')
            config = home / '.openclaw/openclaw.json'
            config.write_text(json.dumps({'agents': {'defaults': {'workspace': str(workspace)}}}), encoding='utf-8')
            result = bench_openclaw.run(home=home, runner=FakeOpenClaw())
            suite_path = ability.DATA / 'quick.json'
            self.assertEqual(result['settings']['suite_sha256'], hashlib.sha256(suite_path.read_bytes()).hexdigest())
            self.assertEqual(result['prompt_fingerprint']['workspace_agents_sha256'],
                             hashlib.sha256(instructions.read_bytes()).hexdigest())

    def test_instruction_change_during_run_marks_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            instructions = workspace / 'AGENTS.md'
            instructions.write_text('Original instructions\n', encoding='utf-8')
            config = home / '.openclaw/openclaw.json'
            config.write_text(json.dumps({'agents': {'defaults': {'workspace': str(workspace)}}}), encoding='utf-8')

            class MutatingRunner(FakeOpenClaw):
                def turn(self, prompt):
                    answer = super().turn(prompt)
                    if self.calls == 1:
                        instructions.write_text('Changed during run\n', encoding='utf-8')
                    return answer

            result = bench_openclaw.run(home=home, runner=MutatingRunner())
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(result['failure_code'], 'instruction-changed-during-run')
            self.assertFalse(result['coverage']['complete'])

    def test_failed_turn_saves_partial_evidence_but_cannot_be_compared(self):
        partial = bench_openclaw.run(runner=FakeOpenClaw(fail_at=6))
        self.assertEqual(partial['state'], 'failed')
        self.assertEqual(partial['failure_code'], 'assistant-error')
        self.assertEqual(partial['coverage'], {'completed': 5, 'total': 20, 'complete': False})

        complete = bench_openclaw.run(runner=FakeOpenClaw())
        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(Path(temp) / 'runs')
            partial_path = store.save(partial)
            saved = store.load(partial['id'])
            self.assertTrue(partial_path.is_file())
            self.assertEqual(saved['failure_code'], 'assistant-error')
            with self.assertRaisesRegex(ValueError, 'partial or cancelled'):
                results.compare([saved, complete])


if __name__ == '__main__':
    unittest.main()
