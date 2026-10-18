"""Cooperating host workload admission; an abandoned worker is never auto-reclaimed.

This is exclusion, not an OS security boundary against an agent with shell access.
The persistent active marker intentionally outlives the OS lock after a crash.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import re
import hashlib
import hmac
from dataclasses import dataclass, field
import sys

from . import storage
from .pull_jobs import read_json, worker_lock, write_json

PROCESS_NONCE = secrets.token_hex(32)


def worker_identity(pid):
    """Process birth, not PID alone; delegation across processes is Linux-only."""
    if sys.platform == 'linux':
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
        if stat[0] in {'Z', 'X'}:
            raise ValueError('Workload owner exited')
        return {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'start_ticks': stat[19]}
    if pid == os.getpid():
        return {'process_nonce': PROCESS_NONCE}
    raise ValueError('Cross-process delegation requires Linux worker identity')

class Busy(ValueError):
    def __init__(self, recovery=False):
        self.recovery = recovery
        super().__init__('Previous workload needs recovery' if recovery else 'Another host workload is active')


@dataclass(frozen=True)
class Delegation:
    """Host-created bearer capability; never put its secret in model tool arguments."""
    parent_id: str
    generation: int
    child_id: str
    secret: str = field(repr=False)


def same_owner(current, expected):
    if (current.get('id'), current.get('generation'), current.get('state')) != (
            expected['id'], expected['generation'], 'active'):
        raise Busy(recovery=True)


def child_root(root):
    directory = storage.safe_local(root / 'child')
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


@contextmanager
def child_lock(root):
    lock = worker_lock(child_root(root))
    try:
        lock.__enter__()
    except ValueError:
        raise Busy() from None
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def checked_child(root, capability):
    if (not isinstance(capability, Delegation) or
            not re.fullmatch('[a-f0-9]{32}', capability.child_id) or
            not isinstance(capability.secret, str)):
        raise ValueError('Invalid workload delegation')
    parent = read_json(root / 'reservation.json')
    if (parent.get('id'), parent.get('generation'), parent.get('state'),
            parent.get('phase'), parent.get('child_id')) != (
            capability.parent_id, capability.generation, 'active', 'delegated', capability.child_id):
        raise Busy(recovery=True)
    path = storage.safe_local(root / 'child' / (capability.child_id + '.json'))
    child = read_json(path)
    supplied = hashlib.sha256(capability.secret.encode()).hexdigest()
    if not hmac.compare_digest(child.get('capability_sha256', ''), supplied):
        raise ValueError('Invalid workload delegation')
    if (child.get('parent_id'), child.get('generation'), child.get('id')) != (
            capability.parent_id, capability.generation, capability.child_id):
        raise Busy(recovery=True)
    try:
        if worker_identity(parent['pid']) != parent.get('worker_identity'):
            raise Busy(recovery=True)
    except (OSError, ValueError, KeyError, IndexError):
        raise Busy(recovery=True) from None
    return parent, path, child


class Reservation:
    def __init__(self, path, record):
        self.path, self.record = path, record
        self.drained = False

    def complete(self, result_id=None):
        """Caller asserts all child work has drained; publish the saved result first."""
        current = read_json(self.path)
        same_owner(current, self.record)
        if current.get('phase') == 'delegated':
            raise Busy(recovery=True)
        if result_id is not None:
            self.record_result(result_id)
        self.drained = True

    def record_result(self, result_id):
        """Attach an already-published outcome without claiming safe release."""
        if not isinstance(result_id, str) or not re.fullmatch('[a-f0-9]{32}', result_id):
            raise ValueError('Invalid saved workload result ID')
        self.record['result_id'] = result_id

    def delegate(self, kind):
        """Suspend the controller before one host-selected child may start.

        Caller owns tool dispatch and must not resume controller inference or
        mutate instructions until resume() succeeds. No secret is published in
        reservation.json or the child record. This is not same-UID isolation.
        """
        if self.record['kind'] != 'controller' or kind not in {'evaluation', 'log', 'maintenance'}:
            raise ValueError('Controller delegation kind is not supported')
        root = self.path.parent
        directory = child_root(root)
        with child_lock(root):
            current = read_json(self.path)
            same_owner(current, self.record)
            if self.drained or current.get('phase') == 'delegated':
                raise Busy()
            capability = Delegation(current['id'], current['generation'], secrets.token_hex(16),
                                    secrets.token_hex(32))
            child = {'schema': 'argos-workload-child/1', 'id': capability.child_id,
                     'parent_id': capability.parent_id, 'generation': capability.generation,
                     'kind': kind, 'state': 'authorized',
                     'capability_sha256': hashlib.sha256(capability.secret.encode()).hexdigest()}
            write_json(directory / (capability.child_id + '.json'), child)
            current.update(phase='delegated', child_id=capability.child_id)
            write_json(self.path, current)
            self.record = current
            return capability

    def resume(self, capability, *, worker_drained=False):
        """Host confirms child transport/worker drainage, after saved publication.

        An SDK end event or expired timeout is not that confirmation. The caller
        must supervise the worker; this API does not infer process/backend exit.
        """
        if worker_drained is not True:
            raise Busy(recovery=True)
        root = self.path.parent
        with child_lock(root):
            current, _path, child = checked_child(root, capability)
            same_owner(current, self.record)
            if child['state'] != 'released':
                raise Busy(recovery=True)
            current.update(phase='running', last_child_id=child['id'])
            current.pop('child_id')
            write_json(self.path, current)
            self.record = current
            return child

    def cancel_unstarted(self, capability):
        """Revoke only an unused grant, under the same lock as child admission."""
        root = self.path.parent
        with child_lock(root):
            current, path, child = checked_child(root, capability)
            same_owner(current, self.record)
            if child['state'] != 'authorized':
                raise Busy(recovery=True)
            child.update(state='released', outcome='cancelled-before-start',
                         finished=datetime.now(timezone.utc).isoformat())
            write_json(path, child)


class ChildReservation(Reservation):
    def __init__(self, root, capability, path, record):
        super().__init__(path, record)
        self.root, self.capability = root, capability

    def complete(self, result_id=None):
        checked_child(self.root, self.capability)
        if result_id is not None:
            self.record_result(result_id)
        if self.record['kind'] == 'evaluation' and 'result_id' not in self.record:
            raise ValueError('Delegated evaluation needs a published saved result')
        self.drained = True

    def delegate(self, kind):
        raise ValueError('A delegated worker cannot delegate another worker')

    def resume(self, capability, *, worker_drained=False):
        raise ValueError('A delegated worker cannot resume a controller')

    def cancel_unstarted(self, capability):
        raise ValueError('A delegated worker cannot revoke host authorization')


@contextmanager
def delegated(root, kind, capability):
    directory = child_root(root)
    try:
        lock = worker_lock(directory)
        lock.__enter__()
    except ValueError:
        raise Busy() from None
    try:
        _parent, path, child = checked_child(root, capability)
        if child['kind'] != kind or child['state'] != 'authorized':
            raise Busy(recovery=True)
        child.update(state='active', pid=os.getpid(), worker_identity=worker_identity(os.getpid()),
                     started=datetime.now(timezone.utc).isoformat())
        write_json(path, child)
        slot = ChildReservation(root, capability, path, child)
        try:
            yield slot
        finally:
            # A lost parent/generation never permits an old child to publish a
            # lifecycle transition into its successor's state.
            checked_child(root, capability)
            child.update(state='released' if slot.drained else 'quarantined',
                         finished=datetime.now(timezone.utc).isoformat())
            write_json(path, child)
    finally:
        lock.__exit__(None, None, None)


@contextmanager
def reserve(home, kind, *, delegation=None):
    if kind not in {'controller', 'evaluation', 'proctor', 'log', 'maintenance'}:
        raise ValueError('Unknown host workload kind')
    root = storage.safe_local(Path(home) / '.local/state/argos-live/workload')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if delegation is not None:
        with delegated(root, kind, delegation) as slot:
            yield slot
        return
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
                  'pid': os.getpid(), 'worker_identity': worker_identity(os.getpid()),
                  'started': datetime.now(timezone.utc).isoformat(),
                  'state': 'active', 'phase': 'running'}
        write_json(path, record)
        reservation = Reservation(path, record)
        try:
            yield reservation
        finally:
            # No expiry heuristic: an orphan can still be doing inference.
            current = read_json(path)
            same_owner(current, record)
            current.update(state='released' if reservation.drained and current.get('phase') != 'delegated'
                           else 'quarantined', finished=datetime.now(timezone.utc).isoformat())
            if 'result_id' in reservation.record:
                current['result_id'] = reservation.record['result_id']
            write_json(path, current)
    finally:
        lock.__exit__(None, None, None)
