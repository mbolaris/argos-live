"""Durable Auto Climb coordinator for bounded, validated assistant self-improvement.

Owner-approved product contract:
- One button starts a bounded session after boot.
- Discloses the approved envelope (time, experiment count, download budget).
- Shows real observable work across shared foundation challenges.
- Proposes structured, reversible interventions with a 30-second server countdown.
- Supports Try now, Skip, Pause, and Stop overrides; opening details pauses countdown.
- Practice identifies candidate gains; independent held-out validation confirms generalization.
- Fresh validation exposure and confirmation policy: disjoint partitions, consumed on exposure.
- Rebased comparisons on verified current kept build; later regression cannot inherit earlier gains.
- Guarded mutations: journal before write, owner-edit protection, verified Undo.
- Single worker ownership, cancellable child execution, cumulative budgets across Resume/reboot.
- Stops honestly at measured plateau (>= 3 non-improving AND all options evaluated), options exhausted, or budget exhaustion.
- Reuses OpenClaw runner, transactions, scoring, hardware probing, and recovery.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from . import assistant_trial, hw, storage
from .assistant_trial import (
    agents_path,
    changed_trial_files,
    fingerprint,
    fingerprint_matches,
    message,
    read_text,
    score,
    staged,
    write_text,
    CHANGE_BY_ID,
    CHANGES,
    Refused,
    TrialTurnError,
)
from .pull_jobs import read_json, write_json

SCHEMA = 'argos-auto-climb/1'
SESSION_REL_PATH = Path('.local/share/argos-live/auto-climb/session.json')

PRACTICE_TASKS_PATH = Path(__file__).with_name('data') / 'assistant-trials' / 'grounded-answers.json'
VALIDATION_TASKS_PATH = Path(__file__).with_name('data') / 'assistant-trials' / 'held-out-validation.json'

DEFAULT_ENVELOPE = {
    'max_duration_seconds': 3600,   # 60 minutes
    'max_experiments': 6,          # 6 completed experiments
    'max_model_downloads': 1,      # At most 1 model download
    'max_download_bytes': 8 * 1024 * 1024 * 1024,  # 8 GiB
    'permissions': 'none',         # No permission expansion
}

# Candidate instruction interventions
INSTRUCTION_CANDIDATES = [
    {
        'id': 'answer-first',
        'kind': 'instruction',
        'title': 'Answer first',
        'change': 'Add rule in AGENTS.md: Answer questions directly before adding detail.',
        'rationale': 'Improves answer directness on factual queries.',
        'cost': '0 MB download · ~2 min test',
        'verification': '8 practice challenges + 8 independent validation challenges',
        'change_id': 'answer-first',
    },
    {
        'id': 'quote-evidence',
        'kind': 'instruction',
        'title': 'Show the source',
        'change': 'Add rule in AGENTS.md: Back up document answers with one exact sentence from the source.',
        'rationale': 'Grounds factual answers in explicit cited source sentences.',
        'cost': '0 MB download · ~2 min test',
        'verification': '8 practice challenges + 8 independent validation challenges',
        'change_id': 'quote-evidence',
    },
    {
        'id': 'honest-uncertainty',
        'kind': 'instruction',
        'title': 'Be honest when missing',
        'change': 'Add rule in AGENTS.md: Say plainly when the provided text does not contain an answer.',
        'rationale': 'Prevents hallucination and guessing when documents are silent.',
        'cost': '0 MB download · ~2 min test',
        'verification': '8 practice challenges + 8 independent validation challenges',
        'change_id': 'honest-uncertainty',
    },
]


def validate_envelope(envelope):
    """Strictly validate approved session limits against specification rules."""
    if envelope is None:
        return dict(DEFAULT_ENVELOPE)
    if not isinstance(envelope, dict):
        raise Refused('Approved envelope must be a dictionary')
    merged = dict(DEFAULT_ENVELOPE)
    for k, v in envelope.items():
        if k not in merged:
            raise Refused(f'Unknown envelope limit: {k}')
        merged[k] = v
    if not isinstance(merged['max_duration_seconds'], int) or not (60 <= merged['max_duration_seconds'] <= 86400):
        raise Refused('max_duration_seconds must be an integer between 60 and 86400')
    if not isinstance(merged['max_experiments'], int) or not (1 <= merged['max_experiments'] <= 50):
        raise Refused('max_experiments must be an integer between 1 and 50')
    if not isinstance(merged['max_model_downloads'], int) or not (0 <= merged['max_model_downloads'] <= 5):
        raise Refused('max_model_downloads must be an integer between 0 and 5')
    if not isinstance(merged['max_download_bytes'], int) or not (0 <= merged['max_download_bytes'] <= 100 * 1024 * 1024 * 1024):
        raise Refused('max_download_bytes must be an integer between 0 and 100 GiB')
    if merged.get('permissions') != 'none':
        raise Refused('permissions must be "none"')
    return merged


def load_task_file(path):
    with path.open('rb') as f:
        return json.loads(f.read().decode('utf-8'))


def load_validation_tasks(path=VALIDATION_TASKS_PATH):
    return load_task_file(path)


def load_validation_partitions(path=VALIDATION_TASKS_PATH):
    data = load_task_file(path)
    if 'partitions' in data and isinstance(data['partitions'], list):
        return data['partitions']
    # Fallback to single partition
    return [{
        'id': 'val-p1',
        'passages': data.get('passages', {}),
        'tasks': data.get('tasks', []),
    }]


class Controller:
    """Server-side Auto Climb coordinator owning session durability, countdown, and execution."""

    def __init__(self, startup, *, home=None, runner=None, clock=time.monotonic,
                 time_fn=time.time, sleep_fn=time.sleep, practice_path=PRACTICE_TASKS_PATH,
                 validation_path=VALIDATION_TASKS_PATH, candidates=None,
                 model_recommender=None, model_switcher=None):
        self.startup = startup
        self.home = Path(home or getattr(startup, 'home', Path.home()))
        self.clock = clock
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn
        self.practice_tasks = load_task_file(practice_path)
        self.validation_partitions = load_validation_partitions(validation_path)
        self.candidate_pool = list(candidates) if candidates is not None else list(INSTRUCTION_CANDIDATES)
        self.model_recommender = model_recommender
        self.model_switcher = model_switcher

        # Wire OpenClaw runner by default if not passed or not in startup
        self.runner = runner or getattr(startup, 'runner', None)
        if self.runner is None and self.home:
            self.runner = assistant_trial.OpenClawRunner(self.home)

        self.cancel_event = threading.Event()
        if hasattr(self.runner, 'cancel_event'):
            self.runner.cancel_event = self.cancel_event

        self.lock = threading.RLock()
        self.worker = None
        self.closed = False

        self.session_path = storage.safe_local(self.home / SESSION_REL_PATH)
        self.session = self._load_or_recover_session()

        # Ephemeral runtime flags
        self.current_action_id = None
        self.countdown_deadline = 0.0
        self.pause_event = threading.Event()
        self.skip_event = threading.Event()
        self.try_now_event = threading.Event()
        self.stop_event = threading.Event()

        # Ephemeral watch streaming data
        self.current_progress = None
        self.current_receipts = []

    def _load_or_recover_session(self):
        """Recover pending session from disk, resolving pending mutations if any."""
        if not self.session_path.exists():
            return None
        try:
            data = read_json(self.session_path)
            if data.get('schema') != SCHEMA:
                return None
            phase = data.get('phase')
            mutation = data.get('mutation')

            if phase in ('staging', 'stage', 'retest', 'validate', 'countdown') or mutation:
                agents = agents_path(self.home)
                raw_before = mutation.get('raw_before') if mutation else data.get('raw_before')
                expected_after = mutation.get('expected_after') if mutation else None

                if agents.exists() and raw_before is not None:
                    current = read_text(agents)
                    clean_current = current.replace('\r\n', '\n') if isinstance(current, str) else ''
                    clean_expected = expected_after.replace('\r\n', '\n') if isinstance(expected_after, str) else None
                    clean_raw = raw_before.replace('\r\n', '\n') if isinstance(raw_before, str) else ''

                    if clean_expected is not None and clean_current == clean_expected:
                        # Staged change is present without owner edits: restore safely
                        write_text(agents, raw_before)
                        data['phase'] = 'paused'
                        data['message'] = 'Recovered from restart. Pending mutation restored; session paused.'
                        data.pop('mutation', None)
                    elif clean_current == clean_raw:
                        # Already at baseline
                        data['phase'] = 'paused'
                        data['message'] = 'Recovered from restart. Workspace matches baseline; session paused.'
                        data.pop('mutation', None)
                    else:
                        # Owner modified AGENTS.md while offline: DO NOT overwrite!
                        data['phase'] = 'blocked'
                        data['failure_code'] = 'owner-edit-conflict'
                        data['message'] = 'Owner edit detected in AGENTS.md; preserved without overwriting. Session blocked.'
                else:
                    data['phase'] = 'paused'
                    data['message'] = 'Recovered from restart. Workspace reset; session paused.'
                write_json(self.session_path, data)
            return data
        except (OSError, ValueError):
            return None

    def _save_session(self):
        """Durably persist current session state using atomic write."""
        with self.lock:
            if self.session is not None:
                self.session_path.parent.mkdir(parents=True, exist_ok=True)
                for attempt in range(5):
                    try:
                        write_json(self.session_path, self.session)
                        break
                    except (PermissionError, OSError):
                        if attempt == 4:
                            raise
                        time.sleep(0.05)

    def _restart_assistant(self, timeout=30):
        """Restart local assistant via startup controller and wait until verified ready."""
        if not self.startup:
            return
        try:
            self.startup.stop()
        except Exception:
            pass
        try:
            self.startup.start(_reserved=True)
        except TypeError:
            self.startup.start()
        start_t = self.clock()
        while self.clock() - start_t < timeout:
            snap = self.startup.snapshot()
            if snap.get('phase') == 'failed':
                raise RuntimeError(f'Assistant startup failed: {snap.get("failure")}')
            phase_ready = snap.get('phase') == 'ready'
            verified = snap.get('model_reply_verified') is True
            gateway_ready = snap.get('gateway_ready', phase_ready) is True
            if phase_ready and verified and gateway_ready:
                return
            self.sleep_fn(0.2)
        raise TimeoutError('Assistant restart timed out waiting to become verified ready')

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            sess = self.session or {}
            phase = sess.get('phase', 'idle')

            countdown_info = None
            if phase == 'countdown' and self.current_action_id:
                remaining = max(0, int(self.countdown_deadline - self.clock()))
                countdown_info = {
                    'action_id': self.current_action_id,
                    'seconds_remaining': remaining,
                    'total_seconds': sess.get('countdown_seconds', 30),
                    'proposal': sess.get('proposal'),
                }

            can_undo = bool(sess.get('initial_raw_before') is not None and
                            sess.get('current_kept_raw') != sess.get('initial_raw_before'))

            return {
                'available': True,
                'active': active,
                'phase': phase,
                'session_id': sess.get('session_id'),
                'approved_envelope': sess.get('approved_envelope', DEFAULT_ENVELOPE),
                'budgets_used': sess.get('budgets_used', {
                    'duration_seconds': 0,
                    'completed_experiments': 0,
                    'model_downloads': 0,
                    'download_bytes': 0,
                }),
                'active_model': sess.get('active_model'),
                'curriculum_version': sess.get('curriculum_version', 'argos-foundation/1'),
                'starting_level': sess.get('starting_level'),
                'current_level': sess.get('current_level'),
                'proposal': sess.get('proposal'),
                'countdown': countdown_info,
                'progress': self.current_progress,
                'receipts': list(self.current_receipts),
                'history': sess.get('history', []),
                'message': sess.get('message', ''),
                'stopping_reason': sess.get('stopping_reason'),
                'failure_code': sess.get('failure_code'),
                'can_start': phase in ('idle', 'plateau', 'options-exhausted', 'budget-exhausted', 'stopped', 'blocked'),
                'can_pause': active and phase not in ('paused', 'stopped', 'plateau', 'options-exhausted', 'budget-exhausted', 'blocked'),
                'can_resume': phase == 'paused',
                'can_stop': active or phase in ('countdown', 'paused'),
                'can_override': phase == 'countdown',
                'can_undo': can_undo and not active,
            }

    def start(self, envelope=None):
        """Start a new Auto Climb session within the approved envelope."""
        with self.startup.lock, self.lock:
            if self.closed:
                raise Refused('Auto Climb coordinator is closed')
            if (self.worker is not None and self.worker.is_alive()) or getattr(self.startup, 'lab_active', False):
                raise Refused('Another desktop workload is active')

            merged_envelope = validate_envelope(envelope)

            status_val = self.startup.snapshot() if hasattr(self.startup, 'snapshot') else {}
            model_info = {'model': status_val.get('model', 'starter'), 'digest': status_val.get('digest')}

            session_id = str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

            raw_before = read_text(agents_path(self.home)) or ''
            fp = fingerprint(self.home)

            self.session = {
                'schema': SCHEMA,
                'session_id': session_id,
                'created_at': now_iso,
                'approved_envelope': merged_envelope,
                'budgets_used': {
                    'duration_seconds': 0,
                    'completed_experiments': 0,
                    'model_downloads': 0,
                    'download_bytes': 0,
                },
                'active_model': model_info,
                'curriculum_version': 'argos-foundation/1',
                'phase': 'preflight',
                'message': 'Starting Auto Climb session…',
                'initial_raw_before': raw_before,
                'current_kept_raw': raw_before,
                'fingerprint': fp,
                'exposure_ledger': {
                    'consumed_partitions': [],
                },
                'history': [],
                'completed_candidates': [],
                'experiments_since_last_gain': 0,
                'starting_level': None,
                'current_level': None,
                'proposal': None,
                'countdown_seconds': 30,
                'stopping_reason': None,
                'failure_code': None,
            }
            self._save_session()

            self.pause_event.clear()
            self.cancel_event.clear()
            self.skip_event.clear()
            self.try_now_event.clear()
            self.stop_event.clear()
            self.current_progress = None
            self.current_receipts = []

            self.startup.lab_active = True
            self.worker = threading.Thread(target=self._run_session, daemon=True, name='auto-climb-coordinator')
            self.worker.start()
            return self.snapshot()

    def try_now(self, action_id):
        """Override countdown: proceed to the proposed action immediately."""
        with self.lock:
            if self.session.get('phase') != 'countdown' or self.current_action_id != action_id:
                raise Refused('That proposal is no longer active')
            self.try_now_event.set()
            self.session['phase'] = 'stage'
            self._save_session()
            return self.snapshot()

    def skip(self, action_id):
        """Override countdown: skip the proposed candidate and propose another."""
        with self.lock:
            if self.session.get('phase') != 'countdown' or self.current_action_id != action_id:
                raise Refused('That proposal is no longer active')
            self.current_action_id = None
            self.skip_event.set()
            return self.snapshot()

    def pause(self):
        """Pause Auto Climb (including during countdown or between steps)."""
        with self.lock:
            if not self.session or self.session.get('phase') in ('idle', 'stopped', 'plateau', 'options-exhausted', 'budget-exhausted', 'blocked'):
                raise Refused('No active Auto Climb session to pause')
            self.pause_event.set()
            self.cancel_event.set()
            self.current_action_id = None
            self.session['phase'] = 'paused'
            self.session['message'] = 'Auto Climb paused. Resume whenever you are ready.'
            self._save_session()
            if self.worker and self.worker.is_alive():
                self.worker.join(timeout=2.0)
            self.session['phase'] = 'paused'
            self._save_session()
            return self.snapshot()

    def resume(self):
        """Resume a paused Auto Climb session."""
        with self.startup.lock, self.lock:
            if not self.session or self.session.get('phase') != 'paused':
                raise Refused('Session is not paused')
            if self.worker is not None and self.worker.is_alive():
                self.worker.join(timeout=2.0)
                if self.worker.is_alive():
                    raise Refused('Previous Auto Climb worker is still terminating')

            self.pause_event.clear()
            self.cancel_event.clear()
            self.skip_event.clear()
            self.try_now_event.clear()
            self.stop_event.clear()

            self.session['phase'] = 'assess'
            self.session['message'] = 'Resuming Auto Climb…'
            self._save_session()

            self.startup.lab_active = True
            self.worker = threading.Thread(target=self._run_session, daemon=True, name='auto-climb-coordinator')
            self.worker.start()
            return self.snapshot()

    def stop(self):
        """Stop Auto Climb cleanly, restoring any in-flight mutation."""
        with self.lock:
            if not self.session or self.session.get('phase') in ('idle', 'stopped'):
                return self.snapshot()
            self.stop_event.set()
            self.cancel_event.set()
            self.current_action_id = None

            # If mutation in flight, safely restore
            mutation = self.session.get('mutation')
            if mutation:
                raw_before = mutation.get('raw_before')
                expected_after = mutation.get('expected_after')
                agents = agents_path(self.home)
                if agents.exists() and read_text(agents) == expected_after and raw_before is not None:
                    write_text(agents, raw_before)
                self.session.pop('mutation', None)

            self.session['phase'] = 'stopped'
            self.session['stopping_reason'] = 'Stopped by owner'
            self.session['message'] = 'Auto Climb stopped.'
            self._save_session()
            return self.snapshot()

    def undo(self):
        """Revert all kept changes from this session back to the initial baseline, protecting owner edits."""
        with self.startup.lock, self.lock:
            if not self.session:
                raise Refused('No Auto Climb session to undo')
            if self.worker is not None and self.worker.is_alive():
                raise Refused('Cannot undo while Auto Climb is actively running')
            initial_raw = self.session.get('initial_raw_before')
            if initial_raw is None:
                raise Refused('No initial baseline recorded for undo')
            current_kept = self.session.get('current_kept_raw', initial_raw)
            clean_initial = initial_raw.replace('\r\n', '\n') if isinstance(initial_raw, str) else ''
            clean_kept = current_kept.replace('\r\n', '\n') if isinstance(current_kept, str) else ''
            if clean_kept == clean_initial:
                raise Refused('No kept changes to undo')
            agents = agents_path(self.home)
            current = read_text(agents)
            clean_current = current.replace('\r\n', '\n') if isinstance(current, str) else ''
            if clean_current != clean_kept:
                raise Refused('Workspace was modified since Auto Climb; Undo blocked to preserve owner edits.')

            write_text(agents, initial_raw)
            self._restart_assistant()
            self.session['current_kept_raw'] = initial_raw
            self.session['phase'] = 'stopped'
            self.session['stopping_reason'] = 'Undone to initial baseline by owner.'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return self.snapshot()

    def close(self):
        """Shutdown coordinator and wait for worker thread."""
        with self.lock:
            self.closed = True
            self.stop_event.set()
            self.cancel_event.set()
            worker = self.worker
        if worker and worker.is_alive():
            worker.join(timeout=5)

    # -------------------------------------------------------------------------
    # Execution Engine
    # -------------------------------------------------------------------------

    def _run_session(self):
        slice_start_time = self.clock()
        try:
            # 1. Assessment / Baseline check
            if not self.session.get('starting_level'):
                self.session['phase'] = 'assess'
                self.session['message'] = 'Assessing your AI’s current baseline on foundation challenges…'
                self._save_session()

                practice_baseline = self._run_task_suite('baseline', self.practice_tasks, 'practice')
                if self._should_stop():
                    return

                # Baseline on partition 1 (initial reference)
                p1 = self.validation_partitions[0]
                validation_baseline = self._run_task_suite('baseline', p1, 'validation')
                if self._should_stop():
                    return

                passed_practice = sum(1 for r in practice_baseline if r['passed'])
                passed_validation = sum(1 for r in validation_baseline if r['passed'])

                baseline_level = {
                    'practice_passed': passed_practice,
                    'practice_total': len(practice_baseline),
                    'validation_passed': passed_validation,
                    'validation_total': len(validation_baseline),
                    'label': f'{passed_practice}/{len(practice_baseline)} practice · {passed_validation}/{len(validation_baseline)} validation',
                }
                self.session['starting_level'] = baseline_level
                self.session['current_level'] = baseline_level
                self.session['practice_baseline'] = practice_baseline
                self.session['validation_baseline'] = validation_baseline
                self.session['partition_baselines'] = {p1['id']: validation_baseline}
                self._save_session()

            # Main experiment loop
            while not self._should_stop():
                # Check budgets before selecting candidate
                if self._check_budget_exhaustion(slice_start_time):
                    break

                # 2. Select next candidate
                candidate = self._select_next_candidate()
                if candidate is None:
                    # Differentiate plateau vs options exhausted
                    if self.session.get('experiments_since_last_gain', 0) >= 3:
                        self.session['phase'] = 'plateau'
                        self.session['stopping_reason'] = 'Plateau within this session’s tested options: 3 consecutive experiments showed no validated gain and all options evaluated.'
                    else:
                        self.session['phase'] = 'options-exhausted'
                        self.session['stopping_reason'] = 'Options exhausted within approved session.'
                    self.session['message'] = self.session['stopping_reason']
                    self._save_session()
                    break

                # 3. Propose candidate and Countdown
                action_id = str(uuid.uuid4())
                with self.lock:
                    self.current_action_id = action_id
                    self.countdown_deadline = self.clock() + 30.0
                    self.session['phase'] = 'countdown'
                    self.session['proposal'] = candidate
                    self.session['message'] = f'Suggested next improvement: {candidate["title"]}'
                    self._save_session()

                countdown_result = self._await_countdown(action_id)

                if countdown_result == 'stopped':
                    break
                if countdown_result == 'paused':
                    break
                if countdown_result == 'skipped':
                    self.session.setdefault('completed_candidates', []).append(candidate['id'])
                    self.session['history'].append({
                        'candidate': candidate,
                        'verdict': 'skipped',
                        'reason': 'Skipped by owner during 30-second preview.',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    })
                    self._save_session()
                    continue

                # 4. Countdown passed or Try Now clicked -> Reserve experiment slot durably!
                budgets = self.session.setdefault('budgets_used', {})
                budgets['completed_experiments'] = budgets.get('completed_experiments', 0) + 1
                self._save_session()

                # Execute experiment!
                self._execute_experiment(candidate, slice_start_time)

                # Check plateau policy after experiment
                if self.session.get('experiments_since_last_gain', 0) >= 3:
                    # Check if all options evaluated
                    remaining = self._select_next_candidate()
                    if remaining is None:
                        self.session['phase'] = 'plateau'
                        self.session['stopping_reason'] = 'Plateau within this session’s tested options: 3 consecutive experiments showed no validated gain and all options evaluated.'
                        self.session['message'] = self.session['stopping_reason']
                        self._save_session()
                        break

        except Exception as error:
            import traceback
            traceback.print_exc()
            with self.lock:
                self.session['phase'] = 'blocked'
                self.session['failure_code'] = 'coordinator-error'
                self.session['message'] = f'Auto Climb stopped due to an error: {type(error).__name__}: {error}'
                self._save_session()
        finally:
            with self.lock:
                # Accumulate elapsed slice duration
                elapsed = max(0, int(self.clock() - slice_start_time))
                budgets = self.session.setdefault('budgets_used', {})
                budgets['duration_seconds'] = budgets.get('duration_seconds', 0) + elapsed
                self._save_session()
                self.startup.lab_active = False

    def _should_stop(self):
        return self.closed or self.stop_event.is_set() or self.pause_event.is_set()

    def _await_countdown(self, action_id):
        """Run countdown loop on server. Returns 'proceed', 'try-now', 'skipped', 'paused', or 'stopped'."""
        self.try_now_event.clear()
        self.skip_event.clear()

        while self.clock() < self.countdown_deadline:
            if self._should_stop():
                return 'stopped' if self.stop_event.is_set() else 'paused'
            if self.skip_event.is_set():
                return 'skipped'
            if self.try_now_event.is_set():
                return 'try-now'
            self.sleep_fn(0.1)

        if self._should_stop():
            return 'stopped' if self.stop_event.is_set() else 'paused'
        return 'proceed'

    def _check_budget_exhaustion(self, slice_start_time):
        envelope = self.session.get('approved_envelope', DEFAULT_ENVELOPE)
        budgets = self.session.get('budgets_used', {})
        current_slice = int(self.clock() - slice_start_time)
        total_duration = budgets.get('duration_seconds', 0) + current_slice

        if budgets.get('completed_experiments', 0) >= envelope.get('max_experiments', 6):
            self.session['phase'] = 'budget-exhausted'
            self.session['stopping_reason'] = f'Session limit reached: {envelope.get("max_experiments")} experiments completed.'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return True

        if total_duration >= envelope.get('max_duration_seconds', 3600):
            self.session['phase'] = 'budget-exhausted'
            self.session['stopping_reason'] = f'Session time budget reached ({envelope.get("max_duration_seconds") // 60} minutes).'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return True

        return False

    def _select_next_candidate(self):
        completed = set(self.session.get('completed_candidates', []))

        # Check model recommendation candidate first if available (AC3)
        if self.model_recommender and 'model-upgrade' not in completed:
            envelope = self.session.get('approved_envelope', DEFAULT_ENVELOPE)
            budgets = self.session.get('budgets_used', {})
            if budgets.get('model_downloads', 0) < envelope.get('max_model_downloads', 1):
                rec = self.model_recommender(self.home, envelope=envelope, budgets=budgets)
                if rec:
                    return rec

        for cand in self.candidate_pool:
            if cand['id'] not in completed:
                return cand
        return None

    def _get_next_fresh_partition(self, exclude=None):
        exclude = set(exclude or [])
        consumed = set(self.session.get('exposure_ledger', {}).get('consumed_partitions', []))
        for p in self.validation_partitions:
            if p['id'] not in consumed and p['id'] not in exclude:
                return p
        return None

    def _execute_experiment(self, candidate, slice_start_time):
        """Reversibly stage candidate, retest, validate on fresh partitions, and Keep or Restore."""
        kind = candidate.get('kind', 'instruction')
        raw_before = read_text(agents_path(self.home)) or ''
        fp_before = fingerprint(self.home)
        change_id = candidate.get('change_id')
        raw_after = staged(raw_before, change_id) if change_id else raw_before

        # Ensure fresh validation partitions are pre-evaluated on the clean current kept build (raw_before)
        p1 = self._get_next_fresh_partition()
        p2 = self._get_next_fresh_partition(exclude=[p1['id']] if p1 else [])
        if p1 is None or p2 is None:
            self.session['phase'] = 'blocked'
            self.session['stopping_reason'] = 'Fresh validation inventory exhausted; automatic promotion paused.'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return

        p_baselines = self.session.setdefault('partition_baselines', {})
        if p1['id'] not in p_baselines:
            p_baselines[p1['id']] = self._run_task_suite('baseline', p1, f'kept-{p1["id"]}')
        if p2['id'] not in p_baselines:
            p_baselines[p2['id']] = self._run_task_suite('baseline', p2, f'kept-{p2["id"]}')
        self._save_session()

        # 1. Journal mutation before write
        self.session['phase'] = 'stage'
        self.session['message'] = f'Staging: {candidate["title"]}…'
        self.session['mutation'] = {
            'kind': kind,
            'raw_before': raw_before,
            'expected_after': raw_after,
            'fingerprint': fp_before,
            'candidate_id': candidate['id'],
            'staged_at': datetime.now(timezone.utc).isoformat(),
        }
        self._save_session()

        if kind == 'instruction':
            write_text(agents_path(self.home), raw_after)
            self._restart_assistant()
        elif kind == 'model':
            if self.model_switcher:
                self.model_switcher(candidate['tag'])
                self._restart_assistant()

        # 2. Retest practice challenges
        self.session['phase'] = 'retest'
        self.session['message'] = f'Evaluating {candidate["title"]} on practice challenges…'
        self._save_session()

        practice_retest = self._run_task_suite('practice', self.practice_tasks, candidate['title'])
        if self._should_stop():
            self._restore_instruction(raw_before, raw_after)
            return

        # Compare against REBASED practice baseline (current kept build)
        practice_comp = assistant_trial.compare(self.session['practice_baseline'], practice_retest)
        practice_improved = len(practice_comp['gains']) >= 2 and not practice_comp['regressions']

        validation_comp = None
        verdict = 'restored'
        decision_reason = ''

        if practice_improved:
            # 3. Independent Fresh Held-Out Validation!
            self.session['phase'] = 'validate'
            self.session['message'] = 'Practice showed gains. Verifying on fresh independent validation partition…'
            self._save_session()

            # Consume partition 1
            self.session.setdefault('exposure_ledger', {}).setdefault('consumed_partitions', []).append(p1['id'])
            self._save_session()

            p1_baseline = p_baselines[p1['id']]
            val1_retest = self._run_task_suite('validation', p1, candidate['title'])
            if self._should_stop():
                self._restore_instruction(raw_before, raw_after)
                return

            comp1 = assistant_trial.compare(p1_baseline, val1_retest)
            val1_improved = len(comp1['gains']) >= 1 and not comp1['regressions']

            if not val1_improved:
                verdict = 'restored'
                decision_reason = 'Practice showed potential gains, but fresh validation partition 1 did not confirm generalization.'
                validation_comp = comp1
            else:
                # 4. Confirmation on a SECOND disjoint fresh partition!
                self.session.setdefault('exposure_ledger', {}).setdefault('consumed_partitions', []).append(p2['id'])
                self._save_session()

                p2_baseline = p_baselines[p2['id']]
                val2_retest = self._run_task_suite('validation', p2, candidate['title'])
                if self._should_stop():
                    self._restore_instruction(raw_before, raw_after)
                    return

                comp2 = assistant_trial.compare(p2_baseline, val2_retest)
                val2_improved = len(comp2['gains']) >= 1 and not comp2['regressions']

                if val2_improved:
                    verdict = 'kept'
                    decision_reason = 'Confirmed gain on both disjoint fresh validation partitions.'
                    validation_comp = comp2
                else:
                    verdict = 'restored'
                    decision_reason = 'Validation partition 1 showed gains, but disjoint confirmation partition did not confirm.'
                    validation_comp = comp2
        else:
            verdict = 'restored'
            decision_reason = (f'Practice challenges did not meet win threshold ({len(practice_comp["gains"])} gains, '
                               f'{len(practice_comp["regressions"])} regressions; needs ≥2 gains, 0 regressions).')

        # 5. Keep or Restore
        self.session['phase'] = 'keep-or-restore'
        self.session['message'] = f'Decision: {verdict.upper()} ({decision_reason})'
        self._save_session()

        if verdict == 'kept':
            # Rebase practice baseline onto the newly verified kept build!
            self.session['practice_baseline'] = practice_retest
            p_baselines[p1['id']] = val1_retest
            p_baselines[p2['id']] = val2_retest
            self.session['current_kept_raw'] = read_text(agents_path(self.home))
            self.session['raw_before'] = self.session['current_kept_raw']
            self.session['experiments_since_last_gain'] = 0
            self.session.pop('mutation', None)

            # Update current level metrics
            passed_practice = sum(1 for r in practice_retest if r['passed'])
            passed_val = sum(1 for r in val2_retest if r['passed']) if 'val2_retest' in locals() else 0
            self.session['current_level'] = {
                'practice_passed': passed_practice,
                'practice_total': len(practice_retest),
                'validation_passed': passed_val,
                'validation_total': len(val2_retest) if 'val2_retest' in locals() else 8,
                'label': f'{passed_practice}/{len(practice_retest)} practice · {passed_val}/8 validation',
            }
        else:
            self._restore_instruction(raw_before, raw_after)
            self.session['experiments_since_last_gain'] = self.session.get('experiments_since_last_gain', 0) + 1

        # Record experiment record in session history
        budgets = self.session.setdefault('budgets_used', {})
        self.session.setdefault('completed_candidates', []).append(candidate['id'])
        self.session.setdefault('history', []).append({
            'experiment_index': budgets.get('completed_experiments', 0),
            'candidate': candidate,
            'verdict': verdict,
            'reason': decision_reason,
            'practice_comparison': {
                'gains': practice_comp.get('gains', []),
                'regressions': practice_comp.get('regressions', []),
                'totals': practice_comp.get('totals', {}),
            },
            'validation_comparison': {
                'gains': validation_comp.get('gains', []) if validation_comp else [],
                'regressions': validation_comp.get('regressions', []) if validation_comp else [],
                'totals': validation_comp.get('totals', {}) if validation_comp else {},
            } if validation_comp else None,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        self._save_session()

    def _restore_instruction(self, raw_before, raw_after):
        """Guarded restoration checking for owner edits."""
        agents = agents_path(self.home)
        if not agents.exists():
            return
        current = read_text(agents)
        clean_current = current.replace('\r\n', '\n') if isinstance(current, str) else ''
        clean_after = raw_after.replace('\r\n', '\n') if isinstance(raw_after, str) else ''
        clean_before = raw_before.replace('\r\n', '\n') if isinstance(raw_before, str) else ''

        if clean_current == clean_after:
            write_text(agents, raw_before)
            restored = read_text(agents)
            if (restored.replace('\r\n', '\n') if isinstance(restored, str) else '') != clean_before:
                raise ValueError('Restoration could not be verified byte-for-byte')
            self.session.pop('mutation', None)
            self._restart_assistant()
        elif clean_current == clean_before:
            self.session.pop('mutation', None)
        else:
            # Owner edit detected! DO NOT overwrite!
            self.session['phase'] = 'blocked'
            self.session['failure_code'] = 'owner-edit-conflict'
            self.session['message'] = 'Owner edit detected during experiment; preserved without overwriting. Session blocked.'
            self._save_session()

    def _run_task_suite(self, side, suite, label):
        """Run tasks through OpenClaw runner turn-by-turn with live streaming progress."""
        if self.runner is None or not hasattr(self.runner, 'turn'):
            raise TrialTurnError('missing-runner')

        results = []
        passages = suite.get('passages', {})
        tasks = suite.get('tasks', [])
        total = len(tasks)

        self.current_receipts = []

        for idx, task in enumerate(tasks):
            if self._should_stop():
                break

            prompt_msg = message(task, passages)
            current_item = {
                'id': task['id'],
                'kind': task['kind'],
                'question': task.get('question') or task.get('message'),
                'passage': passages.get(task.get('passage')),
            }

            self.current_progress = {
                'side': side,
                'label': label,
                'done': idx,
                'total': total,
                'current': current_item,
            }

            start_t = self.clock()
            try:
                turn_res = self.runner.turn(prompt_msg)
            except TrialTurnError as exc:
                if self._should_stop() or (hasattr(exc, 'code') and exc.code == 'cancelled'):
                    break
                raise
            if isinstance(turn_res, dict):
                reply_text = turn_res.get('text', '')
                elapsed = turn_res.get('elapsed_seconds', round(self.clock() - start_t, 2))
            elif isinstance(turn_res, str):
                reply_text = turn_res
                elapsed = round(self.clock() - start_t, 2)
            else:
                raise TrialTurnError('invalid-reply')

            if not reply_text or not reply_text.strip():
                raise TrialTurnError('empty-reply')

            score_res = score(task, passages, reply_text)
            receipt = {
                'id': task['id'],
                'kind': task['kind'],
                'passed': score_res['passed'],
                'checks': score_res['checks'],
                'reply': {
                    'text': reply_text,
                    'elapsed_seconds': elapsed,
                    'session_id': getattr(self.runner, 'session_id', None) or f'turn-{idx}',
                },
                'elapsed_seconds': elapsed,
            }

            results.append(receipt)
            self.current_receipts.append(receipt)
            self.current_progress['latest'] = receipt
            self.current_progress['done'] = idx + 1

        return results
