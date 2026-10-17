import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog, first_model


def gpu(gib):
    return {'gpus': [{'vram_total_bytes': gib * 1024**3}]} if gib else {'gpus': []}


class Fake:
    def __init__(self, phase='completed'):
        self.started, self.kept, self.phase = [], False, phase

    def start(self, *, tag):
        self.started.append(tag)

    def snapshot(self):
        return {'active': False, 'phase': self.phase}

    def keep_current(self):
        self.kept = True


class Ready:
    def snapshot(self):
        return {'phase': 'ready'}


class FirstModelTests(unittest.TestCase):
    def test_choice_is_the_largest_comfortable_tool_model(self):
        models = catalog.load()['models']
        self.assertEqual(first_model.choose(gpu(24), models), 'qwen3:14b')
        self.assertIsNone(first_model.choose(gpu(0), models))
        self.assertIsNone(first_model.choose(gpu(8), models))  # 32k context needs more than 70% of 8 GB
        small = first_model.choose(gpu(16), models)
        self.assertIsNotNone(small)
        self.assertLessEqual(first_model.footprint(next(m for m in models if m['tag'] == small)), 16 * 1024**3 * 0.7)
        self.assertEqual(first_model.choose(gpu(48), models), 'qwen3.8:27b')
        for size in (8, 12, 16, 24, 32, 48):
            picked = first_model.choose(gpu(size), models)
            self.assertTrue(picked is None or ('/' not in picked and 'coder' not in picked and 'vl' not in picked))

    def run_with(self, home, state, *, online=True, download='completed'):
        (home / '.config/argos-live').mkdir(parents=True, exist_ok=True)
        (home / '.config/argos-live/state.json').write_text(json.dumps(state))
        downloads, selection = Fake(download), Fake()
        with patch.object(first_model.storage_view, 'confirmed', return_value=True):
            result = first_model.run(home, Ready(), downloads, selection, threading.Event(),
                                     snapshot=lambda: gpu(24), is_online=lambda: online)
        return result, downloads, selection

    def test_bundled_install_switches_once_and_records_it(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result, downloads, selection = self.run_with(home, {'model_source': 'bundled'})
            self.assertEqual(result, {'outcome': 'switched', 'tag': 'qwen3:14b'})
            self.assertEqual((downloads.started, selection.started, selection.kept), (['qwen3:14b'], ['qwen3:14b'], True))
            again, downloads, _ = self.run_with(home, {'model_source': 'bundled'})
            self.assertEqual((again['outcome'], downloads.started), ('switched', []))

    def test_offline_retries_later_and_managed_installs_are_left_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result, downloads, _ = self.run_with(home, {'model_source': 'bundled'}, online=False)
            self.assertIsNone(result)
            self.assertFalse((home / '.local/state/argos-live/first-model.json').exists())
            result, downloads, _ = self.run_with(home, {'model_source': 'managed'})
            self.assertEqual((result['outcome'], downloads.started), ('skipped', []))

    def test_failed_download_does_not_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            result, _, selection = self.run_with(Path(temp), {'model_source': 'bundled'}, download='failed')
            self.assertEqual((result['outcome'], result['stage'], selection.started), ('failed', 'download', []))


if __name__ == '__main__':
    unittest.main()
