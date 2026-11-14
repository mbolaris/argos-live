from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.shakedown import loadout


class LoadoutTests(unittest.TestCase):
    def saved_run(self):
        return {
            'id': 'run-secret', 'session_id': 'session-secret',
            'model': 'qwen3.8:27b', 'manifest_digest': 'sha256:' + 'a' * 64,
            'recipe': {'context': 8192, 'output_cap': 256, 'temperature': 0,
                       'seed': 42, 'thinking': False, 'request_format': 'json'},
            'metadata': {'details': {'parameter_size': '27B', 'quantization_level': 'Q4_K_M'}},
            'hardware': {'cpu': {'model': 'Fixture CPU', 'cores': 8, 'threads': 16},
                         'ram': {'total_bytes': 32 * 1024**3, 'available_bytes': 12},
                         'gpus': [{'name': 'Fixture GPU', 'vendor': 'NVIDIA',
                                   'vram_total_bytes': 16 * 1024**3}],
                         'kernel': '6.1.0', 'secure_boot': True,
                         'disks': [{'path': '/private/disk'}]},
            'openclaw_version': '2026.11.1', 'ollama_version': '0.35.1',
            'argos_version': '0.1.0', 'instruction_cards': ['quote-evidence', 'honesty'],
            'instructions_changed': True, 'tool_profile': 'default',
            'instruction_text': 'private instructions',
        }

    def test_same_build_has_stable_id_and_private_values_are_not_public(self):
        run = self.saved_run()
        first, second = loadout.snapshot(run), loadout.snapshot(run)
        self.assertEqual(first, second)
        public = json.dumps(first)
        for private in ('sha256:', 'instruction_text', 'private instructions', 'session-secret',
                        '/private/disk', 'run-secret'):
            self.assertNotIn(private, public)
        self.assertEqual(first['quantization'], 'Q4_K_M')
        self.assertEqual(first['parameter_size'], '27B')
        self.assertEqual(first['hardware']['memory_bytes'], 32 * 1024**3)

    def test_tunable_changes_change_identity_and_diff_sentence(self):
        before = loadout.snapshot(self.saved_run())
        changed = self.saved_run()
        changed['recipe']['context'] = 16384
        after = loadout.snapshot(changed)
        self.assertNotEqual(before['id'], after['id'])
        self.assertIn('Context 8 KiB to 16 KiB.',
                      [item['sentence'] for item in loadout.diff(before, after)])

    def test_old_saved_run_marks_unknown_fields_and_never_guesses(self):
        result = loadout.snapshot({'model': 'legacy-model', 'items': []})
        self.assertEqual(result['recipe']['context'], loadout.UNKNOWN)
        self.assertEqual(result['quantization'], loadout.UNKNOWN)
        self.assertEqual(result['hardware']['cpu_model'], loadout.UNKNOWN)
        self.assertEqual(result['tool_profile'], loadout.UNKNOWN)

    def test_owner_name_is_saved_under_private_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            loadout_id = loadout.snapshot(self.saved_run())['id']
            self.assertEqual(loadout.name(loadout_id, '  Q5   16k  ', home=directory), 'Q5 16k')
            path = Path(directory) / '.local/state/argos-live/shakedown-loadout-names.json'
            self.assertEqual(json.loads(path.read_text())[loadout_id], 'Q5 16k')
            if sys.platform != 'win32':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
