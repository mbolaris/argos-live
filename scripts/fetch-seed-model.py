#!/usr/bin/env python3
"""Fetch the reviewed Ollama registry manifest and content-addressed artifacts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

registry = 'https://registry.ollama.ai/v2/library/qwen3'
dest = Path(sys.argv[1]).resolve()
dest.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(registry + '/manifests/0.6b') as r:
    raw = r.read()
manifest = json.loads(raw)
if hashlib.sha256(raw).hexdigest() != '7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435':
    raise SystemExit('Manifest changed. Review a new pin before fetching.')
expected_model = 'sha256:7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa'
if manifest['layers'][0]['digest'] != expected_model:
    raise SystemExit('Upstream tag changed. Review and pin a new manifest before fetching.')
needed = sum(x['size'] for x in [manifest['config']] + manifest['layers'])
if shutil.disk_usage(dest).free < needed + 1024**3:
    raise SystemExit('Not enough free space for seed model and working margin.')
(dest / 'blobs').mkdir(exist_ok=True)
for part in [manifest['config']] + manifest['layers']:
    digest = part['digest']
    file = dest / 'blobs' / digest.replace(':', '-')
    partial = file.with_suffix('.partial')
    if not file.exists():
        subprocess.run(['curl', '--fail', '--location', '--retry', '5', '--continue-at', '-',
                        '--output', str(partial), registry + '/blobs/' + digest], check=True)
        partial.replace(file)
    h = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(chunk)
    if file.stat().st_size != part['size'] or h.hexdigest() != digest.split(':')[1]:
        raise SystemExit('Artifact verification failed: ' + file.name)
target = dest / 'manifests/registry.ollama.ai/library/qwen3/0.6b'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(raw)
license_part = next(x for x in manifest['layers'] if x['mediaType'].endswith('.license'))
shutil.copyfile(dest / 'blobs' / license_part['digest'].replace(':', '-'), dest / 'LICENSE-Qwen3.txt')
print(json.dumps({'model': 'qwen3:0.6b', 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                  'bytes': needed, 'manifest': manifest}, indent=2))
