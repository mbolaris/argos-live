import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import pack_apply, pack_import
import test_pack_import


class FixtureRuntime:
    def __init__(self, home, fail_active=False, fail_candidate=False):
        self.home, self.fail_active, self.fail_candidate = home, fail_active, fail_candidate
        self.active_checks = 0

    def validate(self, path):
        json.loads(path.read_text())
        if path == self.home / 'openclaw.json':
            self.active_checks += 1
            if self.fail_active and self.active_checks == 2:
                raise ValueError('Injected post-write validation failure')
        elif self.fail_candidate:
            raise ValueError('Injected candidate rejection')

    def backup(self, path):
        path.write_bytes(b'Fictional verified native backup')


class ApplyTests(unittest.TestCase):
    def fixture(self, root):
        archive, staging, home, manifest, payload = test_pack_import.ImportTests().fixture(root)
        workspace = root / 'workspace'
        workspace.mkdir()
        (workspace / 'SOUL.md').write_bytes(b'Original fictional identity\n')
        (workspace / 'MEMORY.md').write_bytes(b'Untouched fictional memory\n')
        config = {'agents': {'entries': {'guide': {'identity': {'name': 'Guide'},
                   'workspace': str(workspace), 'default': True,
                   'model': 'ollama/qwen3:0.6b', 'tools': {'profile': 'full'}}}},
                  'models': {'providers': {'ollama': {'api': 'ollama',
                             'baseUrl': 'http://127.0.0.1:11434', 'apiKey': 'fixture-only',
                             'models': [{'id': 'qwen3:0.6b'}]}}},
                  'gateway': {'mode': 'local'}}
        original = json.dumps(config, indent=1).encode()
        (home / 'openclaw.json').write_bytes(original)
        report = pack_import.stage(archive, staging, home, stage_id='reviewed')
        snapshots = root / 'snapshots'
        snapshots.mkdir()
        inventory = {'qwen3:0.6b': {'verified': True, 'manifest_sha256': 'a' * 64,
                                  'quantization': 'Q4_K_M'}}
        return staging / 'reviewed', home, snapshots, workspace, report['archive_sha256'], inventory, original

    def activate(self, fixture, **kwargs):
        stage, home, snapshots, _, sha, inventory, _ = fixture
        options = dict(installed=inventory, reviewed_skills=True, gateway_stopped=True)
        options.update(kwargs)
        return pack_apply.apply(stage, home, snapshots, sha, FixtureRuntime(home), **options)

    def test_apply_then_rollback_restores_exact_bytes_and_retains_other_state(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(Path(directory))
            stage, home, snapshots, workspace, _, _, original = f
            result = self.activate(f)
            self.assertTrue(result['activation'])
            self.assertFalse(result['model_capability_verified'])
            entry = json.loads((home / 'openclaw.json').read_bytes())['agents']['entries']['guide']
            self.assertEqual(entry['tools'], pack_apply.CHAT)
            self.assertEqual((workspace / 'SOUL.md').read_bytes(), b'Fictional helpful guide.\n')
            self.assertEqual((workspace / 'MEMORY.md').read_bytes(), b'Untouched fictional memory\n')
            self.assertTrue((workspace / 'skills/example/SKILL.md').is_file())
            pack_apply.rollback(snapshots / result['snapshot_id'], home, FixtureRuntime(home), gateway_stopped=True)
            self.assertEqual((home / 'openclaw.json').read_bytes(), original)
            self.assertEqual((workspace / 'SOUL.md').read_bytes(), b'Original fictional identity\n')
            self.assertFalse((workspace / 'skills').exists())

    def test_post_write_failure_automatically_restores_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, home, snapshots, workspace, sha, inventory, original = self.fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'original files restored'):
                pack_apply.apply(stage, home, snapshots, sha, FixtureRuntime(home, fail_active=True),
                                 installed=inventory, reviewed_skills=True, gateway_stopped=True)
            self.assertEqual((home / 'openclaw.json').read_bytes(), original)
            self.assertEqual((workspace / 'SOUL.md').read_bytes(), b'Original fictional identity\n')
            self.assertFalse((workspace / 'skills').exists())
            tx = json.loads(next(snapshots.glob('*/transaction.json')).read_text())
            self.assertEqual(tx['status'], 'automatically-restored')

    def test_missing_model_is_pending_and_never_inherits_a_default(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(Path(directory))
            result = self.activate(f, installed={})
            self.assertFalse(result['activation'])
            self.assertEqual(result['pending'][0]['id'], 'guide')
            self.assertEqual((f[1] / 'openclaw.json').read_bytes(), f[-1])
            self.assertEqual(list(f[2].iterdir()), [])

    def test_wrong_hash_unreviewed_skills_and_running_gateway_ack_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'skill'):
                self.activate(f, reviewed_skills=False)
            with self.assertRaisesRegex(ValueError, 'gateway'):
                self.activate(f, gateway_stopped=False)
            with self.assertRaises(ValueError):
                pack_apply.apply(f[0], f[1], f[2], '0' * 64, FixtureRuntime(f[1]),
                                 reviewed_skills=True, gateway_stopped=True)
            self.assertEqual((f[1] / 'openclaw.json').read_bytes(), f[-1])

    def test_later_edits_and_corrupt_snapshots_block_rollback_without_clobbering(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(Path(directory))
            result = self.activate(f)
            snapshot = f[2] / result['snapshot_id']
            (f[3] / 'SOUL.md').write_bytes(b'Later owner edit\n')
            active = (f[1] / 'openclaw.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'changed since'):
                pack_apply.rollback(snapshot, f[1], FixtureRuntime(f[1]), gateway_stopped=True)
            self.assertEqual((f[1] / 'openclaw.json').read_bytes(), active)
            (f[3] / 'SOUL.md').write_bytes(b'Fictional helpful guide.\n')
            (snapshot / 'before-0').write_bytes(b'Corrupt original')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                pack_apply.rollback(snapshot, f[1], FixtureRuntime(f[1]), gateway_stopped=True)
            self.assertEqual((f[1] / 'openclaw.json').read_bytes(), active)

    def test_candidate_rejection_does_not_write_active_files(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, home, snapshots, workspace, sha, inventory, original = self.fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'candidate'):
                pack_apply.apply(stage, home, snapshots, sha, FixtureRuntime(home, fail_candidate=True),
                                 installed=inventory, reviewed_skills=True, gateway_stopped=True)
            self.assertEqual((home / 'openclaw.json').read_bytes(), original)
            self.assertFalse((workspace / 'skills').exists())

    def test_add_agent_and_rollback_removes_only_created_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(Path(directory))
            config = json.loads(f[-1])
            config['agents']['entries'] = {}
            original = json.dumps(config).encode()
            (f[1] / 'openclaw.json').write_bytes(original)
            pack_import.stage(f[0] / 'reference.zip', f[0].parent, f[1], stage_id='fresh')
            f = (f[0].parent / 'fresh', *f[1:])
            result = self.activate(f)
            self.assertTrue((f[1] / 'workspace-guide/SOUL.md').is_file())
            pack_apply.rollback(f[2] / result['snapshot_id'], f[1], FixtureRuntime(f[1]), gateway_stopped=True)
            self.assertFalse((f[1] / 'workspace-guide').exists())
            self.assertTrue((f[3] / 'SOUL.md').exists())
            self.assertEqual((f[1] / 'openclaw.json').read_bytes(), original)

    def test_target_edit_after_preview_requires_fresh_review(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(Path(directory))
            (f[3] / 'SOUL.md').write_bytes(b'New owner changes after preview')
            with self.assertRaisesRegex(ValueError, 'changed since staging'):
                self.activate(f)
            self.assertEqual((f[3] / 'SOUL.md').read_bytes(), b'New owner changes after preview')
            self.assertEqual(list(f[2].iterdir()), [])

    def test_change_during_backup_is_retained_and_blocks_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, home, snapshots, workspace, sha, inventory, original = self.fixture(Path(directory))
            class RacingRuntime(FixtureRuntime):
                def backup(self, path):
                    super().backup(path)
                    (workspace / 'SOUL.md').write_bytes(b'Owner edit during backup')
            with self.assertRaisesRegex(ValueError, 'changed while taking backup'):
                pack_apply.apply(stage, home, snapshots, sha, RacingRuntime(home),
                                 installed=inventory, reviewed_skills=True, gateway_stopped=True)
            self.assertEqual((home / 'openclaw.json').read_bytes(), original)
            self.assertEqual((workspace / 'SOUL.md').read_bytes(), b'Owner edit during backup')
