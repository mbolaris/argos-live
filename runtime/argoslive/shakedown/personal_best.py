"""Owner-local personal bests from fully completed Shakedown laps only."""
import hashlib
import json
from pathlib import Path
import re

from .. import storage
from ..pull_jobs import read_json, write_json
from . import loadout


SCHEMA = 'argos-shakedown-personal-bests/1'
_RUN_ID = re.compile(r'^[0-9a-f]{32}$')


def _path(home):
    home = Path(home).absolute()
    return storage.safe_local(home / '.local/state/argos-live/shakedown-personal-bests.json')


def _hardware_key(run):
    public = loadout.snapshot(run)['hardware']
    raw = json.dumps(public, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _read(home):
    path = _path(home)
    if not path.exists():
        return {'schema': SCHEMA, 'entries': []}
    value = read_json(path)
    if value.get('schema') != SCHEMA or not isinstance(value.get('entries'), list):
        raise ValueError('Personal-best record needs review')
    return value


def record_complete_lap(home, store, run_ids):
    """Record complete ability runs only after their entire lap completed."""
    if (not isinstance(run_ids, (list, tuple)) or len(run_ids) < 2 or
            any(not isinstance(value, str) or not _RUN_ID.fullmatch(value) for value in run_ids) or
            len(set(run_ids)) != len(run_ids)):
        raise ValueError('A complete Shakedown lap result is required')
    runs = [store.load(run_id) for run_id in run_ids]
    lap_ids = {run.get('lap_id') for run in runs}
    if (len(lap_ids) != 1 or not isinstance(next(iter(lap_ids)), str) or
            not _RUN_ID.fullmatch(next(iter(lap_ids)))):
        raise ValueError('Lap result identities do not match')
    for run in runs:
        coverage = run.get('coverage')
        if (run.get('state') != 'completed' or not isinstance(coverage, dict) or
                coverage.get('complete') is not True):
            raise ValueError('Incomplete lap results cannot set a personal best')
    abilities = [run for run in runs if run.get('kind') == 'ability']
    if not abilities or not any(run.get('kind') == 'speed' for run in runs):
        raise ValueError('A complete lap must include speed and ability results')
    data = _read(home)
    by_key = {(entry.get('suite_version'), entry.get('slice_name'), entry.get('slice_version'),
               entry.get('hardware_sha256')): entry for entry in data['entries']
              if isinstance(entry, dict)}
    changed = 0
    for run in abilities:
        items = run.get('items')
        if (not isinstance(run.get('suite_version'), str) or not isinstance(run.get('slice_name'), str) or
                not isinstance(run.get('slice_version'), str) or not isinstance(items, list) or
                any(not isinstance(item, dict) or type(item.get('score')) is not int or
                    item['score'] not in (0, 1) for item in items) or not items):
            continue
        correct, total = sum(item['score'] for item in items), len(items)
        hardware_sha256 = _hardware_key(run)
        key = (run['suite_version'], run['slice_name'], run['slice_version'], hardware_sha256)
        prior = by_key.get(key)
        if prior is not None and correct <= prior.get('correct', -1):
            continue
        entry = {'suite_version': run['suite_version'], 'slice_name': run['slice_name'],
                 'slice_version': run['slice_version'], 'hardware_sha256': hardware_sha256,
                 'run_id': run['id'], 'correct': correct, 'total': total,
                 'created': run.get('created')}
        if prior is None:
            data['entries'].append(entry)
        else:
            data['entries'][data['entries'].index(prior)] = entry
        by_key[key] = entry
        changed += 1
    if changed:
        path = _path(home)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_json(path, data)
    return {'recorded': changed}


def best_run_ids(home):
    """Return only opaque run IDs used internally to mark scorecard cells."""
    return {entry['run_id'] for entry in _read(home)['entries']
            if isinstance(entry, dict) and isinstance(entry.get('run_id'), str) and
            _RUN_ID.fullmatch(entry['run_id'])}

