"""Cooperative owner cancellation, fenced to one admitted evaluation.

This is an owner CLI, not an agent tool or proof of process/backend drainage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import threading

from . import storage
from .pull_jobs import read_json, write_json


def root(home):
    return storage.safe_local(Path(home).absolute() / '.local/state/argos-live/workload')


def target(home):
    directory = root(home)
    record = read_json(storage.safe_local(directory / 'reservation.json'))
    if record.get('state') != 'active':
        raise ValueError('No recorded active evaluation; quarantine is never cancelled or released here')
    child_id = None
    if record.get('phase') == 'delegated':
        child_id = record.get('child_id')
        from .results import identifier
        child = read_json(storage.safe_local(directory / 'child' / (identifier(child_id) + '.json')))
        if (child.get('parent_id'), child.get('generation'), child.get('kind'), child.get('state')) != (
                record['id'], record['generation'], 'evaluation', 'active'):
            raise ValueError('No recorded active evaluation child')
    elif record.get('kind') != 'evaluation' or record.get('phase') != 'running':
        raise ValueError('Current workload is not an evaluation')
    value = {'id': record['id'], 'generation': record['generation'], 'child_id': child_id}
    current = read_json(directory / 'reservation.json')
    if any(current.get(key) != record.get(key) for key in ('id', 'generation', 'state', 'phase', 'child_id')):
        raise ValueError('Evaluation changed while reading owner control')
    return value


def request_path(home, value):
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return storage.safe_local(root(home) / 'owner-cancel' / (digest + '.json'))


def request_stop(home, expected):
    if target(home) != expected:
        raise ValueError('Evaluation identity changed; inspect status again')
    path = request_path(home, expected)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(path, {'action': 'cancel', 'target': expected})
    return {'status': 'cancel_requested', 'target': expected,
            'drainage_verified': False, 'reservation_released': False}


class Cancellation:
    def __init__(self, home, upstream=None):
        self.upstream = upstream if upstream is not None else threading.Event()
        self.path = None
        try:
            value = target(home)
        except FileNotFoundError:
            return  # Standalone test runners have no admission record.
        self.expected = {'action': 'cancel', 'target': value}
        self.path = request_path(home, value)

    def set(self):
        self.upstream.set()

    def is_set(self):
        if self.upstream.is_set():
            return True
        if self.path is None or not self.path.exists():
            return False
        # The marker path is fenced to this exact target. Any marker content
        # requests a conservative stop; it can never certify drainage/release.
        return True



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('status', 'stop'))
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--id')
    parser.add_argument('--generation', type=int)
    parser.add_argument('--child-id')
    args = parser.parse_args(argv)
    if args.operation == 'status':
        value = {'status': 'recorded_active', 'target': target(args.home), 'liveness_verified': False}
    else:
        if not args.id or args.generation is None:
            parser.error('stop requires --id and --generation from status, plus --child-id when present')
        value = request_stop(args.home, {'id': args.id, 'generation': args.generation, 'child_id': args.child_id})
    print(json.dumps(value))
    return 0
