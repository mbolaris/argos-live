"""Owner-started dashboard controller for a managed Proctor improvement campaign."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import threading
import time

from . import storage_view
from .pack_export import private_directory
from .pull_jobs import write_json
from .storage import safe_local

# The watch says so plainly when nothing has been heard for this long. These
# only label what the owner sees; the host timeouts still decide when work stops.
SLOW_ANSWER_SECONDS = 120
QUIET_SECONDS = 300
OWNER_ACTIONS = frozenset({'start', 'retry-recovery', 'ssh-recovery-approval'})
RECORD_LIMIT = 512 * 1024
WATCH_ID = re.compile(r'[a-f0-9]{32}')


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
             failure in (None, 'already-active'))
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
        self.watch_id = None
        self.started_at = None
        self.owner_actions = []
        self.last_event = None
        self.record_saved = None
        self.records_root = Path(self.home) / '.local/state/argos-live/proctor-watch'

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
            watch_id, started_at, last_event = self.watch_id, self.started_at, self.last_event
            owner_actions, record_saved = copy.deepcopy(self.owner_actions), self.record_saved
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
        answering_seconds = None
        if isinstance(progress, dict):
            question_started = progress.pop('_current_started_at', None)
            if isinstance(question_started, (int, float)):
                progress['current_elapsed_seconds'] = max(0, self.clock() - question_started)
                answering_seconds = progress['current_elapsed_seconds']
        watch = None
        if watch_id is not None:
            quiet = max(0, int(self.clock() - last_event)) if active and last_event is not None else None
            if not active:
                stall = None
            elif answering_seconds is not None and answering_seconds >= SLOW_ANSWER_SECONDS:
                stall = 'slow-answer'
            elif answering_seconds is None and quiet is not None and quiet >= QUIET_SECONDS:
                stall = 'quiet'
            else:
                stall = None
            watch = {'id': watch_id, 'started_at': started_at,
                     # The pinned OpenClaw CLI returns each answer only after the turn
                     # finishes. Partial text is shown only when the runner sends it.
                     'answer_streaming': bool(isinstance(progress, dict) and progress.get('answer_streaming')),
                     'seconds_since_event': quiet, 'stall': stall,
                     'slow_answer_seconds': SLOW_ANSWER_SECONDS, 'quiet_seconds': QUIET_SECONDS,
                     'owner_actions': owner_actions, 'owner_action_count': len(owner_actions),
                     'record_saved': record_saved}
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
            elif (isinstance(campaign_result, dict) and
                  campaign_result.get('outcome') == 'agent-turn-incomplete'):
                message = ('Argos did not finish its bounded read-only campaign turns. The unused '
                           'campaign reservation was released; no evaluation or improvement is claimed.')
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
            'watch': watch,
        }

    def note_owner_action(self, action):
        """Count an owner click this dashboard accepted while a campaign owns the reservation."""
        if action not in OWNER_ACTIONS:
            return
        with self.lock:
            if self.watch_id is None or self.started is None or self.finished is not None:
                return
            if len(self.owner_actions) < 32:
                self.owner_actions.append({'action': action,
                                           'at_seconds': max(0, int(self.clock() - self.started))})

    def _save_record(self):
        """Keep a bounded, already-public account of the finished campaign for later replay."""
        try:
            value = self.snapshot()
            watch = value.get('watch')
            # Called as the last act of the worker, after the final phase is set.
            if not isinstance(watch, dict):
                return
            progress = value.get('progress') if isinstance(value.get('progress'), dict) else {}
            rounds = [{key: run.get(key) for key in ('run_id', 'round_number', 'suite', 'suite_version',
                                                     'model', 'completed', 'total')}
                      for run in progress.get('evaluation_runs', []) if isinstance(run, dict)]
            current = progress.get('current') if isinstance(progress.get('current'), dict) else None
            interrupted = None
            if current and current.get('state') == 'interrupted':
                interrupted = {key: current.get(key) for key in ('run_id', 'item_id', 'category', 'question')}
                interrupted['elapsed_seconds'] = progress.get('current_elapsed_seconds')
            record = {
                'schema': 'argos-proctor-watch/1', 'id': watch['id'], 'started_at': watch['started_at'],
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'elapsed_seconds': value.get('elapsed_seconds'), 'phase': value.get('phase'),
                'model': value.get('model'), 'failure_code': value.get('failure_code'),
                'failure_stage': value.get('failure_stage'), 'result': value.get('result'),
                'rounds': rounds, 'campaign_steps': progress.get('campaign_steps', []),
                'interrupted': interrupted,
                'owner_actions': watch['owner_actions'], 'owner_action_count': watch['owner_action_count'],
            }
            if len(json.dumps(record).encode('utf-8')) > RECORD_LIMIT:
                record['campaign_steps'], record['result'] = [], None
            root = safe_local(self.records_root)
            if not root.exists():
                root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                private_directory(root)
            path = safe_local(root / (watch['id'] + '.json'))
            if not path.exists():
                write_json(path, record)
            with self.lock:
                if self.watch_id == watch['id']:
                    self.record_saved = True
        except (OSError, ValueError, TypeError):
            with self.lock:
                self.record_saved = False

    @staticmethod
    def _load_record(path):
        with path.open('rb') as stream:
            raw = stream.read(RECORD_LIMIT + 1)
        if len(raw) > RECORD_LIMIT:
            raise ValueError('watch-record-too-large')
        value = json.loads(raw.decode('utf-8'))
        if (not isinstance(value, dict) or value.get('schema') != 'argos-proctor-watch/1' or
                value.get('id') != path.stem):
            raise ValueError('watch-record-invalid')
        return value

    def history(self, limit=24):
        """Newest finished campaigns this dashboard recorded, including failed and interrupted ones."""
        try:
            root = safe_local(self.records_root)
            if not root.is_dir():
                return []
            paths = [path for path in root.glob('*.json') if WATCH_ID.fullmatch(path.stem)][:2048]
        except (OSError, ValueError):
            return []
        records = []
        for path in paths:
            try:
                value = self._load_record(path)
            except (OSError, ValueError, UnicodeError):
                continue
            result = value.get('result') if isinstance(value.get('result'), dict) else {}
            campaign = result.get('campaign') if isinstance(result.get('campaign'), dict) else {}
            row = {key: value.get(key) for key in (
                'id', 'started_at', 'finished_at', 'elapsed_seconds', 'phase', 'model', 'failure_code',
                'failure_stage', 'rounds', 'interrupted', 'owner_action_count')}
            row['outcome'] = campaign.get('outcome')
            records.append(row)
        records.sort(key=lambda item: str(item.get('finished_at') or ''), reverse=True)
        return records[:limit]

    def record(self, watch_id):
        if not isinstance(watch_id, str) or not WATCH_ID.fullmatch(watch_id):
            raise Refused('Choose a saved campaign watch ID.')
        path = safe_local(self.records_root / (watch_id + '.json'))
        if not path.is_file():
            raise Refused('Saved campaign watch not found.')
        return self._load_record(path)

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
            self.watch_id = secrets.token_hex(16)
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.owner_actions = [{'action': 'start', 'at_seconds': 0}]
            self.last_event = self.started
            self.record_saved = None
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
            if self.watch_id is not None and self.started is not None and len(self.owner_actions) < 32:
                self.owner_actions.append({'action': 'retry-recovery',
                                           'at_seconds': max(0, int(self.clock() - self.started))})
            self.last_event = self.clock()
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
        if not failed:
            self._save_record()

    def _set_phase(self, phase):
        if phase not in {'practice', 'campaign'}:
            return
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                self.last_event = self.clock()
                self.phase = phase
                if self.progress is None or self.progress.get('phase') != phase:
                    self.progress = {'phase': phase, 'stage': 'starting'}

    def _set_progress(self, event):
        """Expose bounded evaluation questions and final answers to the local live watch."""
        if (not isinstance(event, dict) or not isinstance(event.get('phase'), str) or
                event.get('phase') not in {'practice', 'campaign'}):
            return
        phase, stage = event['phase'], event.get('stage')
        allowed_stages = {'starting', 'turn-start', 'turn-finished',
                          'evaluation-question', 'evaluation-scored', 'evaluation-answer-partial',
                          'practice-question', 'practice-answer', 'campaign-step'}
        if not isinstance(stage, str) or stage not in allowed_stages:
            return
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                return
            previous = self.progress if isinstance(self.progress, dict) and self.progress.get('phase') == phase else {}
            if stage == 'evaluation-answer-partial':
                # Genuine visible-answer snapshots only: bounded, for the question
                # on the clock, and replaced by the scored answer when it lands.
                current = previous.get('current') if isinstance(previous.get('current'), dict) else None
                text = event.get('text')
                if (phase != 'campaign' or current is None or current.get('state') != 'thinking' or
                        current.get('run_id') != event.get('run_id') or
                        current.get('item_id') != event.get('item_id') or not isinstance(text, str)):
                    return
                value = copy.deepcopy(previous)
                value['current']['answer_partial'] = text[:8192]
                value['answer_streaming'] = True
                self.last_event = self.clock()
                self.progress = value
                return
            self.last_event = self.clock()
            value = copy.deepcopy(previous)
            value.update(phase=phase, stage=stage)
            if phase == 'practice':
                state = event.get('state')
                if isinstance(state, str) and state in {'ACTIVE', 'BREAK', 'COMPLETED', 'ABANDONED', 'TIMED_OUT',
                                                         'INVALIDATED', 'starting', 'unavailable'}:
                    value['state'] = state
                if stage in {'practice-question', 'practice-answer'}:
                    item_id = event.get('item_id')
                    if not isinstance(item_id, str) or not item_id or len(item_id) > 128:
                        return
                    question = event.get('question')
                    question = question[:6000] if isinstance(question, str) else ''
                    category = event.get('category')
                    category = category[:80] if isinstance(category, str) else ''
                    if stage == 'practice-question':
                        value['current'] = {'item_id': item_id, 'category': category,
                                            'question': question,
                                            'question_truncated': event.get('question_truncated') is True,
                                            'state': 'thinking'}
                        value['_current_started_at'] = self.clock()
                    else:
                        answer = event.get('answer')
                        answer = answer[:8192] if isinstance(answer, str) else ''
                        latency = event.get('latency_seconds')
                        latency = latency if isinstance(latency, (int, float)) and not isinstance(latency, bool) and latency >= 0 else None
                        item = {'item_id': item_id, 'category': category, 'question': question,
                                'question_truncated': event.get('question_truncated') is True,
                                'answer': answer, 'latency_seconds': latency,
                                'outcome': None, 'score': None}
                        items = value.get('practice_items')
                        if not isinstance(items, list):
                            items = []
                        if not any(existing.get('item_id') == item_id for existing in items):
                            items.append(item)
                        value['practice_items'] = items[-100:]
                        value['current'] = {**item, 'state': 'recorded'}
                        value['_current_started_at'] = None
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
            if phase == 'campaign' and stage == 'campaign-step':
                step_id, tool, status = event.get('step_id'), event.get('tool'), event.get('status')
                if (not isinstance(step_id, str) or not 1 <= len(step_id) <= 256 or
                        any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-'
                            for character in step_id) or
                        not isinstance(tool, str) or not isinstance(status, str) or
                        tool not in {'evaluation', 'evaluation_wait', 'inspect', 'audit', 'edit', 'resolve',
                                     'adopt', 'compare', 'log', 'ssh_status'} or
                        status not in {'running', 'completed', 'failed'}):
                    return
                steps = value.get('campaign_steps')
                if not isinstance(steps, list):
                    steps = []
                step = {'step_id': step_id, 'tool': tool, 'status': status}
                step_status = event.get('step_status')
                if isinstance(step_status, str) and step_status in {
                        'completed', 'running', 'changed', 'kept', 'restored', 'adopted', 'appended',
                        'empty', 'verified', 'failed', 'available', 'unavailable', 'cancel_requested',
                        'already_finished', 'compatible', 'incompatible', 'rejected'}:
                    step['step_status'] = step_status
                error_class = event.get('error_class')
                if isinstance(error_class, str) and len(error_class) <= 80:
                    step['error_class'] = error_class
                for key in ('suite', 'result_id', 'resolution', 'run_state'):
                    item = event.get(key)
                    if isinstance(item, str) and len(item) <= 160:
                        if key != 'result_id' or (len(item) == 32 and
                                                  all(char in '0123456789abcdef' for char in item)):
                            step[key] = item
                if event.get('coverage_complete') is True:
                    step['coverage_complete'] = True
                for key in ('completed', 'total', 'correct', 'format_errors'):
                    number = event.get(key)
                    if type(number) is int and 0 <= number <= 1000:
                        step[key] = number
                for key in ('passed', 'qualified_experiment', 'independent_gain_verified'):
                    if type(event.get(key)) is bool:
                        step[key] = event[key]
                existing = next((index for index, item in enumerate(steps)
                                 if isinstance(item, dict) and item.get('step_id') == step_id), None)
                if existing is None:
                    steps.append(step)
                else:
                    merged = dict(steps[existing])
                    merged.update(step)
                    steps[existing] = merged
                value['campaign_steps'] = steps[-32:]
            if phase == 'campaign' and stage in {'evaluation-question', 'evaluation-scored'}:
                run_id, item_id = event.get('run_id'), event.get('item_id')
                if (not isinstance(run_id, str) or len(run_id) > 64 or
                        not isinstance(item_id, str) or not item_id or len(item_id) > 128):
                    return
                question = event.get('question')
                question = question[:6000] if isinstance(question, str) else ''
                category = event.get('category')
                category = category[:80] if isinstance(category, str) else ''
                runs = value.get('evaluation_runs')
                if not isinstance(runs, list):
                    runs = []
                run = next((entry for entry in runs if entry.get('run_id') == run_id), None)
                if run is None:
                    last_round = runs[-1].get('round_number', len(runs)) if runs else 0
                    round_number = last_round + 1 if type(last_round) is int else len(runs) + 1
                    run = {'run_id': run_id, 'total': event.get('total'), 'completed': 0, 'items': [],
                           'round_number': round_number,
                           'suite': event.get('suite') if isinstance(event.get('suite'), str) else None,
                           'suite_version': event.get('suite_version')
                           if isinstance(event.get('suite_version'), str) else None,
                           'model': event.get('model') if isinstance(event.get('model'), str) else None}
                    runs.append(run)
                    if len(runs) > 4:
                        runs.pop(0)
                run['total'] = event.get('total') if type(event.get('total')) is int else run.get('total')
                if isinstance(event.get('suite'), str):
                    run['suite'] = event['suite'][:80]
                if isinstance(event.get('suite_version'), str):
                    run['suite_version'] = event['suite_version'][:160]
                if isinstance(event.get('model'), str):
                    run['model'] = event['model'][:160]
                if stage == 'evaluation-question':
                    value['current'] = {'run_id': run_id, 'item_id': item_id, 'category': category,
                                        'question': question,
                                        'question_truncated': event.get('question_truncated') is True,
                                        'state': 'thinking'}
                    value['_current_started_at'] = self.clock()
                else:
                    answer = event.get('answer')
                    answer = answer[:8192] if isinstance(answer, str) else ''
                    outcome = event.get('outcome')
                    outcome = outcome if outcome in {'pass', 'wrong_answer', 'format_error', 'unscored'} else None
                    latency = event.get('latency_seconds')
                    latency = latency if isinstance(latency, (int, float)) and not isinstance(latency, bool) and latency >= 0 else None
                    score = event.get('score')
                    score = score if type(score) in (int, float) and score in (0, 1) else None
                    item = {'run_id': run_id, 'item_id': item_id, 'category': category, 'question': question,
                            'question_truncated': event.get('question_truncated') is True,
                            'answer': answer, 'answer_truncated': event.get('answer_truncated') is True,
                            'outcome': outcome, 'latency_seconds': latency, 'score': score}
                    items = run.get('items') if isinstance(run.get('items'), list) else []
                    if not any(existing.get('item_id') == item_id for existing in items):
                        items.append(item)
                    run['items'] = items[-100:]
                    completed = event.get('completed')
                    if type(completed) is int and completed >= 0:
                        run['completed'] = completed
                    value['current'] = {**item, 'state': 'scored'}
                    value['_current_started_at'] = None
                value['evaluation_runs'] = runs
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
                if isinstance(self.progress, dict) and isinstance(self.progress.get('current'), dict) and \
                        self.progress['current'].get('state') == 'thinking':
                    current_started = self.progress.pop('_current_started_at', None)
                    if isinstance(current_started, (int, float)):
                        self.progress['current_elapsed_seconds'] = max(0, self.clock() - current_started)
                    self.progress['current']['state'] = 'interrupted'
                self.owner_task = None
                self.success_criteria = None
                self.measurement_suite = None
                self.finished = self.clock()
            self._save_record()

    def close(self):
        with self.lock:
            self.closed = True
            worker = self.worker
        if worker is not None and worker is not threading.current_thread():
            # Do not close startup underneath a campaign that owns the shared
            # reservation. Let its bounded Proctor turns finish and recover.
            worker.join()
