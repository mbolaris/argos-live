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

    def test_files_left_in_the_workspace_are_moved_aside_and_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            (workspace / 'AGENTS.md').write_text('Instructions\n', encoding='utf-8')
            (workspace / 'IMPROVEMENT-LOG.md').write_text('# Log\n', encoding='utf-8')
            (home / '.openclaw/openclaw.json').write_text(
                json.dumps({'agents': {'defaults': {'workspace': str(workspace)}}}), encoding='utf-8')

            class Littering(FakeOpenClaw):
                def turn(self, prompt):
                    if self.calls == 2:
                        (workspace / 'OUTPUT.txt').write_text('scratch', encoding='utf-8')
                    return super().turn(prompt)

            result = bench_openclaw.run(home=home, runner=Littering())
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(sorted(p.name for p in workspace.iterdir()), ['AGENTS.md', 'IMPROVEMENT-LOG.md'])
            self.assertEqual(result['workspace_side_effects']['moved_entries'], ['OUTPUT.txt'])
            moved = Path(result['workspace_side_effects']['moved_to'])
            self.assertEqual((moved / 'OUTPUT.txt').read_text(encoding='utf-8'), 'scratch')

    def test_a_task_that_rewrites_the_instructions_is_undone_before_the_next_task(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            (workspace / 'tools').mkdir(parents=True)
            guide = workspace / 'AGENTS.md'
            guide.write_text('Real guidebook\n', encoding='utf-8')
            (workspace / 'tools/argos-control.py').write_text('print(1)\n', encoding='utf-8')
            (home / '.openclaw/openclaw.json').write_text(
                json.dumps({'agents': {'defaults': {'workspace': str(workspace)}}}), encoding='utf-8')
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
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(set(seen), {'Real guidebook\n'})
            self.assertEqual(guide.read_text(encoding='utf-8'), 'Real guidebook\n')
            self.assertTrue((workspace / 'tools/argos-control.py').is_file())
            self.assertEqual(result['workspace_restored'][0]['files'], ['AGENTS.md', 'tools/argos-control.py'])
            self.assertTrue(result['restoration']['mutated'])

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
