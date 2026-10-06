import sys
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import auto_setup, session_mode, storage, storage_view, starter


class GuestTests(unittest.TestCase):
    def test_exact_boot_token_only(self):
        self.assertTrue(session_mode.guest('boot=live nopersistence argos.guest=1'))
        for line in ('argos.guest=0', 'other=argos.guest=1', 'argos.guest=10', ''):
            self.assertFalse(session_mode.guest(line))

    def test_guest_setup_refuses_disk_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(session_mode, 'guest', return_value=True):
                with self.assertRaisesRegex(ValueError, 'requires RAM'):
                    auto_setup.configure(home, planner=lambda _: self.fail('planner ran'))
            self.assertEqual(list(home.iterdir()), [])

    def test_guest_setup_mode_and_persistence_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'home'
            home.mkdir()
            models = Path(directory) / 'models'
            with patch.object(session_mode, 'guest', return_value=True), \
                    patch.object(session_mode, 'require_ram') as check:
                args = dict(planner=lambda _: {'path': str(models), 'kind': 'ram'},
                            verify_seed=lambda: {'tag': starter.TAG})
                with self.assertRaisesRegex(ValueError, 'cannot use live persistence'):
                    auto_setup.configure(home, probe_persistence=lambda: {'active': True}, **args)
                self.assertFalse(models.exists())
                result = auto_setup.configure(home, probe_persistence=lambda: {'active': False}, **args)
                self.assertEqual(result['mode'], 'guest')
                self.assertTrue(result['storage_temporary'])
                check.assert_any_call(home)
                check.assert_any_call(models)

    def test_guest_cannot_adopt_existing_disk_store_or_check_retention(self):
        with patch.object(session_mode, 'guest', return_value=True):
            with self.assertRaisesRegex(ValueError, 'requires RAM'):
                storage.validate_configured({'storage': '/mnt/data/models'}, mounts=[])
            with self.assertRaisesRegex(ValueError, 'reset on reboot'):
                storage_view.start_reboot_check('/unused')

    def test_ram_and_overlay_backing_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            common = {'root': '/', 'options': ['rw'], 'device': '0:1', 'source': 'none'}
            ram = dict(common, target=str(path.anchor), fstype='tmpfs', super_options=['rw'])
            session_mode.require_ram(path, [ram])
            disk = dict(ram, fstype='ext4')
            with self.assertRaises(ValueError):
                session_mode.require_ram(path, [disk])
            overlay = dict(common, target=str(path.anchor), fstype='overlay',
                           super_options=['rw', 'upperdir=' + str(path / 'upper')])
            upper = dict(ram, target=str(path / 'upper'))
            session_mode.require_ram(path, [overlay, upper])

    @unittest.skipUnless(os.name == 'posix', 'Linux mount paths')
    def test_disk_candidates_hidden_but_ram_retained(self):
        common = {'root': '/', 'options': ['rw'], 'super_options': ['rw'], 'source': 'none'}
        mounts = [dict(common, target='/run/live/medium', device='8:1', fstype='iso9660'),
                  dict(common, target='/data', device='8:2', fstype='ext4'),
                  dict(common, target='/run', device='0:1', fstype='tmpfs')]
        blocks = {device: {'uuid': device, 'ancestors': {device}, 'encrypted_paths': [False],
                          'name': device} for device in ('8:1', '8:2')}
        capacity = lambda _: {'total_bytes': 8 * 1024**3, 'free_bytes': 7 * 1024**3}
        with patch.object(session_mode, 'guest', return_value=True):
            rows = storage.eligible(mounts, blocks, 1, ram_available=8 * 1024**3, probe=capacity)
        self.assertEqual([row['kind'] for row in rows], ['ram'])


if __name__ == '__main__':
    unittest.main()
