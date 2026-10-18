"""Score the configured OpenClaw assistant with Argos' fixed ability suite."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import threading
import time

from . import ability, hw
from .assistant_trial import OpenClawRunner, TrialTurnError, agents_path
from .bench_ability import summaries
from .results import Store
from .evaluation_context import EXECUTION_PATH, configuration_receipt
from .workload import Busy, reserve


PROTECTED_LIMIT = 1024 ** 2


@contextmanager
def graceful_termination():
    """CLI signals request cancellation; the runner must drain before saving."""
    cancelled = threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def request_cancel(_signum, _frame):
            cancelled.set()
        for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
            number = getattr(signal, name, None)
            if number is not None:
                previous[number] = signal.signal(number, request_cancel)
    try:
        yield cancelled
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def protected_files(workspace):
    """Bytes of the assistant's own workspace files that benchmark tasks must not change."""
    saved = {}
    if workspace is None or not workspace.is_dir():
        return saved
    candidates = [path for path in workspace.iterdir() if path.is_file()]
    for folder in ('tools', 'skills'):
        if (workspace / folder).is_dir():
            candidates += [path for path in (workspace / folder).rglob('*') if path.is_file()]
    for path in candidates:
        if not path.is_symlink() and path.stat().st_size <= PROTECTED_LIMIT:
            saved[path.relative_to(workspace).as_posix()] = path.read_bytes()
    return saved


def changed_inputs(workspace, saved):
    """Detect changed inputs without overwriting controller work."""
    changed = []
    for name, original in saved.items():
        path = workspace / name
        try:
            if path.is_file() and not path.is_symlink() and path.read_bytes() == original:
                continue
            changed.append(name)
        except OSError:
            changed.append(name)
    return changed


def run(*, suite='quick', home=None, runner=None, progress=None, clock=time.monotonic, cancel=None,
        delegation=None, results_dir=None):
    """Evaluate and publish the outcome before returning/releasing admission."""
    home = Path.home() if home is None else Path(home)
    with reserve(home, 'evaluation', delegation=delegation) as slot:
        result = _run(suite=suite, home=home, runner=runner, progress=progress, clock=clock, cancel=cancel)
        Store(results_dir if results_dir is not None else home / '.local/share/argos-live/results').save(result)
        slot.record_result(result['id'])
        if result['state'] == 'completed':
            slot.complete(result['id'])
        return result


def _run(*, suite='quick', home=None, runner=None, progress=None, clock=time.monotonic, cancel=None):
    """Run fixed text tasks with copied instructions and no execution capabilities."""
    data = ability.load(suite)
    suite_path = ability.DATA / (suite + '.json')
    suite_digest = hashlib.sha256(suite_path.read_bytes()).hexdigest()
    instruction_digest = None
    instruction_path = None
    if home is not None:
        instruction_path = agents_path(Path(home))
        if instruction_path.exists():
            instruction_digest = hashlib.sha256(instruction_path.read_bytes()).hexdigest()
    workspace_before = (set(os.listdir(instruction_path.parent))
                        if instruction_path is not None and instruction_path.parent.is_dir() else None)
    workspace = instruction_path.parent if workspace_before is not None else None
    protected = protected_files(workspace)
    configuration = configuration_receipt(home)

    def protect(item_id):
        if cancel is not None and cancel.is_set():
            raise TrialTurnError('cancelled')
        # Evaluation cannot edit owner files. A concurrent controller edit is
        # newer owner work: invalidate the comparison, never roll it back.
        changed = changed_inputs(workspace, protected) if protected else []
        if changed:
            result['workspace_changed'] = {'item_id': item_id, 'files': changed}
            raise TrialTurnError('workspace-changed-during-run')
        try:
            same = configuration_receipt(home)['sha256'] == configuration['sha256']
        except (OSError, ValueError, KeyError, TypeError):
            same = False
        if not same:
            raise TrialTurnError('configuration-changed-during-run')
    runner = runner or OpenClawRunner(home=home)
    if isinstance(runner, OpenClawRunner):
        runner.expected_model = configuration['model']['primary'].removeprefix('ollama/')
        runner.cancel_event = cancel
    started = clock()
    result = {
        'schema': 'argos-bench/1', 'id': secrets.token_hex(16),
        'created': datetime.now(timezone.utc).isoformat(), 'kind': 'ability',
        'suite': 'openclaw-' + suite,
        'suite_version': 'argos-openclaw-ability/' + suite + '/' + data['version'],
        'model': 'identity pending first OpenClaw turn', 'manifest_digest': None,
        'settings': {'execution_path': EXECUTION_PATH,
                     'suite_sha256': suite_digest, 'model': configuration['model'],
                     'configured_generation': configuration['configured_generation']},
        'prompt_fingerprint': {'workspace_agents_sha256': instruction_digest,
                               'evaluation_config_sha256': configuration['sha256']},
        'hardware': hw.snapshot(), 'state': 'running', 'items': [],
        'omitted_categories': data['omitted_categories'],
        'restoration': {'succeeded': True, 'mutated': False},
    }
    try:
        for index, task in enumerate(data['items'], 1):
            protect(task['id'])
            item_started = clock()
            if progress:
                progress({'phase': 'asking', 'completed': index - 1, 'run_id': result['id'],
                          'total': len(data['items']), 'item_id': task['id'], 'category': task['scorer']['kind']})
            try:
                answer = runner.turn(task['prompt'])
            except TrialTurnError as exc:
                if exc.code != 'empty-reply':
                    raise
                # The assistant ran but produced no usable answer: score it as a
                # wrong answer and keep going instead of voiding the whole run.
                scored = ability.score(task, '')
                scored.update(category=task['scorer']['kind'], output='', output_truncated=False,
                              no_reply=True, latency_seconds=max(0, clock() - item_started),
                              measurement={'source': 'OpenClaw CLI elapsed time', 'elapsed_seconds': None},
                              session_id=None)
                protect(task['id'])
                result['items'].append(scored)
                if progress:
                    progress({'phase': 'scored', 'completed': index, 'run_id': result['id'],
                              'total': len(data['items']), 'item_id': task['id'],
                              'model': result['model'], 'receipt': scored})
                continue
            protect(task['id'])
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
                progress({'phase': 'scored', 'completed': index, 'run_id': result['id'],
                          'total': len(data['items']), 'item_id': task['id'],
                          'model': result['model'], 'receipt': scored})
        protect('final')
        result['state'] = 'completed'
    except KeyboardInterrupt:
        result['state'] = 'cancelled'
        result['failure_code'] = 'cancelled'
    except TrialTurnError as exc:
        result['state'] = 'cancelled' if exc.code == 'cancelled' else 'failed'
        result['failure_code'] = exc.code
    if hashlib.sha256(suite_path.read_bytes()).hexdigest() != suite_digest:
        result['state'] = 'failed'
        result['failure_code'] = 'benchmark-changed-during-run'
    if workspace_before is not None:
        # Preserve concurrent owner/controller additions; never move them away.
        created = sorted(set(os.listdir(instruction_path.parent)) - workspace_before)
        if created:
            result['workspace_side_effects'] = {'added_entries': created, 'preserved': True}
            result['state'] = 'failed'
            result['failure_code'] = 'workspace-changed-during-run'
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


class LiveBoard:
    """Publish a running benchmark's progress for the dashboard's live view."""

    def __init__(self, home, suite):
        self.path = Path(home) / '.local/state/argos-live/assistant-bench-live.json'
        self.state = {'schema': 'argos-assistant-bench-live/1', 'suite': 'openclaw-' + suite, 'phase': 'starting',
                      'started': datetime.now(timezone.utc).isoformat(), 'items': []}
        self.write()

    def write(self):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_name('.' + self.path.name + '.tmp')
            temporary.write_text(json.dumps(self.state, ensure_ascii=False))
            os.replace(temporary, self.path)
        except OSError:
            pass  # The live view is a convenience; never let it break a benchmark.

    def update(self, event):
        self.state.update(phase='running', run_id=event.get('run_id'), total=event.get('total'),
                          completed=event.get('completed'), updated=datetime.now(timezone.utc).isoformat())
        if event.get('phase') == 'asking':
            self.state['current'] = {'item_id': event.get('item_id'), 'category': event.get('category')}
        elif event.get('phase') == 'scored':
            receipt = event.get('receipt') or {}
            self.state['model'] = event.get('model')
            self.state['current'] = None
            self.state['items'].append({
                'item_id': event.get('item_id'), 'category': receipt.get('category'),
                'correct': bool(receipt.get('score')), 'outcome': receipt.get('outcome'),
                'no_reply': bool(receipt.get('no_reply')), 'answer': (receipt.get('output') or '')[:240],
                'seconds': round(receipt.get('latency_seconds') or 0, 1)})
            self.state['correct'] = sum(item['correct'] for item in self.state['items'])
        self.write()

    def finish(self, result):
        self.state.update(phase=result['state'], run_id=result['id'], summary=result.get('summary'),
                          coverage=result.get('coverage'), elapsed_seconds=round(result.get('elapsed_seconds') or 0, 1),
                          failure_code=result.get('failure_code'), current=None,
                          updated=datetime.now(timezone.utc).isoformat())
        self.write()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Evaluate the configured OpenClaw assistant with fixed Argos tasks.')
    parser.add_argument('--suite', choices=('quick', 'standard'), default='quick')
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--results-dir', type=Path, default=Store().root)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        with graceful_termination() as cancel, reserve(args.home, 'evaluation') as slot:
            # Admission precedes even live-board publication; a rejected request
            # must not overwrite the first run's progress or save a partial run.
            board = LiveBoard(args.home, args.suite)
            def progress(value):
                print(json.dumps(value, ensure_ascii=False), file=__import__('sys').stderr, flush=True)
                board.update(value)
            result = _run(suite=args.suite, home=args.home, progress=progress, cancel=cancel)
            path = Store(args.results_dir).save(result)
            slot.record_result(result['id'])
            board.finish(result)
            if result['state'] == 'completed':
                slot.complete(result['id'])
    except Busy as error:
        print(json.dumps({'status': 'busy', 'recovery_required': error.recovery,
                          'message': str(error)}))
        return 75
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
