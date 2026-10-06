"""Guided catalog acquisition using the existing verified Ollama pipeline."""
from . import catalog, storage, storage_view
from .lab import Controller as Workload
from .model_onboarding import OnboardingQueue
from .pull_jobs import write_json, worker_lock, stamp
from .web.status import read_json


def queue(home):
    root = home / '.config/argos-live'
    configured = read_json(storage.safe_local(root / 'state.json'))
    storage.validate_configured(configured)
    OnboardingQueue.initialize(root / 'pull-jobs')
    return OnboardingQueue(root / 'pull-jobs', configured)


class Controller(Workload):
    budget_seconds = 3600

    def __init__(self, startup, *, queue_factory=queue, storage_gate=storage_view.require_ready_for_download,
                 **options):
        super().__init__(startup, **options)
        self.queue_factory = queue_factory
        self.storage_gate = storage_gate
        self.queue = None
        self.job_id = None
        self.receipt = None
        self.cancel_action = 'cancel'

    def snapshot(self):
        with self.lock:
            value = super().snapshot()
            value.update(job_id=self.job_id, reply_test=self.receipt)
            return value

    def start(self, *, tag=None, job=None):
        if (tag is None) == (job is None):
            raise ValueError('Choose one catalog model or existing job')
        if tag is not None and (not isinstance(tag, str) or
                not any(entry['tag'] == tag for entry in catalog.load()['models'])):
            raise ValueError('Choose an exact reviewed catalog tag')
        with self.startup.lock, self.lock:
            if self.closed or self.snapshot()['active'] or self.startup.lab_active:
                raise ValueError('Another desktop workload is active')
            # Deliberate storage choice and a fresh bounded write check (S3/S4).
            self.storage_gate(self.startup.home)
            self.queue = self.queue_factory(self.startup.home)
            if tag is not None:
                value = self.queue.create(tag)
            else:
                value = self.queue.get(job)
                self.queue.check(value)
                if value['state'] == 'queued':
                    write_json(self.queue.path(job, '.control.json'), {'action': 'run'})
                else:
                    value = self.queue.retry(job)
            self.job_id = value['id']
            self.receipt = None
            self.cancel_action = 'cancel'
            return super().start()

    def cancel(self, action='cancel'):
        if action not in ('pause', 'cancel'):
            raise ValueError('Unknown model job control')
        with self.lock:
            active = self.snapshot()['active']
            self.cancel_action = action
            if active and self.queue and self.job_id:
                try:
                    self.queue.request(self.job_id, action)
                except (ValueError, OSError):
                    # A shutdown request must still reach the owned backend.
                    pass
            return super().cancel()

    def execute(self):
        self.startup.resolve_source(self.startup.home)
        self.model = self.queue.get(self.job_id)['tag']
        def progress(job):
            measured = job['progress']
            public = {key: measured.get(key) for key in
                      ('bytes_done', 'bytes_total', 'recent_mib_per_second', 'eta_seconds')}
            self.report(job['state'], public)
        def backend(target):
            # Durable control requests also interrupt owned daemon startup.
            return self.startup.backend(target, cancel=self.cancel_event.is_set)
        result = self.queue.run_verified(self.job_id, backend=backend,
            callback=progress, assistant_stopped=True, cancel=self.cancel_event.is_set)
        with self.lock:
            receipt = result.get('reply_test')
            self.receipt = {key: receipt.get(key) for key in ('eval_count', 'eval_duration',
                'time_to_first_token_seconds', 'elapsed_seconds', 'text_reply_verified',
                'performance_benchmark')} if isinstance(receipt, dict) else None
        return 'completed' if result['state'] == 'ready' else result['state']

    def settle_unstarted(self):
        if not self.queue or not self.job_id:
            return
        value = self.queue.get(self.job_id)
        if value['state'] != 'queued':
            return
        with worker_lock(self.queue.root):
            value = self.queue.get(self.job_id)
            if value['state'] != 'queued':
                return
            value.update(state=('paused' if self.cancel_action == 'pause' else 'cancelled')
                         if self.cancel_event.is_set() else 'failed', updated=stamp(),
                         inference_ready=False)
            write_json(self.queue.path(self.job_id), value)
