from contextlib import contextmanager
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog, model_verify as artifacts
from argoslive.model_onboarding import OnboardingQueue, main
from argoslive.ollama import Client
from argoslive.owned_ollama import PIN
from argoslive.pull_jobs import Queue, worker_lock


class OnboardingTests(unittest.TestCase):
    def test_external_shutdown_cancelled_before_artifact_requests(self):
        value = self.queue.run_verified(self.job['id'], backend=self.backend,
            assistant_stopped=True, cancel=lambda: True)
        self.assertEqual(value['state'], 'paused')
        self.assertFalse(value['inference_ready'])
        self.assertFalse(artifacts.manifest_path(self.models, self.entry['tag']).exists())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.models = self.root / 'models'
        self.models.mkdir()
        (self.models / '.argos-storage-id').write_text('fixture')
        self.config = {'storage': str(self.models), 'storage_id': 'fixture'}
        self.jobs = self.root / 'jobs'
        self.jobs.mkdir()
        self.data = copy.deepcopy(catalog.load())
        self.entry = self.data['models'][0]
        self.payload = {}
        for item in self.entry['artifacts']:
            if item['media_type'].endswith('.license'):
                raw = (catalog.DEFAULT.parent / 'licenses' / (item['digest'][7:] + '.txt')).read_bytes()
            else:
                raw = ('authored fixture ' + item['media_type']).encode()
                item.update(digest='sha256:' + hashlib.sha256(raw).hexdigest(), size=len(raw))
            self.payload[item['digest']] = raw
        self.entry['total_download_bytes'] = sum(a['size'] for a in self.entry['artifacts'])
        self.entry['weight_bytes'] = sum(a['size'] for a in self.entry['artifacts']
                                       if a['media_type'].endswith(('.model', '.projector')))
        descriptors = [{'digest': a['digest'], 'size': a['size'], 'mediaType': a['media_type']}
                       for a in self.entry['artifacts']]
        config = next(a for a in descriptors if a['mediaType'] == 'application/vnd.docker.container.image.v1+json')
        self.raw = json.dumps({'schemaVersion': 2, 'config': config,
                               'layers': [a for a in descriptors if a != config]}, separators=(',', ':')).encode()
        self.entry['manifest_digest'] = 'sha256:' + hashlib.sha256(self.raw).hexdigest()
        self.queue = OnboardingQueue(self.jobs, self.config, self.data)
        self.job = self.queue.create(self.entry['tag'])
        self.requests, self.exited = [], False
        self.mode = 'ok'
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.respond({})
            def do_POST(self):
                self.respond(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            def respond(self, body):
                outer.requests.append((self.path, body))
                self.send_response(200)
                self.end_headers()
                if self.path == '/api/version':
                    events = {'version': 'wrong' if outer.mode == 'wrong-version' else PIN}
                elif self.path == '/api/show':
                    events = {'details': {'family': outer.entry['family'],
                                          'quantization_level': outer.entry['quantization']}}
                elif self.path == '/api/pull':
                    outer.write_stage()
                    events = [{'digest': a['digest'], 'total': a['size'], 'completed': a['size']}
                              for a in outer.entry['artifacts']]
                    if outer.mode != 'interrupted':
                        events.append({'status': 'success'})
                elif body.get('keep_alive') == 0 and body.get('stream') is False:
                    events = {'done': True}
                else:
                    events = [{'response': '' if outer.mode == 'empty-reply' else 'Hello.',
                               'done': True, 'eval_count': 2, 'eval_duration': 200000000,
                               'load_duration': 10000000}]
                raw = (b''.join(json.dumps(e).encode() + b'\n' for e in events)
                       if isinstance(events, list) else json.dumps(events).encode())
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        def cleanup():
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(5)
        self.addCleanup(cleanup)

    def write_stage(self):
        path = artifacts.manifest_path(self.stage, self.entry['tag'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.raw + (b' ' if self.mode == 'changed-tag' else b''))
        (self.stage / 'blobs').mkdir(exist_ok=True)
        for digest, raw in self.payload.items():
            if self.mode == 'corrupt' and raw.startswith(b'authored'):
                raw = b'x' * len(raw)
            (self.stage / 'blobs' / digest.replace(':', '-')).write_bytes(raw)

    @contextmanager
    def backend(self, target):
        self.stage = target
        try:
            yield Client(f'http://127.0.0.1:{self.server.server_port}', timeout=2)
        finally:
            self.exited = True
            with self.assertRaises(ValueError):
                with worker_lock(self.models):
                    pass

    def run_job(self, **kwargs):
        return self.queue.run_verified(self.job['id'], backend=self.backend,
                                       revision=lambda e: artifacts.check_manifest(self.raw, e),
                                       free=lambda p: 100 * 1024**3, assistant_stopped=True, **kwargs)

    def test_ready_requires_verification_reply_unload_and_publication(self):
        states = []
        original_publish = artifacts.publish
        def publish(*args):
            self.assertTrue(self.exited)
            return original_publish(*args)
        with patch.object(artifacts, 'publish', side_effect=publish):
            job = self.run_job(callback=lambda j: states.append(j['state']))
        self.assertEqual(job['state'], 'ready')
        self.assertTrue(job['integrity_verified'])
        self.assertTrue(job['inference_ready'])
        self.assertEqual(job['verification_bytes'], self.entry['total_download_bytes'])
        self.assertEqual(job['reply_test']['eval_count'], 2)
        self.assertFalse(job['reply_test']['performance_benchmark'])
        self.assertFalse(job['reply_test']['vision_verified'])
        for state in ('downloading', 'verifying', 'loading', 'testing', 'publishing', 'ready'):
            self.assertIn(state, states)
        self.assertEqual(artifacts.verify(self.models, self.entry), self.entry['total_download_bytes'])
        self.assertFalse(self.requests[-1][1]['stream'])
        self.assertEqual(self.queue.get(job['id'])['state'], 'ready')

    def test_post_pull_corruption_revision_and_empty_reply_never_publish(self):
        for mode in ('corrupt', 'changed-tag', 'empty-reply', 'wrong-version'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.job = self.queue.create(self.entry['tag'])
                job = self.run_job()
                self.assertEqual(job['state'], 'failed')
                self.assertFalse(job['inference_ready'])
                self.assertFalse(artifacts.manifest_path(self.models, self.entry['tag']).exists())
                self.assertTrue(self.exited)

    def test_existing_starter_manifest_is_never_replaced(self):
        path = artifacts.manifest_path(self.models, self.entry['tag'])
        path.parent.mkdir(parents=True)
        path.write_bytes(b'original starter revision')
        job = self.run_job()
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(path.read_bytes(), b'original starter revision')
        self.assertEqual(self.requests, [])

    def test_cancel_during_verification_and_retry_after_interruption(self):
        def pause(job):
            if job['state'] == 'verifying':
                self.queue.request(job['id'], 'pause')
        job = self.run_job(callback=pause)
        self.assertEqual(job['state'], 'paused')
        self.assertTrue(self.exited)
        self.assertFalse(artifacts.manifest_path(self.models, self.entry['tag']).exists())
        self.queue.retry(job['id'])
        self.mode = 'interrupted'
        self.assertEqual(self.run_job()['state'], 'interrupted')
        reopened = OnboardingQueue(self.jobs, self.config, self.data)
        reopened.retry(job['id'])
        self.mode = 'ok'
        self.assertEqual(self.run_job()['state'], 'ready')

    def test_stale_testing_state_and_explicit_stopped_ack(self):
        from argoslive.pull_jobs import write_json
        job = self.queue.get(self.job['id'])
        job.update(state='testing', integrity_verified=True)
        write_json(self.queue.path(job['id']), job)
        self.assertEqual(self.queue.retry(job['id'])['state'], 'queued')
        with self.assertRaises(ValueError):
            self.queue.run_verified(job['id'])
        self.assertEqual(self.requests, [])

    def test_cli_read_only_status_and_control(self):
        from argoslive.pull_jobs import write_json
        state = self.root / 'state.json'
        write_json(state, self.config)
        self.jobs.rename(self.root / 'pull-jobs')
        with patch('builtins.print'):
            self.assertEqual(main(['--state', str(state), 'status', self.job['id']]), 0)
            self.assertEqual(main(['--state', str(state), 'pause', self.job['id']]), 0)
        self.assertEqual(self.requests, [])

    def test_registry_drift_blocks_backend_and_publication_checks_existing_blobs(self):
        with patch.object(artifacts, 'check_manifest', side_effect=ValueError('changed')):
            self.assertEqual(self.run_job()['state'], 'failed')
        self.assertEqual(self.requests, [])
        self.queue.retry(self.job['id'])
        blobs = self.models / 'blobs'
        blobs.mkdir()
        item = self.entry['artifacts'][0]
        path = artifacts.blob_path(self.models, item)
        path.write_bytes(b'corrupt')
        self.assertEqual(self.run_job()['state'], 'failed')
        self.assertEqual(path.read_bytes(), b'corrupt')
        self.assertFalse(artifacts.manifest_path(self.models, self.entry['tag']).exists())
