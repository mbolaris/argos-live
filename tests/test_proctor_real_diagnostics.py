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
                {'kind': 'other', 'error_class': 'RuntimeError'},
                {'kind': 'proctor_answer', 'error_class': 'X' * 100},
            ],
            'tools': [
                {'kind': 'proctor_answer', 'status': 'accepted', 'call_id': 'private-call',
                 'answer': 'private answer'},
                {'kind': 'proctor_host_submit', 'module_id': 'private-module'},
                {'kind': 'proctor_finalize', 'transcript_id': 'private-transcript'},
            ],
            'admission_diagnostics': {
                'tool_hooks': 4, 'bound_calls': 2, 'executions': 2,
                'rejected': {'unknown_tool': 0, 'missing_admission': 0,
                    'invalid_call_id': 0, 'stale_binding': 0},
            },
        }
        result = smoke.safe_controller_diagnostics(turn)
        self.assertEqual(result['host_tool_requests'], 3)
        self.assertEqual(result['host_tool_failures'], [
            {'kind': 'proctor_item', 'error_class': 'ValueError'}])
        self.assertEqual(result['tool_outcomes'], [{'kind': 'proctor_answer', 'status': 'accepted'}])
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


if __name__ == '__main__':
    unittest.main()
