import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_openclaw, campaign_log, results, workload
from test_bench_openclaw import FakeOpenClaw, configure_fake


class CampaignLogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.workspace = self.home / '.openclaw/workspace'
        self.workspace.mkdir(parents=True)
        (self.workspace / 'AGENTS.md').write_text('Owner guide\n', encoding='utf-8')
        configure_fake(self.home, self.workspace)
        self.log = self.workspace / 'IMPROVEMENT-LOG.md'
        self.original = b'Owner history\r\nKeep these bytes.\r\n'
        self.log.write_bytes(self.original)

    def test_append_preserves_history_and_supplies_actual_receipts(self):
        run = bench_openclaw.run(home=self.home, runner=FakeOpenClaw())
        results.Store(self.home / '.local/share/argos-live/results').save(run)
        note = 'Measured baseline ' + run['id'] + '\n## Next\nChoose one hypothesis.'
        receipt = campaign_log.append(self.home, note)
        actual = self.log.read_bytes()
        self.assertTrue(actual.startswith(self.original))
        self.assertIn(receipt['observed'].encode(), actual)
        self.assertEqual(receipt['receipts'][0]['summary'], run['summary'])
        self.assertFalse(receipt['note_claims_verified'])
        self.assertEqual((Path(receipt['snapshot']) / self.log.name).read_bytes(), self.original)
        self.assertIn('## Next', actual.decode())

    def test_no_log_write_while_evaluation_owns_slot(self):
        with workload.reserve(self.home, 'evaluation') as slot:
            with self.assertRaises(workload.Busy):
                campaign_log.append(self.home, 'Do not invalidate this evaluation')
            self.assertEqual(self.log.read_bytes(), self.original)
            slot.complete()

    def test_invented_run_is_rejected_without_stranding_admission(self):
        with self.assertRaisesRegex(ValueError, 'not found'):
            campaign_log.append(self.home, 'Result ' + 'a' * 32)
        self.assertEqual(self.log.read_bytes(), self.original)
        campaign_log.append(self.home, '## Next\nMeasure a baseline.')

    def test_bad_input_is_rejected_before_admission(self):
        for value in ('', 'x' * 4097, 'x\0y', None):
            with self.assertRaises(ValueError):
                campaign_log.append(self.home, value)
        self.assertEqual(self.log.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
