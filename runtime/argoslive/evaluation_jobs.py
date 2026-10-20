"""Host-owned evaluation lifetime, independent of a bounded client wait.

This primitive does not authorize controller inference during an evaluation.
Adapters must keep controller suspension/resource mediation in force. No client
message is accepted as proof of backend drainage, and abandoned jobs never expire.
"""
from contextlib import contextmanager
from pathlib import Path
import secrets
import threading
import time

from . import ability, bench_openclaw, workload, storage
from .pull_jobs import read_json, write_json, worker_lock, WorkerBusy
from .results import Store, identifier

MAX_WAIT_SECONDS = 480


class WaitAborted(ValueError):
    """Only the caller's wait ended; its evaluation continues."""


class Cancellation:
    def __init__(self, path, read=read_json):
        self.path = path
        self.read = read

    def is_set(self):
        if not self.path.exists():
            return False
        # Invalid owner control fails closed, without interpreting commands.
        return self.read(self.path) != {'action': 'run'}


class Jobs:
    def __init__(self, home, *, evaluate=None, admission=None):
        self.home = storage.safe_local(Path(home).absolute())
        self.root = storage.safe_local(self.home / '.local/state/argos-live/evaluation-jobs')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.metadata_root = self.root / 'metadata-lock'
        self.metadata_root.mkdir(mode=0o700, exist_ok=True)
        self.evaluate = evaluate or bench_openclaw._run
        self.admission = admission or (lambda: workload.reserve(self.home, 'evaluation'))
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.threads = {}

    @contextmanager
    def metadata(self):
        # Windows readers otherwise prevent atomic replacement of a progress
        # file. Use the same short OS lock across host instances and writers.
        deadline = time.monotonic() + 10
        while True:
            lock = worker_lock(self.metadata_root)
            try:
                lock.__enter__()
                break
            except WorkerBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.005)
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def read(self, path):
        with self.metadata():
            return read_json(path)

    def write(self, path, value):
        with self.metadata():
            write_json(path, value)

    def path(self, job_id):
        return storage.safe_local(self.root / (identifier(job_id) + '.json'))

    def control(self, job_id):
        return storage.safe_local(self.root / (identifier(job_id) + '.control.json'))

    def start(self, suite='quick'):
        if suite not in ('quick', 'standard', 'challenge'):
            raise ValueError('Unsupported evaluation suite')
        job_id = secrets.token_hex(16)
        ready = threading.Event()
        errors = []

        def execute():
            accepted = False
            record = None
            try:
                # The host thread owns exclusion through saved publication and
                # reservation settlement, including when all clients disappear.
                with worker_lock(self.root):
                    prior_path = self.root / 'current.json'
                    prior = self.read(prior_path) if prior_path.exists() else {}
                    if prior.get('state') in ('running', 'quarantined'):
                        raise workload.Busy(recovery=True)
                    with self.admission() as slot:
                        record = {'schema': 'argos-evaluation-job/1', 'job_id': job_id,
                                  'suite': suite, 'state': 'running', 'settled': False,
                                  'completed': 0, 'total': len(ability.load(suite)['items']),
                                  'inference_dispatched': False,
                                  'reservation_id': slot.record['id'],
                                  'reservation_generation': slot.record['generation']}
                        self.write(self.control(job_id), {'action': 'run'})

                        def publish():
                            self.write(self.path(job_id), record)
                            self.write(prior_path, {'job_id': job_id, 'state': record['state']})

                        publish()
                        accepted = True
                        ready.set()

                        def progress(event):
                            if event.get('phase') == 'asking':
                                record['inference_dispatched'] = True
                            record.update(completed=event.get('completed', record['completed']),
                                          total=event.get('total', record['total']))
                            publish()

                        result = self.evaluate(suite=suite, home=self.home, progress=progress,
                                               cancel=Cancellation(self.control(job_id), self.read))
                        path = self.store.save(result)
                        slot.record_result(result['id'])
                        # Completed fixed native turns have the same release
                        # policy as bench_openclaw. Cancellation after dispatch
                        # needs independent backend proof; never infer it from
                        # CLI exit, a signal, or the result state alone.
                        releasable = result['state'] == 'completed' or (
                            result['state'] == 'cancelled' and not record['inference_dispatched'])
                        record.update(state='completed' if releasable else 'quarantined',
                                      outcome=result['state'], result_id=result['id'], path=str(path),
                                      completed=result['coverage']['completed'],
                                      total=result['coverage']['total'])
                        publish()
                        if releasable:
                            slot.complete(result['id'])
                    # Terminal responses are eligible only AFTER admission's
                    # finally has durably published release/quarantine.
                    record['settled'] = True
                    publish()
            except BaseException as error:
                if not accepted:
                    errors.append(error)
                else:
                    record.update(state='quarantined', settled=True,
                                  error_category=type(error).__name__)
                    self.write(self.path(job_id), record)
                    self.write(self.root / 'current.json', {'job_id': job_id, 'state': 'quarantined'})
            finally:
                ready.set()

        thread = threading.Thread(target=execute, name='argos-evaluation-' + job_id,
                                  daemon=False)
        self.threads[job_id] = thread
        thread.start()
        ready.wait()
        if errors:
            thread.join()
            raise errors[0]
        return self.status(job_id)

    def status(self, job_id):
        record = self.read(self.path(job_id))
        if record.get('job_id') != job_id:
            raise ValueError('Evaluation identity mismatch')
        if record['state'] == 'running' or not record.get('settled'):
            return {'status': 'running', 'job_id': job_id,
                    'completed': record['completed'], 'total': record['total']}
        value = {'status': 'completed', 'job_id': job_id,
                 'recovery_required': record['state'] == 'quarantined'}
        if 'result_id' in record:
            result = self.store.load(record['result_id'])
            value.update(result=result, path=str(self.store.path(result['id'])))
        else:
            value.update(status='failed', error_category=record.get('error_category'))
        return value

    def wait(self, job_id, *, seconds=MAX_WAIT_SECONDS, aborted=None, on_update=None):
        if (type(seconds) not in (int, float) or not 0 <= seconds <= MAX_WAIT_SECONDS):
            raise ValueError('Wait must be bounded to eight minutes')
        deadline = time.monotonic() + seconds
        previous = None
        while True:
            if aborted is not None and aborted.is_set():
                raise WaitAborted('Client wait ended; evaluation remains host-owned')
            value = self.status(job_id)
            progress = (value.get('completed'), value.get('total'))
            if on_update and value['status'] == 'running' and progress != previous:
                on_update(value)
                previous = progress
            if value['status'] != 'running' or time.monotonic() >= deadline:
                return value
            time.sleep(min(.05, max(0, deadline - time.monotonic())))

    def cancel_owner(self, job_id):
        """Host owner operation, never a tool AbortSignal handler."""
        value = self.status(job_id)
        if value['status'] == 'running':
            self.write(self.control(job_id), {'action': 'cancel'})
        return value
