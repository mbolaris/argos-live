#!/usr/bin/env python3
"""Integration test confined to an explicitly chosen build-test directory."""
import hashlib
from pathlib import Path
import subprocess
import sys
import time

target = Path('/var/lib/argos-live/download-recovery-test')
target.mkdir(parents=True, exist_ok=True)
digest = '7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa'
url = 'https://registry.ollama.ai/v2/library/qwen3/blobs/sha256:' + digest
file = target / 'model.partial'
if file.exists():
    raise SystemExit('Test path already has partial data; inspect before repeating.')
with (target / 'curl.log').open('w') as log:
    p = subprocess.Popen(['curl', '--fail', '--location', '--limit-rate', '20M', '-o', str(file), url], stdout=log, stderr=log)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if file.exists() and file.stat().st_size > 16 * 1024**2:
            break
        if p.poll() is not None:
            raise SystemExit('Download ended before interruption.')
        time.sleep(.1)
    p.terminate()
    p.wait()
    partial_bytes = file.stat().st_size
    if not 0 < partial_bytes < 522640096:
        raise SystemExit('Did not create a partial artifact.')
    subprocess.run(['curl', '--fail', '--location', '--continue-at', '-', '-o', str(file), url], stdout=log, stderr=log, check=True)
h = hashlib.sha256()
with file.open('rb') as stream:
    for b in iter(lambda: stream.read(8 * 1024**2), b''):
        h.update(b)
if h.hexdigest() != digest or file.stat().st_size != 522640096:
    raise SystemExit('Resumed artifact does not match expected content.')
print(f'Interrupted at {partial_bytes} bytes; resumed to 522640096 bytes; SHA256 verified.')
