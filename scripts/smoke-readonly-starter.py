#!/usr/bin/env python3
"""Hosted CI integration: real pinned Ollama on an unwritable public seed."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import starter
from argoslive.bench_speed import placement
from argoslive.storage import safe_local

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ollama', required=True, type=Path)
parser.add_argument('--seed', required=True, type=Path)
args = parser.parse_args()
seed = safe_local(args.seed.absolute())
scratch = safe_local(Path(os.environ.get('RUNNER_TEMP', '/missing')).absolute())
if (os.environ.get('GITHUB_ACTIONS') != 'true' or
        os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
        scratch not in seed.parents or not seed.is_dir() or os.geteuid() == 0):
    raise SystemExit('Read-only fixture preparation requires an unprivileged hosted CI scratch directory')
starter.verify(seed)
files = [safe_local(path) for path in seed.rglob('*')]
for path in files:
    path.chmod(0o555 if path.is_dir() else 0o444)
seed.chmod(0o555)
def snapshot():
    return {str(path.relative_to(seed)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in seed.rglob('*') if path.is_file()}
before = snapshot()
started = time.monotonic()
with starter.serve(seed, executable=args.ollama.absolute()) as client:
    client.timeout = 120
    answer = client.generate(starter.TAG, 'Say hello in one short sentence.',
                             # CPU acceptance must request CPU explicitly;
                             # Ollama otherwise chooses placement dynamically.
                             # This affects only the hosted public fixture.
                             options={'num_ctx': 2048, 'num_predict': 16, 'temperature': 0, 'seed': 1,
                                      'num_gpu': 0},
                             think=False, keep_alive='5m')
    if not answer['text'].strip() or answer['final'].get('eval_count', 0) <= 0:
        raise SystemExit('Read-only starter did not produce a measured reply')
    observed = placement(client.ps()['models'], starter.TAG)
    if observed['mode'] != 'CPU':
        raise SystemExit('CPU inference was not established: ' + json.dumps(observed))
    client.unload(starter.TAG)
if snapshot() != before:
    raise SystemExit('Read-only seed file inventory or metadata changed')
identity = starter.verify(seed)
print(json.dumps({'schema': 'argos-readonly-starter-smoke/1', **identity,
                  'elapsed_seconds': time.monotonic() - started, 'backend': 'CPU',
                  'seed_unchanged': True, 'weights_copied': False,
                  'requested_gpu_layers': 0,
                  'source_access': 'unwritable to unprivileged CI user',
                  'physical_acceptance': False}, indent=2))
