#!/usr/bin/env python3
"""Fetch one catalog-pinned Ollama model into an isolated model store."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog, model_verify


def fetch(tag, destination):
    data = catalog.load(ROOT / 'runtime/argoslive/data/catalog.json')
    entry = next((model for model in data['models'] if model['tag'] == tag), None)
    if entry is None:
        raise ValueError('Model tag is not in the reviewed catalog')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    needed = entry['total_download_bytes']
    if shutil.disk_usage(destination).free < needed + 1024**3:
        raise ValueError('Not enough free disk space for model and verification margin')

    model_name, revision = tag.rsplit(':', 1)
    repository = model_name if '/' in model_name else 'library/' + model_name
    manifest_url = f'https://registry.ollama.ai/v2/{repository}/manifests/{revision}'
    with urllib.request.urlopen(manifest_url, timeout=30) as response:
        raw = response.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Model manifest exceeds metadata limit')
    model_verify.check_manifest(raw, entry)
    manifest = json.loads(raw)
    registry = f'https://registry.ollama.ai/v2/{repository}'
    (destination / 'blobs').mkdir(exist_ok=True)
    for item in entry['artifacts']:
        target = model_verify.blob_path(destination, item)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            partial = target.with_name(target.name + '.partial')
            subprocess.run(['curl', '--fail', '--location', '--retry', '5', '--continue-at', '-',
                            '--output', str(partial), registry + '/blobs/' + item['digest']], check=True)
            partial.replace(target)
        model_verify.verify_blob(target, item, sync=True)

    manifest_path = model_verify.manifest_path(destination, tag)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists() and manifest_path.read_bytes() != raw:
        raise ValueError('A different manifest already occupies this model tag')
    if not manifest_path.exists():
        manifest_path.write_bytes(raw)
    identity = model_verify.verify(destination, entry, sync=False, include_identity=True)
    print(json.dumps({'model': tag, 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                      'verified_bytes': identity['verified_bytes'], 'artifacts': len(manifest['layers'])}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag', help='Exact tag from the reviewed Argos catalog')
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    fetch(args.tag, args.destination)
