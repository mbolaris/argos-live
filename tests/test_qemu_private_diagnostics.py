import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
spec = importlib.util.spec_from_file_location('managed_check', ROOT / 'scripts/qemu-managed-check.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiagnosticFlagsTests(unittest.TestCase):
    def test_lab_launch_wait_resets_stability_after_transient_navigation(self):
        clock = [0.0]
        samples = []
        def visible():
            samples.append(clock[0])
            return clock[0] < 1 or clock[0] >= 3
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(module.time, 'sleep', side_effect=sleep), \
                patch.object(module, 'firefox_model_lab_visible', side_effect=visible):
            module.wait_model_lab_visible()
        self.assertEqual(clock[0], 8.0)
        self.assertGreater(len(samples), 2)

    def test_lab_launch_never_accepts_a_flickering_title_or_extends_deadline(self):
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        output = io.StringIO()
        with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(module.time, 'sleep', side_effect=sleep), \
                patch.object(module, 'firefox_model_lab_visible', side_effect=lambda: clock[0] % 2 < 1), \
                patch('sys.stdout', output):
            with self.assertRaisesRegex(ValueError, 'stable shipped Firefox view'):
                module.wait_model_lab_visible()
        self.assertEqual(clock[0], 30.0)
        self.assertEqual(output.getvalue(), 'ARGOS_C3_STAGE model-lab-visibility-timeout\n')

    def test_assistant_chat_http_failure_reports_only_check_and_status(self):
        body = io.BytesIO(b'{"error":"private token and response body"}')
        error = HTTPError('http://127.0.0.1/private-token/chat', 409,
                          'private reason', {'X-Private': 'secret'}, body)
        output = io.StringIO()
        with patch('sys.stdout', output):
            module.report_http_failure('assistant-chat-availability', error)
        self.assertEqual(json.loads(output.getvalue().split(' ', 1)[1]),
                         {'check': 'assistant-chat-availability', 'status': 409})
        for private in ('private-token', 'private reason', 'private response body', 'secret'):
            self.assertNotIn(private, output.getvalue())
        self.assertTrue(body.closed)

    def test_unknown_http_failure_check_is_collapsed_to_other(self):
        error = HTTPError('http://127.0.0.1/private-token', 700,
                          'private reason', {}, io.BytesIO(b'secret'))
        output = io.StringIO()
        with patch('sys.stdout', output):
            module.report_http_failure('private-route', error)
        self.assertEqual(json.loads(output.getvalue().split(' ', 1)[1]),
                         {'check': 'other', 'status': None})

    def test_model_lab_status_http_failure_reports_only_check_and_status(self):
        error = HTTPError('http://127.0.0.1/private-token/api/lab', 409,
                          'private reason', {}, io.BytesIO(b'secret'))
        output = io.StringIO()
        with patch('sys.stdout', output):
            module.report_http_failure('model-lab-status', error)
        self.assertEqual(json.loads(output.getvalue().split(' ', 1)[1]),
                         {'check': 'model-lab-status', 'status': 409})
        for private in ('private-token', 'private reason', 'secret'):
            self.assertNotIn(private, output.getvalue())

    def test_only_assistant_chat_readiness_conflict_is_retryable(self):
        conflict = HTTPError('http://127.0.0.1/private-token/chat', 409,
                             'private reason', {}, io.BytesIO(b'secret'))
        unavailable = HTTPError('http://127.0.0.1/private-token/chat', 503,
                                'private reason', {}, io.BytesIO(b'secret'))
        self.assertTrue(module.assistant_chat_failure_is_transient(conflict))
        self.assertFalse(module.assistant_chat_failure_is_transient(unavailable))
        self.assertFalse(module.assistant_chat_failure_is_transient(ValueError('private reason')))
        conflict.close()
        unavailable.close()

    def test_chat_conflict_retry_has_fixed_two_minute_bound(self):
        self.assertFalse(module.assistant_chat_conflict_retry_expired(None, 1000))
        self.assertFalse(module.assistant_chat_conflict_retry_expired(10, 129.9))
        self.assertTrue(module.assistant_chat_conflict_retry_expired(10, 130))

    def test_assistant_chat_preflight_reports_only_configuration_booleans(self):
        with tempfile.TemporaryDirectory() as temp:
            config_dir = Path(temp) / '.openclaw'
            config_dir.mkdir()
            config = {'gateway': {'mode': 'local', 'bind': 'loopback', 'port': 18789,
                'auth': {'mode': 'token', 'token': 'fictional-private-token'}}}
            (config_dir / 'openclaw.json').write_text(json.dumps(config))
            with patch('argoslive.web.status.gateway_ready', return_value=True):
                value = module.assistant_chat_preconditions(Path(temp))
            self.assertEqual(value, {'config_readable': True, 'gateway_config_valid': True,
                'token_mode': True, 'token_present': True, 'token_length_valid': True,
                'gateway_ready': True})
            self.assertNotIn('fictional-private-token', json.dumps(value))

    def test_assistant_chat_preflight_collapses_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            config_dir = Path(temp) / '.openclaw'
            config_dir.mkdir()
            (config_dir / 'openclaw.json').write_text(json.dumps(
                {'gateway': {'bind': '0.0.0.0', 'auth': {'token': 'secret'}}}))
            value = module.assistant_chat_preconditions(Path(temp))
            self.assertTrue(value['config_readable'])
            self.assertFalse(value['gateway_config_valid'])
            self.assertFalse(value['token_present'])
            self.assertNotIn('secret', json.dumps(value))

    def test_trial_keyboard_refuses_wrong_active_window(self):
        output = io.StringIO()
        with patch.object(module, 'firefox_model_lab_visible', return_value=False), \
                patch('sys.stdout', output), \
                patch.object(module.ctypes, 'CDLL') as library:
            with self.assertRaisesRegex(ValueError, 'active Firefox'):
                module.click_model_lab_baseline("http://127.0.0.1:49355", "fixture-token")
            library.assert_not_called()
        self.assertEqual(output.getvalue(), 'ARGOS_C3_INPUT_FAILURE verify-active-firefox\n')
        self.assertNotIn('fixture-token', output.getvalue())

    def test_trial_keyboard_failure_releases_control_and_closes_display(self):
        x11, xtst = MagicMock(), MagicMock()
        x11.XOpenDisplay.return_value = 123
        x11.XKeysymToKeycode.side_effect = lambda display, symbol: symbol
        # Control press succeeds; typing the location shortcut fails.
        xtst.XTestFakeKeyEvent.side_effect = [1, 0, 1]
        output = io.StringIO()
        with patch.object(module, 'firefox_model_lab_visible', return_value=True), \
                patch.object(module.ctypes, 'CDLL', side_effect=[x11, xtst]), \
                patch('sys.stdout', output):
            with self.assertRaisesRegex(ValueError, 'keyboard input failed'):
                module.click_model_lab_baseline("http://127.0.0.1:49355", "fixture-token")
        self.assertEqual(xtst.XTestFakeKeyEvent.call_args.args, (123, 0xffe3, 0, 0))
        x11.XCloseDisplay.assert_called_once_with(123)
        self.assertEqual(output.getvalue(), 'ARGOS_C3_INPUT_FAILURE focus-location-bar\n')
        self.assertNotIn('fixture-token', output.getvalue())

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
                ('"firefox-esr"', '"OpenClaw Control"', True),
                ('"firefox-esr"', '"main — OpenClaw — Mozilla Firefox"', True),
                ('"firefox-esr"', '"main — OpenClaw"', True),
                ('"firefox-esr"', '"main — OpenClaw unrelated"', False),
                ('"other-browser"', '"main — OpenClaw"', False)):
            with self.subTest(title=title, kind=kind), patch.object(module.subprocess,
                    'check_output', side_effect=['_NET_ACTIVE_WINDOW: 0x123', kind,
                                                 '_NET_WM_NAME(UTF8_STRING) = ' + title]):
                self.assertEqual(module.firefox_control_page_visible(), expected)

    def test_model_lab_capture_requires_the_active_shipped_firefox_dashboard(self):
        for kind, title, expected in (
                ('"firefox-esr"', '"Argos Live · Local workspace"', True),
                ('"firefox-esr"', '"Argos Live · Local workspace — Mozilla Firefox"', True),
                ('"other-browser"', '"Argos Live · Local workspace"', False),
                ('"firefox-esr"', '"OpenClaw Control"', False),
                ('"firefox-esr"', '"Argos Live — Mozilla Firefox"', False),
                ('"firefox-esr"', '"Argos Live · Local workspace with private URL"', False)):
            with self.subTest(title=title, kind=kind), patch.object(module.subprocess,
                    'check_output', side_effect=['_NET_ACTIVE_WINDOW: 0x123', kind,
                                                 '_NET_WM_NAME(UTF8_STRING) = ' + title]):
                self.assertEqual(module.firefox_model_lab_visible(), expected)

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
