import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import image_refresh


class RuntimeOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root, self.lower = base / 'root', base / 'image'
        for base in (self.root, self.lower):
            (base / 'usr/local/bin').mkdir(parents=True)
            (base / image_refresh.RUNTIME_TREE).mkdir(parents=True)
            (base / image_refresh.OWNED_TREES[1]).mkdir(parents=True)
            for name in image_refresh.ENTRYPOINTS:
                path = base / 'usr/local/bin' / name
                path.write_text('image ' + name + '\n')
                path.chmod(0o755)
        (self.root / image_refresh.RUNTIME_TREE / '__init__.py').write_text('updated runtime\n')
        (self.lower / image_refresh.RUNTIME_TREE / '__init__.py').write_text('image runtime\n')
        (self.root / image_refresh.OWNED_TREES[1] / 'index.js').write_text('old plugin\n')
        (self.lower / image_refresh.OWNED_TREES[1] / 'index.js').write_text('image plugin\n')
        self.marker = self.root / image_refresh.OVERRIDE_MARKER

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_image_override_survives_boot_while_other_owned_files_refresh(self):
        recorded = image_refresh.record_override(self.root, self.lower, self.marker)
        self.assertIsNotNone(recorded)
        changed = image_refresh.refresh(self.root, self.lower, marker=self.marker)
        self.assertEqual((self.root / image_refresh.RUNTIME_TREE / '__init__.py').read_text(),
                         'updated runtime\n')
        self.assertEqual((self.root / image_refresh.OWNED_TREES[1] / 'index.js').read_text(),
                         'image plugin\n')
        self.assertEqual(set(changed), {'usr/local/share/argos-live/plugins/argos-improve/index.js'})
        self.assertTrue(self.marker.exists())

    def test_changed_image_runtime_replaces_override_and_clears_marker(self):
        image_refresh.record_override(self.root, self.lower, self.marker)
        (self.lower / image_refresh.RUNTIME_TREE / '__init__.py').write_text('newer image runtime\n')
        changed = image_refresh.refresh(self.root, self.lower, marker=self.marker)
        self.assertIn('usr/local/lib/argos-live/argoslive/__init__.py', changed)
        self.assertEqual((self.root / image_refresh.RUNTIME_TREE / '__init__.py').read_text(),
                         'newer image runtime\n')
        self.assertFalse(self.marker.exists())

    def test_modified_installed_runtime_does_not_match_override_marker(self):
        image_refresh.record_override(self.root, self.lower, self.marker)
        (self.root / image_refresh.RUNTIME_TREE / '__init__.py').write_text('unrecognized runtime\n')
        changed = image_refresh.refresh(self.root, self.lower, marker=self.marker)
        self.assertIn('usr/local/lib/argos-live/argoslive/__init__.py', changed)
        self.assertEqual((self.root / image_refresh.RUNTIME_TREE / '__init__.py').read_text(),
                         'image runtime\n')
        self.assertFalse(self.marker.exists())

    def test_bytecode_does_not_invalidate_a_matching_runtime_override(self):
        image_refresh.record_override(self.root, self.lower, self.marker)
        cache = self.root / image_refresh.RUNTIME_TREE / '__pycache__'
        cache.mkdir()
        (cache / 'runtime.cpython-314.pyc').write_bytes(b'ephemeral')
        changed = image_refresh.refresh(self.root, self.lower, marker=self.marker)
        self.assertNotIn('usr/local/lib/argos-live/argoslive/__init__.py', changed)
        self.assertTrue((cache / 'runtime.cpython-314.pyc').exists())

    def test_corrupt_marker_falls_back_to_the_image(self):
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text(json.dumps({'schema': 'wrong'}))
        changed = image_refresh.refresh(self.root, self.lower, marker=self.marker)
        self.assertIn('usr/local/lib/argos-live/argoslive/__init__.py', changed)
        self.assertEqual((self.root / image_refresh.RUNTIME_TREE / '__init__.py').read_text(),
                         'image runtime\n')


if __name__ == '__main__':
    unittest.main()
