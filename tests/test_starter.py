from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog, model_verify, starter


class StarterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'seed'
        (self.root / 'blobs').mkdir(parents=True)
        self.data = copy.deepcopy(catalog.load())
        self.entry = next(entry for entry in self.data['models'] if entry['tag'] == starter.TAG)
        for item in self.entry['artifacts']:
            if item['media_type'].endswith('.license'):
                raw = (catalog.DEFAULT.parent / 'licenses' / (item['digest'][7:] + '.txt')).read_bytes()
            else:
                raw = ('Public starter fixture ' + item['media_type']).encode()
                item.update(size=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())
            (self.root / 'blobs' / item['digest'].replace(':', '-')).write_bytes(raw)
        self.entry['total_download_bytes'] = sum(item['size'] for item in self.entry['artifacts'])
        self.entry['weight_bytes'] = sum(item['size'] for item in self.entry['artifacts']
                                       if item['media_type'].endswith(('.model', '.projector')))
        descriptors = [{'digest': item['digest'], 'size': item['size'], 'mediaType': item['media_type']}
                       for item in self.entry['artifacts']]
        config = next(item for item in descriptors if item['mediaType'].endswith('.v1+json'))
        raw = json.dumps({'schemaVersion': 2, 'config': config,
                          'layers': [item for item in descriptors if item != config]}).encode()
        self.entry['manifest_digest'] = 'sha256:' + hashlib.sha256(raw).hexdigest()
        manifest = model_verify.manifest_path(self.root, starter.TAG)
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(raw)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_exact_integrity_without_writes_or_readonly_fsync(self):
        before = self.snapshot()
        with patch('argoslive.model_verify.os.fsync', side_effect=AssertionError('read-only fsync')):
            identity = starter.verify(self.root, data=self.data)
        self.assertEqual(identity['verified_bytes'], self.entry['total_download_bytes'])
        self.assertEqual(self.snapshot(), before)
        blob = model_verify.blob_path(self.root, self.entry['artifacts'][0])
        blob.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            starter.verify(self.root, data=self.data)

    def test_writable_source_refused_before_starting_daemon(self):
        with patch('argoslive.starter.owned') as backend:
            with self.assertRaisesRegex(ValueError, 'read-only'):
                with starter.serve(self.root, data=self.data):
                    self.fail('Writable source served')
            backend.assert_not_called()

    def test_inference_uses_source_and_separate_ephemeral_lease(self):
        before = self.snapshot()
        seen = {}
        class Client:
            def list(inner):
                return {'models': [{'name': starter.TAG, 'digest': self.entry['manifest_digest'][7:]}]}
        @contextmanager
        def backend(target, **options):
            seen.update(target=target, **options)
            self.assertTrue(options['lease_store'].is_dir())
            yield Client()
            seen['stopped'] = True
        with patch('argoslive.starter.os.access', return_value=False), patch('argoslive.starter.owned', backend):
            with starter.serve(self.root, data=self.data) as client:
                self.assertEqual(client.list()['models'][0]['name'], starter.TAG)
                self.assertEqual(seen['target'], self.root)
                self.assertNotEqual(seen['lease_store'], self.root)
        self.assertTrue(seen['stopped'])
        self.assertFalse(seen['lease_store'].exists())
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
