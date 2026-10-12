"""Score the configured OpenClaw assistant with Argos' fixed ability suite."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import time

from . import ability, hw
from .assistant_trial import OpenClawRunner, TrialTurnError, agents_path
from .bench_ability import summaries
from .results import Store


def run(*, suite='quick', home=None, runner=None, progress=None, clock=time.monotonic):
    """Run fixed tasks as fresh ordinary OpenClaw main-agent sessions."""
    data = ability.load(suite)
    suite_path = ability.DATA / (suite + '.json')
    suite_digest = hashlib.sha256(suite_path.read_bytes()).hexdigest()
    instruction_digest = None
    instruction_path = None
    if home is not None:
        instruction_path = agents_path(Path(home))
        if instruction_path.exists():
            instruction_digest = hashlib.sha256(instruction_path.read_bytes()).hexdigest()
    runner = runner or OpenClawRunner(home=home)
    started = clock()
    result = {
        'schema': 'argos-bench/1', 'id': secrets.token_hex(16),
        'created': datetime.now(timezone.utc).isoformat(), 'kind': 'ability',
        'suite': 'openclaw-' + suite,
        'suite_version': 'argos-openclaw-ability/' + suite + '/' + data['version'],
        'model': 'identity pending first OpenClaw turn', 'manifest_digest': None,
        'settings': {'execution_path': 'openclaw gateway; fresh session per task',
                     'suite_sha256': suite_digest},
        'prompt_fingerprint': {'workspace_agents_sha256': instruction_digest},
        'hardware': hw.snapshot(), 'state': 'running', 'items': [],
        'omitted_categories': data['omitted_categories'],
        'restoration': {'succeeded': True, 'mutated': False},
    }
    try:
        for index, task in enumerate(data['items'], 1):
            item_started = clock()
            if progress:
                progress({'phase': 'asking', 'completed': index - 1,
                          'total': len(data['items']), 'item_id': task['id']})
            answer = runner.turn(task['prompt'])
            identity = '/'.join(str(answer.get(key) or 'unknown') for key in ('provider', 'model'))
            if result['model'] == 'identity pending first OpenClaw turn':
                result['model'] = identity
                result['settings']['assistant_model'] = identity
            elif result['model'] != identity:
                raise TrialTurnError('model-mismatch')
            scored = ability.score(task, answer['text'])
            scored.update(
                category=task['scorer']['kind'], output=answer['text'][:8192],
                output_truncated=len(answer['text'].encode('utf-8')) > 8192,
                latency_seconds=max(0, clock() - item_started),
                measurement={'source': 'OpenClaw CLI elapsed time',
                             'elapsed_seconds': answer['elapsed_seconds']},
                session_id=answer['session_id'])
            result['items'].append(scored)
            if progress:
                progress({'phase': 'scored', 'completed': index,
                          'total': len(data['items']), 'item_id': task['id'],
                          'receipt': scored})
        result['state'] = 'completed'
    except KeyboardInterrupt:
        result['state'] = 'cancelled'
        result['failure_code'] = 'cancelled'
    except TrialTurnError as exc:
        result['state'] = 'failed'
        result['failure_code'] = exc.code
    if hashlib.sha256(suite_path.read_bytes()).hexdigest() != suite_digest:
        result['state'] = 'failed'
        result['failure_code'] = 'benchmark-changed-during-run'
    if instruction_path is not None:
        current_digest = (hashlib.sha256(instruction_path.read_bytes()).hexdigest()
                          if instruction_path.exists() else None)
        if current_digest != instruction_digest:
            result['state'] = 'failed'
            result['failure_code'] = 'instruction-changed-during-run'
    result['elapsed_seconds'] = max(0, clock() - started)
    result['summary'] = summaries(result['items'])
    result['coverage'] = {'completed': len(result['items']),
                          'total': len(data['items']),
                          'complete': result['state'] == 'completed' and
                                      len(result['items']) == len(data['items'])}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Evaluate the configured OpenClaw assistant with fixed Argos tasks.')
    parser.add_argument('--suite', choices=('quick', 'standard'), default='quick')
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--results-dir', type=Path, default=Store().root)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    def progress(value):
        print(json.dumps(value, ensure_ascii=False), file=__import__('sys').stderr, flush=True)
    result = run(suite=args.suite, home=args.home, progress=progress)
    path = Store(args.results_dir).save(result)
    if args.json:
        print(json.dumps({'result': result, 'path': str(path)}, ensure_ascii=False))
    else:
        summary = result['summary']
        print(f"OpenClaw ability: {summary['correct']}/{summary['total']}; result {result['id']}")
        print(f"Saved: {path}")
    # A saved partial run is a useful, inspectable outcome. Its state and
    # coverage prevent comparison; a nonzero exit would hide it from callers.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
