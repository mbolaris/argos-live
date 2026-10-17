"""Cooperating host workload admission; an abandoned worker is never auto-reclaimed.

This is exclusion, not an OS security boundary against an agent with shell access.
The persistent active marker intentionally outlives the OS lock after a crash.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import re

from . import storage
from .pull_jobs import read_json, worker_lock, write_json


class Busy(ValueError):
    def __init__(self, recovery=False):
        self.recovery = recovery
        super().__init__('Previous workload needs recovery' if recovery else 'Another host workload is active')


class Reservation:
    def __init__(self, path, record):
        self.path, self.record = path, record
        self.drained = False

    def complete(self, result_id=None):
        """Caller asserts all child work has drained; publish the saved result first."""
        if result_id is not None:
            self.record_result(result_id)
        self.drained = True

    def record_result(self, result_id):
        """Attach an already-published outcome without claiming safe release."""
        if not isinstance(result_id, str) or not re.fullmatch('[a-f0-9]{32}', result_id):
            raise ValueError('Invalid saved workload result ID')
        self.record['result_id'] = result_id


@contextmanager
def reserve(home, kind):
    if kind not in {'evaluation', 'proctor', 'log', 'maintenance'}:
        raise ValueError('Unknown host workload kind')
    root = storage.safe_local(Path(home) / '.local/state/argos-live/workload')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = storage.safe_local(root / 'reservation.json')
    lock = worker_lock(root)
    try:
        lock.__enter__()
    except ValueError:
        raise Busy() from None
    try:
        prior = read_json(path) if path.exists() else {}
        if prior.get('state') not in (None, 'released'):
            raise Busy(recovery=True)
        record = {'schema': 'argos-workload/1', 'id': secrets.token_hex(16),
                  'generation': prior.get('generation', 0) + 1, 'kind': kind,
                  'pid': os.getpid(), 'started': datetime.now(timezone.utc).isoformat(),
                  'state': 'active'}
        write_json(path, record)
        reservation = Reservation(path, record)
        try:
            yield reservation
        finally:
            # No expiry heuristic: an orphan can still be doing inference.
            record.update(state='released' if reservation.drained else 'quarantined',
                          finished=datetime.now(timezone.utc).isoformat())
            write_json(path, record)
    finally:
        lock.__exit__(None, None, None)
