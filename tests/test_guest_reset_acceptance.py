import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guest_reset', ROOT / 'scripts/smoke-guest-reset.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GuestResetTests(unittest.TestCase):
    nonce = 'ab' * 16
    first_boot = '11111111-1111-1111-1111-111111111111'
    second_boot = '22222222-2222-2222-2222-222222222222'

    def test_seed_roundtrips_then_only_a_fresh_home_verifies(self):
        with tempfile.TemporaryDirectory() as temp, patch('argoslive.session_mode.require_ram') as ram:
            home = Path(temp) / 'first'
            first = module.probe_user_state(home, 'seed', self.nonce, self.first_boot, [])
            self.assertEqual(ram.call_count, 5)
            self.assertEqual(len(list(home.rglob('.argos-guest-reset-*'))), 5)
            with self.assertRaisesRegex(ValueError, 'unexpectedly exists'):
                module.probe_user_state(home, 'verify', self.nonce, self.second_boot, [])
            fresh = Path(temp) / 'second'
            second = module.probe_user_state(fresh, 'verify', self.nonce, self.second_boot, [])
            self.assertFalse(fresh.exists())
            self.assertTrue(module.verify_reset(first, second, self.nonce))

    def test_all_ram_checks_precede_any_write(self):
        with tempfile.TemporaryDirectory() as temp, patch('argoslive.session_mode.require_ram',
                side_effect=[None, None, None, None, ValueError('disk backed')]):
            home = Path(temp) / 'untouched'
            with self.assertRaisesRegex(ValueError, 'disk backed'):
                module.probe_user_state(home, 'seed', self.nonce, self.first_boot, [])
            self.assertFalse(home.exists())

    def test_same_boot_and_incomplete_receipts_cannot_establish_reset(self):
        with tempfile.TemporaryDirectory() as temp, patch('argoslive.session_mode.require_ram'):
            first = module.probe_user_state(Path(temp) / 'first', 'seed', self.nonce, self.first_boot, [])
            second = module.probe_user_state(Path(temp) / 'second', 'verify', self.nonce, self.second_boot, [])
        same_boot = dict(second, boot_id=self.first_boot)
        with self.assertRaisesRegex(ValueError, 'distinct kernel boot'):
            module.verify_reset(first, same_boot, self.nonce)
        for key, value in (('markers_checked', True), ('markers_checked', 4),
                ('all_markers_absent', False), ('ram_backing_verified', False),
                ('boot_id', 'unknown'), ('marker_sha256', '0' * 64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                changed = dict(second, **{key: value})
                module.verify_reset(first, changed, self.nonce)

    def test_reboot_requires_natural_exit_and_kernel_reboot_marker(self):
        for code, requested, text in ((1, True, 'reboot: Restarting system'),
                (0, False, 'reboot: Restarting system'), (0, True, 'reboot: Power down')):
            with self.subTest(code=code, requested=requested, text=text), self.assertRaises(ValueError):
                module.checked_exit(code, requested, 'seed', text)
        module.checked_exit(0, True, 'seed', '[12.34] reboot: Restarting system\n')

    def test_payload_is_serial_chunked_and_has_no_inference_or_model_download(self):
        payload = module.guest_payload('seed', self.nonce)
        compile(payload, '<guest-reset>', 'exec')
        commands = module.boot.guest_commands(payload)
        self.assertGreater(len(commands), 1)
        self.assertTrue(all(len(command) < 2000 for command in commands))
        self.assertNotIn(b'11434', payload)
        self.assertNotIn(b'argos_evaluate', payload)
