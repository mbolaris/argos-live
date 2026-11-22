"""Cooperating host workload admission; same-boot orphans are never auto-reclaimed.

This is exclusion, not an OS security boundary against an agent with shell access.
The persistent active marker intentionally outlives the OS lock after a crash;
only a verified kernel reboot can settle an orphaned reservation automatically.
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
from .pull_jobs import WorkerBusy, read_json, worker_lock, write_json

PROCESS_NONCE = secrets.token_hex(32)
BOOT_ID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def current_boot_id():
    """Return a verified Linux boot identity, or None when it is unavailable."""
    if sys.platform != 'linux':
        return None
    try:
        value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return None
    return value if BOOT_ID_PATTERN.fullmatch(value) else None


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


def _process_group_drained(pid):
    """Confirm the worker and every live member of its process group are absent."""
    proc = Path('/proc')
    if not proc.is_dir() or Path(f'/proc/{pid}').exists():
        return False
    try:
        entries = list(proc.iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
            if int(fields[2]) == pid and fields[0] not in {'Z', 'X'}:
                return False
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, ValueError, IndexError):
            return False
    return True

class Busy(ValueError):
    def __init__(self, recovery=False):
        self.recovery = recovery
        super().__init__('Previous workload needs recovery' if recovery else 'Another host workload is active')


def _evidence_complete_controller(root, prior, boot_id):
    """Fail-closed check for a drained, evidence-complete Proctor controller.

    A same-boot quarantine is normally permanent. This narrow exception exists
    for a controller whose terminal host evidence was written before an older
    runtime failed to release its reservation. It is deliberately stricter
    than a worker exit marker: saved evaluations, the comparison, final audit,
    session-bound drained turn, and child leases must all agree.
    """
    try:
        if (prior.get('state') != 'quarantined' or prior.get('kind') != 'controller' or
                prior.get('phase') != 'running' or prior.get('child_id') is not None or
                not isinstance(prior.get('id'), str) or
                not re.fullmatch(r'[a-f0-9]{32}', prior['id']) or
                type(prior.get('generation')) is not int or prior['generation'] < 1 or
                (prior.get('worker_identity') or {}).get('boot_id') != boot_id):
            return False

        worker = read_json(root / 'controller-worker.json')
        turn = read_json(root / 'controller-turn.json')
        parent_id, generation = prior['id'], prior['generation']
        if (worker.get('parent_id'), worker.get('generation'), worker.get('state'),
                worker.get('process_group_drained'), worker.get('sdk_end_observed'),
                worker.get('turn_outcome')) != (
                parent_id, generation, 'completed', True, True, 'incomplete-turn'):
            return False
        if (type(worker.get('returncode')) is not int or worker['returncode'] == 0 or
                type(worker.get('pid')) is not int or worker['pid'] <= 0 or
                Path(f'/proc/{worker["pid"]}').exists()):
            return False
        session_id, session_key = worker.get('session_id'), worker.get('session_key')
        if (not isinstance(session_id, str) or not session_id or
                not isinstance(session_key, str) or
                not session_key.startswith('agent:main:argos_proctor_improvement_')):
            return False
        if (turn.get('parent_id'), turn.get('generation'), turn.get('uncertain')) != (
                parent_id, generation, False):
            return False
        worker_turns = turn.get('worker_turns')
        if (not isinstance(worker_turns, list) or not worker_turns or
                any(not isinstance(item, dict) or item.get('turn') != index or
                    item.get('process_group_drained') is not True or
                    item.get('session_bound') is not True or
                    item.get('host_tool_failures') != 0
                    for index, item in enumerate(worker_turns, 1)) or
                worker_turns[-1].get('outcome') != 'incomplete-turn' or
                worker_turns[-1].get('returncode') != worker.get('returncode') or
                worker_turns[-1].get('turn') != worker.get('turn_number') or
                worker_turns[-1].get('turn') != len(worker_turns)):
            return False
        if (turn.get('run_id') != worker.get('run_id') or
                turn.get('session_id') != session_id or turn.get('ended') is not True or
                turn.get('session_key') != session_key or
                turn.get('host_tool_failures') not in ([], None, 0)):
            return False

        # No current-generation child may still be authorized, active, or
        # quarantined. The child lock is held by the caller during this check.
        children = root / 'child'
        if children.exists():
            for path in children.glob('*.json'):
                child = read_json(path)
                if (child.get('parent_id'), child.get('generation')) == (parent_id, generation):
                    if child.get('state') != 'released':
                        return False

        tools = turn.get('tools')
        if not isinstance(tools, list) or not tools:
            return False
        allowed = {'inspect', 'audit', 'evaluation', 'compare'}
        if any(not isinstance(item, dict) or item.get('kind') not in allowed for item in tools):
            return False
        evaluations = [item for item in tools if item.get('kind') == 'evaluation']
        ids = [item.get('result_id') for item in evaluations]
        if (len(evaluations) < 2 or len(set(ids)) != len(ids) or
                any(not isinstance(item.get('result_id'), str) or
                    not re.fullmatch(r'[a-f0-9]{32}', item['result_id']) or
                    item.get('state') != 'completed' or item.get('coverage_complete') is not True or
                    type(item.get('correct')) is not int or type(item.get('total')) is not int or
                    type(item.get('format_errors')) is not int or item['total'] < 1 or
                    not 0 <= item['correct'] <= item['total'] or
                    not 0 <= item['format_errors'] <= item['total'] for item in evaluations)):
            return False
        comparisons = [item for item in tools if item.get('kind') == 'compare']
        if not any(item.get('baseline_id') in ids and item.get('candidate_id') in ids and
                   item.get('baseline_id') != item.get('candidate_id') for item in comparisons):
            return False
        last_audit = max((index for index, item in enumerate(tools)
                          if item.get('kind') == 'audit'), default=-1)
        last_evidence = max((index for index, item in enumerate(tools)
                             if item.get('kind') in {'evaluation', 'compare'}), default=-1)
        if (last_audit <= last_evidence or tools[last_audit].get('host_final') is not True or
                tools[last_audit].get('status') != 'verified' or tools[last_audit].get('passed') is not True):
            return False

        # Re-open the saved outcomes through the normal result validator; the
        # compact controller ledger alone is not sufficient to release a lease.
        from .results import Store
        home = root.parents[3]
        store = Store(home / '.local/share/argos-live/results')
        for item in evaluations:
            result = store.load(item['result_id'])
            coverage = result.get('coverage', {})
            summary = result.get('summary', {})
            if (result.get('state') != 'completed' or result.get('kind') != 'ability' or
                    coverage.get('complete') is not True or coverage.get('total') != item['total'] or
                    coverage.get('completed') != item['total'] or
                    result.get('suite_version') != item.get('suite_version') or
                    summary.get('correct') != item['correct'] or
                    summary.get('format_errors') != item['format_errors']):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return False


def _recover_evidence_complete_controller(root, prior, boot_id):
    """Publish a recovery receipt before releasing a provably finished controller."""
    if (prior.get('state') != 'quarantined' or prior.get('kind') != 'controller' or
            prior.get('phase') != 'running' or prior.get('child_id') is not None or
            (prior.get('worker_identity') or {}).get('boot_id') != boot_id):
        return False
    # Match the established lock order: parent workload lock, then child lock.
    with child_lock(root):
        if not _evidence_complete_controller(root, prior, boot_id):
            return False
        receipt = {'schema': 'argos-workload-recovery/2', 'reservation_id': prior['id'],
                   'generation': prior['generation'], 'previous_state': prior['state'],
                   'previous_kind': prior['kind'], 'previous_phase': prior['phase'],
                   'result_id': prior.get('result_id'), 'previous_boot_id': boot_id,
                   'current_boot_id': boot_id,
                   'reason': 'evidence-complete-drained-controller',
                   'recovered': datetime.now(timezone.utc).isoformat()}
        recovered = storage.safe_local(root / 'recovered')
        recovered.mkdir(mode=0o700, parents=True, exist_ok=True)
        recovery_path = storage.safe_local(
            recovered / f"{receipt['generation']}-{receipt['reservation_id']}.json")
        if recovery_path.exists():
            saved_receipt = read_json(recovery_path)
            if any(saved_receipt.get(key) != value for key, value in receipt.items()
                   if key != 'recovered') or not isinstance(saved_receipt.get('recovered'), str):
                return False
            receipt = saved_receipt
        else:
            write_json(recovery_path, receipt)
        prior.update(state='released', phase='recovered-evidence-complete-controller',
                     recovered=receipt['recovered'], recovery_reason=receipt['reason'])
        write_json(root / 'reservation.json', prior)
        return True


def recover_owner_approved_readonly_incomplete_controller(home, watch_record, *, owner_pid=None):
    """Release one quarantined controller after its owner requests safe recovery.

    This narrow path is for a saved campaign whose completed host calls were
    limited to read-only inspect/audit steps, then exited with a session-bound
    incomplete turn. It never treats scores or capability evidence as complete.
    An explicit dashboard recovery request, exact same-boot process identities,
    a drained worker process group, and matching durable controller/watch
    records are all required before a recovery receipt reopens admission.
    """
    from datetime import datetime, timezone

    if not sys.platform == 'linux' or not isinstance(watch_record, dict):
        raise Busy(recovery=True)
    watch_id = watch_record.get('id')
    result = watch_record.get('result') if isinstance(watch_record.get('result'), dict) else {}
    campaign = result.get('campaign') if isinstance(result.get('campaign'), dict) else {}
    steps = watch_record.get('campaign_steps')
    simple_readonly = (isinstance(steps, list) and len(steps) == 1 and
                       isinstance(steps[0], dict) and steps[0].get('tool') == 'inspect')
    chain_readonly = (isinstance(steps, list) and 2 <= len(steps) <= 16 and
                      all(isinstance(step, dict) and step.get('tool') in {'inspect', 'audit'}
                          for step in steps) and
                      any(step.get('tool') == 'inspect' for step in steps) and
                      any(step.get('tool') == 'audit' for step in steps))
    if (not isinstance(watch_id, str) or not re.fullmatch(r'[a-f0-9]{32}', watch_id) or
            watch_record.get('phase') != 'incomplete' or
            watch_record.get('failure_code') != 'campaign-invalid-state' or
            result.get('status') != 'incomplete' or result.get('failure_code') != 'campaign-invalid-state' or
            campaign.get('status') != 'failed' or campaign.get('outcome') != 'campaign-runtime-failed' or
            campaign.get('saved_evaluation_ids') != [] or
            not (simple_readonly or chain_readonly) or
            any(step.get('status') != 'completed' or
                (step.get('tool') == 'inspect' and step.get('step_status') != 'completed') or
                (step.get('tool') == 'audit' and
                 (step.get('step_status') != 'verified' or step.get('passed') is not True)) or
                not isinstance(step.get('step_id'), str) or not step.get('step_id')
                for step in steps) or
            len({step['step_id'] for step in steps}) != len(steps)):
        raise Busy(recovery=True)

    root = storage.safe_local(Path(home).resolve(strict=True) / '.local/state/argos-live/workload')
    lock = worker_lock(root)
    try:
        lock.__enter__()
    except ValueError:
        raise Busy() from None
    try:
        prior = read_json(storage.safe_local(root / 'reservation.json'))
        current_boot = current_boot_id()
        owner_pid = os.getpid() if owner_pid is None else owner_pid
        prior_pid = prior.get('pid')
        if (not isinstance(current_boot, str) or
                prior.get('state') != 'quarantined' or prior.get('kind') != 'controller' or
                prior.get('phase') != 'running' or prior.get('child_id') is not None or
                prior.get('result_id') is not None or
                (prior.get('worker_identity') or {}).get('boot_id') != current_boot or
                type(prior_pid) is not int or prior_pid <= 0 or
                type(owner_pid) is not int or owner_pid <= 0 or
                type(prior.get('generation')) is not int or prior['generation'] < 1):
            raise Busy(recovery=True)
        try:
            prior_owner_identity = worker_identity(prior_pid)
        except (OSError, ValueError):
            prior_owner_identity = None
        if (prior_pid == owner_pid and prior_owner_identity != prior.get('worker_identity') or
                prior_pid != owner_pid and prior_owner_identity == prior.get('worker_identity')):
            raise Busy(recovery=True)

        parent_id, generation = prior['id'], prior['generation']
        worker = read_json(storage.safe_local(root / 'controller-worker.json'))
        failure = read_json(storage.safe_local(root / 'controller-failure.json'))
        turn = read_json(storage.safe_local(root / 'controller-turn.json'))
        worker_pid = worker.get('pid')
        session_id = worker.get('session_id')
        session_key = worker.get('session_key')
        response = failure.get('failure') if isinstance(failure.get('failure'), dict) else {}
        summary = response.get('worker_response') if isinstance(response.get('worker_response'), dict) else {}
        if (worker.get('parent_id'), worker.get('generation'), worker.get('state')) != (
                parent_id, generation, 'starting'):
            raise Busy(recovery=True)
        if (failure.get('parent_id'), failure.get('generation'),
                failure.get('worker_pid'), failure.get('session_id'), response.get('code'),
                response.get('returncode')) != (
                parent_id, generation, worker_pid, session_id, 'worker-exit', 1):
            raise Busy(recovery=True)
        if (summary.get('status'), summary.get('session_bound'), summary.get('error_kind')) != \
                ('error', True, 'incomplete_turn') or \
                not isinstance(session_id, str) or not session_id or \
                not isinstance(session_key, str) or \
                not session_key.startswith('agent:main:argos_proctor_improvement_'):
            raise Busy(recovery=True)
        if type(worker_pid) is not int or worker_pid <= 0:
            raise Busy(recovery=True)
        # The CLI process and every process in its session must be absent. This
        # is deliberately checked under the host workload lock before release.
        if not _process_group_drained(worker_pid):
            raise Busy(recovery=True)
        worker_turns = turn.get('worker_turns')
        if (turn.get('parent_id'), turn.get('generation'), turn.get('ended'), turn.get('uncertain'),
                turn.get('session_id'), turn.get('session_key'), turn.get('host_tool_failures')) != (
                parent_id, generation, True, False, session_id, session_key, []):
            raise Busy(recovery=True)
        tools = turn.get('tools')
        if (not isinstance(tools, list) or len(tools) != len(steps) or
                type(turn.get('host_tool_requests')) is not int or
                turn.get('host_tool_requests') not in range(1, len(tools) + 1) or
                not all(isinstance(item, dict) for item in tools) or
                [item.get('call_id') for item in tools] != [step.get('step_id') for step in steps] or
                [item.get('kind') for item in tools] != [step.get('tool') for step in steps]):
            raise Busy(recovery=True)
        if simple_readonly:
            if worker_turns != [] or turn.get('host_tool_requests') != 1:
                raise Busy(recovery=True)
        else:
            if (not isinstance(worker_turns, list) or not 1 <= len(worker_turns) <= 3 or
                    any(not isinstance(item, dict) or
                        item.get('outcome') != 'completed' or
                        item.get('response_status') != 'ok' or
                        item.get('process_group_drained') is not True or
                        item.get('session_bound') is not True or
                        item.get('host_tool_failures') != 0 or
                        type(item.get('host_tool_requests')) is not int or
                        item.get('host_tool_requests') < 1 or
                        type(item.get('returncode')) is not int or item.get('returncode') != 0
                        for item in worker_turns) or
                    [item.get('turn') for item in worker_turns] != list(range(1, len(worker_turns) + 1)) or
                    sum(item['host_tool_requests'] for item in worker_turns) > len(tools)):
                raise Busy(recovery=True)

        # No child reservation from this generation may still be active or
        # quarantined. Keep the parent-then-child lock order used by reserve().
        with child_lock(root):
            children = child_root(root)
            for path in children.glob('*.json'):
                child = read_json(storage.safe_local(path))
                if (child.get('parent_id'), child.get('generation')) == (parent_id, generation):
                    if child.get('state') != 'released':
                        raise Busy(recovery=True)
            receipt = {'schema': 'argos-workload-recovery/4' if chain_readonly else 'argos-workload-recovery/3',
                       'reservation_id': parent_id,
                       'generation': generation, 'previous_state': 'quarantined',
                       'previous_kind': 'controller', 'previous_phase': 'running',
                       'previous_boot_id': current_boot, 'current_boot_id': current_boot,
                       'watch_id': watch_id,
                       'reason': ('owner-approved-drained-readonly-chain-incomplete-turn'
                                  if chain_readonly else
                                  'owner-approved-drained-readonly-incomplete-turn'),
                       'recovered': datetime.now(timezone.utc).isoformat()}
            recovered = storage.safe_local(root / 'recovered')
            recovered.mkdir(mode=0o700, parents=True, exist_ok=True)
            recovery_path = storage.safe_local(
                recovered / f"{generation}-{parent_id}.json")
            if recovery_path.exists():
                saved = read_json(recovery_path)
                if any(saved.get(key) != value for key, value in receipt.items()
                       if key != 'recovered') or not isinstance(saved.get('recovered'), str):
                    raise Busy(recovery=True)
                receipt = saved
            else:
                write_json(recovery_path, receipt)
            prior.update(state='released', phase=('recovered-owner-approved-readonly-chain-incomplete'
                                                   if chain_readonly else
                                                   'recovered-owner-approved-readonly-incomplete'),
                         recovered=receipt['recovered'], recovery_reason=receipt['reason'])
            write_json(storage.safe_local(root / 'reservation.json'), prior)
        return {'status': 'recovered',
                'reason': ('drained-readonly-chain-incomplete-turn' if chain_readonly else
                           'drained-readonly-incomplete-turn'),
                'watch_id': watch_id}
    finally:
        lock.__exit__(None, None, None)


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
    # A surviving process/PID alone does not prove its reservation context is
    # still open (e.g. final marker publication failed). The parent's live OS
    # lock must also exclude this probe. A stale file is never an owner.
    probe = worker_lock(root)
    try:
        probe.__enter__()
    except WorkerBusy:
        pass
    else:
        probe.__exit__(None, None, None)
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
            identity = prior.get('worker_identity')
            prior_boot = identity.get('boot_id') if isinstance(identity, dict) else None
            this_boot = current_boot_id()
            recovered_controller = bool(
                isinstance(this_boot, str) and BOOT_ID_PATTERN.fullmatch(this_boot) and
                prior_boot == this_boot and
                _recover_evidence_complete_controller(root, prior, this_boot))
            if not recovered_controller and not (isinstance(prior_boot, str) and BOOT_ID_PATTERN.fullmatch(prior_boot) and
                    isinstance(this_boot, str) and BOOT_ID_PATTERN.fullmatch(this_boot) and
                    prior_boot != this_boot):
                raise Busy(recovery=True)
            if not recovered_controller:
                # A different kernel boot is a hard drainage boundary: no process
                # or in-flight local inference from the old boot can still exist.
                # Publish an immutable recovery receipt before releasing the old
                # generation; if either write fails, admission remains closed.
                receipt = {'schema': 'argos-workload-recovery/1',
                           'reservation_id': prior.get('id'),
                           'generation': prior.get('generation'),
                           'previous_state': prior.get('state'),
                           'previous_kind': prior.get('kind'),
                           'previous_phase': prior.get('phase'),
                           'result_id': prior.get('result_id'),
                           'previous_boot_id': prior_boot,
                           'current_boot_id': this_boot,
                           'reason': 'verified-kernel-reboot-boundary',
                           'recovered': datetime.now(timezone.utc).isoformat()}
                if not (isinstance(receipt['reservation_id'], str) and
                        re.fullmatch('[a-f0-9]{32}', receipt['reservation_id']) and
                        type(receipt['generation']) is int and receipt['generation'] > 0):
                    raise Busy(recovery=True)
                recovered = storage.safe_local(root / 'recovered')
                recovered.mkdir(mode=0o700, parents=True, exist_ok=True)
                recovery_path = storage.safe_local(
                    recovered / f"{receipt['generation']}-{receipt['reservation_id']}.json")
                if recovery_path.exists():
                    saved_receipt = read_json(recovery_path)
                    if any(saved_receipt.get(key) != value for key, value in receipt.items()
                           if key != 'recovered') or not isinstance(saved_receipt.get('recovered'), str):
                        raise Busy(recovery=True)
                    receipt = saved_receipt
                else:
                    write_json(recovery_path, receipt)
                prior.update(state='released', phase='recovered-after-reboot',
                             recovered=receipt['recovered'], recovery_reason=receipt['reason'])
                write_json(path, prior)
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
