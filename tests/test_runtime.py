import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('argos', Path(__file__).parents[1] / 'runtime/argos.py')
argos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(argos)

class StorageTests(unittest.TestCase):
    def test_missing_storage_never_created(self):
        with tempfile.TemporaryDirectory() as t:
            state = Path(t) / 'state.json'
            target = Path(t) / 'missing'
            argos.save(state, {'storage': str(target), 'storage_id': 'expected', 'model': 'x'})
            previous = argos.STATE
            argos.STATE = state
            try:
                with self.assertRaisesRegex(ValueError, 'missing'):
                    argos.load()
                self.assertFalse(target.exists())
            finally:
                argos.STATE = previous

    def test_wrong_storage_identity_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(t)
            (target / '.argos-storage-id').write_text('wrong')
            state = target / 'state.json'
            argos.save(state, {'storage': t, 'storage_id': 'expected'})
            previous = argos.STATE
            argos.STATE = state
            try:
                with self.assertRaisesRegex(ValueError, 'identity'):
                    argos.load()
            finally:
                argos.STATE = previous

    def test_free_space_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, 'Insufficient'):
                argos.probe_storage(t, 2**90)

    def test_corrupt_model_blob_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / 'manifests').mkdir()
            (root / 'blobs').mkdir()
            digest = hashlib.sha256(b'correct').hexdigest()
            blob = root / 'blobs' / ('sha256-' + digest)
            blob.write_bytes(b'correct')
            (root / 'manifests' / 'model').write_text(json.dumps({'config': {'digest': 'sha256:' + digest}, 'layers': []}))
            self.assertEqual(argos.verify_blobs(root), 1)
            blob.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                argos.verify_blobs(root)

if __name__ == '__main__':
    unittest.main()
