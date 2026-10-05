"""Durable pull state, independent of daemon startup and model activation.

Internal API: the caller supplies a context manager owning an isolated backend.
It must stop all server-side writes before __exit__ returns (also on errors).
model_onboarding supplies the verified CLI/daemon adapter; run() below remains
the original internal download-only API and never marks a model ready.
"""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time

from . import catalog, storage
from .ollama import Cancelled, OllamaError
from .pack_export import private_directory

LIMIT = 1024 * 1024
ID = re.compile(r'[a-f0-9]{32}')
STATES = {'queued', 'downloading', 'paused', 'cancelled', 'interrupted',
          'failed', 'downloaded_needs_verification', 'verifying', 'loading', 'testing', 'publishing', 'ready'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    path = storage.safe_local(path)
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Job metadata exceeds limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Invalid job metadata')
    return value


def write_json(path, value):
    path = storage.safe_local(path)
    temp = path.parent / ('.job-' + secrets.token_hex(16))
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if len(raw) > LIMIT:
        raise ValueError('Job metadata exceeds limit')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def worker_lock(root):
    """OS-held lock survives neither crash nor reboot; its file is never removed."""
    path = storage.safe_local(root / '.worker-lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'0')
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError('Another model job operation is active') from None
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('Another model job operation is active') from None
        yield
    finally:
        os.close(fd)


class Progress:
    """Aggregate validated per-artifact counters; rolling speed is measured only."""
    def __init__(self, entry, clock=time.monotonic):
        self.sizes = {a['digest']: a['size'] for a in entry['artifacts']}
        self.done = {key: 0 for key in self.sizes}
        self.clock = clock
        self.samples = deque()

    def event(self, event):
        digest = event.get('digest')
        if digest is None:
            return self.snapshot()
        if digest not in self.sizes:
            raise ValueError('Pull artifact differs from the reviewed catalog')
        total, done = event.get('total'), event.get('completed', 0)
        if (type(total) is not int or total != self.sizes[digest]
                or type(done) is not int or not 0 <= done <= total
                or done < self.done[digest]):
            raise ValueError('Invalid or decreasing pull progress')
        self.done[digest] = done
        now, count = self.clock(), sum(self.done.values())
        self.samples.append((now, count))
        while len(self.samples) > 2 and self.samples[1][0] < now - 10:
            self.samples.popleft()
        # Bound metadata even when a server emits many events in one clock tick.
        while len(self.samples) > 256:
            self.samples.popleft()
        return self.snapshot()

    def snapshot(self):
        done, total = sum(self.done.values()), sum(self.sizes.values())
        rate = None
        if len(self.samples) >= 2:
            elapsed = self.samples[-1][0] - self.samples[0][0]
            delta = self.samples[-1][1] - self.samples[0][1]
            if elapsed >= 1 and delta > 0:
                rate = delta / elapsed
        return {'bytes_done': done, 'bytes_total': total,
                'recent_mib_per_second': rate / 1024**2 if rate else None,
                'eta_seconds': (total - done) / rate if rate else None,
                'artifact_bytes': dict(self.done)}


class Control:
    def __init__(self, queue, job_id, external=None):
        self.queue, self.job_id = queue, job_id
        self.external = external

    def action(self):
        value = read_json(self.queue.path(self.job_id, '.control.json'))
        action = value.get('action')
        if action not in {'run', 'pause', 'cancel'}:
            raise ValueError('Invalid job control')
        return action

    def is_set(self):
        return bool(self.external and self.external()) or self.action() != 'run'


class Queue:
    """One queue per selected store, in private config/persistence, never DATA.

Caller owns establishing private/encrypted persistence before initializing root.
Only existing identity-marked model storage is accepted; no mount or fallback.
The same root must be used by all cooperating workers. No cross-queue/global
exclusion against unrelated Ollama processes is claimed.
"""
    def __init__(self, root, configured, data=None, *, validate=storage.validate_configured):
        self.root = storage.safe_local(root)
        if not self.root.is_dir():
            raise ValueError('Initialize a private job directory first')
        self.configured = dict(configured)
        self.validate = validate
        self.data = catalog.validate(data) if data is not None else catalog.load()

    @staticmethod
    def initialize(root):
        root = storage.safe_local(root)
        private_directory(root)
        return root

    def path(self, job_id, suffix='.json'):
        if not isinstance(job_id, str) or not ID.fullmatch(job_id):
            raise ValueError('Invalid job ID')
        return storage.safe_local(self.root / (job_id + suffix))

    def entry(self, tag):
        for entry in self.data['models']:
            if entry['tag'] == tag:
                return entry
        raise ValueError('Model is not in the reviewed catalog')

    def identity(self):
        path = self.validate(self.configured)
        return {'path': str(path), 'marker': self.configured['storage_id'],
                'uuid': self.configured.get('storage_uuid')}

    def create(self, tag):
        with worker_lock(self.root):
            entry, target = self.entry(tag), self.identity()
            job_id = secrets.token_hex(16)
            job = {'schema': 'argos-pull/1', 'id': job_id, 'tag': tag,
                   'manifest_digest': entry['manifest_digest'], 'storage': target,
                   'state': 'queued', 'attempts': 0, 'created': stamp(), 'updated': stamp(),
                   'error': None, 'integrity_verified': False, 'inference_ready': False,
                   'progress': Progress(entry).snapshot()}
            write_json(self.path(job_id, '.control.json'), {'action': 'run'})
            write_json(self.path(job_id), job)
            return job

    def get(self, job_id):
        job = read_json(self.path(job_id))
        if (job.get('schema') != 'argos-pull/1' or job.get('id') != job_id
                or job.get('state') not in STATES or type(job.get('attempts')) is not int
                or job['attempts'] < 0 or type(job.get('integrity_verified')) is not bool
                or type(job.get('inference_ready')) is not bool
                or (job['inference_ready'] and (not job['integrity_verified'] or job['state'] != 'ready'))
                or (job['state'] == 'ready' and not job['inference_ready'])):
            raise ValueError('Invalid durable job state')
        return job

    def request(self, job_id, action):
        if action not in {'pause', 'cancel'}:
            raise ValueError('Choose pause or cancel')
        self.get(job_id)
        # Separate control file avoids losing requests to progress-state updates.
        write_json(self.path(job_id, '.control.json'), {'action': action})

    def retry(self, job_id):
        with worker_lock(self.root):
            job = self.get(job_id)
            if job['state'] not in {'paused', 'interrupted', 'failed', 'downloading',
                                    'downloaded_needs_verification', 'verifying', 'loading', 'testing', 'publishing'}:
                raise ValueError('Job is not resumable; cancelled jobs stay cancelled')
            self.check(job)
            job.update(state='queued', error=None, updated=stamp(),
                       integrity_verified=False, inference_ready=False)
            write_json(self.path(job_id, '.control.json'), {'action': 'run'})
            write_json(self.path(job_id), job)
            return job

    def check(self, job):
        entry = self.entry(job['tag'])
        if job['manifest_digest'] != entry['manifest_digest'] or job['storage'] != self.identity():
            raise ValueError('Catalog or selected storage changed; review a new job')
        return entry

    def budget(self, entry, target):
        """Deduct only full SHA-verified blobs. Partials get no trusted credit.

        Conservative space budget can require extra free space on resume; never
        delete partials, manifests or shared blobs to make room automatically.
        """
        missing = 0
        for item in entry['artifacts']:
            path = storage.safe_local(target / 'blobs' / item['digest'].replace(':', '-'))
            if not path.exists():
                missing += item['size']
                continue
            if not path.is_file() or path.stat().st_size != item['size']:
                raise ValueError('Existing artifact is corrupt; manual review required')
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024**2), b''):
                    digest.update(chunk)
            if 'sha256:' + digest.hexdigest() != item['digest']:
                raise ValueError('Existing artifact is corrupt; manual review required')
        return missing + 1024**3

    def run(self, job_id, owned_backend, *, free=lambda p: shutil.disk_usage(p).free,
            clock=time.monotonic, callback=None):
        """Internal worker core, NOT a verified/ready publication path.

        No automatic retry storm: caller explicitly retries a failed/interrupted
        job. owned_backend(target) yields a B2 Client. Exiting it must terminate
        the backend, including outstanding pulls, before the queue lock releases.
        """
        with worker_lock(self.root):
            job = self.get(job_id)
            if job['state'] != 'queued':
                raise ValueError('Queue or explicitly retry the job before running')
            control = Control(self, job_id)
            def save():
                job['updated'] = stamp()
                write_json(self.path(job_id), job)
                if callback:
                    # A detached snapshot prevents UI callbacks mutating worker state.
                    callback(json.loads(json.dumps(job)))
            try:
                entry = self.check(job)
                target = Path(job['storage']['path'])
                if control.is_set():
                    raise Cancelled('Job control requested')
                if free(target) < self.budget(entry, target):
                    raise ValueError('Insufficient free space including safety margin')
                job.update(state='downloading', attempts=job['attempts'] + 1, error=None)
                progress = Progress(entry, clock)
                job['progress'] = progress.snapshot()
                save()
                with owned_backend(target) as client:
                    def event(value):
                        self.check(job)
                        if control.is_set():
                            raise Cancelled('Job control requested')
                        job['progress'] = progress.event(value)
                        save()
                    client.pull(job['tag'], callback=event, cancel=control)
                # Success of the HTTP pull alone cannot establish pinned identity.
                self.check(job)
                if control.is_set():
                    raise Cancelled('Job control requested')
                job['state'] = 'downloaded_needs_verification'
            except Cancelled:
                job['state'] = 'cancelled' if control.action() == 'cancel' else 'paused'
            except OllamaError:
                job.update(state='interrupted', error='Backend pull interrupted; retry explicitly')
            except (ValueError, OSError):
                job.update(state='failed', error='Storage, catalog, capacity or progress check failed')
            except KeyboardInterrupt:
                job.update(state='paused', error=None)
            save()
            return job
