import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('smoke_native_chat', ROOT / 'scripts/smoke-native-chat.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class NativeChatCaptureTests(unittest.TestCase):
    def metrics(self, events):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'requests.jsonl'
            path.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
            return smoke.request_metrics({'ARGOS_NATIVE_REQUEST_LOG': str(path)})

    def test_request_log_requires_matching_process_summary_and_hides_raw_fields(self):
        events = [
            {'kind': 'probe', 'pid': 123, 'probe_loaded': True, 'runtime_fetch_hooked': True},
            {'kind': 'request', 'pid': 123, 'body_inspected': True, 'num_predict': 32,
             'prompt': 'PRIVATE_PROMPT'},
            {'kind': 'summary', 'pid': 123, 'request_count': 1,
             'requests_logged': 1, 'log_failed': False},
        ]
        metrics = self.metrics(events)
        self.assertFalse(metrics['requests_truncated'])
        self.assertEqual(metrics['request_count'], 1)
        self.assertEqual(metrics['missing_summary_count'], 0)
        self.assertEqual(metrics['summary_mismatch_count'], 0)
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(metrics))

    def test_missing_process_summary_is_reported_with_bounded_counters(self):
        metrics = self.metrics([
            {'kind': 'probe', 'pid': 123, 'probe_loaded': True, 'runtime_fetch_hooked': True},
            {'kind': 'request', 'pid': 123, 'body_inspected': True, 'num_predict': 32},
        ])
        self.assertTrue(metrics['requests_truncated'])
        self.assertEqual(metrics['probe_process_count'], 1)
        self.assertEqual(metrics['summary_process_count'], 0)
        self.assertEqual(metrics['request_process_count'], 1)
        self.assertEqual(metrics['missing_summary_count'], 1)
        self.assertEqual(metrics['request_without_probe_count'], 0)


if __name__ == '__main__':
    unittest.main()
