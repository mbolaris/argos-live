"""Measured, deterministic original ability probes; no generated code executes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys
import time

from . import __version__, ability, hw
from .bench_speed import measurement
from .ollama import Client, Cancelled, OllamaError
from .pack_export import private_directory
from .pull_jobs import write_json
from .storage import safe_local

CONTEXT = 2048
LIMIT = 128
OUTPUT_LIMIT = 8192


def summaries(items):
    categories = {}
    for item in items:
        category = categories.setdefault(item['category'], {'correct': 0, 'total': 0, 'format_errors': 0})
        category['total'] += 1
        category['correct'] += item['score']
        category['format_errors'] += int(item['outcome'] == 'format_error')
    for category in categories.values():
        category['accuracy'] = category['correct'] / category['total']
    total = len(items)
    return {'correct': sum(i['score'] for i in items), 'total': total,
            'accuracy': sum(i['score'] for i in items) / total if total else None,
            'format_errors': sum(i['outcome'] == 'format_error' for i in items),
            'categories': categories}


def run(client, model, *, suite='quick', hardware=hw.snapshot, clock=time.monotonic,
        cancel=None, progress=None):
    data = ability.load(suite)
    started = clock()
    identity = next((m for m in client.list().get('models', [])
                     if m.get('name') == model or m.get('model') == model), None)
    if identity is None:
        raise ValueError('Benchmark model must already be installed with its exact tag')
    metadata = client.show(model)
    info = metadata.get('model_info', {})
    context = info.get(str(info.get('general.architecture')) + '.context_length')
    if type(context) is not int or context < CONTEXT:
        raise ValueError('Ability benchmark requires an advertised context of at least 2048 tokens')
    previous = client.ps().get('models', [])
    if len(previous) > 1:
        raise ValueError('Benchmark requires at most one loaded model; stop other workloads first')
    previous_model = previous[0].get('name', previous[0].get('model')) if previous else None
    if previous and not isinstance(previous_model, str):
        raise ValueError('Cannot establish the previously loaded model')
    previous_context = previous[0].get('context_length') if previous else None
    think = False if 'thinking' in metadata.get('capabilities', []) else None
    result = {'schema': 'argos-bench/1', 'id': secrets.token_hex(16),
              'created': datetime.now(timezone.utc).isoformat(), 'kind': 'ability',
              'suite': suite, 'suite_version': 'ability/' + suite + '/' + data['version'],
              'model': model, 'manifest_digest': identity.get('digest'),
              'metadata': {'details': metadata.get('details'), 'model_info': info,
                           'capabilities': metadata.get('capabilities')},
              'ollama_version': client.version(), 'argos_version': __version__, 'hardware': hardware(),
              'settings': {'context': CONTEXT, 'seed': 1, 'temperature': 0, 'think': think,
                           'generation_limit': LIMIT},
              'omitted_categories': data['omitted_categories'], 'state': 'running', 'items': [],
              'restoration': {'previous_model': previous_model, 'succeeded': False}}
    options = {'num_ctx': CONTEXT, 'num_predict': LIMIT, 'temperature': 0, 'seed': 1}
    total = len(data['items'])
    def report(phase, item_id=None):
        if progress:
            completed = len(result['items'])
            elapsed = max(0, clock() - started)
            progress({'phase': phase, 'item_id': item_id, 'completed': completed, 'total': total,
                      'elapsed_seconds': elapsed,
                      'eta_seconds': elapsed / completed * (total - completed) if completed else None})
    try:
        if previous_model:
            client.unload(previous_model)
        client.unload(model)
        for item in data['items']:
            if cancel is not None and cancel.is_set():
                raise Cancelled('Ability benchmark cancelled')
            report('generating', item['id'])
            item_started = clock()
            reply = client.generate(model, item['prompt'], options=dict(options), think=think,
                                    keep_alive='5m', cancel=cancel)
            text = reply.get('text', '')
            scored = ability.score(item, text)
            # Bound saved raw output too; the scorer classifies oversized output as format_error.
            encoded = text.encode('utf-8', errors='replace') if isinstance(text, str) else b''
            scored.update(category=item['scorer']['kind'],
                          output=encoded[:OUTPUT_LIMIT].decode('utf-8', errors='ignore'),
                          output_truncated=len(encoded) > OUTPUT_LIMIT,
                          latency_seconds=max(0, clock() - item_started),
                          measurement=measurement(reply, client.ps().get('models', []), model))
            result['items'].append(scored)
            report('scored', item['id'])
        result['state'] = 'completed'
    except (Cancelled, KeyboardInterrupt):
        result['state'] = 'cancelled'
    finally:
        try:
            client.unload(model)
        finally:
            if previous_model:
                restore = {'num_ctx': previous_context} if type(previous_context) is int and previous_context > 0 else {}
                client.generate(previous_model, '', options=restore, keep_alive='5m')
            result['restoration']['succeeded'] = True
    result['elapsed_seconds'] = max(0, clock() - started)
    result['summary'] = summaries(result['items'])
    result['coverage'] = {'completed': len(result['items']), 'total': total,
                          'complete': result['state'] == 'completed'}
    report(result['state'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run original ability probes; code execution is excluded.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--suite', choices=['quick', 'standard'], default='quick')
    parser.add_argument('--ollama', default='http://127.0.0.1:11434')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--timeout', type=int, default=120, help='API read timeout, 1–600 seconds.')
    parser.add_argument('--results-dir', type=Path, default=Path.home() / '.local/share/argos-live/results')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 600:
        raise ValueError('Benchmark timeout must be between 1 and 600 seconds')
    def progress(value):
        if not args.json and value['phase'] == 'scored':
            eta = value['eta_seconds']
            print(f"Ability {value['completed']}/{value['total']}: {value['elapsed_seconds']:.1f}s elapsed; "
                  f"ETA {eta:.1f}s", file=sys.stderr, flush=True)
    try:
        result = run(Client(args.ollama, timeout=args.timeout), args.model, suite=args.suite, progress=progress)
    except OllamaError as exc:
        raise ValueError('Ability backend failed; no successful result was saved.') from exc
    root = safe_local(args.results_dir.absolute())
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_directory(root)
    write_json(root / (result['id'] + '.json'), result)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Ability {result['state']}: {root / (result['id'] + '.json')}")
        for name, category in result['summary']['categories'].items():
            print(f"{name}: {category['correct']}/{category['total']}; {category['format_errors']} format errors")
        print('Code execution excluded. Partial or cancelled results are not comparable to complete runs.')
    return 0 if result['coverage']['complete'] else 130
