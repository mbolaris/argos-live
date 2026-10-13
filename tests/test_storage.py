import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import storage

GIB = 2**30
FIXTURES = ROOT / 'tests/fixtures/storage'


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.mounts = storage.mount_table((FIXTURES / 'mountinfo.txt').read_text())
        self.blocks = storage.block_table((FIXTURES / 'blocks.json').read_text())
        self.metrics = {'/mnt/small': {'total_bytes': 100 * GIB, 'free_bytes': 30 * GIB},
                        '/mnt/big disk': {'total_bytes': 500 * GIB, 'free_bytes': 20 * GIB},
                        '/mnt/boot-persistence': {'total_bytes': 1000 * GIB, 'free_bytes': 900 * GIB},
                        '/ram': {'total_bytes': 16 * GIB, 'free_bytes': 10 * GIB}}

    def probe(self, path):
        for root, metrics in self.metrics.items():
            if str(path).startswith(root + '/'):
                return metrics
        return None

    def select(self, **options):
        return storage.select(self.mounts, self.blocks, 4 * GIB, probe=self.probe, uid=1000, **options)

    def test_largest_disk_excludes_all_partitions_of_boot_device(self):
        result = self.select(ram_available=100 * GIB)
        self.assertEqual(result['path'], '/mnt/big disk/ArgosLive/Models/catalog')
        self.assertFalse(result['encrypted'])
        self.assertTrue(result['persistent'])
        self.assertEqual(result['volume_uuid'], 'fixture-big')
        self.assertTrue(result['selection_only'])
        self.assertFalse(result['write_verified'])

    def live_encrypted_overlay(self, root):
        home = root / 'home/argos'
        persist = root / 'run/live/persistence/sdb2'
        medium = root / 'run/live/medium'
        home.mkdir(parents=True)
        persist.mkdir(parents=True)
        medium.mkdir(parents=True)
        (persist / 'persistence.conf').write_text('/ union\n')
        mounts = storage.mount_table('\n'.join([
            f'20 1 8:17 / {medium} ro - iso9660 /dev/sdb1 ro',
            f'21 1 253:0 / {persist} rw - ext4 /dev/mapper/persist rw',
            f'22 1 0:40 / {home} rw - overlay overlay rw,upperdir={persist}/upper,workdir={persist}/work',
            f'23 1 8:1 / /mnt/small rw - ext4 /dev/sda1 rw',
            f'24 1 8:2 / /mnt/big rw - ntfs3 /dev/sda2 rw']))
        blocks = storage.block_table(json.dumps({'blockdevices': [
            {'name': '/dev/sda', 'type': 'disk', 'maj:min': '8:0', 'children': [
                {'name': '/dev/sda1', 'type': 'part', 'fstype': 'ext4', 'uuid': 'small', 'maj:min': '8:1'},
                {'name': '/dev/sda2', 'type': 'part', 'fstype': 'ntfs', 'uuid': 'big', 'maj:min': '8:2'}]},
            {'name': '/dev/sdb', 'type': 'disk', 'tran': 'usb', 'maj:min': '8:16', 'children': [
                {'name': '/dev/sdb1', 'type': 'part', 'fstype': 'iso9660', 'uuid': 'boot', 'maj:min': '8:17'},
                {'name': '/dev/sdb2', 'type': 'part', 'fstype': 'crypto_LUKS', 'uuid': 'luks', 'maj:min': '8:18',
                 'children': [{'name': '/dev/mapper/persist', 'type': 'crypt', 'fstype': 'ext4',
                               'uuid': 'persist-uuid', 'maj:min': '253:0'}]}]}]}))
        return home, persist, medium, mounts, blocks

    def test_encrypted_full_root_boot_persistence_is_stable_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, _, medium, mounts, blocks = self.live_encrypted_overlay(root)
            metrics = {'total_bytes': 58 * GIB, 'free_bytes': 48 * GIB}
            with patch('argoslive.storage.Path.home', return_value=home), \
                    patch.object(storage, 'LIVE_MEDIA', {str(medium)}), \
                    patch.object(storage, 'PERSISTENCE_ROOTS', (str(root / 'run/live/persistence').rstrip('\\/') + os.sep,)):
                result = storage.select(mounts, blocks, 4 * GIB,
                    probe=lambda path: metrics, ram_available=64 * GIB, uid=1000)
                self.assertEqual(result['kind'], 'persistence')
                self.assertEqual(result['path'], str(home / '.local/share/argos-live/models'))
                self.assertEqual(result['volume_uuid'], 'persist-uuid')
                self.assertIs(result['encrypted'], True)
                self.assertTrue(result['live_persistence'])
                self.assertEqual(result['filesystem'], 'overlay')

    def test_unverified_or_small_boot_persistence_falls_back_to_other_drive(self):
        for change in ('missing-file', 'not-full-root', 'unencrypted', 'readonly', 'too-small', 'not-boot-card'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home, persist, medium, mounts, blocks = self.live_encrypted_overlay(root)
                if change == 'missing-file':
                    (persist / 'persistence.conf').unlink()
                elif change == 'not-full-root':
                    (persist / 'persistence.conf').write_text('/home union\n')
                elif change == 'unencrypted':
                    luks = blocks['253:0']
                    luks['encrypted_paths'] = [False]
                elif change == 'readonly':
                    next(m for m in mounts if m['target'] == str(persist))['super_options'] = ['ro']
                if change == 'not-boot-card':
                    blocks['253:0']['ancestors'] = {'8:32', '8:33', '253:0'}
                def probe(path):
                    small = change == 'too-small' and str(path).startswith(str(home))
                    return {'total_bytes': 58 * GIB, 'free_bytes': 4 * GIB if small else 48 * GIB}
                with patch('argoslive.storage.Path.home', return_value=home), \
                        patch.object(storage, 'LIVE_MEDIA', {str(medium)}), \
                        patch.object(storage, 'PERSISTENCE_ROOTS', (str(root / 'run/live/persistence').rstrip('\\/') + os.sep,)):
                    result = storage.select(mounts, blocks, 4 * GIB,
                        probe=probe, ram_available=64 * GIB, uid=1000)
                    self.assertEqual(result['kind'], 'disk')
                    self.assertEqual(result['volume_uuid'], 'big')

    def test_configured_model_store_tracks_the_encrypted_volume_not_device_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, persist, medium, mounts, blocks = self.live_encrypted_overlay(root)
            models = home / '.local/share/argos-live/models'
            models.mkdir(parents=True)
            (models / '.argos-storage-id').write_text('owner-id\n')
            config = {'storage': str(models), 'storage_id': 'owner-id', 'storage_uuid': 'persist-uuid'}
            with patch('argoslive.storage.Path.home', return_value=home), \
                    patch.object(storage, 'LIVE_MEDIA', {str(medium)}), \
                    patch.object(storage, 'PERSISTENCE_ROOTS', (str(root / 'run/live/persistence').rstrip('\\/') + os.sep,)):
                selected = storage.select(mounts, blocks, GIB, configured=config,
                    probe=lambda path: {'total_bytes': 58 * GIB, 'free_bytes': 48 * GIB})
                self.assertEqual(selected['kind'], 'persistence')
                self.assertIs(selected['encrypted'], True)
                blocks['253:0']['uuid'] = 'replacement-volume'
                with self.assertRaisesRegex(ValueError, 'UUID differs'):
                    storage.select(mounts, blocks, GIB, configured=config,
                        probe=lambda path: {'total_bytes': 58 * GIB, 'free_bytes': 48 * GIB})

    def test_readonly_and_insufficient_capacity_are_skipped(self):
        self.mounts[2]['super_options'] = ['ro']
        result = self.select()
        self.assertEqual(result['mountpoint'], '/mnt/small')
        self.mounts[2]['super_options'] = ['rw']
        self.metrics['/mnt/big disk']['free_bytes'] = 5 * GIB - 1
        self.assertEqual(self.select()['mountpoint'], '/mnt/small')
        self.metrics['/mnt/big disk']['free_bytes'] = 5 * GIB
        self.assertEqual(self.select()['mountpoint'], '/mnt/big disk')

    def test_ram_requires_both_available_memory_and_mount_capacity(self):
        self.mounts = [m for m in self.mounts if m['fstype'] not in storage.DISK_FILESYSTEMS]
        with self.assertRaisesRegex(ValueError, 'No suitable'):
            self.select(ram_available=5 * GIB - 1)
        result = self.select(ram_available=5 * GIB)
        self.assertEqual(result['kind'], 'ram')
        self.assertFalse(result['persistent'])
        self.assertIsNone(result['encrypted'])
        self.metrics['/ram']['free_bytes'] = 4 * GIB
        with self.assertRaisesRegex(ValueError, 'No suitable'):
            self.select(ram_available=100 * GIB)

    def test_unknown_boot_identity_blocks_automatic_disk_selection(self):
        self.mounts = [m for m in self.mounts if m['target'] != '/run/live/medium']
        with self.assertRaisesRegex(ValueError, 'boot device identity unavailable'):
            self.select()
        self.assertEqual(self.select(ram_available=100 * GIB)['kind'], 'ram')

    def configured_fixture(self, root):
        directory = root / 'models'
        directory.mkdir()
        (directory / '.argos-storage-id').write_text('fixture-owner-identity\n')
        configured = {'storage': str(directory), 'storage_id': 'fixture-owner-identity',
                      'storage_uuid': 'fixture-big'}
        mount = dict(self.mounts[2], target=str(root))
        return directory, configured, [mount]

    def test_configured_identity_wins_and_mismatch_never_uses_other_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path, configured, mounts = self.configured_fixture(Path(directory))
            probe = Mock(return_value={'total_bytes': 20 * GIB, 'free_bytes': 10 * GIB})
            result = storage.select(mounts, self.blocks, GIB, configured=configured, probe=probe)
            self.assertEqual(result['path'], str(path))
            self.assertEqual(result['kind'], 'configured')
            configured['storage_id'] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                storage.select(mounts + self.mounts, self.blocks, GIB, configured=configured, probe=probe)
            configured['storage_id'] = 'fixture-owner-identity'
            configured['storage_uuid'] = 'different-volume'
            probe.reset_mock()
            with self.assertRaisesRegex(ValueError, 'UUID differs'):
                storage.select(mounts + self.mounts, self.blocks, GIB, configured=configured, probe=probe)
            probe.assert_not_called()

    def test_missing_configured_path_does_not_create_any_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing'
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                self.select(configured={'storage': str(path), 'storage_id': 'fixture'})
            self.assertFalse(path.exists())

    def test_configured_readonly_or_full_stops_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            _, configured, mounts = self.configured_fixture(Path(directory))
            mounts[0]['options'] = ['ro']
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                storage.select(mounts, self.blocks, GIB, configured=configured,
                               probe=lambda p: {'total_bytes': 30 * GIB, 'free_bytes': 20 * GIB})
            mounts[0]['options'] = ['rw']
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                storage.select(mounts, self.blocks, GIB, configured=configured,
                               probe=lambda p: {'total_bytes': 30 * GIB, 'free_bytes': 0})

    def test_crypt_ancestry_and_mixed_ancestry_report_conservatively(self):
        plain = json.loads((FIXTURES / 'blocks.json').read_text())
        original = plain['blockdevices'][0]['children'][1]
        encrypted = {'name': '/dev/mapper/fixture', 'type': 'crypt', 'fstype': 'ext4',
                     'uuid': 'fixture-big', 'maj:min': '253:0'}
        original['fstype'] = 'crypto_LUKS'
        original['children'] = [encrypted]
        self.blocks = storage.block_table(json.dumps(plain))
        self.mounts[2].update(device='253:0', source='/dev/mapper/fixture', fstype='ext4')
        self.assertTrue(self.select()['encrypted'])
        plain['blockdevices'].append(dict(encrypted, type='part'))
        self.blocks = storage.block_table(json.dumps(plain))
        self.assertIsNone(self.select()['encrypted'])

    def test_bind_views_missing_uuid_and_unwritable_mounts_not_selected(self):
        self.mounts[2]['root'] = '/subdir'
        self.blocks['8:1']['uuid'] = None
        with self.assertRaisesRegex(ValueError, 'No suitable'):
            self.select()
        self.mounts[2]['root'] = '/'
        with self.assertRaisesRegex(ValueError, 'No suitable'):
            storage.select(self.mounts, self.blocks, GIB, probe=lambda p: None, ram_available=100 * GIB)

    def test_capacity_probe_is_readonly_and_models_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ArgosLive/Models/catalog'
            result = storage.capacity(path)
            self.assertGreater(result['total_bytes'], 0)
            self.assertFalse((Path(directory) / 'ArgosLive').exists())

    @unittest.skipUnless(sys.platform != 'win32', 'Unlinked-path fixture requires Linux symlinks')
    def test_linked_model_directory_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / 'actual'
            actual.mkdir()
            (actual / '.argos-storage-id').write_text('fixture\n')
            link = root / 'link'
            link.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                storage.validate_configured({'storage': str(link), 'storage_id': 'fixture'})

    def test_configured_ram_requires_available_memory_and_is_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            _, configured, mounts = self.configured_fixture(Path(directory))
            del configured['storage_uuid']
            mounts[0].update(fstype='tmpfs', device='0:25', source='tmpfs')
            probe = lambda p: {'total_bytes': 20 * GIB, 'free_bytes': 10 * GIB}
            with self.assertRaisesRegex(ValueError, 'available memory'):
                storage.select(mounts, self.blocks, GIB, configured=configured, probe=probe)
            result = storage.select(mounts, self.blocks, GIB, configured=configured,
                                    probe=probe, ram_available=2 * GIB)
            self.assertFalse(result['persistent'])

    def test_cli_storage_uses_readonly_plan_before_setup_load(self):
        spec = importlib.util.spec_from_file_location('storage_fixture_cli', ROOT / 'runtime/argos.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, 'STATE', Path(directory) / 'no-state.json'), \
                 patch.object(sys, 'argv', ['argos', 'storage', '--json']), \
                 patch.object(storage, 'plan', return_value={'selection_only': True}) as plan, \
                 patch('builtins.print') as output, patch.object(cli, 'load') as active_load:
                cli.main()
            plan.assert_called_once_with(4 * GIB, None)
            active_load.assert_not_called()
            self.assertTrue(json.loads(output.call_args.args[0])['selection_only'])

    def test_parser_and_budget_reject_ambiguous_input(self):
        self.assertEqual(self.mounts[2]['target'], '/mnt/big disk')
        with self.assertRaises(ValueError):
            storage.mount_table('malformed')
        with self.assertRaises(ValueError):
            storage.block_table('{"blockdevices":[{"name":"unknown"}]}')
        with self.assertRaises(ValueError):
            storage.select(self.mounts, self.blocks, -1)

    def test_nested_or_stacked_mount_cannot_misreport_storage_identity(self):
        self.mounts.append(dict(self.mounts[2], target='/mnt/big disk/ArgosLive',
                                root='/subdir', source='/dev/other', device='8:99'))
        self.assertEqual(self.select()['mountpoint'], '/mnt/small')
        self.mounts.pop()
        self.mounts.append(dict(self.mounts[2], source='/dev/other', device='8:99'))
        self.assertEqual(self.select()['mountpoint'], '/mnt/small')
        with self.assertRaisesRegex(ValueError, 'Ambiguous stacked'):
            storage.covering('/mnt/big disk/models', self.mounts)

    def test_automount_trigger_and_direct_child_keep_disk_eligible(self):
        volume = self.mounts[2]
        volume['parent_id'] = 900
        trigger = dict(volume, mount_id=900, parent_id=1, fstype='autofs',
                       device='0:90', source='systemd-1')
        self.mounts.append(trigger)
        self.assertIs(storage.covering('/mnt/big disk/models', self.mounts), volume)
        self.assertEqual(self.select()['volume_uuid'], 'fixture-big')
        volume['options'] = ['ro']
        self.assertEqual(self.select()['mountpoint'], '/mnt/small')

    def test_automount_without_proven_child_stays_ambiguous(self):
        volume = self.mounts[2]
        trigger = dict(volume, mount_id=900, parent_id=1, fstype='autofs',
                       device='0:90', source='systemd-1')
        self.mounts.append(trigger)
        with self.assertRaisesRegex(ValueError, 'Ambiguous stacked'):
            storage.covering('/mnt/big disk/models', self.mounts)
        self.assertEqual(self.select()['mountpoint'], '/mnt/small')
