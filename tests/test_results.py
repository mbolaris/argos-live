import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_ability, bench_speed, results
from test_bench_ability import AbilityBackend
from test_bench_speed import Backend


def ability_result(answer='reference'):
    return bench_ability.run(AbilityBackend(answer), 'fixture:latest', hardware=lambda: {})


class ResultsTests(unittest.TestCase):
    def test_round_trip_list_delete_and_duplicate_protection(self):
        value = ability_result()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'results'
            store = results.Store(root)
            self.assertEqual(store.list(), {'runs': [], 'rejected': []})
            path = store.save(value)
            self.assertEqual(store.load(value['id']), value)
            self.assertEqual(store.list()['runs'][0]['id'], value['id'])
            if os.name != 'nt':
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                store.save(value)
            store.delete(value['id'])
            self.assertFalse(path.exists())
            with self.assertRaisesRegex(ValueError, 'not found'):
                store.load(value['id'])

    def test_schema_bounds_id_and_corrupt_files(self):
        value = ability_result()
        for update in ({'schema': 'argos-bench/2'}, {'id': '../escape'}, {'created': 'yesterday'},
                       {'created': '2026-10-04T00:00:00'}, {'hardware': {'x': float('nan')}}):
            changed = dict(value, **update)
            with self.assertRaises(ValueError):
                results.validate(changed)
        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(temp)
            path = store.save(value)
            for raw in (b'{', b'\xff', b'x' * (results.LIMIT + 1), b'{"id":1,"id":2}'):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    store.load(value['id'])
                self.assertEqual(store.list()['rejected'], [path.name])
            changed = dict(value, id='a' * 32)
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'embedded ID'):
                store.load(value['id'])
            store.delete(value['id'])

    def test_comparison_rank_accuracy_and_csv(self):
        good, wrong = ability_result(), ability_result('wrong')
        good['model'] = '=SUM(1,2)'
        compared = results.compare([wrong, good])
        self.assertEqual([row['value'] for row in compared['rows']], [1, 0])
        self.assertEqual(compared['suite_version'], 'ability/quick/1.0.0')
        rows = list(csv.DictReader(io.StringIO(results.export_csv(compared))))
        self.assertEqual(rows[0]['model'], "'=SUM(1,2)")
        self.assertEqual(rows[0]['value'], '1.0')
        self.assertIn('Hardware', compared['limitations'])

    def test_mixed_kind_version_settings_and_duplicate_refused(self):
        first, second = ability_result(), ability_result()
        speed = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {})
        for values in ([first, speed], [first, dict(second, suite_version='ability/quick/2.0.0')],
                       [first, dict(second, settings={'temperature': 1})], [first, first], [first]):
            with self.assertRaises(ValueError):
                results.compare(values)

    def test_partial_cleanup_and_tampered_summary_refused(self):
        first, second = ability_result(), ability_result()
        for update in ({'summary': dict(second['summary'], accuracy=100)},
                       {'restoration': {'succeeded': False}},
                       {'state': 'cancelled', 'coverage': {'completed': 20, 'total': 20, 'complete': False}},
                       {'coverage': {'completed': 19, 'total': 20, 'complete': True}}):
            with self.assertRaises(ValueError):
                results.compare([first, dict(second, **update)])
        changed = copy.deepcopy(second)
        changed['items'][0]['category'] = 'another-category'
        changed['summary'] = bench_ability.summaries(changed['items'])
        with self.assertRaisesRegex(ValueError, 'coverage differs'):
            results.compare([first, changed])

    def test_speed_medians_unknown_and_coverage(self):
        first = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {})
        second = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {})
        second['prompts'][0]['runs'][0]['generation_tokens_per_second'] = None
        second['prompts'][0]['summary']['generation_tokens_per_second']['median'] = 999
        compared = results.compare([first, second])
        short = [r for r in compared['rows'] if r['metric'].startswith('short')]
        self.assertEqual([r['value'] for r in short], [20, None])
        changed = copy.deepcopy(second)
        changed['prompts'][0]['context_tokens'] = 999
        with self.assertRaisesRegex(ValueError, 'coverage differs'):
            results.compare([first, changed])

    def test_cli_list_compare_export_inspect_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(temp)
            first, second = ability_result(), ability_result('wrong')
            store.save(first)
            store.save(second)
            def invoke(*args):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(results.main(['--results-dir', temp, *args]), 0)
                return output.getvalue()
            self.assertIn(first['id'], invoke())
            self.assertEqual(len(json.loads(invoke('--json'))['runs']), 2)
            self.assertEqual(json.loads(invoke('--load', first['id']))['summary']['accuracy'], 1)
            self.assertIn('Metric', invoke('--compare', first['id'], second['id']))
            self.assertEqual(len(list(csv.DictReader(io.StringIO(invoke(
                '--compare', first['id'], second['id'], '--csv'))))), 2)
            self.assertIn(first['id'], invoke('--delete', first['id']))
            self.assertEqual(len(store.list()['runs']), 1)

    @unittest.skipIf(os.name == 'nt', 'Unprivileged symlink fixture uses Linux')
    def test_symlink_outside_store_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = results.Store(root)
            outside = root / 'outside'
            outside.write_text('private fixture')
            linked = root / ('a' * 32 + '.json')
            linked.symlink_to(outside)
            for operation in (store.load, store.delete):
                with self.assertRaises(ValueError):
                    operation('a' * 32)
            self.assertEqual(outside.read_text(), 'private fixture')


if __name__ == '__main__':
    unittest.main()
