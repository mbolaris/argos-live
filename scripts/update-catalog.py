#!/usr/bin/env python3
"""Refresh public metadata into a reviewed catalog; never download weight blobs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlparse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog

LIMIT = 1024**2
PUBLIC_HOSTS = {'registry.ollama.ai', 'huggingface.co',
                'dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com'}


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if urlparse(newurl).hostname not in PUBLIC_HOSTS or not newurl.startswith('https://'):
            raise ValueError('Unexpected metadata redirect')
        return super().redirect_request(request, response, code, message, headers, newurl)


def fetch(url):
    if urlparse(url).hostname not in {'registry.ollama.ai', 'huggingface.co'} or not url.startswith('https://'):
        raise ValueError('Use the approved public metadata hosts')
    request = urllib.request.Request(url, headers={'User-Agent': 'argos-live-catalog/1'})
    with urllib.request.build_opener(PublicRedirect()).open(request, timeout=30) as response:
        # Hub config redirects may use its cache path on the same public host.
        if urlparse(response.url).hostname not in PUBLIC_HOSTS:
            raise ValueError('Unexpected metadata redirect')
        raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Metadata exceeds bounded download limit')
        return raw, dict(response.headers)


def checked_blob(repository, item, get):
    if not catalog.DIGEST.fullmatch(item.get('digest', '')) or not catalog.positive(item.get('size')):
        raise ValueError('Invalid metadata blob descriptor')
    if item['size'] > LIMIT:
        raise ValueError('Metadata blob is too large; weights are never fetched')
    raw, _ = get('https://registry.ollama.ai/v2/' + repository + '/blobs/' + item['digest'])
    if len(raw) != item['size'] or 'sha256:' + hashlib.sha256(raw).hexdigest() != item['digest']:
        raise ValueError('Metadata blob checksum/size mismatch')
    return raw


def build(spec, get=fetch):
    if (not isinstance(spec, dict) or spec.get('schema') != 'argos-catalog-spec/1' or
            not isinstance(spec.get('models'), list) or not 1 <= len(spec['models']) <= 24):
        raise ValueError('Expected a reviewed catalog specification with between 1 and 24 models')
    entries, license_texts = [], {}
    for choice in spec['models']:
        tag = choice['tag']
        if not catalog.TAG.fullmatch(tag) or 'cloud' in tag.rsplit(':', 1)[1].lower():
            raise ValueError('Only explicit local Ollama tags are allowed')
        name, revision = tag.rsplit(':', 1)
        repository = name if '/' in name else 'library/' + name
        raw, headers = get('https://registry.ollama.ai/v2/' + repository + '/manifests/' + revision)
        manifest_digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        reported = next((v for k, v in headers.items() if k.lower() == 'docker-content-digest'), None)
        if reported and reported != manifest_digest:
            raise ValueError('Registry manifest digest differs')
        manifest = json.loads(raw)
        config = json.loads(checked_blob(repository, manifest['config'], get))
        if config.get('model_format') != 'gguf' or config.get('model_family') != choice['family']:
            raise ValueError('Model family/format changed; review the catalog specification')
        if config.get('file_type') != choice['quantization']:
            raise ValueError('Quantization changed; review the catalog specification')
        parameter = re.fullmatch(r'(\d+(?:\.\d+)?)([BM])', config.get('model_type', ''))
        if not parameter:
            raise ValueError('Missing registry parameter-count metadata')
        count = round(float(parameter[1]) * (10**9 if parameter[2] == 'B' else 10**6))
        artifacts = {}
        for item in [manifest['config'], *manifest['layers']]:
            if not catalog.DIGEST.fullmatch(item.get('digest', '')) or not catalog.positive(item.get('size')):
                raise ValueError('Missing artifact identity/size')
            descriptor = {'digest': item['digest'], 'size': item['size'], 'media_type': item['mediaType']}
            if item['digest'] in artifacts and artifacts[item['digest']] != descriptor:
                raise ValueError('Conflicting duplicate artifact descriptors')
            artifacts[item['digest']] = descriptor
        licenses = []
        for item in artifacts.values():
            if item['media_type'] == 'application/vnd.ollama.image.license':
                if item['digest'] not in catalog.LICENSE_DIGESTS:
                    raise ValueError('Unreviewed license digest; manual review required')
                blob = checked_blob(repository, item, get)
                if not re.search(rb'Apache License\s+Version 2\.0', blob):
                    raise ValueError('License changed or missing; manual review required')
                license_texts[item['digest']] = blob
                licenses.append(item['digest'])
        source = choice['architecture_source']
        if not re.fullmatch(r'https://huggingface.co/(?:Qwen|huihui-ai)/[A-Za-z0-9_.-]+/resolve/main/config.json', source):
            raise ValueError('Unexpected architecture source')
        architecture_raw, architecture_headers = get(source)
        commit = next((v for k, v in architecture_headers.items() if k.lower() == 'x-repo-commit'), '')
        if not re.fullmatch(r'[a-f0-9]{40}', commit):
            raise ValueError('Architecture source has no immutable revision')
        pinned_source = source.replace('/resolve/main/', '/resolve/' + commit + '/')
        pinned_raw, _ = get(pinned_source)
        if pinned_raw != architecture_raw:
            raise ValueError('Architecture revision differs from resolved metadata')
        architecture = json.loads(pinned_raw)
        architecture = architecture.get('text_config', architecture)
        head_dim = architecture.get('head_dim')
        if head_dim is None:
            hidden, heads = architecture.get('hidden_size'), architecture.get('num_attention_heads')
            if not catalog.positive(hidden) or not catalog.positive(heads) or hidden % heads:
                raise ValueError('Missing explicit or exactly derivable attention head dimension')
            head_dim = hidden // heads
        kv = {'layers': architecture.get('num_hidden_layers'),
              'kv_heads': architecture.get('num_key_value_heads'), 'head_dim': head_dim,
              'bytes_per_element': 2, 'source_url': pinned_source,
              'source_sha256': hashlib.sha256(pinned_raw).hexdigest()}
        values = list(artifacts.values())
        entries.append({'tag': tag, 'family': choice['family'], 'quantization': choice['quantization'],
                        'parameter_count': count, 'parameter_label': config['model_type'],
                        'license': 'Apache-2.0', 'license_digests': licenses,
                        'capabilities': choice['capabilities'], 'capability_verified': False,
                        'description': choice['description'], 'publisher_url': choice['publisher_url'],
                        'context_tokens': 32768, 'kv_cache': kv, 'manifest_digest': manifest_digest,
                        'artifacts': values, 'total_download_bytes': sum(a['size'] for a in values),
                        'weight_bytes': sum(a['size'] for a in values if a['media_type'] in
                                            {'application/vnd.ollama.image.model', 'application/vnd.ollama.image.projector'})})
    data = {'schema': 'argos-catalog/1', 'updated': datetime.now(timezone.utc).isoformat(), 'models': entries}
    return catalog.validate(data), license_texts


def atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', default=str(ROOT / 'runtime/argoslive/data/catalog-spec.json'))
    parser.add_argument('--output', default=str(catalog.DEFAULT))
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    data, licenses = build(spec)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    directory = output.parent / 'licenses'
    directory.mkdir(exist_ok=True)
    for key, blob in licenses.items():
        atomic(directory / (key.split(':')[1] + '.txt'), blob)
    # Publish catalog last: a failed refresh leaves the previous catalog intact.
    atomic(output, (json.dumps(data, indent=2) + '\n').encode())
    print('Catalog refreshed: ' + str(len(data['models'])) + ' models. Review changes before promotion; no weights downloaded.')


if __name__ == '__main__':
    main()
