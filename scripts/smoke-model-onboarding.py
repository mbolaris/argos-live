#!/usr/bin/env python3
"""NETWORK integration: real pinned Ollama CPU pull/pause/resume/reply in scratch."""
import argparse
from functools import partial
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.model_onboarding import OnboardingQueue
from argoslive.owned_ollama import owned

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ollama', required=True, type=Path)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='argos-onboarding-') as temp:
    root = Path(temp)
    models = root / 'models'
    models.mkdir()
    (models / '.argos-storage-id').write_text('public-integration-fixture')
    queue_root = root / 'jobs'
    queue_root.mkdir(mode=0o700)
    queue = OnboardingQueue(queue_root, {'storage': str(models), 'storage_id': 'public-integration-fixture'})
    job = queue.create('qwen3:0.6b')
    backend = partial(owned, executable=args.ollama.absolute())
    def pause(snapshot):
        if snapshot['state'] == 'downloading' and snapshot['progress']['bytes_done'] >= 8 * 1024**2:
            queue.request(job['id'], 'pause')
    first = queue.run_verified(job['id'], backend=backend, callback=pause, assistant_stopped=True)
    if first['state'] != 'paused':
        raise SystemExit('Real partial pull did not pause: ' + json.dumps(first))
    partials = list((models / '.argos-pulls' / job['id'] / 'blobs').glob('*partial*'))
    if not partials:
        raise SystemExit('No real partial artifacts retained')
    queue.retry(job['id'])
    result = queue.run_verified(job['id'], backend=backend, assistant_stopped=True)
    if result['state'] != 'ready':
        raise SystemExit('Real resume/verification/reply failed: ' + json.dumps(result))
    print(json.dumps({'schema': 'argos-onboarding-smoke/1', 'model': result['tag'],
                      'manifest_digest': result['manifest_digest'], 'pause_verified': True,
                      'retained_partial_files': len(partials), 'resumed_to_ready': True,
                      'reply_test': result['reply_test'], 'physical_acceptance': False}, indent=2))
