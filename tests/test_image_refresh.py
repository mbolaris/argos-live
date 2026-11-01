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
        runtime_rel = Path('usr/local/lib/argos-live/argoslive')
        plugin_rel = Path('usr/local/share/argos-live/plugins/argos-improve')
        (self.root / runtime_rel / 'data').mkdir(parents=True)
        (self.lower / runtime_rel / 'data').mkdir(parents=True)
        (self.root / plugin_rel / 'skills/argos-improvement').mkdir(parents=True)
        (self.lower / plugin_rel / 'skills/argos-improvement').mkdir(parents=True)
        for name in image_refresh.ENTRYPOINTS:
            target = self.root / 'usr/local/bin' / name
            source = self.lower / 'usr/local/bin' / name
            target.write_text('old ' + name + '\n')
            source.write_text('new ' + name + '\n')
            target.chmod(0o755)
            source.chmod(0o755)
        self.files = {
            runtime_rel / '__init__.py': ('old runtime\n', 'new runtime\n', 0o644),
            runtime_rel / 'data/challenge.json': ('{}\n', '{"version":2}\n', 0o644),
            plugin_rel / 'index.js': ('old plugin\n', 'new plugin\n', 0o644),
            plugin_rel / 'skills/argos-improvement/SKILL.md': ('old skill\n', 'new skill\n', 0o644),
        }
        for relative, (old, new, mode) in self.files.items():
            target, source = self.root / relative, self.lower / relative
            target.write_text(old)
            source.write_text(new)
            target.chmod(mode)
            source.chmod(mode)
        self.stale = self.root / plugin_rel / 'legacy.js'
        self.stale.write_text('old plugin code\n')
        self.unrelated = self.root / 'home/argos/workspace/AGENTS.md'
        self.unrelated.parent.mkdir(parents=True)
        self.unrelated.write_text('owner and agent workspace\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_only_the_image_as_a_lower_layer(self):
        report = 'overlay rw,lowerdir=/other:/run/live/rootfs/filesystem.squashfs/,upperdir=/run/live/persistence/rw'
        self.assertTrue(image_refresh.supports_live_lower(report))
        self.assertFalse(image_refresh.supports_live_lower('ext4 rw,lowerdir=/run/live/rootfs/filesystem.squashfs'))
        self.assertFalse(image_refresh.supports_live_lower('overlay rw,lowerdir=/other'))

    def test_updates_runtime_plugin_and_entrypoints_with_snapshot(self):
        changed = image_refresh.refresh(self.root, self.lower)
        expected = {f'usr/local/bin/{name}' for name in image_refresh.ENTRYPOINTS}
        expected.update(relative.as_posix() for relative in self.files)
        expected.add(self.stale.relative_to(self.root).as_posix())
        self.assertEqual(set(changed), expected)
        for name in image_refresh.ENTRYPOINTS:
            target = self.root / 'usr/local/bin' / name
            self.assertEqual(target.read_text(), 'new ' + name + '\n')
            if os.name != 'nt':
                self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        for relative, (_, new, _) in self.files.items():
            self.assertEqual((self.root / relative).read_text(), new)
        self.assertFalse(self.stale.exists())
        self.assertEqual(self.unrelated.read_text(), 'owner and agent workspace\n')
        snapshots = list((self.root / 'var/lib/argos-live/runtime-refresh').iterdir())
        self.assertEqual(len(snapshots), 1)
        manifest = __import__('json').loads((snapshots[0] / 'manifest.json').read_text())
        self.assertEqual(manifest['schema'], 'argos-runtime-refresh-snapshot/1')
        self.assertEqual({item['path'] for item in manifest['changes']}, expected)
        with __import__('tarfile').open(snapshots[0] / 'before.tar.gz', 'r:gz') as archive:
            self.assertIn('before/usr/local/lib/argos-live/argoslive/__init__.py', archive.getnames())
        for tree in image_refresh.OWNED_TREES:
            self.assertFalse(list((self.root / tree).rglob('.argos-refresh-*')))

    def test_matching_entrypoints_are_not_rewritten(self):
        image_refresh.refresh(self.root, self.lower)
        before = {p.relative_to(self.root).as_posix(): p.stat().st_mtime_ns
                  for tree in image_refresh.OWNED_TREES
                  for p in (self.root / tree).rglob('*') if p.is_file()}
        before.update({f'usr/local/bin/{name}': (self.root / 'usr/local/bin' / name).stat().st_mtime_ns
                       for name in image_refresh.ENTRYPOINTS})
        snapshot_count = len(list((self.root / 'var/lib/argos-live/runtime-refresh').iterdir()))
        self.assertEqual(image_refresh.refresh(self.root, self.lower), [])
        after = {p.relative_to(self.root).as_posix(): p.stat().st_mtime_ns
                 for tree in image_refresh.OWNED_TREES
                 for p in (self.root / tree).rglob('*') if p.is_file()}
        after.update({f'usr/local/bin/{name}': (self.root / 'usr/local/bin' / name).stat().st_mtime_ns
                      for name in image_refresh.ENTRYPOINTS})
        self.assertEqual(after, before)
        self.assertEqual(len(list((self.root / 'var/lib/argos-live/runtime-refresh').iterdir())), snapshot_count)

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

    def test_late_write_failure_rolls_back_all_files(self):
        target = self.root / 'usr/local/share/argos-live/plugins/argos-improve/index.js'
        original_replace = os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if Path(destination) == target and not failed:
                failed = True
                raise OSError('injected replace failure')
            return original_replace(source, destination)

        with patch.object(image_refresh.os, 'replace', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected replace failure'):
                image_refresh.refresh(self.root, self.lower)
        self.assertEqual((self.root / 'usr/local/bin/argos').read_text(), 'old argos\n')
        for relative, (old, _, _) in self.files.items():
            self.assertEqual((self.root / relative).read_text(), old)
        self.assertEqual(self.stale.read_text(), 'old plugin code\n')
        self.assertEqual(self.unrelated.read_text(), 'owner and agent workspace\n')

    def test_unsafe_file_in_owned_tree_fails_before_any_update(self):
        target = self.root / 'usr/local/lib/argos-live/argoslive/data'
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', autospec=True,
                side_effect=lambda path: path == target or original(path)):
            with self.assertRaisesRegex(ValueError, 'unsafe directory'):
                image_refresh.refresh(self.root, self.lower)
        self.assertEqual((self.root / 'usr/local/bin/argos').read_text(), 'old argos\n')


if __name__ == '__main__':
    unittest.main()
