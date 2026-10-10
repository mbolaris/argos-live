#!/usr/bin/env python3
"""Audit every saved document-trial miss: separate answer acceptance from quote validity.

Read-only. Prints a Markdown table of distinct misses with their diagnostic label. Diagnostics
explain saved verdicts; they never change scores, accepted answers, suites or thresholds.

    python3 scripts/audit-document-misses.py ~/.local/share/argos-live/results
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import doc_trial, replay  # noqa: E402
from argoslive.results import Store  # noqa: E402


def misses(store):
    data = doc_trial.load()
    suite = {item['id']: item for item in data['items']}
    seen, runs = {}, 0
    for path in sorted(store.root.glob('*.json')):
        try:
            run = store.load(path.stem)
        except (ValueError, OSError):
            continue
        if (run.get('suite') != 'documents-short' or not (run.get('coverage') or {}).get('complete')
                or run.get('suite_version') != 'documents/short/' + data['version']):
            continue
        runs += 1
        preset = (run.get('recipe') or {}).get('preset', 'standard') if isinstance(run.get('recipe'), dict) else 'standard'
        for item in run['items']:
            if item['outcome'] == 'pass':
                continue
            key = (item['item_id'], item.get('output'))
            entry = seen.setdefault(key, {'item': item, 'runs': 0, 'models': set(), 'presets': set()})
            entry['runs'] += 1
            entry['models'].add(run['model'])
            entry['presets'].add(preset)
    rows = []
    for (item_id, output), entry in sorted(seen.items(), key=lambda kv: kv[0][0]):
        rule = suite[item_id]['scorer']
        value = replay.diagnose(entry['item'], rule, rule.get('passage'))
        rows.append({'item_id': item_id, 'question': suite[item_id]['question'], 'accepted': rule.get('accepted') or [],
                     'output': output or '', 'runs': entry['runs'], 'models': sorted(entry['models']),
                     'presets': sorted(entry['presets']), **value})
    return runs, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('results', type=Path)
    args = parser.parse_args(argv)
    runs, rows = misses(Store(args.results))
    print(f'{runs} complete document runs; {len(rows)} distinct misses.\n')
    print('| Item | Runs | Model | Answer | Answer accepted | Quote exact | Quote supports | Diagnostic |')
    print('|---|---|---|---|---|---|---|---|')
    for row in rows:
        checks = row.get('checks') or {}
        try:
            answer = doc_trial.parse(row['output'])['answer']
        except (ValueError, TypeError):
            answer = '(unparsed)'
        flag = lambda key: {True: 'yes', False: 'no', None: '—'}[checks.get(key)]
        label = (row.get('diagnosis') or {}).get('label', '')
        print(f"| {row['item_id']} | {row['runs']} | {', '.join(row['models'])} | {answer[:60]} | "
              f"{flag('answer_accepted')} | {flag('quote_exact')} | {flag('quote_supports')} | {label} |")
    return 0


if __name__ == '__main__':
    sys.exit(main())
