#!/usr/bin/env python3
"""Print aggregate unclassified-miss rates for one saved shakedown ability run."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))

from argoslive import ability, results
from argoslive.shakedown import diagnose, fault, taxonomy

SUPPORTED = {'challenge', 'tool-schema', 'tool-plan', 'tool-sequence'}
SUITE_VERSION = re.compile(r'argos-openclaw-ability/([a-z][a-z0-9-]*)/(\d+\.\d+\.\d+)')


def report(run):
    """Return counts and rates only; never project prompts, answers, or matcher data."""
    if run.get('kind') != 'ability':
        raise ValueError('The selected run is not an ability evaluation')
    match = SUITE_VERSION.fullmatch(run.get('suite_version', ''))
    if match is None or match.group(1) not in SUPPORTED:
        raise ValueError('The selected run is not one of the four sidecar suites')
    form_name, version = match.groups()
    form = ability.load(form_name, version)
    sidecar = fault.load(form_name, version, suite=form)
    forms = {item['id']: item for item in form['items']}
    cards = {item['item']: item for item in sidecar['cards']}
    counts = {partition: {'misses': 0, 'unclassified': 0}
              for partition in fault.PARTITIONS}
    for saved in run.get('items', []):
        item_id = saved.get('item_id')
        item, card = forms.get(item_id), cards.get(item_id)
        if item is None or card is None:
            raise ValueError('The saved run contains an item outside its exact suite version')
        codes = diagnose.diagnose(card, item, saved)
        if codes:
            bucket = counts[card['partition']]
            bucket['misses'] += 1
            bucket['unclassified'] += int(taxonomy.UNCLASSIFIED in codes)
    for bucket in counts.values():
        bucket['rate'] = (bucket['unclassified'] / bucket['misses']
                          if bucket['misses'] else None)
    return {'suite': form_name, 'version': version, 'partitions': counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id', help='32-character saved benchmark result ID')
    parser.add_argument('--results-dir', type=Path, default=results.DEFAULT,
                        help='saved results directory (default: Argos results directory)')
    args = parser.parse_args(argv)
    try:
        result = report(results.Store(args.results_dir).load(args.run_id))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Unclassified misses - {result['suite']} {result['version']}")
    print('partition  misses  unclassified  rate')
    for partition in fault.PARTITIONS:
        bucket = result['partitions'][partition]
        rate = 'n/a' if bucket['rate'] is None else f"{bucket['rate']:.1%}"
        print(f"{partition:<9}  {bucket['misses']:>6}  {bucket['unclassified']:>12}  {rate}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
