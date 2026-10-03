import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('personal_export', pathlib.Path(__file__).parents[1] / 'scripts/export-personal-config.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PersonalExportTests(unittest.TestCase):
    def test_private_configuration_remains_inert_and_credentials_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / 'source'
            destination = root / 'export'
            source.mkdir(); destination.mkdir()
            (source / 'credentials').mkdir()
            secret = 'fixture-secret-never-export-this'
            (source / 'credentials/provider.json').write_text(json.dumps({'apiKey': secret}))
            entries = {}
            for agent_id, name in [('main', 'Argos'), ('nyx', 'Nyx'), ('experimental', 'Proteus')]:
                workspace = source / agent_id
                workspace.mkdir()
                (workspace / 'SOUL.md').write_text('Personal instructions with ' + secret)
                (workspace / 'setup.sh').write_text('echo unauthorized')
                (workspace / 'history.sqlite').write_bytes(b'private sessions')
                entries[agent_id] = {'name': name, 'workspace': str(workspace), 'tools': {'exec': {'enabled': True}}}
            (source / 'openclaw.json').write_text(json.dumps({'agents': {'entries': entries}, 'gateway': {'auth': {'token': secret}}}))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                module.export(source, destination)
            self.assertNotIn(secret, output.getvalue())
            with zipfile.ZipFile(destination / 'argos-nyx-proteus-config.zip') as archive:
                for name in archive.namelist():
                    self.assertNotIn(secret.encode(), archive.read(name))
                    self.assertNotIn('credentials', name)
                    self.assertFalse(name.endswith(('.sh', '.sqlite')))
                reference = json.loads(archive.read('migration-reference.json'))
                self.assertEqual(len(reference['profiles']), 3)
                self.assertIn('Do not replace live config', reference['importPolicy'])
                self.assertIsNone(archive.testzip())

    def test_export_never_follows_external_skill_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / 'source'; source.mkdir()
            destination = root / 'export'; destination.mkdir()
            (source / 'openclaw.json').write_text('{"agents":{"entries":{}}}')
            skills = source / 'skills'; skills.mkdir()
            external = root / 'external'; external.mkdir()
            (external / 'SKILL.md').write_text('Must not copy external installation')
            try:
                (skills / 'linked').symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks requires Windows developer mode or administrator privileges')
            with contextlib.redirect_stdout(io.StringIO()):
                module.export(source, destination)
            with zipfile.ZipFile(destination / 'argos-nyx-proteus-config.zip') as archive:
                self.assertFalse(any(name.startswith('capability-reference/') for name in archive.namelist()))
                reference = json.loads(archive.read('migration-reference.json'))
                self.assertEqual(len(reference['excludedReferences']), 1)


if __name__ == '__main__':
    unittest.main()
