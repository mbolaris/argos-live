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
    if 'recipe' in value:
        from . import recipe as recipe_mod
        recipe_mod.validate(value['recipe'])
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
        if value.get('recipe') != first.get('recipe'):
            raise ValueError('Comparison requires matching recipes')
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


def stable_gpu_identity(g):
    if not isinstance(g, dict):
        return None
    # Compare stable device identity, bus, and total VRAM capacity.
    # Transient runtime fields (vram_used_bytes, temperature, power, clock) are excluded.
    return (
        g.get('vendor'),
        g.get('name'),
        g.get('bus'),
        g.get('vram_total_bytes'),
        g.get('driver'),
    )


def same_hardware(a, b):
    def key(run):
        h = run.get('hardware')
        if not isinstance(h, dict) or not h:
            return None
        cpu = h.get('cpu')
        if not isinstance(cpu, dict) or not cpu.get('model'):
            return None
        cpu_key = (cpu.get('model'), cpu.get('cores'), cpu.get('threads'))
        gpus = h.get('gpus')
        if not isinstance(gpus, list):
            return None
        gpu_key = tuple(stable_gpu_identity(g) for g in gpus)
        if any(g is None for g in gpu_key):
            return None
        ram = h.get('ram')
        if not isinstance(ram, dict) or not isinstance(ram.get('total_bytes'), int) or ram['total_bytes'] <= 0:
            return None
        return (cpu_key, gpu_key, ram['total_bytes'])
    ka, kb = key(a), key(b)
    return ka is not None and ka == kb


def digest_of(value):
    if not isinstance(value, str):
        return None
    value = value[7:] if value.startswith('sha256:') else value
    return value if len(value) == 64 and all(c in '0123456789abcdef' for c in value) else None


def same_model(a, b):
    da, db = digest_of(a.get('manifest_digest')), digest_of(b.get('manifest_digest'))
    return a.get('model') == b.get('model') and da is not None and da == db


def compare_experiment(baseline, candidate, *, allowed_intervention=None):
    """Controlled one-variable experiment comparator.

    Validates that baseline and candidate differ in EXACTLY ONE declared
    intervention variable ('recipe' or 'model'), while matching all other
    fields: kind, suite, suite_version, settings, hardware, complete coverage,
    matching runtime versions, and successful restoration.
    """
    validate(baseline)
    validate(candidate)
    if baseline['id'] == candidate['id']:
        raise ValueError('Choose distinct runs for experiment comparison')

    # Successful cleanup/restoration is mandatory
    if not baseline.get('restoration', {}).get('succeeded') or not candidate.get('restoration', {}).get('succeeded'):
        raise ValueError('Experiment comparison requires successful cleanup/restoration for both runs')

    # Both runs must be completed (no partial/cancelled runs)
    if baseline.get('state', 'completed') != 'completed' or candidate.get('state', 'completed') != 'completed':
        raise ValueError('Cannot compare partial or cancelled runs')

    # Kind and suite version must match
    if (baseline['kind'], baseline['suite_version']) != (candidate['kind'], candidate['suite_version']):
        raise ValueError('Experiment comparison requires matching benchmark kind and suite version')

    # Coverage must be complete and identical
    if baseline['kind'] == 'ability':
        if not baseline.get('coverage', {}).get('complete') or not candidate.get('coverage', {}).get('complete'):
            raise ValueError('Experiment comparison requires complete coverage for both runs')
        if ([(i['item_id'], i['category']) for i in baseline['items']] !=
                [(i['item_id'], i['category']) for i in candidate['items']]):
            raise ValueError('Runs must cover the exact same test items in identical order')
        if baseline.get('omitted_categories') != candidate.get('omitted_categories'):
            raise ValueError('Runs must have identical category coverage')
    else:
        if ([(p['size'], p.get('context_tokens'), p['skipped']) for p in baseline['prompts']] !=
                [(p['size'], p.get('context_tokens'), p['skipped']) for p in candidate['prompts']]):
            raise ValueError('Speed prompt coverage differs between runs')

    # Hardware must match and have complete evidence
    if not same_hardware(baseline, candidate):
        raise ValueError('Experiment comparison requires complete, matching hardware evidence (CPU, GPU, RAM)')

    # Recorded runtime versions must match and have complete evidence
    ov_b = baseline.get('ollama_version')
    ov_c = candidate.get('ollama_version')
    av_b = baseline.get('argos_version')
    av_c = candidate.get('argos_version')
    if not isinstance(ov_b, str) or not ov_b or not isinstance(ov_c, str) or not ov_c:
        raise ValueError('Experiment comparison requires recorded Ollama version evidence')
    if ov_b != ov_c:
        raise ValueError(f"Experiment comparison requires identical Ollama version (found {ov_b} vs {ov_c})")
    if not isinstance(av_b, str) or not av_b or not isinstance(av_c, str) or not av_c:
        raise ValueError('Experiment comparison requires recorded Argos version evidence')
    if av_b != av_c:
        raise ValueError(f"Experiment comparison requires identical Argos version (found {av_b} vs {av_c})")

    # Verified identities: incomplete identities are rejected
    da = digest_of(baseline.get('manifest_digest'))
    db = digest_of(candidate.get('manifest_digest'))
    if da is None or db is None:
        raise ValueError('Experiment comparison requires verified manifest digests for both runs')

    # Resolve recipes
    from . import recipe as recipe_mod
    ctx_b = baseline.get('settings', {}).get('context', 2048)
    ctx_c = candidate.get('settings', {}).get('context', 2048)
    b_rec = recipe_mod.resolve(baseline.get('recipe'), context=ctx_b)
    c_rec = recipe_mod.resolve(candidate.get('recipe'), context=ctx_c)

    # Check recipe preset difference
    recipe_preset_differs = (b_rec['preset'] != c_rec['preset'])

    # Check other recipe fields: they MUST NOT differ
    recipe_other_differs = (
        b_rec['context'] != c_rec['context'] or
        b_rec['output_cap'] != c_rec['output_cap'] or
        b_rec['temperature'] != c_rec['temperature'] or
        b_rec['seed'] != c_rec['seed'] or
        b_rec['thinking'] != c_rec['thinking'] or
        b_rec['request_format'] != c_rec['request_format']
    )
    if recipe_other_differs:
        raise ValueError('Experiment comparison allows at most one recipe variable; multiple recipe settings differed')

    # Check non-recipe settings: must match
    b_settings_no_rec = {k: v for k, v in baseline.get('settings', {}).items() if k != 'recipe'}
    c_settings_no_rec = {k: v for k, v in candidate.get('settings', {}).items() if k != 'recipe'}
    if b_settings_no_rec != c_settings_no_rec:
        raise ValueError('Experiment comparison requires identical non-recipe settings')

    # Model difference
    model_differs = (baseline['model'] != candidate['model'] or da != db)

    # Validate that EXACTLY ONE intervention occurred
    if recipe_preset_differs and model_differs:
        raise ValueError('Controlled experiment allows exactly one declared intervention; both model and recipe differed')
    if not recipe_preset_differs and not model_differs:
        raise ValueError('Baseline and candidate configurations are identical; repeated practice is not an independent experiment')

    detected = 'model' if model_differs else 'recipe'
    if allowed_intervention is not None and allowed_intervention != detected:
        raise ValueError(f"Declared intervention '{allowed_intervention}' does not match detected change '{detected}'")

    # Build delta
    if baseline['kind'] == 'ability':
        b_sum = baseline['summary']
        c_sum = candidate['summary']
        acc_delta = round(c_sum['accuracy'] - b_sum['accuracy'], 4)
        corr_delta = c_sum['correct'] - b_sum['correct']
        fmt_delta = c_sum['format_errors'] - b_sum['format_errors']

        cat_deltas = {}
        for cat_name, b_cat in b_sum.get('categories', {}).items():
            c_cat = c_sum.get('categories', {}).get(cat_name, {})
            cat_deltas[cat_name] = {
                'baseline_correct': b_cat.get('correct', 0),
                'candidate_correct': c_cat.get('correct', 0),
                'total': b_cat.get('total', 0),
                'delta_correct': c_cat.get('correct', 0) - b_cat.get('correct', 0),
                'delta_format_errors': c_cat.get('format_errors', 0) - b_cat.get('format_errors', 0),
            }

        label = c_rec['preset'] if detected == 'recipe' else candidate['model']
        if corr_delta > 0:
            verdict = 'observed_gain'
            summary_text = f"Observed gain (+{corr_delta} tasks) under {label}. Single-suite observed gain; repeated practice or single-exercise delta is not confirmed general improvement."
        elif corr_delta < 0:
            verdict = 'regression'
            summary_text = f"Observed regression ({corr_delta} tasks) under {label}."
        else:
            if fmt_delta < 0:
                verdict = 'observed_gain'
                summary_text = f"Identical accuracy with fewer format errors ({fmt_delta}) under {label}."
            elif fmt_delta > 0:
                verdict = 'regression'
                summary_text = f"Identical accuracy with additional format errors (+{fmt_delta}) under {label}."
            else:
                verdict = 'no_change'
                summary_text = f"No change in task outcomes ({c_sum['correct']}/{c_sum['total']} tasks)."

        # Per item side-by-side
        items_map = {it['item_id']: it for it in candidate['items']}
        item_rows = []
        for b_it in baseline['items']:
            item_id = b_it['item_id']
            c_it = items_map.get(item_id, {})
            item_rows.append({
                'item_id': item_id,
                'category': b_it['category'],
                'passage_id': b_it.get('passage_id'),
                'question': b_it.get('question'),
                'baseline_outcome': b_it['outcome'],
                'candidate_outcome': c_it.get('outcome'),
                'baseline_output': b_it.get('output', '')[:ITEM_OUTPUT_LIMIT] if isinstance(b_it.get('output'), str) else None,
                'candidate_output': c_it.get('output', '')[:ITEM_OUTPUT_LIMIT] if isinstance(c_it.get('output'), str) else None,
                'changed': (b_it['outcome'] != c_it.get('outcome') or b_it.get('output') != c_it.get('output')),
            })

        delta = {
            'accuracy_delta': acc_delta,
            'correct_delta': corr_delta,
            'format_error_delta': fmt_delta,
            'category_deltas': cat_deltas,
            'verdict': verdict,
            'summary': summary_text,
        }
    else:
        from .bench_speed import numeric, summary
        prompts_delta = []
        for b_p in baseline['prompts']:
            size = b_p['size']
            c_p = next((p for p in candidate['prompts'] if p['size'] == size), None)
            if c_p:
                b_gen = summary([numeric(r.get('generation_tokens_per_second')) for r in b_p['runs']])['median'] if not b_p['skipped'] and len(b_p['runs']) == 3 else None
                c_gen = summary([numeric(r.get('generation_tokens_per_second')) for r in c_p['runs']])['median'] if not c_p['skipped'] and len(c_p['runs']) == 3 else None
                b_ttft = summary([numeric(r.get('time_to_first_token_seconds')) for r in b_p['runs']])['median'] if not b_p['skipped'] and len(b_p['runs']) == 3 else None
                c_ttft = summary([numeric(r.get('time_to_first_token_seconds')) for r in c_p['runs']])['median'] if not c_p['skipped'] and len(c_p['runs']) == 3 else None
                prompts_delta.append({
                    'size': size,
                    'baseline_generation_tok_s': b_gen,
                    'candidate_generation_tok_s': c_gen,
                    'delta_generation_tok_s': round(c_gen - b_gen, 2) if b_gen is not None and c_gen is not None else None,
                    'baseline_ttft_s': b_ttft,
                    'candidate_ttft_s': c_ttft,
                    'delta_ttft_s': round(c_ttft - b_ttft, 3) if b_ttft is not None and c_ttft is not None else None,
                })
        item_rows = []
        delta = {
            'prompts': prompts_delta,
            'verdict': 'speed_evaluated',
            'summary': 'Speed evaluated across paired 3-run prompt measurements; inspect median token rates and latency deltas directly.',
        }

    return {
        'schema': 'argos-experiment/1',
        'intervention': detected,
        'kind': baseline['kind'],
        'suite_version': baseline['suite_version'],
        'baseline': {
            'id': baseline['id'],
            'model': baseline['model'],
            'manifest_digest': baseline.get('manifest_digest'),
            'recipe': b_rec,
            'created': baseline['created'],
            'accuracy': baseline.get('summary', {}).get('accuracy'),
            'correct': baseline.get('summary', {}).get('correct'),
            'total': baseline.get('summary', {}).get('total'),
            'format_errors': baseline.get('summary', {}).get('format_errors'),
        },
        'candidate': {
            'id': candidate['id'],
            'model': candidate['model'],
            'manifest_digest': candidate.get('manifest_digest'),
            'recipe': c_rec,
            'created': candidate['created'],
            'accuracy': candidate.get('summary', {}).get('accuracy'),
            'correct': candidate.get('summary', {}).get('correct'),
            'total': candidate.get('summary', {}).get('total'),
            'format_errors': candidate.get('summary', {}).get('format_errors'),
        },
        'delta': delta,
        'items': item_rows,
        'limitations': 'Controlled one-variable experiment comparison. Observed differences reflect this specific suite under identical hardware and settings. Observed +1 is not confirmed general improvement without independent validation.',
    }


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
