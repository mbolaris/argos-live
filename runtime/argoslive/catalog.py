"""Pinned public Ollama metadata and explicit full-context memory estimates."""
import json
import math
from pathlib import Path
import re

DEFAULT = Path(__file__).resolve().parent / 'data/catalog.json'
TAG = re.compile(r'(?:[a-z0-9][a-z0-9_-]*/)?[a-z0-9][a-z0-9_.-]*:[a-zA-Z0-9][a-zA-Z0-9_.-]*')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
LICENSE_DIGESTS = {'sha256:d18a5cc71b84bc4af394a31116bd3932b42241de70c77d2b76d69a314ec8aa12',
                   'sha256:7339fa418c9ad3e8e12e74ad0fd26a9cc4be8703f9c110728a992b193be85cb2',
                   'sha256:832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e'}


def positive(value):
    return type(value) is int and value > 0


def validate(data):
    if (not isinstance(data, dict) or data.get('schema') != 'argos-catalog/1'
            or not isinstance(data.get('models'), list) or not 8 <= len(data['models']) <= 12):
        raise ValueError('Expected an argos-catalog/1 with eight to twelve entries')
    tags = set()
    for entry in data['models']:
        if not isinstance(entry, dict):
            raise ValueError('Invalid catalog entry')
        tag = entry.get('tag')
        if (not isinstance(tag, str) or not TAG.fullmatch(tag) or tag in tags
                or 'cloud' in tag.rsplit(':', 1)[1].lower()):
            raise ValueError('Expected unique explicit local Ollama tags')
        tags.add(tag)
        for name in ('family', 'quantization', 'description', 'parameter_label', 'publisher_url'):
            if not isinstance(entry.get(name), str) or not entry[name]:
                raise ValueError('Missing model metadata: ' + name)
        if (entry.get('license') != 'Apache-2.0' or not positive(entry.get('parameter_count'))
                or not positive(entry.get('context_tokens')) or not positive(entry.get('weight_bytes'))
                or not positive(entry.get('total_download_bytes'))
                or not DIGEST.fullmatch(entry.get('manifest_digest', ''))):
            raise ValueError('Missing license, identity or numeric metadata')
        if (not isinstance(entry.get('capabilities'), list) or not entry['capabilities']
                or set(entry['capabilities']) - {'text', 'tools', 'thinking', 'vision'}
                or entry.get('capability_verified') is not False):
            raise ValueError('Capability claims must remain explicitly untested')
        artifacts = entry.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError('Missing artifact descriptors')
        seen, total, weights = set(), 0, 0
        for item in artifacts:
            if (not isinstance(item, dict) or not DIGEST.fullmatch(item.get('digest', ''))
                    or item['digest'] in seen or not positive(item.get('size'))
                    or not isinstance(item.get('media_type'), str)):
                raise ValueError('Invalid artifact descriptor')
            seen.add(item['digest'])
            total += item['size']
            if item['media_type'] in {'application/vnd.ollama.image.model', 'application/vnd.ollama.image.projector'}:
                weights += item['size']
        if total != entry['total_download_bytes'] or weights != entry['weight_bytes']:
            raise ValueError('Artifact byte totals differ')
        licenses = entry.get('license_digests')
        if (not isinstance(licenses, list) or not licenses or not set(licenses) <= LICENSE_DIGESTS or set(licenses) !=
                {a['digest'] for a in artifacts if a['media_type'] == 'application/vnd.ollama.image.license'}):
            raise ValueError('Missing license evidence')
        architecture = entry.get('kv_cache')
        if (not isinstance(architecture, dict) or
                any(not positive(architecture.get(k)) for k in ('layers', 'kv_heads', 'head_dim'))
                or architecture.get('bytes_per_element') != 2
                or not re.fullmatch(r'[a-f0-9]{64}', architecture.get('source_sha256', ''))
                or not re.fullmatch(r'https://huggingface.co/[^/]+/[^/]+/resolve/[a-f0-9]{40}/config.json',
                                    architecture.get('source_url', ''))):
            raise ValueError('Missing revision-pinned cache architecture')
    return data


def load(path=DEFAULT):
    with Path(path).open('r', encoding='utf-8') as stream:
        data = validate(json.load(stream))
    import hashlib
    for key in {key for m in data['models'] for key in m['license_digests']}:
        raw = (Path(path).parent / 'licenses' / (key.split(':')[1] + '.txt')).read_bytes()
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != key:
            raise ValueError('Packaged model license checksum mismatch')
    return data


def inventory(data):
    """Verified catalog identities only; this is NOT an installed-model inventory."""
    validate(data)
    return {m['tag']: {'verified': True, 'manifest_sha256': m['manifest_digest'].split(':')[1],
                      'quantization': m['quantization']} for m in data['models']}


def fit(entry, available_bytes, *, context_tokens=None, device='gpu'):
    if device not in {'gpu', 'cpu'}:
        raise ValueError('Use explicit GPU VRAM or CPU RAM capacity')
    context = entry['context_tokens'] if context_tokens is None else context_tokens
    if not positive(context):
        raise ValueError('Use a positive context-token count')
    cache = entry['kv_cache']
    kv = 2 * cache['layers'] * cache['kv_heads'] * cache['head_dim'] * cache['bytes_per_element'] * context
    overhead = max(512 * 1024**2, math.ceil(entry['weight_bytes'] * 0.10))
    if 'vision' in entry['capabilities']:
        overhead += 512 * 1024**2
    required = entry['weight_bytes'] + kv + overhead
    comfortable = math.ceil(required * 1.10)
    if available_bytes is None:
        status, reason = 'unknown', 'Available memory not measured'
    elif type(available_bytes) is not int or available_bytes < 0:
        raise ValueError('Use nonnegative measured available memory')
    elif available_bytes < required:
        status, reason = "won't fit", 'Estimated weights, full-context KV cache and overhead exceed available memory'
    elif available_bytes < comfortable:
        status, reason = 'tight', 'Estimate fits with less than ten percent headroom'
    else:
        status, reason = 'fits', 'Estimate fits with at least ten percent headroom'
    return {'status': status, 'reason': reason, 'device': device, 'available_bytes': available_bytes,
            'weight_bytes': entry['weight_bytes'], 'kv_cache_bytes': kv, 'overhead_bytes': overhead,
            'estimated_required_bytes': required, 'comfortable_bytes': comfortable,
            'context_tokens': context, 'estimate': True, 'inference_ready': False,
            'method': 'All weights plus full f16 K/V cache plus overhead; no split-offload prediction'}
