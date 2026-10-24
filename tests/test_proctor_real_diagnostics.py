import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('smoke_proctor_real', ROOT / 'scripts/smoke-proctor-real.py')
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class ProctorRealDiagnosticTests(unittest.TestCase):
    def test_controller_diagnostics_export_only_bounded_safe_fields(self):
        turn = {
            'host_tool_requests': 3,
            'host_tool_failures': [
                {'kind': 'proctor_item', 'error_class': 'ValueError', 'message': 'private raw error'},
                {'kind': 'proctor_answer', 'error_class': 'ProctorError',
                 'error_code': 'INVALID_ANSWER_FORMAT'},
                {'kind': 'proctor_answer', 'error_class': 'ProctorError',
                 'error_code': 'private raw error'},
                {'kind': 'other', 'error_class': 'RuntimeError'},
                {'kind': 'proctor_answer', 'error_class': 'X' * 100},
            ],
            'tools': [
                {'kind': 'proctor_answer', 'status': 'accepted', 'call_id': 'private-call',
                 'answer': 'private answer'},
                {'kind': 'proctor_host_submit', 'module_id': 'private-module'},
                {'kind': 'proctor_finalize', 'transcript_id': 'private-transcript'},
            ],
            'worker_turns': [{
                'turn': 1, 'outcome': 'incomplete-turn', 'returncode': 1,
                'stdout_bytes': 80, 'stderr_bytes': 0,
                'process_group_drained': True, 'session_bound': True,
                'host_tool_requests': 0, 'host_tool_failures': 0,
                'response_status': 'error', 'sdk_error_kind': 'incomplete_turn',
                'model_text': 'must not be exported',
            }, {'turn': 2, 'outcome': 'completed', 'returncode': 0,
                'stdout_bytes': 240, 'stderr_bytes': 0,
                'process_group_drained': True, 'session_bound': True,
                'host_tool_requests': 3, 'host_tool_failures': 0,
                'response_status': 'ok'}],
            'admission_diagnostics': {
                'tool_hooks': 4, 'bound_calls': 2, 'executions': 2,
                'rejected': {'unknown_tool': 0, 'missing_admission': 0,
                    'invalid_call_id': 0, 'stale_binding': 0},
            },
        }
        result = smoke.safe_controller_diagnostics(turn)
        self.assertEqual(result['host_tool_requests'], 3)
        self.assertEqual(result['host_tool_failures'], [
            {'kind': 'proctor_item', 'error_class': 'ValueError'},
            {'kind': 'proctor_answer', 'error_class': 'ProctorError',
             'error_code': 'INVALID_ANSWER_FORMAT'},
            {'kind': 'proctor_answer', 'error_class': 'ProctorError'}])
        self.assertEqual(result['tool_outcomes'], [{'kind': 'proctor_answer', 'status': 'accepted'}])
        self.assertEqual(result['worker_turns'], [
            {'turn': 1, 'outcome': 'incomplete-turn', 'returncode': 1,
             'stdout_bytes': 80, 'stderr_bytes': 0, 'process_group_drained': True,
             'session_bound': True, 'host_tool_requests': 0, 'host_tool_failures': 0,
             'response_status': 'error', 'sdk_error_kind': 'incomplete_turn'},
            {'turn': 2, 'outcome': 'completed', 'returncode': 0,
             'stdout_bytes': 240, 'stderr_bytes': 0, 'process_group_drained': True,
             'session_bound': True, 'host_tool_requests': 3, 'host_tool_failures': 0,
             'response_status': 'ok'},
        ])
        self.assertEqual(result['admission']['executions'], 2)
        self.assertNotIn('private', repr(result))

    def test_malformed_or_unbounded_diagnostics_are_omitted(self):
        result = smoke.safe_controller_diagnostics({
            'host_tool_requests': True,
            'host_tool_failures': 'not-a-list',
            'tools': None,
            'admission_diagnostics': {'tool_hooks': -1},
        })
        self.assertEqual(result, {})

    def test_worker_turn_diagnostics_drop_unbounded_or_malformed_rows(self):
        result = smoke.safe_controller_diagnostics({'worker_turns': [
            {'turn': 1, 'outcome': 'completed', 'returncode': 0, 'stdout_bytes': 10,
             'stderr_bytes': 0, 'process_group_drained': True, 'session_bound': True,
             'host_tool_requests': 0, 'host_tool_failures': 0, 'response_status': 'ok'},
            {'turn': 2, 'outcome': 'invented', 'returncode': 0, 'stdout_bytes': 10,
             'stderr_bytes': 0, 'process_group_drained': True, 'session_bound': True,
             'host_tool_requests': 0, 'host_tool_failures': 0, 'response_status': 'ok'},
            {'turn': 3, 'outcome': 'completed', 'returncode': 0, 'stdout_bytes': 10,
             'stderr_bytes': 0, 'process_group_drained': True, 'session_bound': 1,
             'host_tool_requests': 0, 'host_tool_failures': 0, 'response_status': 'ok'},
        ]})
        self.assertEqual(len(result['worker_turns']), 1)
        self.assertEqual(result['worker_turns'][0]['outcome'], 'completed')


if __name__ == '__main__':
    unittest.main()
