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

    def comparison(self, previous=None):
        """Compare the latest build with one earlier build using fixed, recorded evidence."""
        records = self.store.list().get('runs', [])
        runs = []
        for record in records:
            try:
                runs.append(self.store.load(record['id']))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        runs.sort(key=_run_sort, reverse=True)
        by_loadout = defaultdict(list)
        identities = {}
        for run in runs:
            snapshot = loadout.snapshot(run)
            identities.setdefault(snapshot['id'], snapshot)
            by_loadout[snapshot['id']].append(run)
        current = next(iter(by_loadout), None)
        names = _owner_names(self.home)
        options = []
        for loadout_id in by_loadout:
            if loadout_id == current:
                continue
            options.append({'id': loadout_id,
                            'name': names.get(loadout_id) or
                                    f'{identities[loadout_id]["model"]} · {identities[loadout_id]["recipe"].get("context")}',
                            'created': by_loadout[loadout_id][0].get('created')})
        current_info = None
        if current is not None:
            current_info = {'id': current,
                            'name': names.get(current) or
                                    f'{identities[current]["model"]} · {identities[current]["recipe"].get("context")}',
                            'created': by_loadout[current][0].get('created')}
        if previous is not None and (not isinstance(previous, str) or previous not in by_loadout or previous == current):
            raise ValueError('Choose an earlier saved build')
        previous = previous or (options[0]['id'] if options else None)
        previous_info = None
        differences = []
        compared_rows = []
        if current is not None and previous is not None:
            previous_info = next(value for value in options if value['id'] == previous)
            differences = loadout.diff(identities[previous], identities[current])

            def entries(loadout_id):
                found = {}
                for run in by_loadout[loadout_id]:
                    produced = _speed_rows(run, loadout_id) if run.get('kind') == 'speed' else _ability_rows(run, loadout_id)
                    for row_id, row in produced:
                        if row_id not in found:
                            found[row_id] = row
                return found

            before_rows, after_rows = entries(previous), entries(current)
            for row_id in sorted(before_rows.keys() | after_rows.keys()):
                before = before_rows.get(row_id)
                after = after_rows.get(row_id)
                template = after or before
                row = {'id': row_id, 'label': template['label'], 'kind': template['kind'],
                       'verdict': 'not-available', 'reason': None,
                       'previous_run_id': None, 'current_run_id': None,
                       'previous_slice': None, 'current_slice': None}
                if before:
                    cell = before['cells'][previous]
                    row.update(previous_run_id=cell.get('run_id'), previous_slice=cell.get('slice'))
                if after:
                    cell = after['cells'][current]
                    row.update(current_run_id=cell.get('run_id'), current_slice=cell.get('slice'))
                if not before or not after:
                    row['reason'] = 'A saved result is missing for one build.'
                elif before['kind'] != after['kind']:
                    row.update(verdict='incomparable', reason='These rows measure different things.')
                else:
                    old_cell, new_cell = before['cells'][previous], after['cells'][current]
                    if (old_cell.get('state') != 'completed' or new_cell.get('state') != 'completed' or
                            old_cell.get('complete', True) is False or new_cell.get('complete', True) is False):
                        row.update(verdict='incomplete', reason='Both results must be complete.')
                    elif (old_cell.get('suite_version') != new_cell.get('suite_version') or
                          old_cell.get('slice') != new_cell.get('slice') or
                          (old_cell.get('slice') != 'full' and
                           old_cell.get('slice_version') != new_cell.get('slice_version'))):
                        row.update(verdict='incomparable', reason='The form version or lap slice differs.')
                    else:
                        try:
                            if after['kind'] == 'ability':
                                result = verdict.compare(before['cells'][previous]['_comparison_run'],
                                                         after['cells'][current]['_comparison_run'])
                            else:
                                old_values = old_cell.get('values') or []
                                new_values = new_cell.get('values') or []
                                result = verdict.compare_speed(
                                    {'measurements': [{'tokens_per_second': value} for value in old_values]},
                                    {'measurements': [{'tokens_per_second': value} for value in new_values]})
                                if not after['higher_is_better']:
                                    result['verdict'] = {'better': 'worse', 'worse': 'better'}.get(
                                        result['verdict'], result['verdict'])
                            row['verdict'] = result['verdict']
                            for key in ('shared_items', 'wins', 'losses', 'ties', 'p_value',
                                        'additional_shared_questions', 'more_questions_note',
                                        'relative_change', 'baseline_spread', 'candidate_spread'):
                                if key in result:
                                    row[key] = result[key]
                        except (ValueError, KeyError) as exc:
                            row.update(verdict='incomparable', reason=str(exc))
                row['suite'] = template.get('suite')
                row['slice_version'] = (after or before)['cells'][current if after else previous].get('slice_version')
                compared_rows.append(row)

        counts = {key: sum(row['verdict'] == key for row in compared_rows)
                  for key in ('better', 'worse', 'too-close')}
        if previous_info is None:
            headline = 'Run this again later to compare two saved builds.'
        elif not any(counts.values()):
            headline = 'No rows could be compared between these builds.'
        else:
            def count_phrase(count, one, many):
                return f'{count} {one if count == 1 else many}'
            better = count_phrase(counts['better'], 'row improved', 'rows improved')
            worse = count_phrase(counts['worse'], 'row worsened', 'rows worsened')
            close = count_phrase(counts['too-close'], 'row too close to call',
                                 'rows too close to call')
            headline = f'Current build: {better}, {worse}, and {close}.'
        next_move = None
        next_size = {'quick': 'standard', 'standard': 'full'}
        for row in compared_rows:
            if row['verdict'] != 'too-close' or row['kind'] != 'ability' or not row.get('suite'):
                continue
            size = next_size.get(row.get('current_slice'))
            if size:
                next_move = {'label': 'Run more questions', 'suite': row['suite'], 'size': size,
                             'description': f'Run the {size} slice for {row["suite"]} to add questions.'}
                break
        return {'schema': 'argos-shakedown-comparison/1', 'available': True,
                'current': current_info, 'previous': previous_info, 'previous_options': options,
                'loadout_diff': differences, 'rows': compared_rows, 'counts': counts,
                'headline': headline, 'next_move': next_move,
                'empty': current_info is None, 'has_comparison': previous_info is not None}
