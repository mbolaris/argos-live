"""Owner-started local lap controller backed by host-owned evaluation jobs."""
from datetime import datetime, timezone
from pathlib import Path
import secrets
import threading
from copy import deepcopy

from .. import storage
from ..pull_jobs import read_json, write_json
from . import lap


class LapController:
    def __init__(self, home=None, *, jobs_factory=None):
        self.home = Path(home).absolute() if home is not None else Path.home().absolute()
        self.root = storage.safe_local(self.home / '.local/state/argos-live/shakedown-laps')
        self.path = storage.safe_local(self.root / 'current.json')
        self.jobs_factory = jobs_factory
        self.lock = threading.RLock()
        self.worker = None
        self.cancel_event = None
        self.record = None

    @staticmethod
    def _stamp():
        return datetime.now(timezone.utc).isoformat()

    def _persist(self):
        if self.record is not None:
            self.record['updated_at'] = self._stamp()
            write_json(self.path, self.record)

    def snapshot(self):
        with self.lock:
            if self.record is not None:
                return deepcopy(self.record)
        try:
            value = read_json(self.path)
            return value if isinstance(value, dict) else {'available': True, 'state': 'idle'}
        except (OSError, ValueError, TypeError):
            return {'available': True, 'state': 'idle'}

    def start(self, size='quick', suites=None):
        suites = tuple(suites) if suites is not None else lap.DEFAULT_FORMS
        plan = lap.build(size, suites)
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise ValueError('A Shakedown lap is already running')
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.record = {'available': True, 'lap_id': secrets.token_hex(16), 'size': size,
                           'state': 'running', 'outcome': None, 'complete': False,
                           'stage': 'starting', 'progress': None, 'steps': [],
                           'recovery_required': False, 'started_at': self._stamp()}
            self.cancel_event = threading.Event()
            self._persist()
            self.worker = threading.Thread(target=self._run, args=(plan,),
                                           name='argos-shakedown-lap', daemon=False)
            self.worker.start()
            return deepcopy(self.record)

    def _run(self, plan):
        try:
            from ..evaluation_jobs import Jobs
            jobs = self.jobs_factory(self.home) if self.jobs_factory else Jobs(self.home)

            def progress(event):
                with self.lock:
                    if 'step' in event:
                        step = event['step']
                        self.record['stage'] = f'{step["kind"]}:{step.get("suite", "speed")}'
                    if 'job' in event:
                        job = event['job']
                        self.record['progress'] = {key: job.get(key) for key in
                                                    ('status', 'completed', 'total')}
                    if event.get('phase') == 'step-finished':
                        self.record['steps'].append(event['result'])
                        self.record['progress'] = None
                    self._persist()

            result = lap.execute(plan, jobs, lap_id=self.record['lap_id'], cancel=self.cancel_event,
                                 on_update=progress)
            with self.lock:
                self.record.update(state='completed' if result['complete'] else result['outcome'],
                                   outcome=result['outcome'], complete=result['complete'],
                                   steps=result['steps'], stage='finished', progress=None,
                                   recovery_required=any(step['recovery_required'] for step in result['steps']))
                self._persist()
        except Exception as error:
            with self.lock:
                self.record.update(state='failed', outcome='failed', complete=False, stage='failed',
                                   error_category=type(error).__name__, progress=None)
                self._persist()

    def cancel(self):
        with self.lock:
            if self.worker is None or not self.worker.is_alive() or self.cancel_event is None:
                raise ValueError('No Shakedown lap is running')
            self.cancel_event.set()
            self.record['stage'] = 'cancelling'
            self._persist()
            return dict(self.record)
