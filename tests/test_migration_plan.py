import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = load('export_fixture', 'export-personal-config.py')
planner = load('migration_plan', 'plan-config-migration.py')


class MigrationPlanTests(unittest.TestCase):
    def fixture(self, root):
        source, exported = root / 'source', root / 'export'
        source.mkdir(); exported.mkdir()
        entries = {}
        for ident, name in [('main', 'Argos'), ('nyx', 'Nyx'), ('experimental', 'Proteus')]:
            workspace = source / ident
            workspace.mkdir()
            (workspace / 'SOUL.md').write_text('fixture persona', encoding='utf-8')
            entries[ident] = {'name': name, 'workspace': str(workspace), 'agentDir': 'C:/fixture/' + ident}
        entries['nyx']['model'] = {'primary': 'fixture/uncensored', 'fallbacks': []}
        config = {'agents': {'entries': entries, 'defaults': {'model': {'primary': 'fixture/main'}}},
                  'gateway': {'auth': {'token': 'fixture-token-never-activate'}}}
        (source / 'openclaw.json').write_text(json.dumps(config), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            exporter.export(source, exported)
        archive = exported / 'argos-nyx-proteus-config.zip'
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest(), source

    def test_roundtrip_keeps_ids_and_models_and_never_activates(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            archive, digest, source = self.fixture(root)
            before = (source / 'openclaw.json').read_bytes()
            result = planner.plan(archive, digest, root / 'stage', '/home/argos')
            self.assertEqual([p['id'] for p in result['profiles']], ['main', 'nyx', 'experimental'])
            self.assertEqual(result['profiles'][1]['effectiveModelReference']['primary'], 'fixture/uncensored')
            self.assertEqual(result['profiles'][0]['effectiveModelReference']['primary'], 'fixture/main')
            self.assertEqual(result['profiles'][2]['proposedWorkspace'], '/home/argos/.openclaw/workspace-experimental')
            self.assertNotIn('gateway', result)
            self.assertFalse(any(p['permissionsGranted'] for p in result['profiles']))
            self.assertEqual((source / 'openclaw.json').read_bytes(), before)
            self.assertFalse((root / 'stage' / 'openclaw.json').exists())
            self.assertFalse((root / 'stage' / 'SOUL.md').exists())

    def test_repeated_import_does_not_overwrite_previous_stage(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            archive, digest, _ = self.fixture(root)
            planner.plan(archive, digest, root / 'stage', '/home/argos')
            with self.assertRaises(ValueError):
                planner.plan(archive, digest, root / 'stage', '/home/argos')

    def test_wrong_digest_or_windows_home_produces_no_stage(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            archive, digest, _ = self.fixture(root)
            for expected, home in [('0' * 64, '/home/argos'), (digest, 'C:/Users/mike')]:
                with self.assertRaises(ValueError):
                    planner.plan(archive, expected, root / 'stage', home)
                self.assertFalse((root / 'stage').exists())


if __name__ == '__main__':
    unittest.main()
