import json
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
