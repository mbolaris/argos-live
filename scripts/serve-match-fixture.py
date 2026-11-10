#!/usr/bin/env python3
"""Serve the real dashboard and Proctor campaign controller over a scripted fixture model.

For iterating on the live watch without Toronado, an SSD move or a reboot, and
for smoke-proctor-match.mjs. Real: HTTP routes and session token, the campaign
controller and its sanitizing progress path, the bridge's live-event projection,
benchmark scoring, the results store, the match replay/comparison module.
Simulated: the assistant, storage readiness, the agent's campaign turns, the
instruction journal entry, and the model (it answers from the suite's own
references, with chosen misses, at a fixed pace). Nothing here is evidence
about Argos.

Start a campaign from the page. The first word of the task picks a scenario:
  fixture:round   one watched round, then a rolled-back comparison (default)
  fixture:fail    the model turn fails midway; the round is saved as failed
  fixture:cancel  the round is cancelled midway and saved as cancelled
  fixture:stall   one answer runs long enough to raise the slow-answer notice
  fixture:crash   the campaign itself stops with a bounded failure code
  fixture:stream  the fixture runtime sends visible-answer snapshots
Prints the tokenized URL on the first line.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, auto_setup, bench_openclaw, controller_bridge, proctor_campaign
from argoslive.assistant_trial import TrialTurnError
from argoslive.results import Store
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer

MODEL = 'qwen3.8:27b'


class Startup:
    """An always-recoverable assistant; only the reservation flags are real."""

    def __init__(self, home):
        self.home, self.lock = home, threading.RLock()
        self.lab_active = self.chat_claimed = False
        self.active, self.phase = True, 'ready'

    def snapshot(self):
        return {'active': self.active, 'phase': self.phase, 'model': MODEL,
                'model_reply_verified': self.phase == 'ready'}

    def stop(self):
        self.active, self.phase = False, 'stopped'

    def start(self, *, _reserved=False):
        self.active, self.phase = True, 'ready'


class FixtureModel:
    """Answers from the suite's references. It is a fixture, never a measurement of a model."""

    def __init__(self, suite, *, misses=(), pace=0.0, fail_at=None, cancel_at=None, cancel=None,
                 slow_at=None, slow_seconds=0.0, partial=None):
        self.tasks = {item['prompt']: item for item in ability.load(suite)['items']}
        self.misses, self.pace = set(misses), pace
        self.fail_at, self.cancel_at, self.cancel = fail_at, cancel_at, cancel
        self.slow_at, self.slow_seconds, self.partial = slow_at, slow_seconds, partial
        self.calls = 0
        self.recorded = 0.0  # seeded rounds advance this instead of sleeping

    def clock(self):
        return self.recorded

    def turn(self, prompt):
        self.calls += 1
        item = self.tasks[prompt]
        if self.calls == self.fail_at:
            time.sleep(self.pace)
            raise TrialTurnError('assistant-error')
        if self.calls == self.cancel_at and self.cancel is not None:
            time.sleep(self.pace)
            self.cancel.set()
        text = 'I am not sure.' if item['id'] in self.misses else item['reference']
        if self.pace < 0:
            # A seeded round: record a plausible reply time without waiting for it.
            self.recorded += -self.pace * (0.7 + (self.calls * 7 % 10) / 10)
            return {'text': text, 'elapsed_seconds': 0.0, 'session_id': f'fixture-{self.calls}',
                    'provider': 'ollama', 'model': MODEL}
        wait = self.slow_seconds if self.calls == self.slow_at else self.pace
        if self.partial is not None and text:
            for cut in range(1, 5):
                time.sleep(wait / 5)
                self.partial(item['id'], text[:max(1, len(text) * cut // 4)])
            time.sleep(wait / 5)
        else:
            time.sleep(wait)
        return {'text': text, 'elapsed_seconds': wait, 'session_id': f'fixture-{self.calls}',
                'provider': 'ollama', 'model': MODEL}


def save_round(home, suite, model, progress=None, cancel=None):
    options = {'clock': model.clock} if model.pace < 0 else {}
    result = bench_openclaw._run(suite=suite, home=home, runner=model, progress=progress, cancel=cancel,
                                 **options)
    Store(home / '.local/share/argos-live/results').save(result)
    return result


def write_journal(home, baselines, candidates):
    """A fixture journal entry shaped like the host's restore record."""
    change = 'fixture' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    directory = home / '.local/state/argos-live/instruction-changes' / change
    directory.mkdir(parents=True)
    (directory / 'intent.json').write_text(json.dumps({'id': change}), encoding='utf-8')
    (directory / 'resolved.json').write_text(json.dumps({
        'observed': datetime.now(timezone.utc).isoformat(), 'action': 'restore',
        'baseline_ids': baselines, 'candidate_ids': candidates,
        'qualified_experiment': True, 'independent_gain_verified': False}), encoding='utf-8')


def make_runner(home, suite, pace, baseline_misses, candidate_misses):
    seeded = {}

    def seed():
        if seeded:
            return
        seeded['baselines'] = [
            save_round(home, suite, FixtureModel(suite, misses=baseline_misses, pace=-pace * 1.15))['id']
            for _ in range(2)]
        time.sleep(0.01)
        seeded['candidate'] = save_round(
            home, suite, FixtureModel(suite, misses=candidate_misses, pace=-pace))['id']

    def runner(_home, *, owner_task, success_criteria, on_phase=None, on_progress=None, **_options):
        scenario = owner_task.split()[0].removeprefix('fixture:') if owner_task.startswith('fixture:') else 'round'
        seed()
        on_phase('campaign')
        publish = SimpleNamespace(on_progress=on_progress)

        def step(step_id, tool, status, **fields):
            on_progress({'phase': 'campaign', 'stage': 'campaign-step', 'step_id': step_id, 'tool': tool,
                         'status': status, **fields})

        def live(event):
            controller_bridge.Bridge._publish_evaluation_progress(publish, event)
            if event.get('phase') in ('asking', 'scored'):
                step('fixture-evaluation', 'evaluation', 'running', suite=suite,
                     completed=event.get('completed'), total=event.get('total'))

        on_progress({'phase': 'campaign', 'stage': 'turn-start', 'turn': 1, 'total': 4,
                     'saved_evaluation_count': 0, 'audit_status': None})
        for step_id, tool in (('fixture-inspect', 'inspect'), ('fixture-audit', 'audit')):
            step(step_id, tool, 'running')
            time.sleep(pace)
            step(step_id, tool, 'completed', **({'passed': True} if tool == 'audit' else {}))
        if scenario == 'crash':
            time.sleep(pace)
            raise TimeoutError('fixture')
        step('fixture-edit', 'edit', 'completed', step_status='changed')
        cancel = threading.Event()
        current = {}

        def partial(item_id, text):
            on_progress({'phase': 'campaign', 'stage': 'evaluation-answer-partial',
                         'run_id': current.get('run_id'), 'item_id': item_id, 'text': text})

        def tracked(event):
            current['run_id'] = event.get('run_id')
            live(event)

        model = FixtureModel(
            suite, misses=candidate_misses, pace=pace, cancel=cancel,
            fail_at=5 if scenario == 'fail' else None, cancel_at=5 if scenario == 'cancel' else None,
            slow_at=3 if scenario == 'stall' else None, slow_seconds=max(8.0, pace * 8),
            partial=partial if scenario == 'stream' else None)
        step('fixture-evaluation', 'evaluation', 'running', suite=suite)
        result = save_round(home, suite, model, progress=tracked, cancel=cancel)
        summary = result['summary']
        step('fixture-evaluation', 'evaluation', 'completed' if result['state'] == 'completed' else 'failed',
             suite=suite, result_id=result['id'], run_state=result['state'],
             completed=result['coverage']['completed'], total=result['coverage']['total'],
             correct=summary['correct'], coverage_complete=result['coverage']['complete'])
        saved = [result['id']]
        outcome, status, missing = 'restored_after_trial', 'completed', []
        if result['state'] == 'completed':
            write_journal(home, seeded['baselines'], [seeded['candidate'], result['id']])
            step('fixture-compare', 'compare', 'completed', step_status='compatible')
            step('fixture-resolve', 'resolve', 'completed', resolution='restored', step_status='restored',
                 qualified_experiment=True, independent_gain_verified=False)
        else:
            outcome, status = 'evaluation-' + result['state'], 'incomplete'
            missing = ['a completed candidate evaluation']
        on_progress({'phase': 'campaign', 'stage': 'turn-finished', 'turn': 1, 'total': 4,
                     'saved_evaluation_count': len(saved), 'audit_status': 'verified'})
        return {'status': status, 'owner_task': owner_task, 'success_criteria': success_criteria,
                'measurement_suite': None,
                'campaign': {'status': status, 'outcome': outcome, 'audit_status': 'verified',
                             'controller_turns': 1, 'missing': missing, 'saved_evaluation_ids': saved,
                             'agent_summary': [{'text': 'Fixture campaign. No claim about Argos is made.'}]},
                'failure_code': None, 'failure_stage': None}

    return runner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--suite', default='challenge', choices=('quick', 'challenge', 'tool-schema'))
    parser.add_argument('--pace', type=float, default=1.2, help='seconds the fixture model takes per answer')
    parser.add_argument('--slow-answer-seconds', type=int, default=6,
                        help='slow-answer notice threshold for the fixture (the product default is longer)')
    parser.add_argument('--home', type=Path)
    args = parser.parse_args(argv)
    temporary = None
    if args.home is None:
        temporary = tempfile.TemporaryDirectory(prefix='argos-match-fixture-')
        args.home = Path(temporary.name)
    home = args.home.resolve()
    workspace = home / '.openclaw/workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / 'AGENTS.md').write_text('Fixture instructions\n', encoding='utf-8')
    (home / '.openclaw/openclaw.json').write_text(
        json.dumps(auto_setup.conversation_config(MODEL, workspace)), encoding='utf-8')
    items = [item['id'] for item in ability.load(args.suite)['items']]
    # Chosen so the fixture trial lands one short of the preset keep bar for its suite.
    baseline_misses = items[2:9:3] if args.suite == 'challenge' else items[2:6:3]
    candidate_misses = items[-1:]
    proctor_campaign.SLOW_ANSWER_SECONDS = args.slow_answer_seconds
    confirmed = {'confirmed': True, 'locations': [
        {'key': key, 'backing': {'encrypted': True, 'persistent': True}}
        for key in ('models', 'profile', 'results', 'settings')]}
    startup = Startup(home)
    controller = proctor_campaign.Controller(
        startup, home=home, storage_snapshot=lambda _home: confirmed,
        runner=make_runner(home, args.suite, args.pace, baseline_misses, candidate_misses))
    store = Store(home / '.local/share/argos-live/results')
    with DashboardServer(port=args.port, startup=None, benchmarks=BenchmarkView(store),
                         proctor_campaign=controller) as server:
        print(server.url, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            controller.close()
    if temporary is not None:
        temporary.cleanup()


if __name__ == '__main__':
    main()
