"""Owner-facing scorecard projections from saved local benchmark runs."""
from collections import defaultdict
import json
from pathlib import Path

from . import lap, loadout, verdict


WILSON_Z = 1.96
MAX_PINNED = 4


def wilson(correct, total, z=WILSON_Z):
    if type(correct) is not int or type(total) is not int or total <= 0 or not 0 <= correct <= total:
        raise ValueError('Wilson interval needs valid scored counts')
    proportion = correct / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * ((proportion * (1 - proportion) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return [max(0, center - margin), min(1, center + margin)]


def _owner_names(home):
    path = loadout._names_path(home)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
            return {}
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return {key: text for key, text in value.items()
            if isinstance(key, str) and isinstance(text, str)} if isinstance(value, dict) else {}


def _run_sort(run):
    return (run.get('created') or '', run.get('id') or '')


def _loadout_record(run):
    snapshot = loadout.snapshot(run)
    return {'id': snapshot['id'], 'model': snapshot['model'],
            'quantization': snapshot['quantization'], 'parameter_size': snapshot['parameter_size'],
            'recipe': snapshot['recipe'], 'created': run.get('created')}


def _speed_rows(run, loadout_id):
    rows = []
    for prompt in run.get('prompts', []):
        if prompt.get('skipped'):
            continue
        for metric, label, higher_is_better, unit in (
                ('generation_tokens_per_second', 'Generation speed', True, 'tokens/s'),
                ('time_to_first_token_seconds', 'Time to first token', False, 's')):
            values = [sample.get(metric) for sample in prompt.get('runs', [])
                      if isinstance(sample, dict) and type(sample.get(metric)) in (int, float)]
            if not values:
                continue
            row_id = f'speed|{prompt.get("size")}|{metric}'
            rows.append((row_id, {'id': row_id, 'kind': 'speed',
                                  'label': f'{prompt.get("size", "unknown").title()} · {label}',
                                  'metric': metric, 'size': prompt.get('size'), 'unit': unit,
                                  'higher_is_better': higher_is_better,
                                  'cells': {loadout_id: {'run_id': run.get('id'),
                                      'value': sum(values) / len(values), 'count': len(values),
                                      'values': values, 'slice': run.get('slice_name', 'full'),
                                      'slice_version': run.get('slice_version'),
                                      'suite_version': run.get('suite_version'),
                                      'date': run.get('created'), 'state': run.get('state', 'completed'),
                                      'footnotes': []}}}))
    return rows


def _ability_rows(run, loadout_id):
    groups = defaultdict(list)
    for item in run.get('items', []):
        if not isinstance(item, dict) or type(item.get('score')) is not int:
            continue
        category = item.get('category', 'all')
        partition = item.get('partition') or 'all'
        groups[(category, partition)].append(item)
    rows = []
    for (category, partition), items in groups.items():
        correct, total = sum(item['score'] for item in items), len(items)
        if not total:
            continue
        row_id = f'ability|{run.get("suite", "unknown")}|{category}|{partition}'
        footnotes = []
        if run.get('calibration_status') == 'uncalibrated':
            footnotes.append('uncalibrated')
        if run.get('benchmark_pack'):
            footnotes.extend(('subset', 'public', 'not the official score'))
        slice_name = run.get('slice_name', 'full')
        projection = {'state': run.get('state'), 'suite_version': run.get('suite_version'),
                      'slice_name': slice_name, 'slice_version': run.get('slice_version'),
                      'items': items, 'suite_total': run.get('suite_total', len(items))}
        rows.append((row_id, {'id': row_id, 'kind': 'ability',
                              'label': f'{run.get("suite", "Ability")} · {category} · '
                                       f'{"sealed" if partition == "heldout" else partition}',
                              'suite': run.get('suite'), 'category': category,
                              'partition': partition, 'cells': {loadout_id: {
                                  'run_id': run.get('id'), 'correct': correct, 'total': total,
                                  'percent': correct / total * 100,
                                  'interval': [value * 100 for value in wilson(correct, total)],
                                  'slice': slice_name, 'slice_version': run.get('slice_version'),
                                  'suite_version': run.get('suite_version'),
                                  'date': run.get('created'), 'state': run.get('state'),
                                  'complete': bool(run.get('coverage', {}).get('complete')),
                                  'footnotes': footnotes,
                                  '_comparison_run': projection}}}))
    return rows


class View:
    def __init__(self, store, *, home=None):
        self.store = store
        self.home = Path(home) if home is not None else Path.home()

    def scorecard(self, pinned=()):
        if not isinstance(pinned, (list, tuple)) or len(pinned) > MAX_PINNED:
            raise ValueError('Choose up to four pinned loadouts')
        if any(not isinstance(value, str) for value in pinned) or len(set(pinned)) != len(pinned):
            raise ValueError('Loadout IDs must be unique strings')
        records = self.store.list().get('runs', [])
        runs = []
        for record in records:
            try:
                run = self.store.load(record['id'])
            except (OSError, ValueError):
                continue
            runs.append(run)
        runs.sort(key=_run_sort, reverse=True)
        known = {}
        by_loadout = defaultdict(list)
        for run in runs:
            identity = _loadout_record(run)
            loadout_id = identity['id']
            known.setdefault(loadout_id, identity)
            by_loadout[loadout_id].append(run)
        current = next(iter(by_loadout), None)
        if any(value not in known for value in pinned):
            raise ValueError('A selected loadout is not in the saved results')
        selected = list(pinned)
        for loadout_id in known:
            if loadout_id not in selected and len(selected) < MAX_PINNED:
                selected.append(loadout_id)
        if current is not None and current not in selected:
            selected = selected[:MAX_PINNED] + [current]
        selected = list(dict.fromkeys(selected))
        names = _owner_names(self.home)
        loadouts = []
        for loadout_id in selected:
            value = dict(known[loadout_id])
            value['name'] = names.get(loadout_id) or f'{value["model"]} · {value["recipe"].get("context")}'
            value['current'] = loadout_id == current
            loadouts.append(value)
        available_loadouts = []
        for loadout_id, value in known.items():
            available = dict(value)
            available['name'] = names.get(loadout_id) or f'{value["model"]} · {value["recipe"].get("context")}'
            available['current'] = loadout_id == current
            available_loadouts.append(available)
        collected = {}
        run_lookup = {}
        for loadout_id in selected:
            for run in by_loadout.get(loadout_id, []):
                entries = _speed_rows(run, loadout_id) if run.get('kind') == 'speed' else _ability_rows(run, loadout_id)
                for row_id, row in entries:
                    cell = row['cells'][loadout_id]
                    if row_id not in collected:
                        collected[row_id] = {**row, 'cells': {}}
                    existing = collected[row_id]['cells'].get(loadout_id)
                    if existing is None or (cell.get('date') or '') > (existing.get('date') or ''):
                        collected[row_id]['cells'][loadout_id] = cell
                        if '_comparison_run' in cell:
                            run_lookup[(row_id, loadout_id)] = cell.pop('_comparison_run')
        rows = []
        for row in collected.values():
            cells = row['cells']
            for loadout_id, cell in cells.items():
                cell.setdefault('best', False)
                others = [(other_id, other) for other_id, other in cells.items() if other_id != loadout_id]
                if not others or cell.get('state') != 'completed' or not cell.get('complete', True):
                    continue
                verdicts = []
                for other_id, other in others:
                    if (cell.get('suite_version') != other.get('suite_version') or
                            cell.get('slice') != other.get('slice') or
                            (cell.get('slice') != 'full' and
                             cell.get('slice_version') != other.get('slice_version'))):
                        cell['incomparable'] = True
                        continue
                    try:
                        if row['kind'] == 'ability':
                            compared = verdict.compare(run_lookup[(row['id'], other_id)],
                                                        run_lookup[(row['id'], loadout_id)])
                            verdicts.append(compared['verdict'])
                        else:
                            a = {'measurements': [{'tokens_per_second': value} for value in other['values']]}
                            b = {'measurements': [{'tokens_per_second': value} for value in cell['values']]}
                            compared = verdict.compare_speed(a, b)
                            better = compared['verdict']
                            if not row['higher_is_better']:
                                better = {'better': 'worse', 'worse': 'better'}.get(better, better)
                            verdicts.append(better)
                    except (ValueError, KeyError):
                        cell['incomparable'] = True
                if verdicts and len(verdicts) == len(others) and all(value == 'better' for value in verdicts):
                    cell['best'] = True
                cell.pop('values', None)
            rows.append(row)
        rows.sort(key=lambda item: (item['kind'] != 'speed', item.get('label', '')))
        estimates = {}
        if current is not None:
            latest_speed = next((run for run in by_loadout[current] if run.get('kind') == 'speed'), None)
            latest_ability = next((run for run in by_loadout[current] if run.get('kind') == 'ability'), None)
            measurements = {
                'latest_speed': latest_speed,
                'last_run': latest_ability,
            }
            for size in lap.SIZES:
                estimates[size] = lap.estimate(lap.build(size), measurements)
        return {'schema': 'argos-shakedown-scorecard/1', 'loadouts': loadouts,
                'available_loadouts': available_loadouts,
                'selected_loadout_ids': selected, 'current_loadout_id': current, 'rows': rows,
                'lap_estimates': estimates, 'empty': not bool(loadouts), 'available': True}
