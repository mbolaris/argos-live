"""Owner-started dashboard controller for a managed Proctor improvement campaign."""
import copy
import threading
import time

from . import storage_view


class Refused(ValueError):
    """A campaign request could not safely start."""


MEASUREMENT_SUITES = frozenset({
    'quick', 'standard', 'challenge', 'tool-schema', 'tool-plan', 'tool-sequence',
    'documents-short', 'owner-recovery-decision'})


def validate_owner_task(owner_task, success_criteria):
    """Require a bounded owner task and an observable success measure."""
    if not isinstance(owner_task, str) or not isinstance(success_criteria, str):
        raise Refused('Describe the owner task and what a successful result looks like.')
    owner_task, success_criteria = owner_task.strip(), success_criteria.strip()
    if not owner_task or not success_criteria:
        raise Refused('Describe the owner task and what a successful result looks like.')
    if len(owner_task) > 1200 or len(success_criteria) > 1200:
        raise Refused('Keep the task and success measure under 1,200 characters each.')
    return owner_task, success_criteria


def validate_measurement_suite(measurement_suite):
    if measurement_suite in (None, ''):
        return None
    if not isinstance(measurement_suite, str) or measurement_suite not in MEASUREMENT_SUITES:
        raise Refused('Choose a listed measurement suite or select that none matches this task.')
    return measurement_suite


MESSAGES = {
    'idle': 'Ready when Argos is active, verified, and using confirmed storage.',
    'pausing': 'Pausing everyday Argos before the task-focused improvement campaign.',
    'practice': 'Separate signed practice is running. Its score is coaching feedback, not improvement evidence.',
    'campaign': 'Argos is running its bounded improvement campaign. Leave this dashboard open; no gain is claimed until the saved evidence is audited.',
    'restarting': 'Restarting Argos and checking that its selected model replies.',
    'completed': 'The campaign completed its evidence checks. Review its saved runs and audit before claiming any improvement.',
    'incomplete': 'The campaign stopped without all required evidence. Review the saved run IDs and missing checks.',
    'failed': 'The campaign did not finish, but Argos is back at its verified model.',
    'recovery-failed': 'Campaign work stopped, but Argos did not recover. Other workloads remain blocked.',
}


def safe_failure_code(error, stage):
    """Return a bounded diagnostic token without exposing exception text or paths."""
    if stage not in {'pausing', 'practice', 'campaign'}:
        stage = 'campaign'
    if isinstance(error, TimeoutError):
        cause = 'timeout'
    elif isinstance(error, PermissionError):
        cause = 'permission-denied'
    elif isinstance(error, FileNotFoundError):
        cause = 'component-missing'
    elif isinstance(error, OSError):
        cause = 'host-io-error'
    elif isinstance(error, (ValueError, KeyError, TypeError)):
        cause = 'invalid-state'
    else:
        cause = 'internal-error'
    return f'{stage}-{cause}'


def _public_host_observation(value):
    """Expose only the bounded, host-verified SSH state in a campaign result."""
    if not isinstance(value, dict) or value.get('schema') != 'argos-host-observation/1' or \
            value.get('system') != 'paired-ssh':
        return None
    if value.get('verified') is False and value.get('state') == 'unavailable':
        return {'schema': 'argos-host-observation/1', 'system': 'paired-ssh',
                'verified': False, 'state': 'unavailable',
                'failure_code': 'signed-status-unavailable'}
    fields = {'schema', 'system', 'verified', 'state', 'persistence_state', 'paired_policy_valid',
              'ssh_enabled', 'ssh_active', 'port22_listening', 'restart_eligible',
              'owner_approval_available', 'recovery_job_state', 'failure_code'}
    if set(value) != fields or value.get('verified') is not True or \
            not isinstance(value.get('state'), str) or value['state'] not in {'ready', 'not-ready'} or \
            not isinstance(value.get('persistence_state'), str) or \
            value['persistence_state'] not in {'verified', 'unverified'} or \
            not isinstance(value.get('recovery_job_state'), str) or \
            value['recovery_job_state'] not in {'idle', 'running', 'completed', 'failed', 'refused'}:
        return None
    bool_fields = ('paired_policy_valid', 'ssh_enabled', 'ssh_active', 'port22_listening',
                   'restart_eligible', 'owner_approval_available')
    if any(type(value.get(key)) is not bool for key in bool_fields):
        return None
    failure = value.get('failure_code')
    if failure is not None and (not isinstance(failure, str) or failure not in {
            'component-missing', 'preflight-unavailable', 'paired-policy-unready',
            'persistence-unverified', 'service-disabled', 'already-active', 'listener-conflict',
            'socket-conflict', 'restart-failed',
            'restart-not-verified', 'boot-changed'}):
        return None
    ready = (value['persistence_state'] == 'verified' and value['paired_policy_valid'] and
             value['ssh_enabled'] and value['ssh_active'] and value['port22_listening'] and
             failure is None)
    if value['state'] != ('ready' if ready else 'not-ready'):
        return None
    return {key: value[key] for key in fields}


class Controller:
    """Reserve shared assistant resources until Proctor is finished and Argos is verified again."""

    def __init__(self, startup, *, home=None, runner=None,
                 storage_snapshot=storage_view.snapshot,
                 ssh_recovery=None,
                 stop_timeout=180, ready_timeout=900, clock=time.monotonic, sleep=time.sleep):
        self.startup = startup
        self.home = startup.home if home is None else home
        self.runner = runner
        self.storage_snapshot = storage_snapshot
        self.ssh_recovery = ssh_recovery
        self.stop_timeout, self.ready_timeout = stop_timeout, ready_timeout
        self.clock, self.sleep = clock, sleep
        self.lock = threading.RLock()
        self.worker = None
        self.phase = 'idle'
        self.started = None
        self.finished = None
        self.model = None
        self.result = None
        self.progress = None
        self.failure_code = None
        self.failure_stage = None
        self.owner_task = None
        self.success_criteria = None
        self.measurement_suite = None
        self.recovery_target_phase = None
        self.storage_checked_at = None
        self.storage_is_safe = False
        self.closed = False

    @staticmethod
    def _public_result(value):
        if not isinstance(value, dict):
            return None
        campaign = value.get('campaign') if isinstance(value.get('campaign'), dict) else {}
        report_parts = []
        payloads = campaign.get('agent_summary')
        if isinstance(payloads, list):
            for payload in payloads[:8]:
                text = payload.get('text') if isinstance(payload, dict) else payload
                if isinstance(text, str) and text.strip():
                    report_parts.append(' '.join(text.split()))
        agent_report = '\n'.join(report_parts)[:1600] or None
        ids = campaign.get('saved_evaluation_ids', [])
        if not isinstance(ids, list):
            ids = []
        ids = [item for item in ids[:32] if isinstance(item, str) and len(item) <= 128]
        missing = campaign.get('missing', [])
        if not isinstance(missing, list):
            missing = []
        missing = [item for item in missing[:16] if isinstance(item, str) and len(item) <= 240]
        failure_code = value.get('failure_code')
        allowed_failure_codes = {
            f'{stage}-{cause}'
            for stage in ('pausing', 'practice', 'campaign')
            for cause in ('timeout', 'permission-denied', 'component-missing',
                          'host-io-error', 'invalid-state', 'internal-error')
        }
        if failure_code not in allowed_failure_codes:
            failure_code = None
        failure_stage = value.get('failure_stage')
        if failure_stage not in {'pausing', 'practice', 'campaign'}:
            failure_stage = None
        owner_task = value.get('owner_task')
        if not isinstance(owner_task, str) or len(owner_task) > 1200:
            owner_task = None
        success_criteria = value.get('success_criteria')
        if not isinstance(success_criteria, str) or len(success_criteria) > 1200:
            success_criteria = None
        measurement_suite = value.get('measurement_suite')
        if measurement_suite not in MEASUREMENT_SUITES:
            measurement_suite = None
        host_observation = _public_host_observation(campaign.get('host_observation'))
        public_campaign = {
            'status': campaign.get('status'),
            'outcome': campaign.get('outcome'),
            'audit_status': campaign.get('audit_status'),
            'controller_turns': campaign.get('controller_turns'),
            'missing': missing,
            'saved_evaluation_ids': ids,
            'agent_report': agent_report,
        }
        if host_observation is not None:
            public_campaign['host_observation'] = host_observation
        return {
            'status': value.get('status') if value.get('status') in {'completed', 'incomplete'} else 'incomplete',
            'owner_task': owner_task,
            'success_criteria': success_criteria,
            'measurement_suite': measurement_suite,
            'campaign': public_campaign,
            'failure_code': failure_code,
            'failure_stage': failure_stage,
        }

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            phase, result, progress, failure_code, failure_stage = (self.phase, copy.deepcopy(self.result),
                                                                   copy.deepcopy(self.progress), self.failure_code,
                                                                   self.failure_stage)
            started, finished, model, closed = self.started, self.finished, self.model, self.closed
            measurement_suite = self.measurement_suite
        try:
            assistant = self.startup.snapshot()
        except Exception:
            assistant = {}
        can_start = (not closed and not active and phase not in {'recovery-failed'} and
                     not getattr(self.startup, 'lab_active', False) and
                     assistant.get('active') is True and assistant.get('phase') == 'ready' and
                     assistant.get('model_reply_verified') is True)
        can_recover = (not closed and not active and phase == 'recovery-failed' and
                       getattr(self.startup, 'lab_active', False))
        storage_confirmed = self._persistent_storage_ready()
        can_start = can_start and storage_confirmed
        elapsed = None
        if started is not None:
            end = finished if finished is not None else self.clock()
            elapsed = max(0, int(end - started))
        message = MESSAGES.get(phase, 'Proctor campaign status unavailable.')
        if phase == 'idle' and not can_start:
            if not storage_confirmed:
                message = 'Confirm encrypted persistent storage for Argos models, profile, results, and settings.'
            elif assistant.get('phase') != 'ready' or assistant.get('model_reply_verified') is not True:
                message = 'Wait for Argos to reach ready with a verified model reply.'
            elif getattr(self.startup, 'lab_active', False):
                message = 'Another Argos workload is running. Wait for it to finish first.'
            else:
                message = MESSAGES['idle']
        elif phase == 'idle':
            message = 'Ready. Starting pauses everyday chat; Argos resumes after the model reply is verified.'
        if phase == 'incomplete' and isinstance(result, dict):
            campaign_result = result.get('campaign')
            if (isinstance(campaign_result, dict) and
                    campaign_result.get('outcome') == 'task-not-measured'):
                message = ('No task-specific measurement was run. Review the diagnostic report and '
                           'missing evidence below; no score or improvement is claimed.')
        if phase == 'failed' and failure_code:
            stage = failure_stage or 'campaign'
            message = f'Proctor {stage} stopped ({failure_code}); Argos is back at its verified model.'
        return {
            'available': True, 'active': active, 'phase': phase, 'message': message,
            'can_start': can_start, 'can_recover': can_recover,
            'elapsed_seconds': elapsed, 'model': model,
            'measurement_suite': measurement_suite,
            'failure_code': failure_code, 'failure_stage': failure_stage,
            'result': result, 'progress': progress,
            'assistant_phase': assistant.get('phase'), 'assistant_ready': assistant.get('phase') == 'ready',
            'storage_confirmed': storage_confirmed,
        }

    def start(self, owner_task=None, success_criteria=None, measurement_suite=None):
        owner_task, success_criteria = validate_owner_task(owner_task, success_criteria)
        measurement_suite = validate_measurement_suite(measurement_suite)
        with self.startup.lock, self.lock:
            if self.closed:
                raise Refused('The Proctor campaign controller is closed.')
            if self.worker is not None and self.worker.is_alive():
                raise Refused('A Proctor campaign is already running.')
            if getattr(self.startup, 'lab_active', False):
                raise Refused('Another Argos workload is already running.')
            assistant = self.startup.snapshot()
            if (assistant.get('phase') != 'ready' or assistant.get('active') is not True or
                    assistant.get('model_reply_verified') is not True):
                raise Refused('Start Argos and wait for its verified reply before starting Proctor.')
            if not self._persistent_storage_ready(fresh=True):
                raise Refused('Confirm encrypted persistent storage for Argos models, profile, results, and settings.')
            self.model = assistant.get('model')
            self.owner_task = owner_task
            self.success_criteria = success_criteria
            self.measurement_suite = measurement_suite
            self.result = None
            self.progress = {'phase': 'campaign', 'stage': 'starting'}
            self.failure_code = None
            self.failure_stage = None
            self.recovery_target_phase = None
            self.started = self.clock()
            self.finished = None
            self.phase = 'pausing'
            self.startup.lab_active = True
            self.startup.chat_claimed = True
            self.startup.stop()
            self.worker = threading.Thread(target=self._run, daemon=True, name='argos-proctor-campaign')
            self.worker.start()
            return self.snapshot()

    def _persistent_storage_ready(self, *, fresh=False):
        now = self.clock()
        with self.lock:
            if (not fresh and self.storage_checked_at is not None and
                    now - self.storage_checked_at < 10):
                return self.storage_is_safe
        safe = False
        try:
            view = self.storage_snapshot(self.home)
            locations = view.get('locations', []) if isinstance(view, dict) else []
            by_key = {item.get('key'): item.get('backing') for item in locations
                      if isinstance(item, dict)}
            required = ('models', 'profile', 'results', 'settings')
            safe = bool(isinstance(view, dict) and view.get('confirmed') is True and all(
                isinstance(by_key.get(key), dict) and by_key[key].get('encrypted') is True and
                by_key[key].get('persistent') is True for key in required))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            safe = False
        with self.lock:
            self.storage_checked_at = now
            self.storage_is_safe = safe
        return safe

    def recover(self):
        """Retry assistant startup while retaining the reservation after a failed recovery."""
        with self.startup.lock, self.lock:
            if self.closed:
                raise Refused('The Proctor campaign controller is closed.')
            if self.worker is not None and self.worker.is_alive():
                raise Refused('The current Proctor or assistant recovery is still running.')
            if self.phase != 'recovery-failed' or not getattr(self.startup, 'lab_active', False):
                raise Refused('No supported assistant recovery retry is pending.')
            self.phase = 'restarting'
            self.failure_code = None
            self.failure_stage = None
            self.worker = threading.Thread(target=self._retry_recovery, daemon=True,
                                           name='argos-proctor-recovery')
            self.worker.start()
            return self.snapshot()

    def _retry_recovery(self):
        failed = False
        try:
            self._ensure_ready()
        except Exception:
            failed = True
        with self.startup.lock, self.lock:
            if failed:
                self.startup.lab_active = True
                self.failure_code = 'assistant-recovery-failed'
                self.phase = 'recovery-failed'
            else:
                self.startup.lab_active = False
                self.phase = self.recovery_target_phase or 'failed'
                self.recovery_target_phase = None
                self.failure_code = None
                self.owner_task = None
                self.success_criteria = None
                self.measurement_suite = None
                self.finished = self.clock()

    def _set_phase(self, phase):
        if phase not in {'practice', 'campaign'}:
            return
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                self.phase = phase
                if self.progress is None or self.progress.get('phase') != phase:
                    self.progress = {'phase': phase, 'stage': 'starting'}

    def _set_progress(self, event):
        """Expose only bounded host progress fields, never agent text or tool payloads."""
        if (not isinstance(event, dict) or not isinstance(event.get('phase'), str) or
                event.get('phase') not in {'practice', 'campaign'}):
            return
        phase, stage = event['phase'], event.get('stage')
        allowed_stages = {'starting', 'turn-start', 'turn-finished'}
        if not isinstance(stage, str) or stage not in allowed_stages:
            return
        value = {'phase': phase, 'stage': stage}
        if phase == 'practice':
            state = event.get('state')
            if isinstance(state, str) and state in {'ACTIVE', 'BREAK', 'COMPLETED', 'ABANDONED', 'TIMED_OUT',
                                                     'INVALIDATED', 'starting', 'unavailable'}:
                value['state'] = state
        turn, total = event.get('turn'), event.get('total')
        if type(turn) is int and type(total) is int and 0 <= turn <= 32 and 1 <= total <= 32:
            value.update(turn=turn, total=total)
        count = event.get('saved_evaluation_count')
        if type(count) is int and 0 <= count <= 128:
            value['saved_evaluation_count'] = count
        audit_status = event.get('audit_status')
        if audit_status is None or (isinstance(audit_status, str) and
                                    audit_status in {'empty', 'verified', 'unverified', 'failed', 'pending'}):
            value['audit_status'] = audit_status
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                self.progress = value

    def _wait_stopped(self):
        deadline = self.clock() + self.stop_timeout
        while True:
            status = self.startup.snapshot()
            if not status.get('active') and status.get('phase') == 'stopped':
                return
            if not status.get('active') and status.get('phase') == 'failed':
                raise RuntimeError('assistant-stop-failed')
            if self.clock() >= deadline:
                raise TimeoutError('assistant-stop-timeout')
            self.sleep(0.1)

    def _ensure_ready(self):
        status = self.startup.snapshot()
        if status.get('phase') != 'ready' or status.get('model_reply_verified') is not True:
            if not status.get('active'):
                self.startup.start(_reserved=True)
        deadline = self.clock() + self.ready_timeout
        while True:
            status = self.startup.snapshot()
            if (status.get('active') is True and status.get('phase') == 'ready' and
                    status.get('model_reply_verified') is True):
                with self.startup.lock:
                    self.startup.chat_claimed = True
                return
            if status.get('phase') == 'failed' or self.clock() >= deadline:
                raise RuntimeError('assistant-recovery-failed')
            self.sleep(0.1)

    def _run(self):
        outcome_phase = 'failed'
        recovery_failed = False
        try:
            self._wait_stopped()
            with self.lock:
                self.phase = 'campaign'
            runner = self.runner
            if runner is None:
                from .proctor_service import run_improvement
                runner = run_improvement
            options = {'owner_task': self.owner_task, 'success_criteria': self.success_criteria,
                       'on_phase': self._set_phase, 'on_progress': self._set_progress}
            if self.ssh_recovery is not None:
                options['ssh_status_provider'] = self.ssh_recovery.proctor_status
                options['ssh_status_verifier'] = self.ssh_recovery.verify_proctor_status
            if self.measurement_suite is not None:
                options['measurement_suite'] = self.measurement_suite
            result = runner(self.home, **options)
            public_result = self._public_result(result)
            with self.lock:
                self.result = public_result
                if public_result:
                    self.failure_code = public_result.get('failure_code')
                    self.failure_stage = public_result.get('failure_stage')
            outcome_phase = 'completed' if public_result and public_result['status'] == 'completed' else 'incomplete'
        except Exception as error:
            with self.lock:
                self.failure_stage = self.phase if self.phase in {'pausing', 'practice', 'campaign'} else 'campaign'
                self.failure_code = safe_failure_code(error, self.failure_stage)
        finally:
            with self.lock:
                self.phase = 'restarting'
            try:
                self._ensure_ready()
            except Exception:
                recovery_failed = True
                self.failure_code = 'assistant-recovery-failed'
            with self.startup.lock, self.lock:
                if recovery_failed:
                    # Keep the shared reservation closed until the owner or a
                    # supported recovery path can restore the assistant.
                    self.startup.lab_active = True
                    self.phase = 'recovery-failed'
                    self.recovery_target_phase = outcome_phase
                else:
                    self.startup.lab_active = False
                    self.phase = outcome_phase
                self.owner_task = None
                self.success_criteria = None
                self.measurement_suite = None
                self.finished = self.clock()

    def close(self):
        with self.lock:
            self.closed = True
            worker = self.worker
        if worker is not None and worker is not threading.current_thread():
            # Do not close startup underneath a campaign that owns the shared
            # reservation. Let its bounded Proctor turns finish and recover.
            worker.join()
