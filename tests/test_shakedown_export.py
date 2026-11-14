from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive.bench_ability import summaries
from argoslive.results import Store
from argoslive.shakedown import loadout
from argoslive.shakedown.export import Exporter
from argoslive.shakedown.personal_best import best_run_ids, record_complete_lap
from argoslive.shakedown.scorecard import View
from test_shakedown_scorecard import ability_run


def speed_run(run_id, lap_id):
    return {'schema': 'argos-bench/1', 'id': run_id,
            'created': datetime.now(timezone.utc).isoformat(), 'kind': 'speed',
            'suite': 'speed', 'suite_version': 'speed/1', 'model': 'ollama:fixture',
            'manifest_digest': None, 'settings': {}, 'hardware': {},
            'state': 'completed', 'prompts': [
                {'size': name, 'skipped': True, 'runs': []}
                for name in ('short', 'medium', 'long')],
            'coverage': {'completed': 0, 'total': 0, 'complete': True},
            'restoration': {'succeeded': True, 'mutated': False}, 'lap_id': lap_id}


class ShakedownExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.view = View(self.store, home=self.home)

    def add_lap(self, first_id, model, scores, *, lap_id='a' * 32, day=1,
                suite_version='argos-openclaw-ability/quick/1.0.0', slice_name='quick'):
        speed_id = first_id
        ability_id = chr(ord(first_id[0]) + 1) * 32
        self.store.save(speed_run(speed_id, lap_id))
        run = ability_run(ability_id, model, scores, suite_version=suite_version,
                          slice_name=slice_name, day=day)
        run['lap_id'] = lap_id
        run['slice_version'] = 'argos-shakedown-slice/1'
        run['suite_total'] = len(scores)
        run['hardware'] = {'cpu': {'model': 'Fixture CPU', 'cores': 8, 'threads': 16},
                           'ram': {'total_bytes': 16 * 1024**3},
                           'gpus': [{'name': 'Fixture GPU', 'vendor': 'Test',
                                     'vram_total_bytes': 8 * 1024**3}],
                           'disks': [{'path': 'C:\\private\\session-secret'}]}
        run['calibration_status'] = 'uncalibrated'
        run['benchmark_pack'] = {'id': 'public-fixture'}
        self.store.save(run)
        return speed_id, ability_id, run

    def test_personal_best_requires_a_complete_lap_and_matches_form_slice_hardware(self):
        first = self.add_lap('1' * 32, 'ollama:q4', [1, 1, 0, 0], day=1)
        second = self.add_lap('3' * 32, 'ollama:q5', [1, 1, 1, 0], day=2,
                              lap_id='b' * 32)
        first_ids = [first[0], first[1]]
        second_ids = [second[0], second[1]]
        record_complete_lap(self.home, self.store, first_ids)
        record_complete_lap(self.home, self.store, second_ids)
        bests = best_run_ids(self.home)
        self.assertNotIn(first[1], bests)
        self.assertIn(second[1], bests)
        card = self.view.scorecard()
        cells = [cell for row in card['rows'] for cell in row['cells'].values()]
        self.assertTrue(any(cell.get('personal_best') for cell in cells))
        with self.assertRaisesRegex(ValueError, 'Incomplete lap'):
            incomplete = second[2].copy()
            incomplete['state'] = 'cancelled'
            incomplete['coverage'] = {'completed': 4, 'total': 6, 'complete': False}
            self.store.save({**incomplete, 'id': 'e' * 32, 'lap_id': 'c' * 32})
            extra_speed = 'f' * 32
            self.store.save(speed_run(extra_speed, 'c' * 32))
            record_complete_lap(self.home, self.store, [extra_speed, 'e' * 32])

    def test_form_versions_and_slices_have_separate_personal_bests(self):
        first = self.add_lap('1' * 32, 'ollama:q4', [1, 0, 0, 0], day=1)
        second = self.add_lap('3' * 32, 'ollama:q5', [1, 1, 1, 1], day=2,
                              lap_id='b' * 32, suite_version='argos-openclaw-ability/quick/2.0.0',
                              slice_name='standard')
        record_complete_lap(self.home, self.store, [first[0], first[1]])
        record_complete_lap(self.home, self.store, [second[0], second[1]])
        self.assertEqual(len(json.loads((self.home / '.local/state/argos-live/shakedown-personal-bests.json').read_text())['entries']), 2)

    def test_json_and_svg_exports_omit_private_fields_and_include_scorecard_footnotes(self):
        _speed_id, _ability_id, run = self.add_lap('1' * 32, 'ollama:q4', [1, 0, 1, 0])
        record_complete_lap(self.home, self.store, ['1' * 32, run['id']])
        ident = loadout.snapshot(run)['id']
        loadout.name(ident, r'C:\private\session-secret token', home=self.home)
        exporter = Exporter(self.store, self.view, home=self.home)
        created = exporter.create()
        json_raw = exporter.file(created['export_id'], 'json').read_bytes()
        svg_raw = exporter.file(created['export_id'], 'svg').read_bytes()
        exported = json.loads(json_raw)
        for forbidden in ('session-secret', 'C:\\private', 'instruction_text', 'sha256',
                          'fingerprint', 'session_id', 'run_id'):
            self.assertNotIn(forbidden.lower(), json_raw.decode('utf-8').lower())
            self.assertNotIn(forbidden.lower(), svg_raw.decode('utf-8').lower())
        self.assertIn('uncalibrated', svg_raw.decode('utf-8'))
        self.assertIn('public', svg_raw.decode('utf-8'))
        self.assertEqual(exported['hardware_line'], 'Fixture CPU · Fixture GPU · 16 GiB RAM')
        self.assertTrue(any(cell['personal_best'] for row in exported['rows'] for cell in row['cells']))
        self.assertTrue(set(created['files']) >= {'json', 'svg'})


if __name__ == '__main__':
    unittest.main()
