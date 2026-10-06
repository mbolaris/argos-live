"""Desktop-owned quick baseline: pause chat, test fixed prompts, save, resume."""
import copy
import threading
import time

from . import bench_ability, bench_speed, doc_trial
from .ollama import Cancelled
from .results import Store


# Each plan lists (phase, runner attribute, options). Plans are fixed so a later
# run of the same plan on another model is a matched, comparable measurement.
PLANS = {'baseline': (('speed', 'speed', {'sizes': ('short',)}), ('ability', 'ability', {'suite': 'quick'})),
         'documents': (('speed', 'speed', {'sizes': ('short', 'medium')}), ('documents', 'documents', {}))}


class Controller:
    budget_seconds = 900

    def __init__(self, startup, *, store=None, clock=time.monotonic,
                 speed=bench_speed.run, ability=bench_ability.run, documents=doc_trial.run):
        self.startup = startup
        self.store = store or Store(startup.home / '.local/share/argos-live/results')
        self.clock, self.speed, self.ability, self.documents = clock, speed, ability, documents
        self.plan = 'baseline'
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.worker = None
        self.phase = 'idle'
        self.progress = None
        self.runs = []
        self.started = None
        self.finished = None
        self.model = None
        self.resume = False
        self.resume_requested = False
        self.closed = False

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            return {'available': not self.closed, 'active': active,
                    'phase': 'cancelling' if active and self.cancel_event.is_set() else self.phase,
                    'model': self.model, 'plan': self.plan, 'progress': copy.deepcopy(self.progress),
                    'runs': list(self.runs), 'resume_requested': self.resume_requested,
                    'elapsed_seconds': max(0, (self.finished if self.finished is not None else self.clock()) - self.started)
                    if self.started is not None else None}

    def start(self, plan='baseline'):
        # Share startup's reservation: chat cannot restart into a benchmark.
        if plan not in PLANS:
            raise ValueError('Unknown model lab plan')
        with self.startup.lock, self.lock:
            if self.closed:
                raise ValueError('The model lab is closed')
            if self.snapshot()['active'] or self.startup.lab_active:
                raise ValueError('Another desktop workload is already active')
            status = self.startup.snapshot()
            self.resume = status['active']
            self.startup.lab_active = True
            self.startup.stop()
            self.plan = plan
            self.cancel_event.clear()
            self.phase, self.started = 'pausing', self.clock()
            self.finished = None
            self.progress, self.runs, self.model = None, [], None
            self.resume_requested = False
            self.worker = threading.Thread(target=self.run, daemon=True, name='argos-model-lab')
            self.worker.start()
            return self.snapshot()

    def start_documents(self):
        return self.start('documents')

    def cancel(self):
        with self.lock:
            if self.snapshot()['active']:
                self.cancel_event.set()
                self.phase = 'cancelling'
            return self.snapshot()

    def report(self, phase, value=None):
        with self.lock:
            if not self.cancel_event.is_set():
                self.phase, self.progress = phase, copy.deepcopy(value)

    def run(self):
        timer = threading.Timer(self.budget_seconds, self.cancel)
        timer.daemon = True
        timer.start()
        outcome = 'failed'
        try:
            deadline = self.clock() + 180
            while self.startup.snapshot()['active']:
                if self.cancel_event.wait(.1):
                    raise Cancelled('Cancelled while pausing')
                if self.clock() >= deadline:
                    raise ValueError('Assistant did not release resources')
            if self.cancel_event.is_set():
                raise Cancelled('Cancelled before benchmark')
            outcome = self.execute()
        except Exception:
            # Never export private configuration paths or exception text to HTTP.
            outcome = self.failure_outcome()
            try:
                self.settle_unstarted()
            except (ValueError, OSError):
                pass
        finally:
            timer.cancel()
            with self.startup.lock, self.lock:
                self.startup.lab_active = False
                if self.resume:
                    try:
                        self.startup.start()
                        # Keep the lab visible; the owner can choose Open chat.
                        self.startup.chat_claimed = True
                        self.resume_requested = True
                    except (ValueError, OSError):
                        outcome = 'failed'
            with self.lock:
                self.phase = outcome
                self.finished = self.clock()

    def execute(self):
        target, model = self.startup.resolve_source(self.startup.home)
        with self.lock:
            self.model = model
        self.report('model-service')
        lease = self.startup.home / '.local/state/argos-live'
        with self.startup.backend(target, lease_store=lease, cancel=self.cancel_event.is_set) as client:
            client.timeout = 120
            for phase, name, options in PLANS[self.plan]:
                runner = getattr(self, name)
                if self.cancel_event.is_set():
                    raise Cancelled('Cancelled between tests')
                self.report(phase)
                result = runner(client, model, cancel=self.cancel_event,
                                progress=lambda value, phase=phase: self.report(phase, value), **options)
                self.store.save(result)
                with self.lock:
                    self.runs.append(result['id'])
        return 'cancelled' if self.cancel_event.is_set() else 'completed'

    def settle_unstarted(self):
        """Specialized workloads may settle a receipt without backend startup."""
        pass

    def failure_outcome(self):
        return 'cancelled' if self.cancel_event.is_set() else 'failed'

    def close(self):
        with self.lock:
            self.closed = True
            self.resume = False
            self.cancel()
            worker = self.worker
        if worker:
            worker.join(timeout=200)
