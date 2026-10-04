from contextlib import contextmanager
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog
from argoslive.ollama import Client
from argoslive.pull_jobs import Progress, Queue, read_json, worker_lock, write_json


class PullJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.requests.append((self.path, body))
                self.send_response(200)
                self.end_headers()
                for event in self.server.events:
                    try:
                        self.wfile.write(json.dumps(event).encode() + b'\n')
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        break
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.requests = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.models = self.root / 'models'
        self.models.mkdir()
        (self.models / '.argos-storage-id').write_text('fixture-store')
        self.config = {'storage': str(self.models), 'storage_id': 'fixture-store'}
        self.data = copy.deepcopy(catalog.load())
        self.entry = self.data['models'][0]
        self.payload = b'authored tiny model fixture'
        self.digest = 'sha256:' + hashlib.sha256(self.payload).hexdigest()
        weight = next(a for a in self.entry['artifacts']
                      if a['media_type'] == 'application/vnd.ollama.image.model')
        weight.update(digest=self.digest, size=len(self.payload))
        self.entry['weight_bytes'] = sum(a['size'] for a in self.entry['artifacts']
                                       if a['media_type'] in {
                                           'application/vnd.ollama.image.model',
                                           'application/vnd.ollama.image.projector'})
        self.entry['total_download_bytes'] = sum(a['size'] for a in self.entry['artifacts'])
        # Keep catalog schema/licence checks real; only weight descriptor is tiny.
        with patch('argoslive.pull_jobs.private_directory', side_effect=lambda p: p.mkdir(mode=0o700)):
            self.jobs = Queue.initialize(self.root / 'jobs')
        self.queue = Queue(self.jobs, self.config, self.data)
        self.job = self.queue.create(self.entry['tag'])
        self.server.requests.clear()
        self.server.events = [self.event(0), self.event(len(self.payload)), {'status': 'success'}]
        self.exited = False

    def event(self, done):
        return {'status': 'pulling fixture', 'digest': self.digest,
                'total': len(self.payload), 'completed': done}

    @contextmanager
    def backend(self, target):
        self.assertEqual(target, self.models)
        try:
            yield Client(f'http://127.0.0.1:{self.server.server_port}', timeout=2)
        finally:
            self.exited = True
            # Worker must hold exclusion through server-side shutdown.
            with self.assertRaises(ValueError):
                with worker_lock(self.jobs):
                    pass

    def run_job(self, **kwargs):
        return self.queue.run(self.job['id'], self.backend, free=lambda p: 100 * 1024**3, **kwargs)

    def test_completed_pull_is_not_integrity_or_inference_ready(self):
        snapshots = []
        times = iter([0, 2])
        job = self.run_job(clock=lambda: next(times), callback=snapshots.append)
        self.assertEqual(job['state'], 'downloaded_needs_verification')
        self.assertFalse(job['integrity_verified'])
        self.assertFalse(job['inference_ready'])
        self.assertTrue(self.exited)
        self.assertEqual(job['progress']['bytes_done'], len(self.payload))
        self.assertGreater(job['progress']['recent_mib_per_second'], 0)
        self.assertGreater(job['progress']['eta_seconds'], 0)  # Other artifacts unreported.
        self.assertEqual(self.queue.get(job['id']), job)
        self.assertEqual(self.server.requests[0],
                         ('/api/pull', {'model': self.entry['tag'], 'stream': True}))
        snapshots[0]['state'] = 'ready'
        self.assertEqual(self.queue.get(job['id'])['state'], 'downloaded_needs_verification')

    def test_interrupted_stream_and_explicit_resume_reset_attempt_progress(self):
        self.server.events = [self.event(8)]
        job = self.run_job()
        self.assertEqual(job['state'], 'interrupted')
        self.assertEqual(job['progress']['bytes_done'], 8)
        reopened = Queue(self.jobs, self.config, self.data)
        reopened.retry(job['id'])
        self.server.events = [self.event(8), self.event(len(self.payload)), {'status': 'success'}]
        job = reopened.run(job['id'], self.backend, free=lambda p: 100 * 1024**3)
        self.assertEqual(job['attempts'], 2)
        self.assertEqual(job['progress']['bytes_done'], len(self.payload))

    def test_pause_cancel_and_backend_shutdown_before_release(self):
        def pause(job):
            if job['progress']['bytes_done']:
                self.queue.request(job['id'], 'pause')
        self.server.events = [self.event(8), self.event(len(self.payload)), {'status': 'success'}]
        job = self.run_job(callback=pause)
        self.assertEqual(job['state'], 'paused')
        self.assertTrue(self.exited)
        self.queue.retry(job['id'])
        self.queue.request(job['id'], 'cancel')
        self.server.requests.clear()
        job = self.run_job()
        self.assertEqual(job['state'], 'cancelled')
        self.assertEqual(self.server.requests, [])
        with self.assertRaises(ValueError):
            self.queue.retry(job['id'])

    def test_reboot_recovery_and_single_worker_lock(self):
        stale = self.queue.get(self.job['id'])
        stale['state'] = 'downloading'
        write_json(self.queue.path(stale['id']), stale)
        reopened = Queue(self.jobs, self.config, self.data)
        with worker_lock(self.jobs):
            with self.assertRaises(ValueError):
                reopened.retry(stale['id'])
        self.assertEqual(reopened.retry(stale['id'])['state'], 'queued')
        self.assertEqual(self.run_job()['state'], 'downloaded_needs_verification')

    def test_disk_full_and_changed_storage_stop_before_http(self):
        job = self.queue.run(self.job['id'], self.backend, free=lambda p: 0)
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.server.requests, [])
        self.queue.retry(job['id'])
        (self.models / '.argos-storage-id').write_text('different')
        job = self.run_job()
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.exited)

    def test_corrupt_full_blob_is_retained_and_blocks_pull(self):
        blobs = self.models / 'blobs'
        blobs.mkdir()
        path = blobs / self.digest.replace(':', '-')
        path.write_bytes(b'x' * len(self.payload))
        job = self.run_job()
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(path.read_bytes(), b'x' * len(self.payload))
        self.assertEqual(self.server.requests, [])
        path.write_bytes(self.payload)
        required = self.queue.budget(self.entry, self.models)
        self.assertEqual(required, self.entry['total_download_bytes'] - len(self.payload) + 1024**3)

    def test_catalog_drift_and_unknown_progress_artifact(self):
        self.entry['manifest_digest'] = 'sha256:' + 'f' * 64
        self.assertEqual(self.run_job()['state'], 'failed')
        self.assertEqual(self.server.requests, [])
        self.entry['manifest_digest'] = self.job['manifest_digest']
        self.queue.retry(self.job['id'])
        self.server.events = [{'digest': 'sha256:' + 'e' * 64, 'total': 1, 'completed': 1}]
        self.assertEqual(self.run_job()['state'], 'failed')
        self.assertTrue(self.exited)

    def test_removed_storage_and_disk_full_during_pull_release_backend(self):
        def removed(job):
            if job['state'] == 'downloading' and job['progress']['bytes_done']:
                (self.models / '.argos-storage-id').unlink(missing_ok=True)
        self.server.events = [self.event(8), self.event(len(self.payload)), {'status': 'success'}]
        self.assertEqual(self.run_job(callback=removed)['state'], 'failed')
        self.assertTrue(self.exited)
        (self.models / '.argos-storage-id').write_text('fixture-store')
        self.queue.retry(self.job['id'])
        @contextmanager
        def full(target):
            try:
                class Backend:
                    def pull(self, *args, **kwargs):
                        raise OSError('fixture disk full')
                yield Backend()
            finally:
                self.exited = True
        self.exited = False
        job = self.queue.run(self.job['id'], full, free=lambda p: 100 * 1024**3)
        self.assertEqual(job['state'], 'failed')
        self.assertTrue(self.exited)

    def test_progress_counters_bounds_and_no_invented_speed(self):
        times = iter([0, 2, 3])
        progress = Progress(self.entry, clock=lambda: next(times))
        first = progress.event(self.event(8))
        self.assertIsNone(first['recent_mib_per_second'])
        self.assertIsNone(first['eta_seconds'])
        last = progress.event(self.event(len(self.payload)))
        expected = (len(self.payload) - 8) / 2 / 1024**2
        self.assertAlmostEqual(last['recent_mib_per_second'], expected)
        self.assertEqual(progress.event(self.event(len(self.payload)))['bytes_done'], len(self.payload))
        for event in (self.event(1), dict(self.event(10), total=999), self.event(True)):
            with self.assertRaises(ValueError):
                progress.event(event)

    def test_private_metadata_paths_bounded_and_control_separate(self):
        for invalid in ('../outside', 'a' * 31, 'A' * 32):
            with self.assertRaises(ValueError):
                self.queue.get(invalid)
        self.queue.request(self.job['id'], 'pause')
        self.assertEqual(read_json(self.queue.path(self.job['id'], '.control.json')), {'action': 'pause'})
        self.assertEqual(self.queue.get(self.job['id'])['state'], 'queued')
        self.assertEqual(self.run_job()['state'], 'paused')
        self.assertEqual(self.server.requests, [])
        path = self.queue.path(self.job['id'])
        path.write_bytes(b' ' * (1024**2 + 1))
        with self.assertRaises(ValueError):
            self.queue.get(self.job['id'])
