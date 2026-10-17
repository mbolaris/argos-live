import sys
import tempfile
import unittest
from unittest.mock import patch
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
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        (home / '.openclaw/workspace').mkdir(parents=True)
        (home / '.openclaw/openclaw.json').write_text('{}', encoding='utf-8')
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

    def test_concurrent_workspace_additions_are_preserved_and_invalidate_run(self):
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
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(set(seen), {'Real guidebook\n'})
            self.assertEqual(guide.read_text(encoding='utf-8'), 'storage optimization')
            self.assertFalse((workspace / 'tools/argos-control.py').exists())
            self.assertEqual(result['workspace_changed']['files'], ['AGENTS.md', 'tools/argos-control.py'])

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


if __name__ == '__main__':
    unittest.main()
