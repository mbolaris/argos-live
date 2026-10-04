import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import pack_export, packs


class ExportTests(unittest.TestCase):
    def fixture(self, root, style='list'):
        source = root / 'source'
        source.mkdir()
        workspace = root / 'workspace'
        workspace.mkdir()
        secret = 'test-secret-must-be-redacted'
        (workspace / 'SOUL.md').write_text('Helpful fictional guide. ' + secret)
        (workspace / 'MEMORY.md').write_text('private memory')
        (workspace / 'TOOLS.md').write_text('runtime grants')
        skill = workspace / 'skills/example'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('Explain an example, with ' + secret)
        (skill / 'helper.py').write_text('do not execute or copy')
        (workspace / 'skills/unselected').mkdir()
        (workspace / 'skills/unselected/SKILL.md').write_text('not selected')
        (source / 'credentials').mkdir()
        (source / 'credentials/provider.json').write_text(json.dumps({'apiKey': secret}))
        entry = {'id': 'main', 'name': 'Guide', 'workspace': str(workspace),
                 'model': {'primary': 'ollama/qwen3:0.6b'}, 'tools': {'profile': 'full'}}
        roster = {'list': [entry]} if style == 'list' else {'entries': {'main': entry}}
        config = {'agents': roster, 'gateway': {'auth': {'token': secret}}}
        (source / 'openclaw.json').write_text(json.dumps(config))
        return source, workspace, secret

    def test_narrow_export_redacts_secrets_and_preserves_source(self):
        for style in ('list', 'entries'):
            with self.subTest(style=style), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, workspace, secret = self.fixture(root, style)
                before = (source / 'openclaw.json').read_bytes()
                original_persona = (workspace / 'SOUL.md').read_bytes()
                output = root / 'private-export'
                result = pack_export.export(source, output, ['main'], ['main:example'])
                archive = output / 'personality-pack.zip'
                verified = packs.inspect(archive, result['archive_sha256'])
                self.assertEqual(len(verified['manifest']['files']), 2)
                agent = verified['manifest']['agents'][0]
                self.assertEqual(agent['model_preference']['name'], 'qwen3:0.6b')
                self.assertNotIn('tools', agent)
                with zipfile.ZipFile(archive) as bundle:
                    for name in bundle.namelist():
                        self.assertNotIn(secret.encode(), bundle.read(name))
                    self.assertFalse(any('MEMORY' in name or 'TOOLS' in name or 'helper' in name
                                         or 'unselected' in name for name in bundle.namelist()))
                self.assertEqual(before, (source / 'openclaw.json').read_bytes())
                self.assertEqual(original_persona, (workspace / 'SOUL.md').read_bytes())
                self.assertNotIn(secret, json.dumps(result))
                self.assertFalse(result['activation'])

    def test_explicit_skill_selection_and_fresh_output_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, _ = self.fixture(root)
            output = root / 'private-export'
            result = pack_export.export(source, output, ['main'])
            self.assertEqual(result['files'], 1)
            with self.assertRaises(ValueError):
                pack_export.export(source, output, ['main'])
            for agents, skills in (([], []), (['missing'], []), (['main'], ['main:missing']),
                                   (['main'], ['other:example'])):
                with self.assertRaises(ValueError):
                    pack_export.export(source, root / 'not-created', agents, skills)
                self.assertFalse((root / 'not-created').exists())

    def test_windows_workspace_mapping_on_linux_style_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, workspace, _ = self.fixture(root)
            config = json.loads((source / 'openclaw.json').read_text())
            config['agents']['list'][0]['workspace'] = r'C:\Users\fixture\.openclaw\workspace'
            (source / 'openclaw.json').write_text(json.dumps(config))
            with patch.object(pack_export, 'WINDOWS_HOST', False):
                with self.assertRaisesRegex(ValueError, 'mapping'):
                    pack_export.export(source, root / 'rejected', ['main'])
            result = pack_export.export(source, root / 'mapped', ['main'],
                                        workspace_overrides={'main': str(workspace)})
            self.assertEqual(result['files'], 1)

    def test_no_source_subdirectory_or_linked_persona(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, workspace, _ = self.fixture(root)
            with self.assertRaises(ValueError):
                pack_export.export(source, workspace / 'export', ['main'])
            (workspace / 'SOUL.md').unlink()
            target = root / 'outside.md'
            target.write_text('outside private text')
            try:
                (workspace / 'SOUL.md').symlink_to(target)
            except OSError:
                self.skipTest('Windows symlink privilege unavailable')
            with self.assertRaises(ValueError):
                pack_export.export(source, root / 'output', ['main'])
            self.assertFalse((root / 'output').exists())

    def test_checkout_cli_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, _ = self.fixture(root)
            result = subprocess.run([sys.executable, str(ROOT / 'runtime/argos.py'),
                                     'pack', 'export', '--source', str(source),
                                     '--output', str(root / 'output'), '--agent', 'main'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['activation'])
