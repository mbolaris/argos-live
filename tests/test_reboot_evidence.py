import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import reboot_evidence as rb

BOOT1 = '11111111-1111-4111-8111-111111111111'
BOOT2 = '22222222-2222-4222-8222-222222222222'


class RebootEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        (self.home / '.config/argos-live').mkdir(parents=True)
        self.models = self.home / 'models'
        self.models.mkdir()
        self.dirs = {'models': self.models}

    def tearDown(self):
        self.tmp.cleanup()

    def test_marker_has_only_identifier_schema_and_boot_id(self):
        self.assertEqual(rb.start(self.home, self.dirs, current=BOOT1), ['models'])
        value = json.loads((self.models / rb.MARKER).read_text())
        self.assertEqual(set(value), {'schema', 'id', 'boot_id'})
        self.assertEqual(value['boot_id'], BOOT1)
        self.assertEqual((self.models / rb.MARKER).stat().st_mode & 0o077, 0)

    def test_never_overwrites_an_existing_marker(self):
        rb.start(self.home, self.dirs, current=BOOT1)
        before = (self.models / rb.MARKER).read_bytes()
        self.assertEqual(rb.start(self.home, self.dirs, current=BOOT2), [])
        self.assertEqual((self.models / rb.MARKER).read_bytes(), before)

    def test_missing_directory_is_skipped_not_created(self):
        missing = {'models': self.home / 'absent'}
        self.assertEqual(rb.start(self.home, missing, current=BOOT1), [])
        self.assertFalse((self.home / 'absent').exists())

    def test_states_pending_then_retained_then_recorded(self):
        self.assertEqual(rb.assess(self.home, self.dirs, current=BOOT1)['models']['state'], 'not-started')
        rb.start(self.home, self.dirs, current=BOOT1)
        self.assertEqual(rb.assess(self.home, self.dirs, current=BOOT1)['models']['state'], 'pending')
        self.assertFalse(rb.record(self.home, self.dirs, current=BOOT1))
        self.assertEqual(rb.assess(self.home, self.dirs, current=BOOT2)['models']['state'], 'retained')
        self.assertTrue(rb.record(self.home, self.dirs, current=BOOT2, clock=lambda: '2026-10-09T00:00:00+00:00'))
        evidence = rb.assess(self.home, self.dirs, current=BOOT2)['models']
        self.assertEqual(evidence['verified_at'], '2026-10-09T00:00:00+00:00')
        self.assertFalse(rb.record(self.home, self.dirs, current=BOOT2))

    def test_lost_marker_is_not_retained(self):
        rb.start(self.home, self.dirs, current=BOOT1)
        (self.models / rb.MARKER).unlink()
        self.assertEqual(rb.assess(self.home, self.dirs, current=BOOT2)['models']['state'], 'not-retained')

    def test_replaced_or_corrupt_marker_needs_attention(self):
        rb.start(self.home, self.dirs, current=BOOT1)
        (self.models / rb.MARKER).write_text('{"schema": "argos-reboot-marker/1", "id": "' + 'a' * 32 +
                                             '", "boot_id": "' + BOOT1 + '"}')
        self.assertEqual(rb.assess(self.home, self.dirs, current=BOOT2)['models']['state'], 'needs-attention')
        (self.models / rb.MARKER).write_text('not json')
        self.assertEqual(rb.assess(self.home, self.dirs, current=BOOT2)['models']['state'], 'needs-attention')

    def test_unknown_when_boot_identity_unavailable(self):
        rb.start(self.home, self.dirs, current=BOOT1)
        self.assertEqual(rb.assess(self.home, self.dirs, current='')['models']['state'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'Boot identity unavailable'):
            rb.start(self.home, {'models': self.models}, current='not-a-boot-id')

    def test_ledger_path_must_match_directory(self):
        rb.start(self.home, self.dirs, current=BOOT1)
        other = self.home / 'other'
        other.mkdir()
        self.assertEqual(rb.assess(self.home, {'models': other}, current=BOOT2)['models']['state'], 'not-started')

    def test_boot_id_reads_proc_and_rejects_garbage(self):
        proc = self.home / 'proc'
        (proc / 'sys/kernel/random').mkdir(parents=True)
        (proc / 'sys/kernel/random/boot_id').write_text(BOOT1 + '\n')
        self.assertEqual(rb.boot_id(proc), BOOT1)
        (proc / 'sys/kernel/random/boot_id').write_text('garbage')
        self.assertIsNone(rb.boot_id(proc))
        self.assertIsNone(rb.boot_id(self.home / 'nowhere'))


if __name__ == '__main__':
    unittest.main()
