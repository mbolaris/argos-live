import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'smoke_tool_sequence_real', ROOT / 'scripts/smoke-tool-sequence-real.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class ToolSequenceSmokeReportTests(unittest.TestCase):
    def test_smoke_runner_uses_its_bounded_six_minute_turn_window(self):
        runner = smoke.ToolSequenceSmokeRunner('/isolated/home')
        with patch.object(smoke.OpenClawRunner, 'turn', return_value={'text': 'reply'}) as turn:
            self.assertEqual(runner.turn('prompt'), {'text': 'reply'})
        turn.assert_called_once_with('prompt', timeout=360)

    def sample(self):
        return {
            'id': 'run-1', 'state': 'completed',
            'model': 'ollama/qwen3:4b-instruct-2507-q4_K_M',
            'suite_version': 'argos-openclaw-ability/tool-sequence/1.0.0',
            'coverage': {'completed': 40, 'total': 40, 'complete': True},
            'summary': {'partitions': {
                'practice': {'total': 20, 'correct': 18},
                'heldout': {'total': 20, 'correct': 12}}},
            'settings': {'execution_path':
                         'openclaw embedded; ephemeral state; tools denied; v2'},
            'items': [{'item_id': 'workflow-1', 'partition': 'practice',
                       'category': 'tool-sequence', 'score': 1, 'outcome': 'pass',
                       'checks': ['sequence'], 'prompt': 'PRIVATE PROMPT',
                       'output': 'PRIVATE MODEL OUTPUT'}],
        }

    def test_complete_result_passes_exact_acceptance_checks(self):
        result = self.sample()
        failures = smoke.result_failures(
            result, 'qwen3:4b-instruct-2507-q4_K_M',
            'argos-openclaw-ability/tool-sequence/1.0.0')
        self.assertEqual(failures, [])

    def test_failed_result_reports_only_safe_facts_and_check_names(self):
        result = self.sample()
        result['state'] = 'failed'
        result['failure_code'] = 'assistant-error'
        result['coverage'] = {'completed': 19, 'total': 40, 'complete': False}
        result['settings']['execution_path'] = 'unexpected path'
        result['summary']['partitions']['heldout']['total'] = 3
        failures = smoke.result_failures(
            result, 'qwen3:4b-instruct-2507-q4_K_M',
            'argos-openclaw-ability/tool-sequence/1.0.0')
        diagnostic = smoke.safe_result_diagnostic(result, failures)
        self.assertEqual(failures, ['state', 'coverage', 'execution_policy', 'partition_totals'])
        serialized = json.dumps(diagnostic)
        self.assertNotIn('PRIVATE PROMPT', serialized)
        self.assertNotIn('PRIVATE MODEL OUTPUT', serialized)
        self.assertEqual(diagnostic['item_scores'][0]['item_id'], 'workflow-1')
        self.assertEqual(diagnostic['failure_code'], 'assistant-error')
        self.assertEqual(diagnostic['turn_timeout_seconds'], 360)

    def test_private_cli_log_exports_only_a_safe_failure_category(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / '.local/state/argos-live/trial-turn-failure.log'
            log.parent.mkdir(parents=True)
            log.write_text('Invalid API key: PRIVATE SECRET VALUE', encoding='utf-8')
            signature = smoke.assistant_failure_signature(directory)
            diagnostic = smoke.safe_result_diagnostic(
                {'id': 'run-1', 'state': 'failed', 'failure_code': 'assistant-error'},
                ['state'], signature)
        serialized = json.dumps(diagnostic)
        self.assertEqual(signature, 'provider_authentication')
        self.assertNotIn('PRIVATE SECRET VALUE', serialized)
        self.assertNotIn('Invalid API key', serialized)


if __name__ == '__main__':
    unittest.main()
