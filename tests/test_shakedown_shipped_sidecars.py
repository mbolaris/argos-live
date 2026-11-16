import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from argoslive import ability, results
from argoslive.shakedown import diagnose, fault, taxonomy

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'shakedown' / 'runs'
SUITES = (('challenge', '1.3.1'), ('tool-schema', '1.2.0'),
          ('tool-plan', '1.1.0'), ('tool-sequence', '1.0.0'))


class ShippedSidecarTest(unittest.TestCase):
    def test_all_sidecars_cover_exact_unchanged_suites(self):
        for name, version in SUITES:
            path = ability.DATA / f'{name}.json'
            before = hashlib.sha256(path.read_bytes()).digest()
            form = ability.load(name, version)
            sidecar = fault.load(name, version)
            self.assertIs(fault.validate(sidecar, form), sidecar)
            self.assertEqual([card['item'] for card in sidecar['cards']],
                             [item['id'] for item in form['items']])
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_fixture_run_unclassified_miss_rates_are_at_most_40_percent(self):
        for name, version in SUITES:
            form = ability.load(name, version)
            sidecar = fault.load(name, version, suite=form)
            form_items = {item['id']: item for item in form['items']}
            cards = {card['item']: card for card in sidecar['cards']}
            run = json.loads((FIXTURES / f'{name}-{version}.json').read_text(encoding='utf-8'))
            results.validate(run)
            by_partition = {partition: [] for partition in fault.PARTITIONS}
            for saved in run['items']:
                item_id = saved['item_id']
                item, card = form_items[item_id], cards[item_id]
                if diagnose.diagnose(card, item, saved):
                    by_partition[card['partition']].append(
                        diagnose.diagnose(card, item, saved))
            for misses in by_partition.values():
                if misses:
                    rate = sum(taxonomy.UNCLASSIFIED in codes for codes in misses) / len(misses)
                    self.assertLessEqual(rate, 0.40, f'{name} exceeded the fixture threshold')

    def test_report_prints_separate_aggregate_partitions_only(self):
        for name, version in SUITES:
            fixture = FIXTURES / f'{name}-{version}.json'
            run = json.loads(fixture.read_text(encoding='utf-8'))
            with tempfile.TemporaryDirectory() as temp:
                Path(temp, f"{run['id']}.json").write_bytes(fixture.read_bytes())
                completed = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts' / 'shakedown-unclassified.py'),
                     run['id'], '--results-dir', temp],
                    cwd=ROOT, capture_output=True, text=True, check=True)
            output = completed.stdout
            self.assertIn('practice', output)
            if any(card['partition'] == 'sealed' for card in fault.load(name, version)['cards']):
                self.assertIn('sealed', output)
            self.assertNotIn('prompt', output)
            self.assertNotIn('expected', output)
            self.assertNotIn('wrong_tool', output)
            self.assertNotIn('not_a_provided_tool', output)


if __name__ == '__main__':
    unittest.main()
