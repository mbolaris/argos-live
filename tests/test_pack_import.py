import hashlib
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
from argoslive import pack_import


class ImportTests(unittest.TestCase):
    def fixture(self, root):
        archive = root / 'pack.zip'
        payload = {'agents/guide/persona/SOUL.md': b'Fictional helpful guide.\n',
                   'agents/guide/skills/example/SKILL.md': b'Review this fictional skill.\n'}
        manifest = {'schema': 'argos-pack/1', 'id': 'sample', 'version': '1',
                    'created': '2026-10-03T00:00:00Z',
                    'agents': [{'id': 'guide', 'name': 'Guide',
                                'persona_files': ['agents/guide/persona/SOUL.md'],
                                'skill_files': ['agents/guide/skills/example/SKILL.md'],
                                'model_preference': {'name': 'qwen3:0.6b', 'quantization': 'Q4_K_M'}}],
                    'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                              for name, data in payload.items()]}
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(manifest))
            for name, data in payload.items():
                bundle.writestr(name, data)
        staging = root / 'staging'
        staging.mkdir()
        home = root / 'active'
        home.mkdir()
        return archive, staging, home, manifest, payload

    def test_new_agent_stages_reference_without_extracting_or_activating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, staging, home, _, _ = self.fixture(root)
            report = pack_import.stage(archive, staging, home, stage_id='test-stage')
            self.assertFalse(report['activation'])
            self.assertEqual(report['agents'][0]['action'], 'add')
            self.assertEqual(report['agents'][0]['model']['status'], 'unresolved')
            self.assertTrue(report['agents'][0]['skills_needing_review'])
            self.assertEqual(set(p.name for p in (staging / 'test-stage').iterdir()),
                             {'reference.zip', 'manifest.json', 'preview.json'})
            self.assertEqual(list(home.iterdir()), [])
            self.assertEqual(archive.read_bytes(), (staging / 'test-stage/reference.zip').read_bytes())

    def test_updates_report_file_differences_and_keep_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, staging, home, _, payload = self.fixture(root)
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'SOUL.md').write_bytes(payload['agents/guide/persona/SOUL.md'])
            (workspace / 'skills/example').mkdir(parents=True)
            (workspace / 'skills/example/SKILL.md').write_text('Old skill')
            config = home / 'openclaw.json'
            config.write_text(json.dumps({'agents': {'list': [{'id': 'guide', 'name': 'Guide',
                                                              'workspace': str(workspace)}]},
                                         'gateway': {'auth': {'token': 'fixture-not-for-export'}}}))
            originals = {p: p.read_bytes() for p in [config, workspace / 'SOUL.md', workspace / 'skills/example/SKILL.md']}
            report = pack_import.stage(archive, staging, home)
            agent = report['agents'][0]
            self.assertEqual(agent['action'], 'update')
            self.assertEqual([f['status'] for f in agent['files']], ['unchanged', 'changed'])
            for path, data in originals.items():
                self.assertEqual(path.read_bytes(), data)
            self.assertNotIn('fixture-not-for-export', json.dumps(report))

    def test_id_conflicts_and_exact_model_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, staging, home, manifest, _ = self.fixture(root)
            (home / 'openclaw.json').write_text(json.dumps({'agents': {'entries': {
                'GUIDE': {'name': 'Other', 'workspace': str(root / 'missing-workspace')}}}}))
            report = pack_import.stage(archive, staging, home)
            self.assertIn('Existing agent ID differs only by case', report['agents'][0]['conflicts'])
            preference = manifest['agents'][0]['model_preference']
            evidence = {'verified': True, 'manifest_sha256': 'a' * 64, 'quantization': 'Q4_K_M'}
            self.assertEqual(pack_import.model_resolution(preference, installed={'qwen3:0.6b': evidence})['status'], 'installed')
            self.assertEqual(pack_import.model_resolution(preference, catalog={'qwen3:0.6b': evidence})['status'], 'in catalog')
            mismatch = dict(evidence, quantization='Q8_0')
            self.assertEqual(pack_import.model_resolution(preference, catalog={'qwen3:0.6b': mismatch})['status'], 'unresolved')

    def test_wrong_checksum_existing_stage_and_unsafe_staging_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, staging, home, _, _ = self.fixture(root)
            with self.assertRaises(ValueError):
                pack_import.stage(archive, staging, home, '0' * 64)
            self.assertEqual(list(staging.iterdir()), [])
            pack_import.stage(archive, staging, home, stage_id='retained')
            before = (staging / 'retained/preview.json').read_bytes()
            with self.assertRaises(ValueError):
                pack_import.stage(archive, staging, home, stage_id='retained')
            self.assertEqual(before, (staging / 'retained/preview.json').read_bytes())
            with self.assertRaises(ValueError):
                pack_import.stage(archive, home, home)

    def test_checkout_cli_import_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, staging, home, _, _ = self.fixture(root)
            result = subprocess.run([sys.executable, str(ROOT / 'runtime/argos.py'), 'pack', 'import',
                                     str(archive), '--staging-root', str(staging), '--active-home', str(home)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['activation'])

    def test_archive_change_after_inspection_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, staging, home, _, _ = self.fixture(root)
            original = pack_import.packs.inspect
            def inspect_then_change(path, expected):
                report = original(path, expected)
                path.write_bytes(b'changed after verification')
                return report
            with patch.object(pack_import.packs, 'inspect', side_effect=inspect_then_change):
                with self.assertRaisesRegex(ValueError, 'changed after inspection'):
                    pack_import.stage(archive, staging, home)
            self.assertEqual(list(staging.iterdir()), [])
