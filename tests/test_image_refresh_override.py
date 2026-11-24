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


class PluginOverrideTests(RuntimeOverrideTests):
    """The Argos Improvement plugin can be preserved across boots like the runtime."""

    def setUp(self):
        super().setUp()
        self.plugin = image_refresh.PLUGIN_TREE
        self.plugin_marker = self.root / image_refresh.PLUGIN_OVERRIDE_MARKER
        (self.root / self.plugin / 'index.js').write_text('updated plugin\n')
        dependency = self.plugin / 'node_modules/typebox/package.json'
        for base in (self.root, self.lower):
            (base / dependency).parent.mkdir(parents=True)
            (base / dependency).write_text('{"name":"typebox"}\n')

    def refresh(self):
        return image_refresh.refresh(self.root, self.lower, marker=self.marker,
                                     plugin_marker=self.plugin_marker)

    def plugin_index(self):
        return (self.root / self.plugin / 'index.js').read_text()

    def test_plugin_override_survives_boot_without_a_runtime_override(self):
        recorded = image_refresh.record_plugin_override(self.root, self.lower, self.plugin_marker)
        self.assertEqual(recorded['schema'], 'argos-plugin-override/1')
        self.assertFalse(self.marker.exists())
        changed = self.refresh()
        self.assertEqual(self.plugin_index(), 'updated plugin\n')
        self.assertEqual(set(changed), {'usr/local/lib/argos-live/argoslive/__init__.py'})
        self.assertTrue(self.plugin_marker.exists())

    def test_runtime_and_plugin_overrides_are_both_preserved(self):
        image_refresh.record_override(self.root, self.lower, self.marker)
        image_refresh.record_plugin_override(self.root, self.lower, self.plugin_marker)
        self.assertEqual(self.refresh(), [])
        self.assertEqual(self.plugin_index(), 'updated plugin\n')
        self.assertEqual((self.root / image_refresh.RUNTIME_TREE / '__init__.py').read_text(),
                         'updated runtime\n')
        self.assertTrue(self.marker.exists() and self.plugin_marker.exists())

    def test_changed_image_plugin_replaces_override_and_clears_only_its_marker(self):
        image_refresh.record_override(self.root, self.lower, self.marker)
        image_refresh.record_plugin_override(self.root, self.lower, self.plugin_marker)
        (self.lower / self.plugin / 'index.js').write_text('newer image plugin\n')
        changed = self.refresh()
        self.assertEqual(set(changed), {'usr/local/share/argos-live/plugins/argos-improve/index.js'})
        self.assertEqual(self.plugin_index(), 'newer image plugin\n')
        self.assertFalse(self.plugin_marker.exists())
        self.assertTrue(self.marker.exists())

    def test_modified_installed_plugin_falls_back_to_the_image(self):
        image_refresh.record_plugin_override(self.root, self.lower, self.plugin_marker)
        (self.root / self.plugin / 'index.js').write_text('unrecognized plugin\n')
        self.refresh()
        self.assertEqual(self.plugin_index(), 'image plugin\n')
        self.assertFalse(self.plugin_marker.exists())

    def test_runtime_marker_does_not_validate_as_a_plugin_marker(self):
        image_refresh.record_override(self.root, self.lower, self.marker)
        self.plugin_marker.write_text(self.marker.read_text())
        self.refresh()
        # An unreadable marker is ignored (as with the runtime marker), so the image wins.
        self.assertEqual(self.plugin_index(), 'image plugin\n')

    def test_matching_plugin_needs_no_override(self):
        (self.root / self.plugin / 'index.js').write_text('image plugin\n')
        self.assertIsNone(image_refresh.record_plugin_override(self.root, self.lower, self.plugin_marker))
        self.assertFalse(self.plugin_marker.exists())


class RefreshWrapperTests(unittest.TestCase):
    def test_wrapper_uses_the_installed_package_for_plugin_overrides(self):
        text = (Path(__file__).resolve().parents[1] / 'runtime/argos-refresh-runtime').read_text()
        self.assertIn("Path('/var/lib/argos-live/runtime-refresh/active-plugin.json')", text)
        self.assertIn('PLUGIN_OVERRIDE_MARKER.exists()', text)
        self.assertIn("hasattr(image_refresh, 'record_plugin_override')", text)


if __name__ == '__main__':
    unittest.main()
