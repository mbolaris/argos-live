#!/usr/bin/env python3
"""Actual Ollama interrupted download test on a dedicated build-test directory."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

src = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('argos', src / 'runtime/argos.py')
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
target = Path('/var/lib/argos-live/large-model-resume-test')
target.mkdir(parents=True, exist_ok=True)
model = 'qwen3:8b'
missing, required = a.download_budget(model, target)
a.probe_storage(target, required)
print(f'Explicit test location: {target}; model {model}; missing {missing} bytes; required {required} bytes.', flush=True)
env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11436', OLLAMA_MODELS=str(target), OLLAMA_NO_CLOUD='1', CUDA_VISIBLE_DEVICES='-1')
binary = '/var/lib/argos-live/runtime-lock/ollama/bin/ollama'
base = 'http://127.0.0.1:11436'
def start():
    log = (target / 'ollama.log').open('a')
    p = subprocess.Popen([binary, 'serve'], env=env, stdout=log, stderr=log)
    for _ in range(30):
        try:
            urllib.request.urlopen(base + '/api/version', timeout=1).close()
            return p
        except OSError:
            time.sleep(1)
    p.terminate(); p.wait(); raise RuntimeError('Startup failed.')
def pull():
    req = urllib.request.Request(base + '/api/pull', data=json.dumps({'model': model}).encode(), headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=600)
p = start()
try:
    with pull() as response:
        for line in response:
            row = json.loads(line)
            if 'error' in row:
                raise RuntimeError(row['error'])
            if row.get('completed', 0) >= 64 * 1024**2:
                p.terminate(); p.wait(timeout=30)
                print('Interrupted daemon after at least 64 MiB of progress.', flush=True)
                break
finally:
    if p.poll() is None:
        p.terminate(); p.wait(timeout=30)
partials = list((target / 'blobs').glob('*partial*'))
if not partials:
    raise RuntimeError('No resumable partial artifacts found.')
print(f'Retained {len(partials)} partial data/metadata files.', flush=True)
p = start()
try:
    success = False
    with pull() as response:
        for line in response:
            row = json.loads(line)
            if 'error' in row:
                raise RuntimeError(row['error'])
            success = success or row.get('status') == 'success'
    if not success:
        raise RuntimeError('Pull did not complete successfully.')
    print(f'Resumed larger model; verified {a.verify_blobs(target)} content-addressed artifacts.', flush=True)
finally:
    p.terminate(); p.wait(timeout=30)
