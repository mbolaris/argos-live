"""Verified image starter inference without copying or writing model files."""
from contextlib import contextmanager
import hashlib
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
    read_only(root, data=data)
    entry = next(entry for entry in (data or catalog.load())['models'] if entry['tag'] == TAG)
    with tempfile.TemporaryDirectory(prefix='argos-starter-') as temp:
        lease = Path(temp) / 'lease'
        lease.mkdir(mode=0o700)
        # Ollama 0.40 writes to its model directory, so serve a private shadow:
        # a copied manifest (a few KB) and blob links to the read-only image.
        shadow = Path(temp) / 'models'
        manifest = shadow / model_verify.manifest_path(root, TAG).relative_to(root)
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(model_verify.read_manifest(root, TAG))
        (shadow / 'blobs').mkdir()
        for item in entry['artifacts']:
            os.symlink(model_verify.blob_path(root, item), shadow / 'blobs' / item['digest'].replace(':', '-'))
        with owned(shadow, executable=executable, timeout=timeout, lease_store=lease) as client:
            raw = manifest.read_bytes()
            model_verify.check_local_manifest(raw, entry)
            served = hashlib.sha256(raw).hexdigest()
            # Ollama's API uses bare hex digests of the manifest it serves.
            if not any(model.get('name') == TAG and model.get('digest') in (served, 'sha256:' + served)
                       for model in client.list().get('models', [])):
                raise ValueError('Ollama starter identity differs from the verified image')
            yield client
