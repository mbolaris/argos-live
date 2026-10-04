"""Exact catalog revision/artifact verification and non-destructive publication."""
import hashlib
import json
import os
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
    if len(raw) > LIMIT or 'sha256:' + hashlib.sha256(raw).hexdigest() != entry['manifest_digest']:
        raise ValueError('Manifest revision differs from reviewed catalog')
    value = json.loads(raw)
    if value.get('schemaVersion') != 2 or not isinstance(value.get('layers'), list):
        raise ValueError('Invalid model manifest')
    descriptors = {}
    for item in [value['config'], *value['layers']]:
        descriptor = {'digest': item['digest'], 'size': item['size'], 'media_type': item['mediaType']}
        if item['digest'] in descriptors and descriptors[item['digest']] != descriptor:
            raise ValueError('Conflicting manifest descriptors')
        descriptors[item['digest']] = descriptor
    if descriptors != {a['digest']: a for a in entry['artifacts']}:
        raise ValueError('Manifest descriptors differ from reviewed catalog')
    return raw


def blob_path(root, item):
    return storage.safe_local(Path(root) / 'blobs' / item['digest'].replace(':', '-'))


def verify_blob(path, item, cancel=None, progress=None):
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
    if 'sha256:' + digest.hexdigest() != item['digest']:
        raise ValueError('Artifact checksum mismatch')


def verify(root, entry, cancel=None, progress=None):
    check_manifest(read_manifest(root, entry['tag']), entry)
    checked = 0
    for item in entry['artifacts']:
        verify_blob(blob_path(root, item), item, cancel,
                    lambda n: progress(checked + n) if progress else None)
        checked += item['size']
    return checked


def publish(stage, target, entry, cancel=None):
    """Publish immutable blobs first; manifest last. Never change an existing tag.

    Interrupted publication leaves reusable complete blobs, never a partial
    manifest. Cooperating workers must hold the store-wide lock while publishing.
    """
    destination = manifest_path(target, entry['tag'])
    raw = read_manifest(stage, entry['tag'])
    check_manifest(raw, entry)
    if destination.exists():
        check_manifest(read_manifest(target, entry['tag']), entry)
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage.safe_local(destination)
    if not destination.exists():
        # Link the already fsynced verified raw manifest, never replace a tag.
        os.link(manifest_path(stage, entry['tag']), destination)
    verify(target, entry, cancel)
