import json
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import catalog, model_verify, starter
from argoslive.pull_jobs import Queue, write_json
from argoslive.web import models


class ModelViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = self.home / 'store'
        self.store.mkdir()
        (self.store / '.argos-storage-id').write_text('fixture-owner')
        self.configured = {'storage': str(self.store), 'storage_id': 'fixture-owner'}
        self.state = self.home / '.config/argos-live/state.json'
        self.state.parent.mkdir(parents=True)
        self.state.write_text(json.dumps(self.configured))
        self.data = catalog.load()
        self.hardware = lambda: {'ram': {'available_bytes': None}, 'gpus': None}

    def snapshot(self):
        return models.snapshot(self.home, data=self.data, hardware=self.hardware, seed=self.home / 'seed')

    def seed_fixture(self):
        root = self.home / 'seed'
        (root / 'blobs').mkdir(parents=True)
        self.data = copy.deepcopy(self.data)
        entry = next(item for item in self.data['models'] if item['tag'] == starter.TAG)
        for item in entry['artifacts']:
            if item['media_type'].endswith('.license'):
                raw = (catalog.DEFAULT.parent / 'licenses' / (item['digest'][7:] + '.txt')).read_bytes()
            else:
                raw = ('Public dashboard fixture ' + item['media_type']).encode()
                item.update(size=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())
            model_verify.blob_path(root, item).write_bytes(raw)
        entry['total_download_bytes'] = sum(item['size'] for item in entry['artifacts'])
        entry['weight_bytes'] = sum(item['size'] for item in entry['artifacts'] if item['media_type'].endswith('.model'))
        descriptors = [{'digest': item['digest'], 'size': item['size'], 'mediaType': item['media_type']}
                       for item in entry['artifacts']]
        config = next(item for item in descriptors if item['mediaType'].endswith('.v1+json'))
        raw = json.dumps({'schemaVersion': 2, 'config': config,
                          'layers': [item for item in descriptors if item != config]}).encode()
        entry['manifest_digest'] = 'sha256:' + hashlib.sha256(raw).hexdigest()
        manifest = model_verify.manifest_path(root, starter.TAG)
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(raw)
        return root, entry

    def test_bundled_starter_separate_from_empty_selected_store_no_hash_or_writes(self):
        root, entry = self.seed_fixture()
        self.configured.update(model_source='bundled', model=starter.TAG)
        self.state.write_text(json.dumps(self.configured))
        before = {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()}
        with patch('argoslive.web.models.os.access', return_value=False), patch.object(model_verify, 'verify', side_effect=AssertionError('expensive hash')):
            result = self.snapshot()
        self.assertEqual(result['selected_source'], 'bundled')
        self.assertEqual(result['installed'], [])
        self.assertEqual(result['bundled']['state'], 'available')
        row = result['bundled']['models'][0]
        self.assertEqual(row['tag'], starter.TAG)
        self.assertFalse(row['artifact_hashes_verified'])
        self.assertFalse(row['inference_ready'])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()})
        # Bundled metadata remains visible if selected storage is unavailable;
        # this does not permit a fallback store or automatic service startup.
        (self.store / '.argos-storage-id').unlink()
        with patch('argoslive.web.models.os.access', return_value=False):
            result = self.snapshot()
        self.assertEqual(result['bundled']['state'], 'available')
        self.assertEqual(result['storage_state'], 'needs-attention')
        self.assertIsNone(result['selected_source'])

    def test_bad_or_writable_bundled_source_does_not_appear_available(self):
        root, entry = self.seed_fixture()
        self.assertEqual(self.snapshot()['bundled']['state'], 'needs-attention')
        model_verify.blob_path(root, entry['artifacts'][0]).unlink()
        with patch('argoslive.web.models.os.access', return_value=False):
            result = self.snapshot()
        self.assertEqual(result['bundled']['state'], 'needs-attention')
        self.assertFalse(result['bundled']['models'][0]['files_present'])

    def test_unknown_model_source_and_nonstarter_bundled_selection_need_attention(self):
        for fields in ({'model_source': 'network-store'}, {'model_source': 'bundled', 'model': 'other:small'}):
            self.state.write_text(json.dumps(dict(self.configured, **fields)))
            result = self.snapshot()
            self.assertEqual(result['storage_state'], 'needs-attention')
            self.assertIsNone(result['selected_source'])

    def test_missing_setup_is_unknown_not_empty_installed(self):
        self.state.unlink()
        result = self.snapshot()
        self.assertEqual(result['storage_state'], 'not-configured')
        self.assertIsNone(result['installed'])
        self.assertIsNone(result['jobs'])
        self.assertGreaterEqual(len(result['catalog']), 8)
        self.assertTrue(all(row['gpu_fit']['status'] == 'unknown' for row in result['catalog']))

    def test_missing_storage_marker_has_no_fallback(self):
        (self.store / '.argos-storage-id').unlink()
        result = self.snapshot()
        self.assertEqual(result['storage_state'], 'needs-attention')
        self.assertIsNone(result['installed'])
        self.assertFalse((self.state.parent / 'pull-jobs').exists())

    def test_manifest_presence_is_not_hash_or_inference_verification(self):
        manifest = self.store / 'manifests/registry.ollama.ai/library/fixture/small'
        manifest.parent.mkdir(parents=True)
        digest = 'sha256:' + 'a' * 64
        manifest.write_text(json.dumps({'schemaVersion': 2,
            'config': {'digest': digest, 'size': 3}, 'layers': []}))
        blobs = self.store / 'blobs'
        blobs.mkdir()
        (blobs / digest.replace(':', '-')).write_bytes(b'abc')
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        model = self.snapshot()['installed'][0]
        self.assertEqual(model['tag'], 'fixture:small')
        self.assertTrue(model['files_present'])
        self.assertFalse(model['catalog_manifest_match'])
        self.assertFalse(model['artifact_hashes_verified'])
        self.assertFalse(model['inference_ready'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        (blobs / digest.replace(':', '-')).unlink()
        self.assertFalse(self.snapshot()['installed'][0]['files_present'])

    def test_corrupt_manifest_omitted_with_reason_count(self):
        manifest = self.store / 'manifests/registry.ollama.ai/library/fixture/small'
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{invalid')
        result = self.snapshot()
        self.assertEqual(result['installed'], [])
        self.assertEqual(result['invalid_manifests'], 1)

    def queue(self):
        root = self.state.parent / 'pull-jobs'
        root.mkdir(mode=0o700)
        return Queue(root, self.configured, self.data)

    def test_job_projection_excludes_identity_and_private_errors(self):
        queue = self.queue()
        job = queue.create(self.data['models'][0]['tag'])
        job['error'] = 'fictional secret must not appear'
        job['progress']['bytes_done'] = 42
        job['progress']['recent_mib_per_second'] = 2.5
        job['progress']['eta_seconds'] = 100
        write_json(queue.path(job['id']), job)
        result = self.snapshot()
        self.assertEqual(len(result['jobs']), 1)
        progress = result['jobs'][0]['progress']
        self.assertEqual(progress['bytes_done'], 42)
        self.assertEqual(progress['recent_mib_per_second'], 2.5)
        self.assertNotIn('fictional secret', json.dumps(result))
        self.assertNotIn('fixture-owner', json.dumps(result))
        self.assertNotIn('storage', result['jobs'][0])

    def test_stale_ready_receipt_rejected_and_current_readiness_not_claimed(self):
        queue = self.queue()
        job = queue.create(self.data['models'][0]['tag'])
        job.update(state='ready', integrity_verified=True, inference_ready=True)
        write_json(queue.path(job['id']), job)
        row = self.snapshot()['jobs'][0]
        self.assertTrue(row['previous_reply_verified'])
        self.assertFalse(row['current_readiness_verified'])
        job['storage']['marker'] = 'different-store'
        write_json(queue.path(job['id']), job)
        result = self.snapshot()
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['invalid_jobs'], 1)

    def test_invalid_progress_does_not_appear_as_success(self):
        queue = self.queue()
        job = queue.create(self.data['models'][0]['tag'])
        job['progress']['bytes_done'] = job['progress']['bytes_total'] + 1
        write_json(queue.path(job['id']), job)
        result = self.snapshot()
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['invalid_jobs'], 1)

    def test_gpu_fit_uses_one_device_not_sum_of_cards(self):
        result = models.snapshot(self.home, data=self.data,
            hardware=lambda: {'ram': {'available_bytes': 16 * 2**30}, 'gpus': [
                {'vram_total_bytes': 8 * 2**30, 'vram_used_bytes': 2 * 2**30},
                {'vram_total_bytes': 8 * 2**30, 'vram_used_bytes': 1 * 2**30}]})
        self.assertTrue(all(row['gpu_fit']['available_bytes'] == 7 * 2**30 for row in result['catalog']))
        self.assertTrue(all(row['gpu_fit']['estimate'] for row in result['catalog']))
