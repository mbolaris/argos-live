"""Verified image starter inference without copying or writing model files."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

from . import catalog, model_verify
from .owned_ollama import owned
from .storage import safe_local

ROOT = Path('/usr/local/share/argos-live/seed-model')
TAG = 'qwen3:0.6b'


def verify(root=ROOT, *, data=None):
    """Check the exact reviewed manifest and every blob; no fsync on SquashFS."""
    root = safe_local(root)
    data = catalog.validate(data) if data is not None else catalog.load()
    entry = next((entry for entry in data['models'] if entry['tag'] == TAG), None)
    if entry is None:
        raise ValueError('Reviewed starter model is missing from the catalog')
    count = model_verify.verify(root, entry, sync=False)
    return {'tag': TAG, 'manifest_digest': entry['manifest_digest'], 'verified_bytes': count}


def read_only(root=ROOT, *, data=None):
    """Verify both content identity and an unwritable model source."""
    root = safe_local(root)
    identity = verify(root, data=data)
    entry = next(entry for entry in (data or catalog.load())['models'] if entry['tag'] == TAG)
    manifest = model_verify.manifest_path(root, TAG)
    paths = {root, root / 'blobs', *manifest.parents}
    # Only ancestors inside the seed are part of the immutable model tree.
    paths = {path for path in paths if path == root or root in path.parents}
    paths.add(manifest)
    paths.update(model_verify.blob_path(root, item) for item in entry['artifacts'])
    if any(os.access(path, os.W_OK) for path in paths):
        raise ValueError('Starter source must be read-only to the inference user')
    return identity


@contextmanager
def serve(root=ROOT, *, executable=None, data=None, timeout=60):
    """Own inference on image weights, with private temporary process leases."""
    root = safe_local(root)
    identity = read_only(root, data=data)
    with tempfile.TemporaryDirectory(prefix='argos-starter-') as lease:
        with owned(root, executable=executable, timeout=timeout, lease_store=Path(lease)) as client:
            models = client.list().get('models', [])
            expected = identity['manifest_digest']
            # Ollama's API uses bare hex; catalog descriptors include sha256:.
            if not any(model.get('name') == TAG and model.get('digest') in (expected, expected[7:])
                       for model in models):
                raise ValueError('Ollama starter identity differs from the verified image')
            yield client
