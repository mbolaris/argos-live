"""Fixed public prompts, actual backend timings, and loaded-model restoration."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import secrets
import statistics
import time

from . import __version__, hw
from .ollama import Client, OllamaError

SUITE = 'speed/1'
LIMIT = 128
PROMPTS = [('short', 32, 2048), ('medium', 512, 4096), ('long', 2048, 12288)]


def numeric(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def rate(count, nanoseconds):
    count, duration = numeric(count), numeric(nanoseconds)
    return count * 10**9 / duration if count is not None and duration and duration > 0 else None


def summary(values):
    known = [v for v in values if v is not None]
    return {'median': statistics.median(known) if known else None,
            'min': min(known) if known else None, 'max': max(known) if known else None,
            'reported_runs': len(known), 'total_runs': len(values)}


def placement(models, tag):
    match = next((m for m in models if m.get('name') == tag or m.get('model') == tag), None)
    if not match:
        return {'mode': None, 'size_bytes': None, 'vram_bytes': None, 'offloaded_layers': None}
    size, vram = numeric(match.get('size')), numeric(match.get('size_vram'))
    mode = None
    if vram == 0:
        mode = 'CPU'
    elif size and vram is not None and vram > 0:
        mode = 'GPU' if vram == size else 'split' if vram < size else None
    # API ps does not reliably expose layer counts: never infer them from VRAM.
    return {'mode': mode, 'size_bytes': size, 'vram_bytes': vram, 'offloaded_layers': None}


def measurement(reply, loaded, tag):
    final = reply['final']
    raw = {key: numeric(final.get(key)) for key in ('total_duration', 'load_duration',
           'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration')}
    return {'raw': raw, 'time_to_first_token_seconds': numeric(reply.get('time_to_first_token_seconds')),
            'elapsed_seconds': numeric(reply.get('elapsed_seconds')),
            'prompt_tokens_per_second': rate(raw['prompt_eval_count'], raw['prompt_eval_duration']),
            'generation_tokens_per_second': rate(raw['eval_count'], raw['eval_duration']),
            'backend': placement(loaded, tag)}


def run(client, model, *, hardware=hw.snapshot, clock=time.monotonic, cancel=None,
        sizes=('short', 'medium', 'long'), progress=None):
    if not sizes or len(set(sizes)) != len(sizes) or set(sizes) - {'short', 'medium', 'long'}:
        raise ValueError('Choose unique short, medium or long prompt sizes')
    started = clock()
    models = client.list().get('models', [])
    identity = next((m for m in models if m.get('name') == model or m.get('model') == model), None)
    if identity is None:
        raise ValueError('Benchmark model must already be installed with its exact tag')
    metadata = client.show(model)
    architecture = metadata.get('model_info', {}).get('general.architecture')
    context = metadata.get('model_info', {}).get(str(architecture) + '.context_length')
    context = context if type(context) is int and context > 0 else None
    previous = client.ps().get('models', [])
    if len(previous) > 1:
        raise ValueError('Benchmark requires at most one loaded model; stop other workloads first')
    previous_model = previous[0].get('name', previous[0].get('model')) if previous else None
    if previous and not isinstance(previous_model, str):
        raise ValueError('Cannot establish the previously loaded model')
    previous_context = previous[0].get('context_length') if previous else None
    result = {'schema': 'argos-bench/1', 'id': secrets.token_hex(16),
              'created': datetime.now(timezone.utc).isoformat(), 'kind': 'speed', 'suite_version': SUITE,
              'model': model, 'manifest_digest': identity.get('digest'),
              'metadata': {'details': metadata.get('details'), 'model_info': metadata.get('model_info'),
                           'capabilities': metadata.get('capabilities')},
              'ollama_version': client.version(), 'argos_version': __version__, 'hardware': hardware(),
              'settings': {'prompt_sizes': list(sizes), 'seed': 1, 'temperature': 0, 'think': False if 'thinking' in
                           metadata.get('capabilities', []) else None, 'generation_limit': LIMIT},
              'cold': None, 'prompts': [], 'restoration': {'previous_model': previous_model, 'succeeded': False}}
    try:
        # Deliberately unload before the first request; filesystem caches are not cleared.
        if previous_model:
            client.unload(previous_model)
        client.unload(model)
        for name, repeats, requested in PROMPTS:
            if name not in sizes:
                continue
            if context is None or context < requested:
                result['prompts'].append({'size': name, 'skipped': True,
                                          'reason': 'Advertised context unavailable or smaller than required',
                                          'required_context': requested, 'runs': []})
                continue
            prompt = ('alpha beta gamma delta ' * repeats +
                      '\nWrite a short paragraph about exploring a quiet coastline.')
            options = {'num_ctx': requested, 'num_predict': LIMIT, 'temperature': 0, 'seed': 1}
            # Context changes require a fresh runner allocation. Explicit unload
            # avoids keeping a mismatched runner resident through that transition.
            client.unload(model)
            def generate():
                response = client.generate(model, prompt, options=options,
                                           think=result['settings']['think'], keep_alive='5m', cancel=cancel)
                if not response.get('text', '').strip():
                    raise ValueError('Benchmark produced an empty text reply')
                return measurement(response, client.ps().get('models', []), model)
            if progress:
                progress({'size': name, 'phase': 'warmup'})
            warmup = generate()
            if result['cold'] is None:
                result['cold'] = {'prompt_size': name, 'measurement': warmup,
                                  'filesystem_caches_cleared': False}
            runs = []
            for index in range(3):
                if progress:
                    progress({'size': name, 'phase': 'measured', 'run': index + 1})
                runs.append(generate())
            result['prompts'].append({'size': name, 'skipped': False, 'context_tokens': requested,
                                     'prompt_characters': len(prompt), 'prompt_version': SUITE,
                                     'warmup': warmup, 'runs': runs,
                                     'summary': {key: summary([r[key] for r in runs]) for key in
                                     ('prompt_tokens_per_second', 'generation_tokens_per_second',
                                      'time_to_first_token_seconds')}})
    finally:
        try:
            client.unload(model)
        finally:
            if previous_model:
                options = {'num_ctx': previous_context} if type(previous_context) is int and previous_context > 0 else {}
                # Empty prompt is Ollama's load-only request; do not run owner text.
                client.generate(previous_model, '', options=options, keep_alive='5m')
            result['restoration']['succeeded'] = True
    result['elapsed_seconds'] = clock() - started
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Benchmark an already-installed Ollama model; fixed public prompts.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--ollama', default='http://127.0.0.1:11434')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--size', action='append', choices=['short', 'medium', 'long'],
                        help='Prompt size to run (repeatable); default all sizes.')
    parser.add_argument('--timeout', type=int, default=120,
                        help='API read timeout seconds, 1–600; increase for long CPU prefill.')
    parser.add_argument('--results-dir', type=Path, default=Path.home() / '.local/share/argos-live/results')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 600:
        raise ValueError('Benchmark timeout must be between 1 and 600 seconds')
    try:
        result = run(Client(args.ollama, timeout=args.timeout), args.model,
                     sizes=args.size or ('short', 'medium', 'long'))
    except OllamaError as exc:
        raise ValueError('Benchmark backend failed; check the service and timeout. '
                         'No successful result was saved.') from exc
    from .results import Store
    path = Store(args.results_dir).save(result)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Speed results: {path}")
        for item in result['prompts']:
            if item['skipped']:
                print(f"{item['size']}: skipped ({item['reason']})")
            else:
                value = item['summary']['generation_tokens_per_second']['median']
                measured = f'{value:.2f} tokens/s' if value is not None else 'unknown'
                print(f"{item['size']}: median generation {measured} (three measured runs)")
    return 0
