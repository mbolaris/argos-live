from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.bench_ability import summaries
from argoslive.results import Store
from argoslive.shakedown.scorecard import View, wilson


def ability_run(run_id, model, scores, *, suite_version='ability/quick/1.0.0', slice_name='full',
                partition=None, day=1):
    items = []
    for index, score in enumerate(scores):
        item = {'item_id': f'item-{index}', 'score': score,
                'outcome': 'pass' if score else 'wrong_answer', 'category': 'choice',
                'latency_seconds': 2.0}
        if partition:
            item['partition'] = partition
        items.append(item)
    stamp = (datetime(2026, 11, day, tzinfo=timezone.utc) + timedelta(seconds=1)).isoformat()
    return {'schema': 'argos-bench/1', 'id': run_id, 'created': stamp, 'kind': 'ability',
            'suite': 'openclaw-quick', 'suite_version': suite_version, 'model': model,
            'manifest_digest': 'sha256:' + (('a' if model == 'q4' else 'b') * 64),
            'settings': {}, 'hardware': {}, 'state': 'completed', 'items': items,
            'coverage': {'completed': len(items), 'total': len(items), 'complete': True},
            'summary': summaries(items), 'restoration': {'succeeded': True},
            'omitted_categories': [], 'slice_name': slice_name, 'slice_version': 'argos-shakedown-slice/1'}


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.view = View(self.store, home=self.home)

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_scorecard_has_no_phantom_loadouts_or_rows(self):
        value = self.view.scorecard()
        self.assertTrue(value['empty'])
        self.assertEqual(value['loadouts'], [])
        self.assertEqual(value['rows'], [])

    def test_paired_distinguishable_result_is_highlighted_and_counted(self):
        self.store.save(ability_run('1' * 32, 'q4', [0] * 8))
        self.store.save(ability_run('2' * 32, 'q5', [1] * 8, day=2))
        value = self.view.scorecard()
        row = next(row for row in value['rows'] if row['kind'] == 'ability')
        cells = list(row['cells'].values())
        self.assertEqual(len(cells), 2)
        self.assertTrue(next(cell for cell in cells if cell['correct'] == 8)['best'])
        self.assertTrue(all(cell['total'] == 8 for cell in cells))
        self.assertEqual(len(cells[0]['interval']), 2)
        self.assertEqual(value['current_loadout_id'], next(x['id'] for x in value['loadouts'] if x['current']))

    def test_different_versions_are_shown_but_never_highlighted(self):
        self.store.save(ability_run('1' * 32, 'q4', [0] * 8))
        self.store.save(ability_run('2' * 32, 'q5', [1] * 8,
                                    suite_version='ability/quick/2.0.0', day=2))
        row = next(row for row in self.view.scorecard()['rows'] if row['kind'] == 'ability')
        self.assertTrue(all(cell.get('incomparable') for cell in row['cells'].values()))
        self.assertFalse(any(cell['best'] for cell in row['cells'].values()))

    def test_wilson_interval_contains_observed_rate(self):
        lower, upper = wilson(7, 10)
        self.assertLessEqual(lower, .7)
        self.assertGreaterEqual(upper, .7)
        with self.assertRaises(ValueError):
            wilson(11, 10)


if __name__ == '__main__':
    unittest.main()
