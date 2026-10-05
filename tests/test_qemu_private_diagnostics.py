import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('managed_check', ROOT / 'scripts/qemu-managed-check.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiagnosticFlagsTests(unittest.TestCase):
    def test_fixed_vocabulary_never_echoes_tokens_paths_or_raw_errors(self):
        raw = b'ERROR: cannot find module /private/secret fictional-token-123\nlistening on 127.0.0.1:18789'
        flags = module.log_flags(raw)
        self.assertTrue(flags['missing_dependency'])
        self.assertTrue(flags['listening_reported'])
        self.assertTrue(flags['error_reported'])
        self.assertTrue(all(type(value) is bool for value in flags.values()))
        public = json.dumps(flags)
        for private in ('fictional-token', '/private', '18789', 'cannot find module'):
            self.assertNotIn(private, public)

    @unittest.skipUnless(sys.platform == 'linux', 'Owner-only Linux diagnostic reads')
    def test_linked_broad_and_hardlinked_logs_are_not_read_or_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / 'log'
            original = b'fictional-token EACCES'
            log.write_bytes(original)
            log.chmod(0o600)
            good = module.private_log_observation(log)
            self.assertEqual(good['state'], 'readable')
            self.assertTrue(good['flags']['permission_error'])
            link = root / 'symlink'
            link.symlink_to(log)
            self.assertEqual(module.private_log_observation(link)['state'], 'unavailable')
            hard = root / 'hardlink'
            os.link(log, hard)
            self.assertEqual(module.private_log_observation(log)['state'], 'unsafe')
            hard.unlink()
            log.chmod(0o644)
            self.assertEqual(module.private_log_observation(log)['state'], 'unsafe')
            self.assertEqual(log.read_bytes(), original)

    @unittest.skipUnless(sys.platform == 'linux', 'Owner-only Linux diagnostic reads')
    def test_reads_only_bounded_tail_and_absent_log_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'log'
            self.assertEqual(module.private_log_observation(log), {'state': 'absent'})
            log.write_bytes(b'EACCES ' + b'x' * 65536)
            log.chmod(0o600)
            report = module.private_log_observation(log)
            self.assertTrue(report['nonempty'])
            self.assertFalse(report['flags']['permission_error'])
