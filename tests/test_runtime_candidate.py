import base64
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_candidate', ROOT / 'scripts/prepare-runtime-candidate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CandidateTests(unittest.TestCase):
    def test_repository_runtime_lock_backend_and_addon_pins_are_synchronized(self):
        accepted = module.pins((ROOT / 'versions.env').read_text())
        lock = json.loads((ROOT / 'live/config/includes.chroot/usr/local/share/argos-live/package-lock.json').read_text())
        addon = json.loads((ROOT / 'runtime/argoslive/data/addons.json').read_text())
        self.assertEqual(lock['packages']['']['dependencies']['openclaw'], accepted['OPENCLAW_VERSION'])
        package = lock['packages']['node_modules/openclaw']
        self.assertEqual(package['version'], accepted['OPENCLAW_VERSION'])
        self.assertEqual(package['integrity'], accepted['OPENCLAW_INTEGRITY'])
        self.assertEqual(addon['host_version'], accepted['OPENCLAW_VERSION'])
        self.assertEqual(addon['host_integrity'], accepted['OPENCLAW_INTEGRITY'])
        backend = (ROOT / 'runtime/argoslive/owned_ollama.py').read_text()
        self.assertIn('PIN = ' + repr(accepted['OLLAMA_VERSION']) + '\n', backend)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        (self.repo / 'runtime/argoslive').mkdir(parents=True)
        self.pins = module.pins((ROOT / 'versions.env').read_text())
        (self.repo / 'versions.env').write_text(''.join(k + '=' + v + '\n' for k, v in self.pins.items()))
        (self.repo / 'runtime/argoslive/owned_ollama.py').write_text('PIN = ' + repr(self.pins['OLLAMA_VERSION']) + '\n')
        def next_patch(value):
            major, minor, patch = module.version(value)
            return f'{major}.{minor}.{patch + 1}'
        self.claw = next_patch(self.pins['OPENCLAW_VERSION'])
        self.ollama = next_patch(self.pins['OLLAMA_VERSION'])
        candidate = dict(self.pins, OPENCLAW_VERSION=self.claw, OLLAMA_VERSION=self.ollama,
                         OPENCLAW_INTEGRITY='sha512-' + base64.b64encode(b'a' * 64).decode(),
                         OLLAMA_SHA256='b' * 64)
        self.now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        self.report = {'status': 'discovery-only', 'checkedAt': self.now.isoformat(),
            'current': self.pins, 'candidate': candidate, 'sources': {
                'openclaw': 'https://github.com/openclaw/openclaw/releases/tag/v' + self.claw,
                'ollama': 'https://github.com/ollama/ollama/releases/tag/v' + self.ollama,
                'node': 'https://nodejs.org/dist/index.json'}}
        self.output = self.root / 'candidate'

    def prepare(self, report=None):
        return module.prepare(report or self.report, self.repo, self.output, now=self.now)

    def test_public_candidate_does_not_change_accepted_files_or_reuse_output(self):
        before = {str(path): path.read_bytes() for path in self.repo.rglob('*') if path.is_file()}
        self.assertEqual(self.prepare(), ['OPENCLAW_VERSION', 'OLLAMA_VERSION'])
        self.assertIn('PIN = ' + repr(self.ollama), (self.output / 'owned_ollama.py').read_text())
        metadata = json.loads((self.output / 'candidate.json').read_text())
        self.assertFalse(metadata['accepted_pins_changed'])
        self.assertEqual(module.pins((self.output / 'versions.env').read_text()), self.report['candidate'])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.repo.rglob('*') if path.is_file()})
        (self.output / 'keep').write_bytes(b'reviewed prior candidate')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual((self.output / 'keep').read_bytes(), b'reviewed prior candidate')

    def test_stale_mismatched_current_and_unexpected_sources_fail_before_output(self):
        for change in ('old', 'future', 'current', 'source', 'pin-set'):
            report = copy.deepcopy(self.report)
            if change in ('old', 'future'):
                report['checkedAt'] = (self.now + timedelta(days=-2 if change == 'old' else 1)).isoformat()
            elif change == 'current':
                report['current']['NODE_VERSION'] = '26.9.0'
            elif change == 'source':
                report['sources']['openclaw'] = 'https://untrusted.invalid/release'
            else:
                report['candidate']['EXTRA'] = 'unexpected'
            with self.assertRaises(ValueError, msg=change):
                self.prepare(report)
            self.assertFalse(self.output.exists())

    def test_downgrades_prerelease_shell_content_bad_hashes_and_base_changes_refused(self):
        for key, value in [('OPENCLAW_VERSION', self.claw + '-beta.1'), ('OLLAMA_VERSION', '0.0.0'),
                           ('NODE_VERSION', '28.0.0'), ('OLLAMA_VERSION', '0.35.1;command'),
                           ('OLLAMA_SHA256', 'missing'), ('OPENCLAW_INTEGRITY', 'sha512-a===bad'),
                           ('OPENCLAW_INTEGRITY', 'sha512-' + base64.b64encode(b'short').decode()),
                           ('DEBIAN_SNAPSHOT', '20261004T000000Z'), ('NODE_SHA256', 'a' * 64)]:
            report = copy.deepcopy(self.report)
            report['candidate'][key] = value
            with self.assertRaises(ValueError, msg=key):
                self.prepare(report)
            self.assertFalse(self.output.exists())

    def test_duplicate_or_shell_pin_assignment_and_backend_drift_refused(self):
        for text in ('NODE_VERSION=26.10.0\nNODE_VERSION=26.10.1\n', 'NODE_VERSION=$(command)\n'):
            with self.assertRaises(ValueError):
                module.pins(text)
        (self.repo / 'runtime/argoslive/owned_ollama.py').write_text("PIN = 'wrong'\n")
        with self.assertRaisesRegex(ValueError, 'backend pin'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_already_current_is_success_but_republished_artifact_drift_is_not(self):
        report = copy.deepcopy(self.report)
        report['candidate'] = dict(self.pins)
        for name, key in [('openclaw', 'OPENCLAW_VERSION'), ('ollama', 'OLLAMA_VERSION')]:
            report['sources'][name] = report['sources'][name].rsplit('/v', 1)[0] + '/v' + self.pins[key]
        self.assertEqual(self.prepare(report), [])
        self.assertEqual(json.loads((self.output / 'candidate.json').read_text())['status'], 'up-to-date')
        self.output = self.root / 'drift'
        report['candidate']['OLLAMA_SHA256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'different artifact identity'):
            self.prepare(report)
        self.assertFalse(self.output.exists())
