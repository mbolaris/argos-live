"""Headroom report: which forms can still show a gain for the deployed build.

A form the deployed build already maxes out cannot show an improvement, so the
improvement loop has nothing to measure there. This module reads saved runs only
and reports, per form, the last three matched scores and one status. It runs no
model and changes nothing.

Rules it keeps:

* One row never mixes suite versions, models or settings. The newest complete
  run of the current form version for the deployed model sets the row's
  settings; only runs with the same model digest, settings, recipe and item
  coverage join it. Everything else is counted under ``left_out``.
* Practice and held-out halves get separate rows and are never added together.
* Instruction changes are what the loop varies, so runs with different
  ``AGENTS.md`` contents may share a row. The row says so in
  ``instructions_varied``.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .results import DEFAULT, Store

SCHEMA = 'argos-headroom/1'
SATURATION_PERCENT = 90
RUNS_REQUIRED = 3
SATURATED, HAS_ROOM, TOO_FEW, NEVER_RUN = 'saturated', 'has room', 'too few runs', 'never run'
STATUSES = (SATURATED, HAS_ROOM, TOO_FEW, NEVER_RUN)
PARTITIONS = ('practice', 'heldout')
LIMITATIONS = (
    'Read from saved runs only; nothing was run. Saturated means the three most recent matched runs '
    f'each scored at least {SATURATION_PERCENT} percent. Hardware and runtime versions are not part of '
    'the match. Auto Climb rows cover the practice set in the current Auto Climb session file only; '
    'its held-out validation partitions are used once and are not reported here.')


def status_of(scores):
    """One status from matched scores, newest first."""
    if not scores:
        return NEVER_RUN
    if len(scores) < RUNS_REQUIRED:
        return TOO_FEW
    recent = scores[:RUNS_REQUIRED]
    # Integer arithmetic: 18/20 is exactly 90 percent and counts as saturated.
    if all(score['correct'] * 100 >= score['total'] * SATURATION_PERCENT for score in recent):
        return SATURATED
    return HAS_ROOM


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _empty_left_out():
    return {'other_suite_versions': 0, 'other_models': 0, 'other_settings': 0, 'incomplete_or_partial': 0}


def _row(form, path, partition, suite_version, version, items, scores, left_out, instructions_varied):
    shown = scores[:RUNS_REQUIRED]
    return {'form': form, 'path': path, 'partition': partition, 'suite_version': suite_version,
            'version': version, 'items': items, 'status': status_of(scores), 'scores': shown,
            'matched_runs': len(scores), 'instructions_varied': instructions_varied,
            'left_out': left_out}


def _forms():
    """Every form the deployed assistant can be measured on, with its current version."""
    from . import ability, bench_openclaw
    forms, unavailable = [], []
    for name in bench_openclaw.SUITES:
        try:
            data, items, _path, _omitted = bench_openclaw.suite_content(name)
            ids = [item['id'] for item in items]
            partitions = {}
            if name != 'documents-short':
                for item in items:
                    rule = item.get('scorer')
                    half = rule.get('partition') if isinstance(rule, dict) else None
                    if half in PARTITIONS:
                        partitions[half] = partitions.get(half, 0) + 1
            version = data['version']
            if not isinstance(version, str) or not ids:
                raise ValueError('Form has no version or no scored items')
        except (OSError, ValueError, KeyError, TypeError):
            unavailable.append(name)
            continue
        families = [('assistant', 'argos-openclaw-ability/' + name + '/')]
        if name in ability.SUITE_COUNTS:
            families.append(('model-only', 'ability/' + name + '/'))
        elif name == 'documents-short':
            families.append(('model-only', 'documents/short/'))
        forms.append({'name': name, 'version': version, 'ids': ids, 'partitions': partitions,
                      'families': families})
    return forms, unavailable


def _match_key(run):
    return (run.get('manifest_digest'), _digest(run.get('settings')), _digest(run.get('recipe')),
            tuple(item['item_id'] for item in run['items']), _digest(run.get('omitted_categories')))


def _usable(run, form):
    if (run.get('state') != 'completed' or not run['coverage'].get('complete')
            or not run['restoration'].get('succeeded')):
        return False
    ids = [item['item_id'] for item in run['items']]
    # A lap slice covers part of a form; its score is not the form's score.
    return len(ids) == len(form['ids']) and set(ids) == set(form['ids'])


def _score(run, partition):
    items = [item for item in run['items'] if partition is None or item.get('partition') == partition]
    return {'run_id': run['id'], 'created': run['created'],
            'correct': sum(item['score'] for item in items), 'total': len(items),
            'percent': round(sum(item['score'] for item in items) / len(items) * 100, 1) if items else None,
            'format_errors': sum(item['outcome'] == 'format_error' for item in items)}


def _model_matches(run_model, model, path):
    """Match the configured local model tag to OpenClaw's provider-qualified identity.

    Argos configuration stores ``qwen3.8:27b`` while assistant benchmark
    records store ``ollama/qwen3.8:27b``. Model-only benchmark records keep the
    unqualified tag, so only the assistant path accepts this provider alias.
    """
    if run_model == model:
        return True
    return path == 'assistant' and isinstance(model, str) and '/' not in model and run_model == 'ollama/' + model


def _suite_rows(form, path, prefix, runs, model):
    current = prefix + form['version']
    left_out = _empty_left_out()
    usable = []
    for run in runs:
        if not run['suite_version'].startswith(prefix):
            continue
        if not _model_matches(run['model'], model, path):
            left_out['other_models'] += 1
        elif run['suite_version'] != current:
            left_out['other_suite_versions'] += 1
        elif not _usable(run, form):
            left_out['incomplete_or_partial'] += 1
        else:
            usable.append(run)
    matched = []
    if usable:
        key = _match_key(usable[0])
        matched = [run for run in usable if _match_key(run) == key]
        left_out['other_settings'] = len(usable) - len(matched)
    hashes = {(run.get('prompt_fingerprint') or {}).get('workspace_agents_sha256')
              for run in matched[:RUNS_REQUIRED]}
    rows = []
    for partition in (sorted(form['partitions'], key=PARTITIONS.index) or [None]):
        scores = [_score(run, partition) for run in matched]
        if any(score['total'] == 0 for score in scores):
            # A run that does not label its halves cannot be split honestly.
            scores = []
        total = form['partitions'].get(partition, len(form['ids']))
        rows.append(_row(form['name'], path, partition, current, form['version'], total, scores,
                         dict(left_out), len(hashes) > 1))
    return rows


def _auto_climb_rows(home, model):
    """Practice-set rows for the Auto Climb tiers, from the current session file."""
    from . import auto_climb
    from .pull_jobs import read_json
    records, note = [], None
    path = Path(home).absolute() / auto_climb.SESSION_REL_PATH
    try:
        if path.is_file():
            session = read_json(path)
            ledger = session.get('suite_runs') if session.get('schema') == auto_climb.SCHEMA else None
            if isinstance(ledger, dict):
                records = [record for record in ledger.values() if isinstance(record, dict)
                           and record.get('comparison_role') == 'practice_baseline']
            else:
                note = 'The Auto Climb session file has no readable run records.'
    except (OSError, ValueError):
        note = 'The Auto Climb session file could not be read.'
    rows = []
    for tier, practice_path, _validation in auto_climb.CURRICULA:
        try:
            tasks = auto_climb.load_task_file(practice_path)
            suite_sha, version, count = auto_climb._canonical_digest(tasks), tasks['version'], len(tasks['tasks'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        left_out = _empty_left_out()
        usable = []
        for record in records:
            # The record stores a digest of the exact task file, so an edited tier never matches.
            if record.get('suite_sha256') != suite_sha:
                continue
            identity = record.get('model_identity')
            active = identity.get('session_active_model') if isinstance(identity, dict) else None
            if not isinstance(active, dict) or model is None or active.get('model') != model:
                left_out['other_models'] += 1
            elif not auto_climb._suite_run_is_complete(record) or not isinstance(record.get('finished_at'), str):
                left_out['incomplete_or_partial'] += 1
            else:
                usable.append(record)
        usable.sort(key=lambda record: (record['finished_at'], record['run_id']), reverse=True)

        def key(record):
            return (record['model_identity']['session_active_model'].get('digest'),
                    _digest(record.get('config_fingerprint')))
        matched = [record for record in usable if key(record) == key(usable[0])]
        left_out['other_settings'] = len(usable) - len(matched)
        scores = []
        for record in matched:
            correct = sum(item['passed'] for item in record['items'])
            scores.append({'run_id': record['run_id'], 'created': record['finished_at'], 'correct': correct,
                           'total': record['task_count'],
                           'percent': round(correct / record['task_count'] * 100, 1), 'format_errors': None})
        hashes = {record.get('instructions_sha256') for record in matched[:RUNS_REQUIRED]}
        row = _row(tier, 'auto-climb', 'practice', tier, version, count, scores, left_out, len(hashes) > 1)
        if note:
            row['note'] = note
        rows.append(row)
    return rows


def _configured_model(home):
    from . import auto_climb
    try:
        return auto_climb.configured_model(Path(home).absolute())
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def report(store, *, home=None, model=None):
    """Build the headroom report from saved runs. Read-only."""
    home = Path(home) if home is not None else Path.home()
    listing = store.list()
    runs = []
    rejected = len(listing.get('rejected', []))
    for record in listing.get('runs', []):
        if record.get('kind') != 'ability':
            continue
        try:
            runs.append(store.load(record['id']))
        except (OSError, ValueError):
            rejected += 1
    runs.sort(key=lambda run: (run['created'], run['id']), reverse=True)
    if model is not None:
        source = 'requested'
    else:
        model = _configured_model(home)
        source = 'configured'
        if model is None:
            # Off the Live system there is no assistant configuration; say which build was assumed.
            model = runs[0]['model'] if runs else None
            source = 'latest saved run' if runs else 'unknown'
    forms, unavailable = _forms()
    rows = []
    for form in forms:
        for path, prefix in form['families']:
            produced = _suite_rows(form, path, prefix, runs, model)
            # Model-only runs are optional extras; the assistant path is the deployed build.
            # They appear only when the deployed model has saved runs of that kind.
            if path == 'assistant' or any(
                    row['matched_runs'] or any(count for name, count in row['left_out'].items()
                                               if name != 'other_models') for row in produced):
                rows.extend(produced)
    rows.extend(_auto_climb_rows(home, model))
    return {'schema': SCHEMA, 'build': {'model': model, 'source': source},
            'saturation_percent': SATURATION_PERCENT, 'runs_required': RUNS_REQUIRED,
            'rows': rows, 'counts': {status: sum(row['status'] == status for row in rows) for status in STATUSES},
            'forms_unavailable': unavailable, 'rejected_files': rejected, 'limitations': LIMITATIONS}


_HALF = {None: 'all', 'practice': 'practice', 'heldout': 'held-out'}
_PATH = {'assistant': 'assistant', 'model-only': 'model only', 'auto-climb': 'Auto Climb'}


def render(result):
    """Plain text table. Scores are raw counts, newest first."""
    build = result['build']
    lines = [f"Deployed build: {build['model'] or 'not known'} ({build['source']})", '']
    table = [('Form', 'Measured', 'Half', 'Version', 'Last three, newest first', 'Status')]
    for row in result['rows']:
        scores = '  '.join(f"{score['correct']}/{score['total']}" for score in row['scores']) or '-'
        table.append((row['form'], _PATH[row['path']], _HALF[row['partition']], row['version'], scores,
                      row['status'] + (' *' if row['instructions_varied'] else '')))
    widths = [max(len(line[column]) for line in table) for column in range(len(table[0]))]
    for line in table:
        lines.append('  '.join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip())
    counts = result['counts']
    lines += ['', ', '.join(f'{counts[status]} {status}' for status in STATUSES) + '.']
    if any(row['instructions_varied'] for row in result['rows']):
        lines.append('* The runs shown were made with different AGENTS.md instructions.')
    left = _empty_left_out()
    seen = set()
    for row in result['rows']:
        # Both halves of a form carry the same counts; add each form once.
        if (row['form'], row['path']) in seen:
            continue
        seen.add((row['form'], row['path']))
        for name in left:
            left[name] += row['left_out'][name]
    if any(left.values()):
        lines.append('Saved runs left out of the rows above: '
                     f"{left['other_suite_versions']} other suite version, {left['other_models']} other model, "
                     f"{left['other_settings']} other settings, {left['incomplete_or_partial']} incomplete or "
                     'partial. Use --json for detail.')
    for note in sorted({row['note'] for row in result['rows'] if row.get('note')}):
        lines.append(note)
    if result['forms_unavailable']:
        lines.append('Forms that could not be loaded: ' + ', '.join(result['forms_unavailable']) + '.')
    if result['rejected_files']:
        lines.append(f"{result['rejected_files']} invalid result files excluded.")
    lines.append(result['limitations'])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='argos headroom',
        description='Show which forms the deployed build can still improve on, from saved runs only.')
    parser.add_argument('--json', action='store_true', help='Print the report as JSON.')
    parser.add_argument('--results-dir', type=Path, default=DEFAULT)
    parser.add_argument('--home', type=Path, default=None,
                        help='Home directory holding the assistant configuration and Auto Climb session.')
    parser.add_argument('--model', default=None,
                        help='Report this exact model tag instead of the configured one.')
    args = parser.parse_args(argv)
    result = report(Store(args.results_dir), home=args.home, model=args.model)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
