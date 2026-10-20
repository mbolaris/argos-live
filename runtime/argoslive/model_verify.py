"""Exact catalog revision/artifact verification and non-destructive publication."""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.request import build_opener, ProxyHandler, Request

from . import catalog, storage
from .ollama import NoRedirect, Cancelled
from .pull_jobs import LIMIT


def manifest_path(root, tag):
    if not catalog.TAG.fullmatch(tag):
        raise ValueError('Expected an explicit catalog tag')
    name, revision = tag.rsplit(':', 1)
    namespace, name = name.split('/') if '/' in name else ('library', name)
    return storage.safe_local(Path(root) / 'manifests/registry.ollama.ai' / namespace / name / revision)


def registry_revision(entry):
    name, revision = entry['tag'].rsplit(':', 1)
    repository = name if '/' in name else 'library/' + name
    url = f'https://registry.ollama.ai/v2/{repository}/manifests/{revision}'
    with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url), timeout=30) as response:
        raw = response.read(LIMIT + 1)
    check_manifest(raw, entry)
    return raw


def read_manifest(root, tag):
    with manifest_path(root, tag).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Manifest exceeds metadata limit')
    return raw


def check_manifest(raw, entry):
    """Registry bytes must be exactly the reviewed revision."""
    if len(raw) > LIMIT or 'sha256:' + hashlib.sha256(raw).hexdigest() != entry['manifest_digest']:
        raise ValueError('Manifest revision differs from reviewed catalog')
    return check_local_manifest(raw, entry)


def check_local_manifest(raw, entry, root=None):
    """A stored manifest must describe exactly the reviewed artifacts.

    Ollama 0.40 re-serializes manifests it stores, so their bytes no longer hash
    to the registry revision. Every descriptor (digest, size, media type) must
    still match the catalog, and verify() checks each blob's SHA256.
    """
    if len(raw) > LIMIT:
        raise ValueError('Manifest exceeds metadata limit')
    value = json.loads(raw)
    if value.get('schemaVersion') != 2 or not isinstance(value.get('layers'), list):
        raise ValueError('Invalid model manifest')
    descriptors = {}
    for item in [value['config'], *value['layers']]:
        descriptor = {'digest': item['digest'], 'size': item['size'], 'media_type': item['mediaType']}
        if item['digest'] in descriptors and descriptors[item['digest']] != descriptor:
            raise ValueError('Conflicting manifest descriptors')
        descriptors[item['digest']] = descriptor
    expected = {a['digest']: a for a in entry['artifacts']}
    # Ollama 0.40 also records the registry manifest it pulled. Accept that one
    # extra descriptor only when it is exactly the reviewed manifest revision.
    reference = descriptors.get(entry.get('manifest_digest'))
    if (reference and reference['media_type'] == 'application/vnd.docker.distribution.manifest.v2+json'
            and entry['manifest_digest'] not in expected):
        descriptors.pop(entry['manifest_digest'])
    # For tags with several variants it also records the registry's manifest
    # list. Accept it only when the stored list document is intact and selects
    # the reviewed manifest revision.
    for digest, item in list(descriptors.items()):
        if item['media_type'] == LIST_TYPE and digest not in expected and root is not None and listed(root, item, entry):
            descriptors.pop(digest)
    if descriptors != expected:
        changed = sorted(f"{d[7:19]} {expected[d]['media_type']}->{descriptors[d]['media_type']} "
                         f"{expected[d]['size']}->{descriptors[d]['size']}"
                         for d in descriptors.keys() & expected.keys() if descriptors[d] != expected[d])
        raise ValueError('Manifest descriptors differ from reviewed catalog: ' + json.dumps({
            'missing': sorted(expected[d]['media_type'] for d in expected.keys() - descriptors.keys()),
            'extra': sorted(descriptors[d]['media_type'] for d in descriptors.keys() - expected.keys()),
            'changed': changed}))
    return raw


LIST_TYPE = 'application/vnd.ollama.manifest.list.v2+json'


def listed(root, item, entry):
    path = blob_path(root, item)
    try:
        raw = path.read_bytes() if path.stat().st_size <= LIMIT else b''
    except OSError:
        return False
    if 'sha256:' + hashlib.sha256(raw).hexdigest() != item['digest'] or len(raw) != item['size']:
        return False
    try:
        value = json.loads(raw)
    except ValueError:
        return False
    return (value.get('mediaType') == LIST_TYPE and isinstance(value.get('manifests'), list)
            and any(isinstance(m, dict) and m.get('digest') == entry['manifest_digest'] for m in value['manifests']))


def blob_path(root, item):
    return storage.safe_local(Path(root) / 'blobs' / item['digest'].replace(':', '-'))


def verify_blob(path, item, cancel=None, progress=None, *, sync=True):
    path = storage.safe_local(path)
    if not path.is_file() or path.stat().st_size != item['size']:
        raise ValueError('Missing or incorrectly sized artifact')
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            if cancel and cancel.is_set():
                raise Cancelled('Verification paused')
            digest.update(chunk)
            count += len(chunk)
            if progress:
                progress(count)
        if sync and os.name != 'nt':
            os.fsync(stream.fileno())
    if 'sha256:' + digest.hexdigest() != item['digest']:
        raise ValueError('Artifact checksum mismatch')


def verify(root, entry, cancel=None, progress=None, *, sync=True, include_identity=False):
    raw_manifest = read_manifest(root, entry['tag'])
    check_local_manifest(raw_manifest, entry, root)
    checked = 0
    for item in entry['artifacts']:
        verify_blob(blob_path(root, item), item, cancel,
                    lambda n: progress(checked + n) if progress else None, sync=sync)
        checked += item['size']
    if include_identity:
        return identity_receipt(entry, raw_manifest, checked)
    return checked


def identity_receipt(entry, raw_manifest, verified_bytes):
    """Describe the exact catalog artifacts whose bytes were just verified.

    ``verify`` calls this only after hashing every blob. The transcript gets
    the full expected artifact identities without copying model weights into
    the Proctor database.
    """
    expected_bytes = sum(item['size'] for item in entry['artifacts'])
    if type(verified_bytes) is not int or verified_bytes != expected_bytes:
        raise ValueError('Model identity requires complete catalog blob verification')
    check_local_manifest(raw_manifest, entry)
    value = {
        'schema': 'argos-verified-model/1',
        'tag': entry['tag'],
        'catalog_manifest_digest': entry['manifest_digest'],
        'local_manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(),
        'artifacts': sorted(
            ({'digest': item['digest'], 'size': item['size'], 'media_type': item['media_type']}
             for item in entry['artifacts']),
            key=lambda item: item['digest']),
        'verified_bytes': verified_bytes,
    }
    value['verification'] = 'catalog manifest and every declared model blob SHA-256 verified'
    unsigned = {key: item for key, item in value.items() if key != 'sha256'}
    value['sha256'] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return value


def validate_identity_receipt(value, expected_tag):
    """Validate the canonical, complete receipt embedded in a Proctor subject."""
    if not isinstance(value, dict) or value.get('schema') != 'argos-verified-model/1':
        raise ValueError('A fully verified catalog model identity is required for Proctor')
    if value.get('tag') != expected_tag:
        raise ValueError('Proctor model identity tag does not match the selected model')
    if (not isinstance(value.get('catalog_manifest_digest'), str) or
            not re.fullmatch(r'sha256:[0-9a-f]{64}', value['catalog_manifest_digest']) or
            not isinstance(value.get('local_manifest_sha256'), str) or
            not re.fullmatch(r'[0-9a-f]{64}', value['local_manifest_sha256'])):
        raise ValueError('Proctor model identity manifest digests are invalid')
    artifacts = value.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError('Proctor model identity has no verified artifacts')
    if any(not isinstance(item, dict) or
           not isinstance(item.get('digest'), str) or
           not re.fullmatch(r'sha256:[0-9a-f]{64}', item['digest']) or
           type(item.get('size')) is not int or item['size'] <= 0 or
           not isinstance(item.get('media_type'), str) or not item['media_type']
           for item in artifacts):
        raise ValueError('Proctor model identity has an invalid artifact descriptor')
    if artifacts != sorted(artifacts, key=lambda item: item['digest']):
        raise ValueError('Proctor model identity artifacts are not in canonical order')
    verified_bytes = value.get('verified_bytes')
    if type(verified_bytes) is not int or verified_bytes != sum(item['size'] for item in artifacts):
        raise ValueError('Proctor model identity does not represent complete blob verification')
    if value.get('verification') != 'catalog manifest and every declared model blob SHA-256 verified':
        raise ValueError('Proctor model identity verification claim is invalid')
    unsigned = {key: item for key, item in value.items() if key != 'sha256'}
    expected_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    if value.get('sha256') != expected_hash:
        raise ValueError('Proctor model identity receipt checksum is invalid')
    return value


def publish(stage, target, entry, cancel=None):
    """Publish immutable blobs first; manifest last. Never change an existing tag.

    Interrupted publication leaves reusable complete blobs, never a partial
    manifest. Cooperating workers must hold the store-wide lock while publishing.
    """
    destination = manifest_path(target, entry['tag'])
    raw = read_manifest(stage, entry['tag'])
    check_local_manifest(raw, entry, stage)
    if destination.exists():
        check_local_manifest(read_manifest(target, entry['tag']), entry, target)
    blobs = storage.safe_local(Path(target) / 'blobs')
    blobs.mkdir(exist_ok=True)
    for item in entry['artifacts']:
        if cancel and cancel.is_set():
            raise Cancelled('Publication paused')
        source, dest = blob_path(stage, item), blob_path(target, item)
        if dest.exists():
            verify_blob(dest, item, cancel)
        else:
            # Staging is on the same filesystem. Hard-link publication is atomic
            # and fails if another writer created the destination in the meantime.
            os.link(source, dest)
    # A verified manifest list the stored manifest names travels with it.
    for item in json.loads(raw)['layers']:
        if (item.get('mediaType') == LIST_TYPE and listed(stage, item, entry)
                and not blob_path(target, item).exists()):
            os.link(blob_path(stage, item), blob_path(target, item))
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage.safe_local(destination)
    if not destination.exists():
        # Link the already fsynced verified raw manifest, never replace a tag.
        os.link(manifest_path(stage, entry['tag']), destination)
    verify(target, entry, cancel)
    if os.name != 'nt':
        for path in (blobs, destination.parent):
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
