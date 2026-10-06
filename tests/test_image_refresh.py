from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import image_refresh


class ImageRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'root'
        self.lower = Path(self.temp.name) / 'image'
        (self.root / 'usr/local/bin').mkdir(parents=True)
        (self.lower / 'usr/local/bin').mkdir(parents=True)
        for name in image_refresh.ENTRYPOINTS:
            target = self.root / 'usr/local/bin' / name
            source = self.lower / 'usr/local/bin' / name
            target.write_text('old ' + name + '\n')
            source.write_text('new ' + name + '\n')
            target.chmod(0o755)
            source.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_only_the_image_as_a_lower_layer(self):
        report = 'overlay rw,lowerdir=/other:/run/live/rootfs/filesystem.squashfs/,upperdir=/run/live/persistence/rw'
        self.assertTrue(image_refresh.supports_live_lower(report))
        self.assertFalse(image_refresh.supports_live_lower('ext4 rw,lowerdir=/run/live/rootfs/filesystem.squashfs'))
        self.assertFalse(image_refresh.supports_live_lower('overlay rw,lowerdir=/other'))

    def test_updates_only_the_three_distro_owned_entrypoints(self):
        changed = image_refresh.refresh(self.root, self.lower)
        self.assertEqual(changed, list(image_refresh.ENTRYPOINTS))
        for name in image_refresh.ENTRYPOINTS:
            target = self.root / 'usr/local/bin' / name
            self.assertEqual(target.read_text(), 'new ' + name + '\n')
            if os.name != 'nt':
                self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertFalse(list((self.root / 'usr/local/bin').glob('.argos-refresh-*')))

    def test_matching_entrypoints_are_not_rewritten(self):
        for name in image_refresh.ENTRYPOINTS:
            target = self.root / 'usr/local/bin' / name
            source = self.lower / 'usr/local/bin' / name
            target.write_bytes(source.read_bytes())
        before = {name: (self.root / 'usr/local/bin' / name).stat().st_mtime_ns
                  for name in image_refresh.ENTRYPOINTS}
        self.assertEqual(image_refresh.refresh(self.root, self.lower), [])
        after = {name: (self.root / 'usr/local/bin' / name).stat().st_mtime_ns
                 for name in image_refresh.ENTRYPOINTS}
        self.assertEqual(after, before)

    def test_symlink_destination_fails_before_any_update(self):
        victim = self.root / 'usr/local/bin/argos-launch'
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', autospec=True,
                side_effect=lambda path: path == victim or original(path)):
            with self.assertRaisesRegex(ValueError, 'not a regular file'):
                image_refresh.refresh(self.root, self.lower)
        self.assertEqual((self.root / 'usr/local/bin/argos').read_text(), 'old argos\n')

    def test_missing_image_entrypoint_fails_before_any_update(self):
        (self.lower / 'usr/local/bin/argos-welcome').unlink()
        with self.assertRaisesRegex(ValueError, 'missing a regular'):
            image_refresh.refresh(self.root, self.lower)
        self.assertEqual((self.root / 'usr/local/bin/argos').read_text(), 'old argos\n')


if __name__ == '__main__':
    unittest.main()
