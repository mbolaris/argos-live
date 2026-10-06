"""Bounded private benchmark storage and comparisons with explicit coverage."""
import argparse
import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
import re

from .ability import decode
from .pack_export import private_directory
from .pull_jobs import write_json, LIMIT
from .storage import safe_local

DEFAULT = Path.home() / '.local/share/argos-live/results'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Choose a benchmark run ID (32 lowercase hexadecimal characters)')
    return value


def finite_tree(value, depth=0):
    if depth > 64:
        raise ValueError('Result nesting exceeds limit')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite benchmark value')
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child, depth + 1)


def validate(value):
    if not isinstance(value, dict) or value.get('schema') != 'argos-bench/1':
        raise ValueError('Unsupported benchmark schema')
    identifier(value.get('id'))
    finite_tree(value)
    if (value.get('kind') not in ('speed', 'ability')
            or not isinstance(value.get('suite_version'), str) or not value['suite_version']
            or not isinstance(value.get('model'), str) or not 1 <= len(value['model']) <= 256
            or not isinstance(value.get('settings'), dict)
            or not isinstance(value.get('hardware'), dict)
            or not isinstance(value.get('restoration'), dict)
            or type(value['restoration'].get('succeeded')) is not bool):
        raise ValueError('Invalid benchmark metadata')
    try:
        created = datetime.fromisoformat(value['created'])
        if created.tzinfo is None:
            raise ValueError('Missing timestamp zone')
    except (ValueError, TypeError, KeyError):
        raise ValueError('Invalid benchmark timestamp') from None
    if value['kind'] == 'ability':
        if (value.get('state') not in ('completed', 'cancelled')
                or not isinstance(value.get('coverage'), dict)
                or not isinstance(value.get('items'), list)
                or not isinstance(value.get('summary'), dict)):
            raise ValueError('Invalid ability result')
        coverage = value['coverage']
        if (type(coverage.get('total')) is not int or not 1 <= coverage['total'] <= 1000
                or coverage.get('completed') != len(value['items'])
                or type(coverage.get('completed')) is not int
                or not 0 <= coverage['completed'] <= coverage['total']
                or type(coverage.get('complete')) is not bool
                or coverage['complete'] != (value['state'] == 'completed' and coverage['completed'] == coverage['total'])):
            raise ValueError('Invalid ability coverage')
        seen = set()
        for item in value['items']:
            if (not isinstance(item, dict) or not isinstance(item.get('item_id'), str)
                    or item['item_id'] in seen or type(item.get('score')) is not int
                    or item['score'] not in (0, 1) or item.get('outcome') not in ('pass', 'wrong_answer', 'format_error')
                    or item['score'] != int(item['outcome'] == 'pass')
                    or not isinstance(item.get('category'), str)):
                raise ValueError('Invalid ability item result')
            seen.add(item['item_id'])
        # Never trust an imported summary independently of its actual scored items.
        from .bench_ability import summaries
        if value['summary'] != summaries(value['items']):
            raise ValueError('Ability summary differs from item evidence')
    elif not isinstance(value.get('prompts'), list) or not value['prompts']:
        raise ValueError('Invalid speed result')
    else:
        seen = set()
        for prompt in value['prompts']:
            if (not isinstance(prompt, dict) or prompt.get('size') not in ('short', 'medium', 'long')
                    or prompt['size'] in seen or type(prompt.get('skipped')) is not bool
                    or not isinstance(prompt.get('runs'), list)):
                raise ValueError('Invalid speed prompt result')
            seen.add(prompt['size'])
            if not prompt['skipped'] and len(prompt['runs']) != 3:
                raise ValueError('Speed result requires three measured runs')
            if any(not isinstance(run, dict) for run in prompt['runs']):
                raise ValueError('Invalid speed measurement')
    return value


class Store:
    def __init__(self, root=DEFAULT):
        self.root = safe_local(Path(root).absolute())

    def path(self, run_id):
        return safe_local(self.root / (identifier(run_id) + '.json'))

    def save(self, value):
        validate(value)
        path = self.path(value['id'])
        if path.exists():
            raise ValueError('Benchmark run already exists; results are not overwritten')
        if not self.root.exists():
            self.root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_directory(self.root)
        write_json(path, value)
        return path

    def load(self, run_id):
        path = self.path(run_id)
        if not path.is_file():
            raise ValueError('Benchmark run not found')
        with path.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Benchmark result exceeds metadata limit')
        try:
            value = validate(decode(raw))
        except (UnicodeError, RecursionError) as exc:
            raise ValueError('Invalid benchmark JSON') from exc
        if value['id'] != run_id:
            raise ValueError('Benchmark filename and embedded ID differ')
        return value

    def list(self):
        runs, rejected = [], []
        if not self.root.exists():
            return {'runs': [], 'rejected': []}
        files = sorted(self.root.glob('*.json'))
        if len(files) > 10000:
            raise ValueError('Too many benchmark files; choose a smaller results directory')
        for path in files:
            try:
                value = self.load(path.stem)
                runs.append({key: value.get(key) for key in
                             ('id', 'created', 'kind', 'suite_version', 'model', 'manifest_digest', 'state')})
            except (ValueError, OSError):
                rejected.append(path.name)
        runs.sort(key=lambda run: (run['created'], run['id']), reverse=True)
        return {'runs': runs, 'rejected': rejected}

    def delete(self, run_id):
        # A corrupt result may be removed, but only by its exact validated ID.
        path = self.path(run_id)
        if not path.is_file():
            raise ValueError('Benchmark run not found')
        path.unlink()


def compare(values):
    if len(values) < 2:
        raise ValueError('Choose at least two runs for comparison')
    for value in values:
        validate(value)
    if len({v['id'] for v in values}) != len(values):
        raise ValueError('Choose distinct runs')
    first = values[0]
    for value in values:
        if (value['kind'], value['suite_version'], value['settings']) != (
                first['kind'], first['suite_version'], first['settings']):
            raise ValueError('Comparison requires the same benchmark kind, suite version and settings')
        if not value['restoration']['succeeded']:
            raise ValueError('Cannot rank a run with failed cleanup/restoration')
        if value['kind'] == 'ability' and not value['coverage']['complete']:
            raise ValueError('Cannot rank partial or cancelled ability runs')
    if first['kind'] == 'ability' and any(
            [(i['item_id'], i['category']) for i in v['items']] !=
            [(i['item_id'], i['category']) for i in first['items']]
            or v.get('omitted_categories') != first.get('omitted_categories') for v in values):
        raise ValueError('Ability coverage differs between runs')
    if first['kind'] == 'speed' and any(
            [(p['size'], p.get('context_tokens'), p['skipped']) for p in v['prompts']] !=
            [(p['size'], p.get('context_tokens'), p['skipped']) for p in first['prompts']]
            for v in values):
        raise ValueError('Speed prompt coverage differs between runs')
    rows = []
    for value in values:
        common = {'id': value['id'], 'model': value['model'], 'manifest_digest': value.get('manifest_digest'),
                  'created': value['created']}
        if value['kind'] == 'ability':
            rows.append(dict(common, metric='accuracy', value=value['summary']['accuracy'],
                             format_errors=value['summary']['format_errors']))
        else:
            from .bench_speed import numeric, summary
            for prompt in value['prompts']:
                # Recompute medians from measured evidence, rather than trusting summaries.
                rates = [] if prompt['skipped'] else [numeric(run.get('generation_tokens_per_second'))
                                                      for run in prompt['runs']]
                rate = summary(rates)['median'] if len(rates) == 3 and all(r is not None for r in rates) else None
                rows.append(dict(common, metric=prompt['size'] + '_generation_tokens_per_second',
                                 value=rate, format_errors=None))
    rows.sort(key=lambda row: (row['metric'], row['value'] is None,
                              -(row['value'] or 0), row['id']))
    return {'kind': first['kind'], 'suite_version': first['suite_version'], 'settings': first['settings'],
            'rows': rows, **matched_details(values), 'limitations': 'Hardware and runtime versions can differ; inspect original runs. '
            'Missing measurements are unranked. Tool formatting is not tool execution.'}


ITEM_OUTPUT_LIMIT = 600


def median_of(prompt, field):
    """Recompute from raw runs; a median needs all three measured runs."""
    from .bench_speed import numeric, summary
    if prompt['skipped']:
        return {'median': None, 'reported_runs': 0}
    values = [numeric(run.get(field)) for run in prompt['runs']]
    reported = sum(v is not None for v in values)
    return {'median': summary(values)['median'] if reported == 3 else None, 'reported_runs': reported}


def matched_details(values):
    """Per-run measurements and per-item answers for runs already proven comparable.

    Speed, input processing, first-token wait and accuracy stay separate fields.
    Nothing here ranks or combines them.
    """
    ordered = sorted(values, key=lambda v: (v['created'], v['id']))
    runs = []
    for value in ordered:
        entry = {'id': value['id'], 'model': value['model'], 'created': value['created'],
                 'manifest_digest': value.get('manifest_digest'), 'kind': value['kind'],
                 'suite_version': value['suite_version']}
        if value['kind'] == 'ability':
            summary = value['summary']
            entry.update(accuracy=summary['accuracy'], correct=summary['correct'], total=summary['total'],
                         format_errors=summary['format_errors'], categories=summary['categories'],
                         qualification=value.get('qualification'), document_context=value.get('document_context'),
                         context=value['settings'].get('context'))
        else:
            entry['prompts'] = []
            for p in value['prompts']:
                row = {'size': p['size'], 'skipped': p['skipped'],
                       'backend_modes': sorted({r['backend']['mode'] for r in p['runs']
                                                if isinstance(r.get('backend'), dict) and r['backend'].get('mode')})}
                for field in ('generation_tokens_per_second', 'prompt_tokens_per_second', 'time_to_first_token_seconds'):
                    measured = median_of(p, field)
                    row[field] = measured['median']
                    row[field + '_reported_runs'] = measured['reported_runs']
                entry['prompts'].append(row)
        runs.append(entry)
    result = {'runs': runs}
    if ordered[0]['kind'] == 'ability':
        passages = {}
        for value in ordered:
            found = (value.get('document_suite') or {}).get('passages')
            if isinstance(found, dict):
                passages.update({k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)})
        if passages:
            result['passages'] = passages
            result['summaries'] = [
                {'item_id': u['item_id'], 'passage_id': u.get('passage_id'), 'question': u.get('question'),
                 'runs': {v['id']: next((x['output'][:ITEM_OUTPUT_LIMIT] for x in v.get('unscored', [])
                                         if x.get('item_id') == u['item_id'] and isinstance(x.get('output'), str)), None)
                          for v in ordered}}
                for u in ordered[0].get('unscored', []) if isinstance(u.get('item_id'), str)]
        items = []
        for item in ordered[0]['items']:
            row = {'item_id': item['item_id'], 'category': item['category'], 'passage_id': item.get('passage_id'),
                   'question': item.get('question'), 'runs': {}}
            for value in ordered:
                scored = next((x for x in value['items'] if x['item_id'] == item['item_id']), None)
                if scored is None:
                    raise ValueError('Runs do not cover the same items')
                output = scored.get('output')
                row['runs'][value['id']] = {'outcome': scored['outcome'], 'score': scored['score'],
                                            'output': output[:ITEM_OUTPUT_LIMIT] if isinstance(output, str) else None}
            items.append(row)
        result['items'] = items
    return result


def export_csv(comparison):
    output = io.StringIO(newline='')
    fields = ['id', 'model', 'manifest_digest', 'created', 'metric', 'value', 'format_errors']
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for row in comparison['rows']:
        # Protect spreadsheet consumers from formula-bearing untrusted model labels.
        safe = {key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value)
                for key, value in row.items()}
        writer.writerow(safe)
    return output.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description='List, inspect, delete or compare saved benchmark runs.')
    parser.add_argument('--results-dir', type=Path, default=DEFAULT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--compare', nargs='+', metavar='ID')
    action.add_argument('--load', metavar='ID')
    action.add_argument('--delete', metavar='ID')
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--json', action='store_true')
    output.add_argument('--csv', action='store_true', help='Comparison CSV on stdout; redirect to a file.')
    args = parser.parse_args(argv)
    if args.csv and not args.compare:
        parser.error('--csv requires --compare')
    store = Store(args.results_dir)
    if args.compare:
        result = compare([store.load(run_id) for run_id in args.compare])
    elif args.load:
        result = store.load(args.load)
    elif args.delete:
        store.delete(args.delete)
        result = {'deleted': args.delete}
    else:
        result = store.list()
    if args.csv:
        print(export_csv(result), end='')
    elif args.json or args.load:
        print(json.dumps(result, indent=2))
    elif args.compare:
        print('Model                       Metric                                  Value')
        for row in result['rows']:
            print(f"{row['model'][:27]:27} {row['metric']:39} {row['value'] if row['value'] is not None else 'unknown'}")
        print(result['limitations'])
    elif args.delete:
        print('Deleted result ' + args.delete)
    else:
        for run in result['runs']:
            print(f"{run['id']}  {run['kind']:7} {run['suite_version']}  {run['model']}")
        if result['rejected']:
            print(f"{len(result['rejected'])} invalid result files excluded; use --json for names.")
        if not result['runs']:
            print('No saved benchmark runs.')
    return 0
