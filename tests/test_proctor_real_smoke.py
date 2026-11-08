import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/smoke-proctor-real.py'
SPEC = importlib.util.spec_from_file_location('argos_smoke_proctor_real', SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


class ApprovalRequestCountTests(unittest.TestCase):
    def test_counts_one_approval_instruction(self):
        self.assertEqual(smoke.approval_request_count(
            'Click “Approve one safe SSH start” in the dashboard.'), 1)

    def test_detects_repeated_approval_instruction(self):
        self.assertEqual(smoke.approval_request_count(
            'Approve one safe SSH start. Please approve one safe SSH start.'), 2)

    def test_healthy_followup_has_no_approval_request(self):
        self.assertEqual(smoke.approval_request_count(
            'SSH is healthy and no action is needed.'), 0)


if __name__ == '__main__':
    unittest.main()
