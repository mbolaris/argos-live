import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('managed_check', ROOT / 'scripts/qemu-managed-check.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiagnosticFlagsTests(unittest.TestCase):
    def test_probe_failure_only_emits_fixed_categories_not_private_error_text(self):
        self.assertEqual(module.probe_failure(TimeoutError('private token')), 'timeout')
        self.assertEqual(module.probe_failure(module.URLError(ConnectionRefusedError(
            module.errno.ECONNREFUSED, 'private path'))), 'connection-refused')
        self.assertEqual(module.probe_failure(ValueError('private response body')), 'invalid-response')
        self.assertEqual(module.probe_failure(module.HTTPException('private URL')), 'http-protocol-error')

    def test_capture_gate_requires_active_firefox_control_page(self):
        for kind, title, expected in (
                ('"firefox-esr"', '"Argos Live — Mozilla Firefox"', False),
                ('"other-browser"', '"OpenClaw Control"', False),
                ('"firefox-esr"', '"OpenClaw Control — Mozilla Firefox"', True),
                ('"firefox-esr"', '"OpenClaw Control"', True)):
            with self.subTest(title=title, kind=kind), patch.object(module.subprocess,
                    'check_output', side_effect=['_NET_ACTIVE_WINDOW: 0x123', kind,
                                                 '_NET_WM_NAME(UTF8_STRING) = ' + title]):
                self.assertEqual(module.firefox_control_page_visible(), expected)

    def test_owned_exit_only_admits_bounded_whole_numeric_records(self):
        self.assertEqual(module.owned_exit(b'private token\nARGOS_OWNED_EXIT returncode=-11\n'), -11)
        self.assertEqual(module.owned_exit(b'ARGOS_OWNED_EXIT returncode=0\n'), 0)
        for raw in (b'ARGOS_OWNED_EXIT returncode=999\n', b'ARGOS_OWNED_EXIT returncode=-65\n',
                    b'ARGOS_OWNED_EXIT returncode=1 token=secret\n', b'xARGOS_OWNED_EXIT returncode=1\n'):
            self.assertIsNone(module.owned_exit(raw))

    def test_post_ready_trace_excludes_dynamic_personal_stages_and_metric_text(self):
        raw = (b'{"message":"startup trace: sidecars.reply-runtime 9000ms total=12000ms eventLoopMax=8000ms token=secret"}\n'
            b'startup trace: post-ready.gateway-data.skills.private-agent 10ms total=12001ms\n'
            b'startup trace: post-ready.gateway-data.chat.history 12ms total=13000ms eventLoopMax=999999999ms\n')
        value = module.startup_trace(raw)
        self.assertEqual(value['sidecars.reply-runtime']['event_loop_max_ms'], 8000)
        self.assertEqual(value['post-ready.gateway-data.chat.history'],
                         {'duration_ms': 12, 'total_ms': 13000})
        self.assertNotIn('secret', json.dumps(value))
        self.assertNotIn('private-agent', json.dumps(value))
        flags = module.log_flags(b'plugin services failed to start: private token=secret')
        self.assertTrue(flags['plugin_service_failure'])
        self.assertNotIn('secret', json.dumps(flags))

    def test_startup_trace_exposes_only_known_stages_and_bounded_timings(self):
        raw = (b'[gateway] startup trace: entry.bootstrap 12.5ms total=20.0ms start=7.5ms secret=token\n'
            b'[gateway] startup trace: owner.private-secret 10ms total=30ms\n'
            b'[gateway] startup trace: entry.argv 40ms total=30ms\n'
            b'[gateway] startup trace: entry.run-main-import 10ms total=999999999ms\n')
        report = module.startup_trace(raw)
        self.assertEqual(report, {'entry.bootstrap': {'duration_ms': 12.5, 'total_ms': 20.0}})
        self.assertNotIn('secret', json.dumps(report))
        self.assertNotIn('token', json.dumps(report))

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
