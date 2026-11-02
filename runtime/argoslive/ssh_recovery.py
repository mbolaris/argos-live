"""Bounded, owner-approved recovery for the already-paired Argos SSH service."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import threading
import time

from . import ssh_boot
from .pack_export import private_directory
from .proctor.signing import Ed25519Signer, generate_key
from .pull_jobs import read_json, write_json

STATUS_SCHEMA = 'argos-ssh-status/1'
RECEIPT_SCHEMA = 'argos-ssh-recovery-receipt/1'
ROOT_STATUS = '/usr/local/sbin/argos-ssh-status'
ROOT_RESTART = '/usr/local/sbin/argos-ssh-restart'
FAILURE_CODES = frozenset({
    'component-missing', 'preflight-unavailable', 'paired-policy-unready',
    'persistence-unverified', 'service-disabled', 'already-active',
    'restart-failed', 'restart-not-verified', 'boot-changed',
})
ID = re.compile(r'^[a-f0-9]{32}$')
RECEIPT_MAX_AGE_SECONDS = 20


def _run(argv, *, timeout=10):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout)
    except FileNotFoundError:
        return None, 'component-missing'
    except subprocess.TimeoutExpired:
        return None, 'preflight-unavailable'
    if result.returncode:
        return result.stdout.strip(), 'preflight-unavailable'
    return result.stdout.strip(), None


def _port22_listening():
    output, error = _run(['/usr/bin/ss', '-ltnH'], timeout=5)
    if error:
        return False
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3].rsplit(':', 1)[-1] == '22':
            return True
    return False


def _boot_id():
    try:
        value = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    except OSError:
        return None
    return value if re.fullmatch(r'[0-9a-f-]{36}', value) else None


def privileged_snapshot():
    """Return only allowlisted facts; never include command output or local paths."""
    boot_id = _boot_id() or ''

    try:
        ssh_boot.ready()
        policy_valid = True
        gate_failure = None
    except FileNotFoundError:
        policy_valid, gate_failure = False, 'component-missing'
    except (OSError, subprocess.SubprocessError):
        policy_valid, gate_failure = False, 'preflight-unavailable'
    except (ValueError, KeyError, TypeError):
        policy_valid, gate_failure = False, 'paired-policy-unready'

    enabled_text, enabled_error = _run(['/usr/bin/systemctl', 'is-enabled', 'ssh.service'])
    active_text, active_error = _run(['/usr/bin/systemctl', 'is-active', 'ssh.service'])
    ssh_enabled = enabled_error is None and enabled_text == 'enabled'
    ssh_active = active_error is None and active_text == 'active'
    persistence = 'verified' if policy_valid else 'unverified'
    code = gate_failure
    if code is None and persistence != 'verified':
        code = 'persistence-unverified'
    if code is None and not ssh_enabled:
        code = 'service-disabled'
    port_listening = _port22_listening()
    eligible = bool(boot_id and persistence == 'verified' and policy_valid and ssh_enabled and
                    not ssh_active and not port_listening)
    return {
        'schema': STATUS_SCHEMA,
        'boot_id': boot_id or None,
        'persistence_state': persistence,
        'paired_policy_valid': policy_valid,
        'ssh_enabled': ssh_enabled,
        'ssh_active': ssh_active,
        'port22_listening': port_listening,
        'restart_eligible': eligible,
        'failure_code': code if code in FAILURE_CODES else None,
    }


def privileged_restart():
    """Start only an enabled, inactive SSH service after rechecking the boot gate."""
    before = privileged_snapshot()
    if before['persistence_state'] != 'verified':
        return {'status': 'refused', 'failure_code': 'persistence-unverified', 'before': before}
    if not before['paired_policy_valid']:
        return {'status': 'refused', 'failure_code': 'paired-policy-unready', 'before': before}
    if not before['ssh_enabled']:
        return {'status': 'refused', 'failure_code': 'service-disabled', 'before': before}
    if before['ssh_active'] or before['port22_listening']:
        return {'status': 'refused', 'failure_code': 'already-active', 'before': before}
    if not before['boot_id']:
        return {'status': 'refused', 'failure_code': 'preflight-unavailable', 'before': before}

    _output, error = _run(['/usr/bin/systemctl', 'start', 'ssh.service'], timeout=15)
    if error:
        return {'status': 'failed', 'failure_code': 'restart-failed', 'before': before}
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        current_boot = _boot_id()
        if current_boot != before['boot_id']:
            return {'status': 'failed', 'failure_code': 'boot-changed', 'before': before,
                    'after': {'boot_id': current_boot}}
        active_text, active_error = _run(['/usr/bin/systemctl', 'is-active', 'ssh.service'])
        if active_error is None and active_text == 'active' and _port22_listening():
            after = privileged_snapshot()
            if after.get('boot_id') != before['boot_id']:
                return {'status': 'failed', 'failure_code': 'boot-changed', 'before': before,
                        'after': after}
            if (after.get('persistence_state') == 'verified' and
                    after.get('paired_policy_valid') is True and after.get('ssh_enabled') is True and
                    after.get('ssh_active') is True and after.get('port22_listening') is True):
                return {'status': 'completed', 'failure_code': None, 'before': before, 'after': after}
            return {'status': 'failed', 'failure_code': 'restart-not-verified', 'before': before,
                    'after': after}
        time.sleep(0.2)
    return {'status': 'failed', 'failure_code': 'restart-not-verified', 'before': before}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _safe_root_status(value):
    if not isinstance(value, dict) or value.get('schema') != STATUS_SCHEMA:
        raise ValueError('SSH status receipt unavailable')
    allowed = {'schema', 'boot_id', 'persistence_state', 'paired_policy_valid', 'ssh_enabled',
               'ssh_active', 'port22_listening', 'restart_eligible', 'failure_code'}
    if set(value) != allowed:
        raise ValueError('SSH status receipt unavailable')
    if value['boot_id'] is not None and (not isinstance(value['boot_id'], str) or
                                         not re.fullmatch(r'[0-9a-f-]{36}', value['boot_id'])):
        raise ValueError('SSH status receipt unavailable')
    if type(value['persistence_state']) is not str or type(value['schema']) is not str:
        raise ValueError('SSH status receipt unavailable')
    if value['persistence_state'] not in {'verified', 'unverified'}:
        raise ValueError('SSH status receipt unavailable')
    if any(type(value[key]) is not bool for key in (
            'paired_policy_valid', 'ssh_enabled', 'ssh_active', 'port22_listening', 'restart_eligible')):
        raise ValueError('SSH status receipt unavailable')
    if value['failure_code'] is not None and value['failure_code'] not in FAILURE_CODES:
        raise ValueError('SSH status receipt unavailable')
    if value['restart_eligible'] != bool(value['boot_id'] and value['persistence_state'] == 'verified' and
            value['paired_policy_valid'] and value['ssh_enabled'] and not value['ssh_active'] and
            not value['port22_listening']):
        raise ValueError('SSH status receipt unavailable')
    return value


class Controller:
    """Dashboard-owned restart job, independent of any model turn or browser poll."""

    def __init__(self, home=None, *, status_provider=None, restart_provider=None,
                 runner=subprocess.run, clock=time.monotonic):
        self.home = Path.home() if home is None else Path(home)
        self.status_provider = status_provider or self._read_root_status
        self.restart_provider = restart_provider or self._run_root_restart
        self.runner, self.clock = runner, clock
        self.root = self.home / '.local/state/argos-live/ssh-recovery'
        self.lock = threading.RLock()
        self.worker = None
        self.job = None
        self.latest = None

    def _persistent(self):
        from . import storage_view
        view = storage_view.snapshot(self.home)
        locations = {item.get('key'): item.get('backing') for item in view.get('locations', [])
                     if isinstance(item, dict)}
        return bool(view.get('confirmed') is True and all(
            isinstance(locations.get(key), dict) and locations[key].get('encrypted') is True and
            locations[key].get('persistent') is True for key in ('models', 'profile', 'results', 'settings')))

    def _signer(self):
        if not self._persistent():
            return None
        try:
            if self.root.exists():
                info = self.root.lstat()
                if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or
                        (hasattr(os, 'getuid') and info.st_uid != os.getuid())):
                    return None
            else:
                private_directory(self.root)
            key = self.root / 'receipt-ed25519.pem'
            if not key.exists():
                generate_key(key)
            return Ed25519Signer(key)
        except (OSError, ValueError):
            return None

    def _read_root_status(self):
        try:
            result = self.runner(['sudo', '-n', ROOT_STATUS], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=50)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Bounded SSH status helper unavailable') from None
        if result.returncode:
            raise ValueError('Bounded SSH status helper unavailable')
        raw = result.stdout
        if len(raw) > 8192:
            raise ValueError('Bounded SSH status helper unavailable')
        return _safe_root_status(json.loads(raw))

    def _run_root_restart(self):
        try:
            result = self.runner(['sudo', '-n', ROOT_RESTART], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=100)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Bounded SSH recovery helper unavailable') from None
        if len(result.stdout) > 16384:
            raise ValueError('Bounded SSH recovery receipt unavailable')
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get('status') not in {'completed', 'failed', 'refused'}:
            raise ValueError('Bounded SSH recovery receipt unavailable')
        if (set(value) - {'status', 'failure_code', 'before', 'after'} or
                'failure_code' not in value or
                (value['failure_code'] is not None and value['failure_code'] not in FAILURE_CODES)):
            raise ValueError('Bounded SSH recovery receipt unavailable')
        for key in ('before', 'after'):
            if key in value:
                _safe_root_status(value[key])
        return value

    def _receipt(self, status, *, result=None, persist=False):
        signer = self._signer()
        payload = {'schema': RECEIPT_SCHEMA, 'receipt_id': None,
                   'created_utc': datetime.now(timezone.utc).isoformat(),
                   'status': status, 'operation': result}
        # Random IDs make each signed readiness approval single-use. The full
        # status remains inside the signed payload for freshness comparison.
        payload['receipt_id'] = secrets.token_hex(16)
        envelope = {'payload_json': _canonical(payload),
                    'signature': signer.sign(_canonical(payload).encode()) if signer else None,
                    'signature_status': 'signed' if signer else 'unavailable'}
        if persist and not signer:
            raise ValueError('Cannot persist an unsigned SSH recovery result')
        if signer and persist:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != 'nt' and self.root.stat().st_mode & 0o077:
                raise ValueError('SSH recovery records require private encrypted storage')
            write_json(self.root / (payload['receipt_id'] + '.json'), envelope)
        return {'payload': payload, 'signature': envelope['signature'],
                'signature_status': envelope['signature_status']}

    def snapshot(self):
        try:
            status = _safe_root_status(self.status_provider())
            receipt = self._receipt(status)
            with self.lock:
                self.latest = receipt
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            status = None
            receipt = None
            with self.lock:
                self.latest = None
        with self.lock:
            job = dict(self.job) if self.job else self._saved_job()
            active = self.worker is not None and self.worker.is_alive()
        return {'available': status is not None, 'status': status, 'receipt': receipt,
                'can_restart': bool(status and status.get('restart_eligible') and
                                    receipt and receipt.get('signature_status') == 'signed' and not active),
                'active': active, 'job': job}

    def _saved_job(self):
        path = self.root / 'latest-job.json'
        try:
            value = read_json(path)
            if value.get('schema') == 'argos-ssh-recovery-job/1' and value.get('state') in {
                    'running', 'completed', 'failed', 'refused'}:
                return value
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _save_job(self):
        write_json(self.root / 'latest-job.json', self.job)

    def restart(self, receipt_id, boot_id):
        if not isinstance(receipt_id, str) or not ID.fullmatch(receipt_id):
            raise ValueError('Fresh SSH receipt required')
        if not isinstance(boot_id, str) or not re.fullmatch(r'[0-9a-f-]{36}', boot_id):
            raise ValueError('Fresh SSH receipt required')
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise ValueError('An SSH recovery job is already running')
            receipt = self.latest
            if (not receipt or receipt.get('signature_status') != 'signed' or
                    receipt.get('payload', {}).get('receipt_id') != receipt_id):
                raise ValueError('Fresh SSH receipt required')
            payload = receipt['payload']
            try:
                created = datetime.fromisoformat(payload['created_utc'])
                age = (datetime.now(timezone.utc) - created).total_seconds()
            except (KeyError, TypeError, ValueError):
                raise ValueError('Fresh SSH receipt required') from None
            if age < -2 or age > RECEIPT_MAX_AGE_SECONDS:
                raise ValueError('Fresh SSH receipt required')
            approved_status = payload.get('status')
            if not isinstance(approved_status, dict) or approved_status.get('boot_id') != boot_id or not approved_status.get('restart_eligible'):
                raise ValueError('SSH restart is not eligible for the current verified boot')
            if not self._persistent():
                raise ValueError('Verified encrypted persistent storage is required')
            self.latest = None  # consume the owner approval before starting work
            self.job = {'schema': 'argos-ssh-recovery-job/1', 'job_id': secrets.token_hex(16),
                        'state': 'running', 'boot_id': boot_id,
                        'approved_receipt_id': receipt_id, 'receipt': None,
                        'failure_code': None}
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._save_job()
            self.worker = threading.Thread(target=self._run_restart, daemon=True,
                                           name='argos-ssh-recovery')
            self.worker.start()
            return dict(self.job)

    def _run_restart(self):
        try:
            result = self.restart_provider()
            status = _safe_root_status(self.status_provider())
            initial_boot = self.job['boot_id']
            if status.get('boot_id') != initial_boot:
                result = {'status': 'failed', 'failure_code': 'boot-changed'}
            elif result.get('status') == 'completed' and not (
                    status.get('persistence_state') == 'verified' and
                    status.get('paired_policy_valid') is True and status.get('ssh_enabled') is True and
                    status.get('ssh_active') is True and status.get('port22_listening') is True):
                result = {'status': 'failed', 'failure_code': 'restart-not-verified'}
            self.job['state'] = result['status']
            self.job['failure_code'] = result.get('failure_code')
            self.job['receipt'] = self._receipt(status, result=result, persist=True)
        except Exception:
            self.job['state'] = 'failed'
            self.job['failure_code'] = 'restart-failed'
        finally:
            try:
                self._save_job()
            except OSError:
                self.job['state'] = 'failed'
                self.job['failure_code'] = 'restart-failed'

    def close(self):
        with self.lock:
            worker = self.worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=105)


def privileged_main(action):
    """Entry point for root-owned fixed no-argument status/restart helpers."""
    if os.geteuid() != 0 or action not in {'status', 'restart'}:
        return 2
    try:
        value = privileged_snapshot() if action == 'status' else privileged_restart()
        print(json.dumps(value, sort_keys=True, separators=(',', ':')))
        return 0
    except Exception:
        code = 'restart-failed' if action == 'restart' else 'preflight-unavailable'
        if action == 'status':
            print(json.dumps({'schema': STATUS_SCHEMA, 'boot_id': None,
                'persistence_state': 'unverified', 'paired_policy_valid': False,
                'ssh_enabled': False, 'ssh_active': False, 'port22_listening': False,
                'restart_eligible': False, 'failure_code': code}, separators=(',', ':')))
            return 0
        print(json.dumps({'status': 'failed', 'failure_code': code}, separators=(',', ':')))
        return 1
