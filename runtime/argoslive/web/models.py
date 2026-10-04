"""Read-only Ollama store/catalog/job projection; no pulls or inference."""
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path

from argoslive import catalog, hw, model_verify, starter, storage
from argoslive.pull_jobs import ID, Queue
from argoslive.web.status import read_json


def present_models(root, data):
    selected = {entry['tag']: entry for entry in data['models']}
    result = []
    invalid = 0
    manifests = storage.safe_local(root / 'manifests/registry.ollama.ai')
    paths = list(islice(manifests.glob('*/*/*'), 1025))
    for path in paths[:1024]:
        try:
            namespace, name, revision = path.relative_to(manifests).parts
            tag = (name if namespace == 'library' else namespace + '/' + name) + ':' + revision
            if not catalog.TAG.fullmatch(tag):
                raise ValueError('Unsupported tag')
            raw = model_verify.read_manifest(root, tag)
            manifest = json.loads(raw)
            if manifest.get('schemaVersion') != 2 or not isinstance(manifest.get('layers'), list):
                raise ValueError('Invalid manifest')
            descriptors = [manifest['config'], *manifest['layers']]
            if len(descriptors) > 512:
                raise ValueError('Too many descriptors')
            complete = True
            for item in descriptors:
                if not catalog.DIGEST.fullmatch(item.get('digest', '')) or not catalog.positive(item.get('size')):
                    raise ValueError('Invalid artifact')
                blob = model_verify.blob_path(root, item)
                if not blob.is_file() or blob.stat().st_size != item['size']:
                    complete = False
            match = False
            if tag in selected:
                try:
                    model_verify.check_manifest(raw, selected[tag])
                    match = True
                except ValueError:
                    pass
            result.append({'tag': tag, 'manifest_digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                           'files_present': complete, 'catalog_manifest_match': match,
                           'artifact_hashes_verified': False, 'inference_ready': False})
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            invalid += 1
    return result, invalid, len(paths) > 1024


def jobs(root, configured, data, selected_path):
    if not root.exists():
        return [], 0, False
    queue = Queue(root, configured, data, validate=lambda _: selected_path)
    paths = list(islice(root.glob('*.json'), 257))
    result, invalid = [], 0
    for path in paths[:256]:
        if not ID.fullmatch(path.stem):
            continue  # Control files are not job receipts.
        try:
            job = queue.get(path.stem)
            entry = queue.check(job)
            source = job['progress']
            total, done = source['bytes_total'], source['bytes_done']
            if total != entry['total_download_bytes'] or type(done) is not int or not 0 <= done <= total:
                raise ValueError('Invalid progress')
            progress = {'bytes_done': done, 'bytes_total': total}
            for key in ('recent_mib_per_second', 'eta_seconds'):
                value = source.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                    raise ValueError('Invalid measurement')
                progress[key] = value
            result.append({'id': job['id'], 'tag': job['tag'], 'state': job['state'],
                           'attempts': job['attempts'], 'progress': progress,
                           'previous_reply_verified': job['inference_ready'],
                           'current_readiness_verified': False})
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            invalid += 1
    return result, invalid, len(paths) > 256


def bundled_source(root, data):
    """Cheap image metadata only: full integrity and inference are separate gates."""
    result = {'state': 'missing', 'models': [], 'read_only': None}
    try:
        root = storage.safe_local(root)
        if not root.exists():
            return result
        rows, invalid, truncated = present_models(root, data)
        rows = [row for row in rows if row['tag'] == starter.TAG]
        entry = next(entry for entry in data['models'] if entry['tag'] == starter.TAG)
        manifest = model_verify.manifest_path(root, starter.TAG)
        paths = {root, root / 'blobs', manifest, *manifest.parents}
        paths = {path for path in paths if path == root or root in path.parents}
        paths.update(model_verify.blob_path(root, item) for item in entry['artifacts'])
        read_only = not any(os.access(path, os.W_OK) for path in paths)
        valid = (not invalid and not truncated and len(rows) == 1 and
                 rows[0]['files_present'] and rows[0]['catalog_manifest_match'] and read_only)
        result.update(state='available' if valid else 'needs-attention',
                      models=rows, read_only=read_only)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration):
        result.update(state='needs-attention', models=[], read_only=None)
    return result


def snapshot(home=None, *, data=None, hardware=hw.snapshot, validate=storage.validate_configured,
             seed=starter.ROOT):
    home = Path.home() if home is None else Path(home)
    data = catalog.load() if data is None else catalog.validate(data)
    state_path = home / '.config/argos-live/state.json'
    result = {'schema': 'argos-models-view/1', 'storage_state': 'not-configured',
              'installed': None, 'jobs': None, 'catalog': [], 'invalid_manifests': 0,
              'invalid_jobs': 0, 'truncated': False, 'read_only': True}
    result['bundled'] = bundled_source(seed, data)
    result['selected_source'] = None
    try:
        configured = read_json(state_path)
        root = validate(configured)
        source = configured.get('model_source') or 'managed'
        if source not in ('managed', 'bundled') or (source == 'bundled' and configured.get('model') != starter.TAG):
            raise ValueError('Unexpected configured model source')
        result['selected_source'] = source
        result['storage_state'] = 'available'
        result['installed'], result['invalid_manifests'], truncated = present_models(root, data)
        result['truncated'] = truncated
        result['jobs'], result['invalid_jobs'], truncated = jobs(state_path.parent / 'pull-jobs', configured, data, root)
        result['truncated'] |= truncated
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result.update(storage_state='needs-attention', installed=None, jobs=None)
    measured = hardware()
    ram = measured.get('ram', {}).get('available_bytes')
    gpus = measured.get('gpus')
    capacities = [g['vram_total_bytes'] - g['vram_used_bytes'] for g in (gpus or [])
                  if type(g.get('vram_total_bytes')) is int and type(g.get('vram_used_bytes')) is int
                  and g['vram_total_bytes'] >= g['vram_used_bytes']]
    vram = max(capacities) if capacities else None  # Never sum separate GPUs.
    for entry in data['models']:
        result['catalog'].append({key: entry[key] for key in ('tag', 'description', 'parameter_label',
            'quantization', 'context_tokens', 'total_download_bytes', 'weight_bytes', 'license', 'capabilities')})
        result['catalog'][-1].update(cpu_fit=catalog.fit(entry, ram, device='cpu'),
                                    gpu_fit=catalog.fit(entry, vram, device='gpu'))
    return result
