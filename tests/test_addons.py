import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import addons


class AddonInventoryTests(unittest.TestCase):
    def test_catalog_matches_host_pin_and_inert_skills(self):
        catalog = addons.load()
        pins = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines()
                    if '=' in line and not line.startswith('#'))
        self.assertEqual(catalog['host_version'], pins['OPENCLAW_VERSION'])
        self.assertEqual(catalog['host_integrity'], pins['OPENCLAW_INTEGRITY'])
        self.assertEqual(len(catalog['plugins']), 6)
        self.assertGreater(len(catalog['shipped_skill_documents']), 0)
        self.assertEqual(catalog['external_addons'], [])

    def test_version_and_false_readiness_claims_rejected(self):
        for field, value in [('version', '0.0.0'), ('invocation_verified', True), ('manifest_sha256', 'invalid')]:
            catalog = copy.deepcopy(addons.load())
            catalog['plugins'][0][field] = value
            with self.assertRaises(ValueError):
                addons.validate(catalog)

    def test_snapshot_loaded_is_not_runtime_or_tool_grant(self):
        raw = {'plugin': {'id': 'ollama', 'version': addons.load()['host_version'], 'status': 'loaded'},
               'private': 'must not copy', 'tools': ['browser']}
        snapshot = addons.observation(raw)
        self.assertIsNone(snapshot['runtime_loaded'])
        self.assertNotIn('private', snapshot)
        registered = addons.observation(raw, runtime=True)
        self.assertTrue(registered['runtime_loaded'])
        result = addons.inventory(addons.load(), observations=[registered], which=lambda name: '/fixture/' + name)
        chat = result['capabilities'][0]
        self.assertTrue(chat['installed_on_target'])
        self.assertFalse(chat['ready'])
        self.assertFalse(chat['invocation_verified'])
        self.assertIsNone(chat['effective_agent_tool_grants'])

    def test_unknown_installation_missing_dependencies_and_pending_selections(self):
        result = addons.inventory(addons.load(), which=lambda name: None)
        rows = {row['capability']: row for row in result['capabilities']}
        self.assertIsNone(rows['local-chat']['installed_on_target'])
        self.assertEqual(rows['local-chat']['missing_binaries'], ['ollama'])
        self.assertEqual(rows['voice-input']['state'], 'selection-pending')
        self.assertTrue(all(not row['ready'] for row in rows.values()))
        self.assertTrue(rows['optional-channel']['requirements_pending'])

    def test_published_archive_rejected_before_metadata_read(self):
        import tempfile
        spec = importlib.util.spec_from_file_location('update_addons', ROOT / 'scripts/update-addons.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'invalid.tgz'
            archive.write_bytes(b'not an archive')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                generator.build(archive, {'OPENCLAW_INTEGRITY': addons.load()['host_integrity']})
