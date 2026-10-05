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
    def test_resource_snapshot_reports_numeric_units_and_missing_as_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            absent = module.resource_observation(proc)
            self.assertIsNone(absent['memory_kib']['MemAvailable'])
            self.assertIsNone(absent['vm_counters']['oom_kill'])
            (proc / 'meminfo').write_text('MemAvailable: 1234 kB\nSwapTotal: 0 kB\n'
                'SwapFree: invalid kB\nprivate-secret: 999 kB\n')
            (proc / 'vmstat').write_text('oom_kill 3\npgmajfault 456\nprivate-secret 8\n')
            report = module.resource_observation(proc)
            self.assertEqual(report['memory_kib'],
                {'MemAvailable': 1234, 'SwapTotal': 0, 'SwapFree': None})
            self.assertEqual(report['vm_counters'], {'oom_kill': 3, 'pgmajfault': 456})
            self.assertNotIn('private-secret', json.dumps(report))

    def test_process_snapshot_does_not_include_command_names_arguments_or_io_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            process = Path(temp) / '123'
            process.mkdir()
            fields = ['S'] + ['0'] * 23
            fields[9], fields[11], fields[12], fields[21] = '5', '70', '30', '10'
            (process / 'stat').write_text('123 (private secret name) ' + ' '.join(fields))
            (process / 'io').write_text('read_bytes: 888\nrchar: 999\nprivate-secret: 42\n')
            report = module.node_observation(process)
            self.assertEqual(report, {'pid': 123, 'state': 'S', 'cpu_ticks': 100,
                'major_faults': 5, 'resident_pages': 10, 'read_bytes': 888, 'read_chars': 999})
            self.assertNotIn('private', json.dumps(report))

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
