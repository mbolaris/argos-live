"""Owner-started dashboard controller for a managed Proctor improvement campaign."""
import copy
import threading
import time

from . import storage_view


class Refused(ValueError):
    """A campaign request could not safely start."""


MESSAGES = {
    'idle': 'Ready when Argos is active, verified, and using confirmed storage.',
    'pausing': 'Pausing everyday Argos before the signed practice run.',
    'practice': 'Signed practice is running. Its score is coaching feedback, not improvement evidence.',
    'campaign': 'Argos is running its bounded improvement campaign. Leave this dashboard open; no gain is claimed until the saved evidence is audited.',
    'restarting': 'Restarting Argos and checking that its selected model replies.',
    'completed': 'The campaign completed its evidence checks. Review its saved runs and audit before claiming any improvement.',
    'incomplete': 'The campaign stopped without all required evidence. Review the saved run IDs and missing checks.',
    'failed': 'The campaign did not finish, but Argos is back at its verified model.',
    'recovery-failed': 'Campaign work stopped, but Argos did not recover. Other workloads remain blocked.',
}


class Controller:
    """Reserve shared assistant resources until Proctor is finished and Argos is verified again."""

    def __init__(self, startup, *, home=None, runner=None,
                 storage_snapshot=storage_view.snapshot,
                 stop_timeout=180, ready_timeout=900, clock=time.monotonic, sleep=time.sleep):
        self.startup = startup
        self.home = startup.home if home is None else home
        self.runner = runner
        self.storage_snapshot = storage_snapshot
        self.stop_timeout, self.ready_timeout = stop_timeout, ready_timeout
        self.clock, self.sleep = clock, sleep
        self.lock = threading.RLock()
        self.worker = None
        self.phase = 'idle'
        self.started = None
        self.finished = None
        self.model = None
        self.result = None
        self.failure_code = None
        self.recovery_target_phase = None
        self.storage_checked_at = None
        self.storage_is_safe = False
        self.closed = False

    @staticmethod
    def _public_result(value):
        if not isinstance(value, dict):
            return None
        practice = value.get('practice') if isinstance(value.get('practice'), dict) else {}
        practice_result = practice.get('result') if isinstance(practice.get('result'), dict) else {}
        campaign = value.get('campaign') if isinstance(value.get('campaign'), dict) else {}
        ids = campaign.get('saved_evaluation_ids', [])
        if not isinstance(ids, list):
            ids = []
        ids = [item for item in ids[:32] if isinstance(item, str) and len(item) <= 128]
        missing = campaign.get('missing', [])
        if not isinstance(missing, list):
            missing = []
        missing = [item for item in missing[:16] if isinstance(item, str) and len(item) <= 240]
        return {
            'status': value.get('status') if value.get('status') in {'completed', 'incomplete'} else 'incomplete',
            'practice': {
                'status': practice.get('status'),
                'transcript_id': practice.get('transcript_id'),
                'calibration_status': practice.get('calibration_status'),
                'state': practice_result.get('state'),
                'correct': practice_result.get('correct'),
                'total': practice_result.get('total'),
                'unanswered': practice_result.get('unanswered'),
            },
            'campaign': {
                'status': campaign.get('status'),
                'outcome': campaign.get('outcome'),
                'audit_status': campaign.get('audit_status'),
                'controller_turns': campaign.get('controller_turns'),
                'missing': missing,
                'saved_evaluation_ids': ids,
            },
        }

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            phase, result, failure_code = self.phase, copy.deepcopy(self.result), self.failure_code
            started, finished, model, closed = self.started, self.finished, self.model, self.closed
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
        return {
            'available': True, 'active': active, 'phase': phase, 'message': message,
            'can_start': can_start, 'can_recover': can_recover,
            'elapsed_seconds': elapsed, 'model': model,
            'failure_code': failure_code, 'result': result,
            'assistant_phase': assistant.get('phase'), 'assistant_ready': assistant.get('phase') == 'ready',
            'storage_confirmed': storage_confirmed,
        }

    def start(self):
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
            self.result = None
            self.failure_code = None
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
                self.finished = self.clock()

    def _set_phase(self, phase):
        if phase not in {'practice', 'campaign'}:
            return
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                self.phase = phase

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
                self.phase = 'practice'
            runner = self.runner
            if runner is None:
                from .proctor_service import run_improvement
                runner = run_improvement
            result = runner(self.home, on_phase=self._set_phase)
            public_result = self._public_result(result)
            with self.lock:
                self.result = public_result
            outcome_phase = 'completed' if public_result and public_result['status'] == 'completed' else 'incomplete'
        except Exception as error:
            with self.lock:
                self.failure_code = ('storage-or-service-failed' if isinstance(error, OSError) else
                                     'proctor-run-failed')
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
                self.finished = self.clock()

    def close(self):
        with self.lock:
            self.closed = True
            worker = self.worker
        if worker is not None and worker is not threading.current_thread():
            # Do not close startup underneath a campaign that owns the shared
            # reservation. Let its bounded Proctor turns finish and recover.
            worker.join()
