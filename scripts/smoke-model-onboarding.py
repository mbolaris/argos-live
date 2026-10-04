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
from argoslive.bench_speed import run as speed_benchmark
from argoslive.bench_ability import run as ability_benchmark
from argoslive.pull_jobs import write_json

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
    with backend(models) as client:
        client.timeout = 600  # Dedicated full CPU lab test; quick run still gated under 60s.
        client.generate(result['tag'], '', options={'num_ctx': 2048}, keep_alive='5m')
        def progress(value):
            print(json.dumps({'benchmark_progress': value}), flush=True)
        speed = speed_benchmark(client, result['tag'], sizes=['short'], progress=progress)
        print(json.dumps({'short_benchmark_seconds': speed['elapsed_seconds']}), flush=True)
        loaded = client.ps()['models']
        if not any(m.get('name') == result['tag'] and m.get('context_length') == 2048 for m in loaded):
            raise SystemExit('Benchmark did not restore the previously loaded model/context')
        client.unload(result['tag'])
        full_speed = speed_benchmark(client, result['tag'], progress=progress)
        ability = ability_benchmark(client, result['tag'], progress=progress)
        if not ability['coverage']['complete'] or len(ability['items']) != 20:
            raise SystemExit('Real quick ability suite did not complete')
        if client.ps()['models']:
            raise SystemExit('Ability benchmark left a model loaded')
        print(json.dumps({'ability_seconds': ability['elapsed_seconds'],
                          'ability_summary': ability['summary']}), flush=True)
    write_json(root / 'ability.json', ability)
    if json.loads((root / 'ability.json').read_text())['coverage']['completed'] != 20:
        raise SystemExit('Ability result did not round-trip')
    write_json(root / 'speed.json', speed)
    if json.loads((root / 'speed.json').read_text())['schema'] != 'argos-bench/1':
        raise SystemExit('Benchmark result file did not round-trip')
    if speed['elapsed_seconds'] >= 60:
        raise SystemExit('CPU starter benchmark exceeded the 60-second acceptance target')
    print(json.dumps({'schema': 'argos-onboarding-smoke/1', 'model': result['tag'],
                      'manifest_digest': result['manifest_digest'], 'pause_verified': True,
                      'retained_partial_files': len(partials), 'resumed_to_ready': True,
                      'reply_test': result['reply_test'],
                      'speed_benchmark_seconds': speed['elapsed_seconds'],
                      'speed_model_restored': speed['restoration']['succeeded'],
                      'full_speed_benchmark_seconds': full_speed['elapsed_seconds'],
                      'speed_summaries': [{'size': p['size'], 'summary': p.get('summary'),
                                            'skipped': p['skipped']} for p in full_speed['prompts']],
                      'physical_acceptance': False}, indent=2))
