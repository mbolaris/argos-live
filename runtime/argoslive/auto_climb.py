"""Durable Auto Climb coordinator for bounded, validated assistant self-improvement.

Owner-approved product contract:
- One button starts a bounded session after boot.
- Discloses the approved envelope (time, experiment count, download budget).
- Shows real observable work across shared foundation challenges.
- Proposes structured, reversible interventions with a 30-second server countdown.
- Supports Try now, Skip, Pause, and Stop overrides; opening details pauses countdown.
- Practice identifies candidate gains; independent held-out validation confirms generalization.
- Deterministic automatic Keep or byte-for-byte Restore.
- Stops honestly at a measured plateau or budget exhaustion.
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


def load_task_file(path):
    with path.open('rb') as f:
        return json.loads(f.read().decode('utf-8'))


def load_validation_tasks(path=VALIDATION_TASKS_PATH):
    return load_task_file(path)


class Controller:
    """Server-side Auto Climb coordinator owning session durability, countdown, and execution."""

    def __init__(self, startup, *, home=None, runner=None, clock=time.monotonic,
                 time_fn=time.time, sleep_fn=time.sleep, practice_path=PRACTICE_TASKS_PATH,
                 validation_path=VALIDATION_TASKS_PATH, candidates=None,
                 model_recommender=None, model_switcher=None):
        self.startup = startup
        self.home = Path(home or getattr(startup, 'home', Path.home()))
        self.runner = runner or getattr(startup, 'runner', None)
        self.clock = clock
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn
        self.practice_tasks = load_task_file(practice_path)
        self.validation_tasks = load_task_file(validation_path)
        self.candidate_pool = list(candidates) if candidates is not None else list(INSTRUCTION_CANDIDATES)
        self.model_recommender = model_recommender
        self.model_switcher = model_switcher

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
            # If interrupted during an in-flight mutation, restore safely and pause
            if phase in ('staging', 'retest', 'validate', 'countdown'):
                raw_before = data.get('raw_before')
                agents = agents_path(self.home)
                if raw_before is not None and agents.exists():
                    current = read_text(agents)
                    if current != raw_before:
                        write_text(agents, raw_before)
                data['phase'] = 'paused'
                data['message'] = 'Recovered from restart. Pending mutation restored; session paused.'
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
                'can_start': phase in ('idle', 'plateau', 'budget-exhausted', 'stopped', 'blocked'),
                'can_pause': active and phase not in ('paused', 'stopped', 'plateau', 'budget-exhausted', 'blocked'),
                'can_resume': phase == 'paused',
                'can_stop': active or phase in ('countdown', 'paused'),
                'can_override': phase == 'countdown',
            }

    def start(self, envelope=None):
        """Start a new Auto Climb session within the approved envelope."""
        with self.startup.lock, self.lock:
            if self.closed:
                raise Refused('Auto Climb coordinator is closed')
            if (self.worker is not None and self.worker.is_alive()) or getattr(self.startup, 'lab_active', False):
                raise Refused('Another desktop workload is active')

            # Verify no pending external rollback exists
            status_val = self.startup.snapshot() if hasattr(self.startup, 'snapshot') else {}
            model_info = {'model': status_val.get('model', 'starter'), 'digest': status_val.get('digest')}

            merged_envelope = dict(DEFAULT_ENVELOPE)
            if envelope:
                for k, v in envelope.items():
                    if k in merged_envelope:
                        merged_envelope[k] = v

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
                'raw_before': raw_before,
                'fingerprint': fp,
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
            if not self.session or self.session.get('phase') in ('idle', 'stopped', 'plateau', 'budget-exhausted'):
                raise Refused('No active Auto Climb session to pause')
            self.pause_event.set()
            self.current_action_id = None
            self.session['phase'] = 'paused'
            self.session['message'] = 'Auto Climb paused. Resume whenever you are ready.'
            self._save_session()
            return self.snapshot()

    def resume(self):
        """Resume a paused Auto Climb session."""
        with self.startup.lock, self.lock:
            if not self.session or self.session.get('phase') != 'paused':
                raise Refused('Session is not paused')
            self.pause_event.clear()
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
            self.current_action_id = None
            self.session['phase'] = 'stopped'
            self.session['stopping_reason'] = 'Stopped by owner'
            self.session['message'] = 'Auto Climb stopped.'
            self._save_session()
            return self.snapshot()

    def close(self):
        """Shutdown coordinator and wait for worker thread."""
        with self.lock:
            self.closed = True
            self.stop_event.set()
            worker = self.worker
        if worker and worker.is_alive():
            worker.join(timeout=5)

    # -------------------------------------------------------------------------
    # Execution Engine
    # -------------------------------------------------------------------------

    def _run_session(self):
        session_start_time = self.clock()
        try:
            # 1. Assessment / Baseline check
            if not self.session.get('starting_level'):
                self.session['phase'] = 'assess'
                self.session['message'] = 'Assessing your AI’s current baseline on foundation challenges…'
                self._save_session()

                practice_baseline = self._run_task_suite('baseline', self.practice_tasks, 'practice')
                if self._should_stop():
                    return
                validation_baseline = self._run_task_suite('baseline', self.validation_tasks, 'validation')
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
                self._save_session()

            # Main experiment loop
            while not self._should_stop():
                # Check budgets before proposing
                if self._check_budget_exhaustion(session_start_time):
                    break

                # 2. Select next candidate
                candidate = self._select_next_candidate()
                if candidate is None:
                    # No candidates remaining -> Plateau!
                    self.session['phase'] = 'plateau'
                    self.session['stopping_reason'] = 'Plateau within this session’s tested options: all evaluated.'
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

                # Release lab_active during countdown so UI/reconnect remains responsive
                with self.lock:
                    self.startup.lab_active = False

                countdown_result = self._await_countdown(action_id)
                with self.lock:
                    self.startup.lab_active = True

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

                # 4. Countdown passed or Try Now clicked -> Execute experiment!
                self._execute_experiment(candidate, session_start_time)

                # Check plateau policy after experiment
                if self.session.get('experiments_since_last_gain', 0) >= 3:
                    self.session['phase'] = 'plateau'
                    self.session['stopping_reason'] = 'Plateau within this session’s tested options: 3 consecutive experiments showed no validated gain.'
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

    def _check_budget_exhaustion(self, session_start_time):
        envelope = self.session.get('approved_envelope', DEFAULT_ENVELOPE)
        budgets = self.session.get('budgets_used', {})
        elapsed = int(self.clock() - session_start_time)
        budgets['duration_seconds'] = elapsed

        if budgets.get('completed_experiments', 0) >= envelope.get('max_experiments', 6):
            self.session['phase'] = 'budget-exhausted'
            self.session['stopping_reason'] = f'Session limit reached: {envelope.get("max_experiments")} experiments completed.'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return True

        if elapsed >= envelope.get('max_duration_seconds', 3600):
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

    def _execute_experiment(self, candidate, session_start_time):
        """Reversibly stage candidate, retest, validate, and Keep or Restore."""
        kind = candidate.get('kind', 'instruction')
        raw_before = read_text(agents_path(self.home)) or ''
        fp_before = fingerprint(self.home)

        # 1. Stage change
        self.session['phase'] = 'stage'
        self.session['message'] = f'Staging: {candidate["title"]}…'
        self._save_session()

        if kind == 'instruction':
            change_id = candidate['change_id']
            raw_after = staged(raw_before, change_id)
            write_text(agents_path(self.home), raw_after)
            self._restart_assistant()
        elif kind == 'model':
            # AC3 model switch
            if self.model_switcher:
                self.model_switcher(candidate['tag'])
                self._restart_assistant()

        # 2. Retest practice challenges
        self.session['phase'] = 'retest'
        self.session['message'] = f'Evaluating {candidate["title"]} on practice challenges…'
        self._save_session()

        practice_retest = self._run_task_suite('practice', self.practice_tasks, candidate['title'])
        if self._should_stop():
            if kind == 'instruction':
                write_text(agents_path(self.home), raw_before)
                self._restart_assistant()
            elif kind == 'model' and self.model_switcher:
                self.model_switcher(self.session['active_model']['model'])
                self._restart_assistant()
            return

        practice_comp = assistant_trial.compare(self.session['practice_baseline'], practice_retest)

        # Did practice improve?
        practice_improved = len(practice_comp['gains']) >= 2 and not practice_comp['regressions']

        validation_comp = None
        verdict = 'restored'
        decision_reason = ''

        if practice_improved:
            # 3. Independent Held-out Validation!
            self.session['phase'] = 'validate'
            self.session['message'] = 'Practice showed gains. Verifying on independent held-out challenges…'
            self._save_session()

            validation_retest = self._run_task_suite('validation', self.validation_tasks, candidate['title'])
            if self._should_stop():
                if kind == 'instruction':
                    write_text(agents_path(self.home), raw_before)
                    self._restart_assistant()
                elif kind == 'model' and self.model_switcher:
                    self.model_switcher(self.session['active_model']['model'])
                    self._restart_assistant()
                return

            validation_comp = assistant_trial.compare(self.session['validation_baseline'], validation_retest)

            validation_improved = len(validation_comp['gains']) >= 1 and not validation_comp['regressions']

            if validation_improved:
                verdict = 'kept'
                decision_reason = 'Validated gain on both practice challenges and independent held-out checks.'
            else:
                verdict = 'restored'
                decision_reason = 'Practice showed potential gains, but held-out validation did not confirm generalization.'
        else:
            verdict = 'restored'
            decision_reason = (f'Practice challenges did not meet win threshold ({len(practice_comp["gains"])} gains, '
                               f'{len(practice_comp["regressions"])} regressions; needs ≥2 gains, 0 regressions).')

        # 4. Keep or Restore
        self.session['phase'] = 'keep-or-restore'
        self.session['message'] = f'Decision: {verdict.upper()} ({decision_reason})'
        self._save_session()

        if verdict == 'kept':
            # Kept: update raw_before to new kept content
            self.session['raw_before'] = read_text(agents_path(self.home))
            self.session['experiments_since_last_gain'] = 0

            # Update current level
            passed_practice = sum(1 for r in practice_retest if r['passed'])
            passed_val = sum(1 for r in (validation_retest if validation_comp else self.session['validation_baseline']) if r['passed'])
            self.session['current_level'] = {
                'practice_passed': passed_practice,
                'practice_total': len(practice_retest),
                'validation_passed': passed_val,
                'validation_total': len(self.validation_tasks['tasks']),
                'label': f'{passed_practice}/{len(practice_retest)} practice · {passed_val}/{len(self.validation_tasks["tasks"])} validation',
            }
        else:
            # Restore byte-for-byte
            if kind == 'instruction':
                write_text(agents_path(self.home), raw_before)
                self._restart_assistant()
                restored = read_text(agents_path(self.home))
                if restored != raw_before:
                    raise ValueError('Restoration could not be verified byte-for-byte')
            elif kind == 'model':
                if self.model_switcher:
                    self.model_switcher(self.session['active_model']['model'])
                    self._restart_assistant()
            self.session['experiments_since_last_gain'] = self.session.get('experiments_since_last_gain', 0) + 1

        # Record experiment record in session history
        budgets = self.session.setdefault('budgets_used', {})
        budgets['completed_experiments'] = budgets.get('completed_experiments', 0) + 1
        budgets['duration_seconds'] = int(self.clock() - session_start_time)

        self.session.setdefault('completed_candidates', []).append(candidate['id'])
        self.session.setdefault('history', []).append({
            'experiment_index': budgets['completed_experiments'],
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

    def _run_task_suite(self, side, suite, label):
        """Run tasks through OpenClaw runner turn-by-turn with live streaming progress."""
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

            reply_text = ''
            elapsed = 0.0
            start_t = self.clock()
            if self.runner and hasattr(self.runner, 'turn'):
                reply_text = self.runner.turn(prompt_msg)
            elapsed = round(self.clock() - start_t, 2)

            score_res = score(task, passages, reply_text)
            outcome = {
                'id': task['id'],
                'kind': task['kind'],
                'passed': score_res['passed'],
                'checks': score_res['checks'],
                'reply': reply_text,
                'elapsed_seconds': elapsed,
            }
            results.append(outcome)
            self.current_receipts.append(outcome)

            self.current_progress['latest'] = outcome

        return results

    def _restart_assistant(self):
        """Restart OpenClaw assistant and wait for verified readiness."""
        if hasattr(self.startup, 'stop'):
            self.startup.stop()
        if hasattr(self.startup, 'start'):
            with self.startup.lock:
                self.startup.start(_reserved=True)
        # Bounded readiness check
        deadline = self.clock() + 30.0
        while self.clock() < deadline:
            snap = self.startup.snapshot() if hasattr(self.startup, 'snapshot') else {'active': True}
            if snap.get('active'):
                return
            self.sleep_fn(0.1)
