import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import storage, storage_view as sv, reboot_evidence as rb

GIB = 2**30
BOOT1 = '11111111-1111-4111-8111-111111111111'
BOOT2 = '22222222-2222-4222-8222-222222222222'


def blocks_json():
    return json.dumps({'blockdevices': [
        {'name': '/dev/sda', 'type': 'disk', 'fstype': None, 'uuid': None, 'label': None, 'tran': 'sata',
         'maj:min': '8:0', 'children': [
            {'name': '/dev/sda1', 'type': 'part', 'fstype': 'ntfs', 'uuid': 'data-uuid', 'label': 'DATA',
             'maj:min': '8:1'}]},
        {'name': '/dev/sdb', 'type': 'disk', 'fstype': None, 'uuid': None, 'label': None, 'tran': 'usb',
         'maj:min': '8:16', 'children': [
            {'name': '/dev/sdb1', 'type': 'part', 'fstype': 'iso9660', 'uuid': 'boot-uuid', 'label': 'ARGOS',
             'maj:min': '8:17'},
            {'name': '/dev/sdb2', 'type': 'part', 'fstype': 'crypto_LUKS', 'uuid': 'luks-uuid', 'label': None,
             'maj:min': '8:18', 'children': [
                {'name': '/dev/mapper/persist', 'type': 'crypt', 'fstype': 'ext4', 'uuid': 'persist-uuid',
                 'label': 'persistence', 'maj:min': '253:0'}]}]}]})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.data = self.root / 'data'
        self.persist = self.root / 'persist'
        self.tmpfs = self.root / 'ram'
        for path in (self.home / '.config/argos-live', self.data, self.persist / 'rw', self.tmpfs):
            path.mkdir(parents=True)
        self.mounts_text = '\n'.join([
            f'20 1 8:17 / {self.root}/medium ro - iso9660 /dev/sdb1 ro',
            f'21 1 8:1 / {self.data} rw - ntfs3 /dev/sda1 rw',
            f'22 1 253:0 / {self.persist} rw - ext4 /dev/mapper/persist rw',
            f'23 1 0:40 / {self.home} rw - overlay overlay rw,lowerdir=/x,upperdir={self.persist}/rw,workdir=/w',
            f'24 1 0:25 / {self.tmpfs} rw - tmpfs tmpfs rw,size=16G'])
        (self.root / 'medium').mkdir()
        self.mounts = storage.mount_table(self.mounts_text)
        self.blocks = storage.block_table(blocks_json())
        self.boot = {'8:16', '8:17'}
        patch = mock.patch.object(storage, 'LIVE_MEDIA', {str(self.root / 'medium')})
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def topology(self):
        return self.mounts, self.blocks, 64 * GIB

    def probe(self, path):
        return {'total_bytes': 500 * GIB, 'free_bytes': 400 * GIB}

    def write_state(self, **extra):
        models = self.persist / 'rw/models'
        models.mkdir(exist_ok=True)
        (models / '.argos-storage-id').write_text('ident\n')
        state = {'storage': str(models), 'storage_id': 'ident', 'model': 'qwen3:0.6b', **extra}
        (self.home / '.config/argos-live/state.json').write_text(json.dumps(state))
        return state


class BackingTests(Base):
    def test_overlay_home_resolves_to_encrypted_persistence(self):
        info = sv.backing(self.home / '.openclaw', self.mounts, self.blocks, self.boot)
        self.assertEqual(info['kind'], 'disk')
        self.assertTrue(info['via_overlay'])
        self.assertTrue(info['live_persistence'] or info['device'] == '/dev/mapper/persist')
        self.assertIs(info['encrypted'], True)
        self.assertEqual(info['label'], 'persistence')

    def test_data_volume_is_unencrypted_disk_with_label(self):
        info = sv.backing(self.data / 'ArgosLive/Models/catalog', self.mounts, self.blocks, self.boot)
        self.assertEqual((info['label'], info['filesystem']), ('DATA', 'ntfs3'))
        self.assertIs(info['encrypted'], False)
        self.assertFalse(info['boot_medium'])

    def test_tmpfs_is_temporary_and_encryption_unknown(self):
        info = sv.backing(self.tmpfs / 'models', self.mounts, self.blocks, self.boot)
        self.assertEqual(info['kind'], 'ram')
        self.assertIs(info['persistent'], False)
        self.assertIsNone(info['encrypted'])

    def test_overlay_without_upperdir_stays_unknown(self):
        self.mounts[3]['super_options'] = ['rw']
        info = sv.backing(self.home / '.openclaw', self.mounts, self.blocks, self.boot)
        self.assertEqual(info['kind'], 'unknown')
        self.assertIsNone(info['encrypted'])
        self.assertIsNone(info['persistent'])

    def test_unmapped_device_is_unknown_not_guessed(self):
        self.mounts[1]['device'] = '9:9'
        self.mounts[1]['source'] = '/dev/missing'
        info = sv.backing(self.data / 'x', self.mounts, self.blocks, self.boot)
        self.assertEqual(info['kind'], 'unknown')
        self.assertIsNone(info['encrypted'])


class WriteCheckTests(Base):
    def test_write_check_round_trips_and_removes_file(self):
        receipt = sv.write_check(self.data, size=1024)
        self.assertTrue(receipt['verified'])
        self.assertEqual(list(self.data.iterdir()), [])

    def test_write_check_rejects_missing_directory(self):
        with self.assertRaisesRegex(ValueError, 'existing directory'):
            sv.write_check(self.data / 'absent')

    def test_read_only_directory_fails(self):
        import os
        if os.name == 'nt' or os.getuid() == 0:
            self.skipTest('Permission denial is not enforceable here')
        self.data.chmod(0o500)
        try:
            with self.assertRaises(OSError):
                sv.write_check(self.data)
        finally:
            self.data.chmod(0o700)


class SnapshotTests(Base):
    def test_snapshot_lists_locations_candidates_and_unused_volume(self):
        self.write_state(storage_confirmed=None)
        value = sv.snapshot(self.home, topology=self.topology, probe=self.probe, boot=BOOT1)
        keys = [row['key'] for row in value['locations']]
        self.assertEqual(keys, ['models', 'profile', 'conversations', 'results', 'settings'])
        models = value['locations'][0]
        self.assertIs(models['backing']['encrypted'], True)
        self.assertEqual(models['reboot']['state'], 'not-started')
        self.assertFalse(value['confirmed'])
        kinds = {c['kind'] for c in value['candidates']}
        self.assertEqual(kinds, {'disk', 'ram'})
        ram = next(c for c in value['candidates'] if c['kind'] == 'ram')
        self.assertTrue(ram['temporary'])
        self.assertEqual([v['label'] for v in value['unused_volumes']], ['DATA'])

    def test_unconfigured_snapshot_is_not_configured(self):
        (self.home / '.config/argos-live/state.json').unlink(missing_ok=True)
        value = sv.snapshot(self.home, topology=self.topology, probe=self.probe, boot=BOOT1)
        self.assertEqual(value['state'], 'not-configured')
        self.assertFalse(value['can_change'])
        self.assertIsNone(value['locations'][0]['path'])

    def test_unreadable_topology_leaves_evidence_unknown(self):
        self.write_state()
        def broken():
            raise ValueError('Mount information unavailable')
        value = sv.snapshot(self.home, topology=broken, probe=self.probe, boot='')
        self.assertFalse(value['boot_id_available'])
        self.assertIsNone(value['locations'][0]['backing'])
        self.assertEqual(value['candidates'], [])

    def test_existing_models_block_a_change(self):
        state = self.write_state()
        store = Path(state['storage'])
        (store / 'blobs').mkdir()
        (store / 'blobs/sha256-x').write_text('x')
        value = sv.snapshot(self.home, topology=self.topology, probe=self.probe, boot=BOOT1)
        self.assertFalse(value['can_change'])
        self.assertIn('manual migration', value['change_blocked_reason'])

    def test_reboot_state_flows_into_locations(self):
        state = self.write_state()
        sv.start_reboot_check(self.home, current=BOOT1)
        pending = sv.snapshot(self.home, topology=self.topology, probe=self.probe, boot=BOOT1)
        self.assertEqual(pending['locations'][0]['reboot']['state'], 'pending')
        retained = sv.snapshot(self.home, topology=self.topology, probe=self.probe, boot=BOOT2)
        self.assertEqual(retained['locations'][0]['reboot']['state'], 'retained')
        self.assertEqual(retained['locations'][2]['reboot']['state'], retained['locations'][1]['reboot']['state'])
        self.assertTrue(Path(state['storage'], rb.MARKER).is_file())
        self.assertFalse((self.data / rb.MARKER).exists())


class ChooseTests(Base):
    def candidate(self, kind):
        rows = sv.candidates(self.mounts, self.blocks, 64 * GIB, probe=self.probe)
        return next(r for r in rows if r['kind'] == kind)

    def test_choose_new_empty_location_confirms_and_marks_identity(self):
        self.write_state()
        row = self.candidate('disk')
        result = sv.choose(self.home, row['id'], topology=self.topology, probe=self.probe,
                           clock=lambda: '2026-10-07T00:00:00+00:00')
        self.assertTrue(result['changed'])
        target = Path(row['path'])
        self.assertTrue((target / '.argos-storage-id').is_file())
        state = json.loads((self.home / '.config/argos-live/state.json').read_text())
        self.assertEqual(state['storage'], str(target))
        self.assertEqual(state['storage_uuid'], 'data-uuid')
        self.assertIs(state['storage_encrypted'], False)
        self.assertTrue(sv.confirmed(state))
        self.assertEqual(storage.validate_configured(state, mounts=self.mounts, blocks=self.blocks), target)

    def test_choose_current_store_only_confirms_after_write_check(self):
        state = self.write_state()
        rows = sv.candidates(self.mounts, self.blocks, 64 * GIB, probe=self.probe)
        rows = [r for r in rows if r['path'] == state['storage']]
        self.assertFalse(rows)  # The current store is not an auto-eligible catalog path.
        seen = []
        calls = {'n': 0}
        def check(path):
            calls['n'] += 1
            return {'verified': True, 'bytes': 1, 'at': 'now'}
        self.mounts = self.mounts[:]  # unchanged
        # Confirm by choosing an id equal to the configured path via a custom topology row.
        original = sv.candidates
        try:
            sv.candidates = lambda *a, **k: [{'id': 'a' * 20, 'path': state['storage'], 'kind': 'disk',
                                              'volume_uuid': None, 'encrypted': True}]
            result = sv.choose(self.home, 'a' * 20, topology=self.topology, probe=self.probe, check=check)
        finally:
            sv.candidates = original
        self.assertFalse(result['changed'])
        self.assertEqual(calls['n'], 1)
        self.assertTrue(sv.confirmed(json.loads((self.home / '.config/argos-live/state.json').read_text())))

    def test_failed_write_check_leaves_state_and_removes_new_directories(self):
        self.write_state()
        before = (self.home / '.config/argos-live/state.json').read_bytes()
        row = self.candidate('disk')
        def check(path):
            raise OSError('disk full')
        with self.assertRaises(OSError):
            sv.choose(self.home, row['id'], topology=self.topology, probe=self.probe, check=check)
        self.assertEqual((self.home / '.config/argos-live/state.json').read_bytes(), before)
        self.assertFalse((self.data / 'ArgosLive').exists())

    def test_nonempty_destination_is_not_adopted(self):
        self.write_state()
        row = self.candidate('disk')
        target = Path(row['path'])
        target.mkdir(parents=True)
        (target / 'something').write_text('x')
        with self.assertRaisesRegex(ValueError, 'already contains data'):
            sv.choose(self.home, row['id'], topology=self.topology, probe=self.probe)
        self.assertEqual([p.name for p in target.iterdir()], ['something'])

    def test_unlisted_or_malformed_choice_is_rejected(self):
        self.write_state()
        for bad in ('0' * 20, 'short', None, 5):
            with self.assertRaises(ValueError):
                sv.choose(self.home, bad, topology=self.topology, probe=self.probe)

    def test_store_with_models_cannot_be_moved(self):
        state = self.write_state()
        Path(state['storage'], 'blobs').mkdir()
        Path(state['storage'], 'blobs/sha256-x').write_text('x')
        row = self.candidate('disk')
        with self.assertRaisesRegex(ValueError, 'manual migration'):
            sv.choose(self.home, row['id'], topology=self.topology, probe=self.probe)

    def test_insufficient_space_removes_candidate(self):
        small = lambda path: {'total_bytes': 500 * GIB, 'free_bytes': 1}
        self.assertEqual(sv.candidates(self.mounts, self.blocks, 64 * GIB, probe=small), [])


class DownloadGateTests(Base):
    def test_unconfirmed_store_blocks_download(self):
        self.write_state()
        with self.assertRaisesRegex(ValueError, 'Choose where models are stored'):
            sv.require_ready_for_download(self.home, check=lambda p: None)

    def test_confirmed_store_runs_fresh_write_check(self):
        state = self.write_state()
        state['storage_confirmed'] = {'path': state['storage'], 'storage_id': 'ident', 'at': 'x'}
        (self.home / '.config/argos-live/state.json').write_text(json.dumps(state))
        seen = []
        path = sv.require_ready_for_download(self.home, check=seen.append)
        self.assertEqual(seen, [path])

    def test_confirmation_for_another_store_does_not_count(self):
        state = self.write_state()
        state['storage_confirmed'] = {'path': '/elsewhere', 'storage_id': 'ident', 'at': 'x'}
        (self.home / '.config/argos-live/state.json').write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            sv.require_ready_for_download(self.home, check=lambda p: None)

    def test_failed_write_check_blocks_download(self):
        state = self.write_state()
        state['storage_confirmed'] = {'path': state['storage'], 'storage_id': 'ident', 'at': 'x'}
        (self.home / '.config/argos-live/state.json').write_text(json.dumps(state))
        def check(path):
            raise OSError('read-only file system')
        with self.assertRaises(OSError):
            sv.require_ready_for_download(self.home, check=check)

    def test_missing_state_blocks_download(self):
        with self.assertRaises(FileNotFoundError):
            sv.require_ready_for_download(self.home, check=lambda p: None)


if __name__ == '__main__':
    unittest.main()
