#!/usr/bin/env python3
"""Watch one real evaluation end to end through the dashboard's Proctor match routes.

Real: a catalog-verified model answering through the isolated, tool-denied
OpenClaw runner; benchmark scoring and the saved result; the campaign
controller; the dashboard HTTP routes a browser polls; the saved-round replay
and comparison. Not covered: the agent-led campaign turns (the host runs the
evaluation directly here), Toronado, the deployed 27B model, or any claim that
Argos improved. The receipt keeps scores, timings and counts; it never copies
prompts or model output.
"""
import argparse
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import (ability, auto_setup, bench_openclaw, catalog, controller_bridge, model_verify,
                       owned_ollama, proctor_campaign)
from argoslive.assistant_trial import OpenClawRunner
from argoslive.results import Store
from argoslive.web.benchmarks import View
from argoslive.web.server import DashboardServer

SUITE = 'quick'
TURN_TIMEOUT_SECONDS = 360
PRIVATE_MARKERS = ('"reference"', '"expected"', '"scorer"', 'session_id', '"hardware"', '"_instructions"')


class WatchRunner(OpenClawRunner):
    def turn(self, text, timeout=TURN_TIMEOUT_SECONDS):
        return super().turn(text, timeout=timeout)


class Startup:
    """The everyday assistant is not running in this scratch host; only the reservation is exercised."""

    def __init__(self, home):
        self.home, self.lock = home, threading.RLock()
        self.lab_active = self.chat_claimed = False
        self.active, self.phase, self.model = True, 'ready', None

    def snapshot(self):
        return {'active': self.active, 'phase': self.phase, 'model': self.model,
                'model_reply_verified': self.phase == 'ready'}

    def stop(self):
        self.active, self.phase = False, 'stopped'

    def start(self, *, _reserved=False):
        self.active, self.phase = True, 'ready'


def request(server, path, method='GET', body=None):
    headers = {'X-Argos-Token': server.token}
    if body is not None:
        body = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)) as connection:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
    return response.status, raw


def watch_round(server, number):
    """Start a campaign as the owner's click would, then follow it the way the page does."""
    status, raw = request(server, '/api/proctor-campaign/start', 'POST',
                          {'owner_task': f'Watch real evaluation round {number}',
                           'success_criteria': 'The round is visible while it runs and replayable afterwards.'})
    if status != 200:
        raise ValueError('campaign-start-refused')
    watch_id = json.loads(raw)['watch']['id']
    seen = {}
    facts = {'polls': 0, 'watch_ids': {watch_id}, 'run_ids': set(), 'phases': [], 'answer_streaming': False,
             'stall_flags': set(), 'score_without_question': 0}
    while True:
        status, raw = request(server, '/api/proctor-campaign')
        if status != 200:
            raise ValueError('watch-status-unavailable')
        value = json.loads(raw)
        facts['polls'] += 1
        watch = value.get('watch') or {}
        facts['watch_ids'].add(watch.get('id'))
        facts['answer_streaming'] = facts['answer_streaming'] or watch.get('answer_streaming') is True
        if watch.get('stall'):
            facts['stall_flags'].add(watch['stall'])
        if not facts['phases'] or facts['phases'][-1] != value.get('phase'):
            facts['phases'].append(value.get('phase'))
        progress = value.get('progress') or {}
        current = progress.get('current') or {}
        if current.get('item_id'):
            facts['run_ids'].add(current.get('run_id'))
            entry = seen.setdefault(current['item_id'], {'thinking_polls': 0, 'clock': [], 'question_shown': False,
                                                         'scored': False})
            if current.get('state') == 'thinking':
                entry['thinking_polls'] += 1
                entry['question_shown'] = entry['question_shown'] or bool(current.get('question'))
                entry['clock'].append(progress.get('current_elapsed_seconds') or 0)
                if 'answer' in current:
                    raise ValueError('answer-visible-before-it-landed')
            elif current.get('state') == 'scored':
                entry['scored'] = True
                if not entry['question_shown']:
                    facts['score_without_question'] += 1
        if not value.get('active') and value.get('phase') not in ('pausing', 'campaign', 'restarting'):
            return watch_id, value, seen, facts
        time.sleep(1.0)


def run(cli, ollama, model_store, model_tag, report, rounds):
    scratch = Path(os.environ.get('RUNNER_TEMP', '/missing')).resolve()
    model_store = model_store.resolve(strict=True)
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            scratch not in model_store.parents or os.geteuid() == 0):
        raise ValueError('The real match watch requires an unprivileged disposable hosted fixture')
    entry = next((row for row in catalog.load()['models'] if row['tag'] == model_tag), None)
    if entry is None:
        raise ValueError('The real match watch requires an exact catalog-pinned model')
    identity = model_verify.verify(model_store, entry, sync=False, include_identity=True)

    with tempfile.TemporaryDirectory(prefix='argos-match-real-', dir=scratch) as temporary:
        home = Path(temporary)
        workspace = home / '.openclaw/workspace'
        workspace.mkdir(mode=0o700, parents=True)
        config_path = home / '.openclaw/openclaw.json'
        config_path.write_text(json.dumps(auto_setup.conversation_config(
            model_tag, workspace, plugin_root=ROOT / 'openclaw-plugin/argos-improve')), encoding='utf-8')
        config_path.chmod(0o600)
        lease_store = home / '.local/state/argos-live'
        lease_store.mkdir(mode=0o700, parents=True, exist_ok=True)
        model = WatchRunner(home, executable=str(cli.resolve(strict=True)))
        model.seed_workspace_defaults(('AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'BOOTSTRAP.md'),
                                      model.bootstrap_templates())

        def backend():
            return owned_ollama.owned(model_store, executable=str(ollama.resolve(strict=True)), port=11434,
                                      context_tokens=32768, lease_store=lease_store)

        watch(home, model, backend, model_tag, identity['sha256'], report, rounds)


def watch(home, model, backend, model_tag, identity_sha256, report, rounds):
    """Run and follow the rounds. Split from run() so the watch logic can be exercised with a fixture model."""
    if True:
        saved_ids = []

        def campaign(_home, *, owner_task, success_criteria, on_phase, on_progress, **_options):
            on_phase('campaign')
            publish = SimpleNamespace(on_progress=on_progress)

            def progress(event):
                controller_bridge.Bridge._publish_evaluation_progress(publish, event)
                if event.get('phase') == 'scored':
                    print(json.dumps({'completed': event.get('completed'), 'total': event.get('total'),
                                      'item_id': event.get('item_id')}, separators=(',', ':')),
                          file=sys.stderr, flush=True)

            step = {'phase': 'campaign', 'stage': 'campaign-step', 'step_id': 'host-evaluation',
                    'tool': 'evaluation', 'suite': SUITE}
            on_progress({**step, 'status': 'running'})
            with backend():
                result = bench_openclaw.run(suite=SUITE, home=home, runner=model, progress=progress)
            saved_ids.append(result['id'])
            on_progress({**step, 'status': 'completed' if result['state'] == 'completed' else 'failed',
                         'result_id': result['id'], 'run_state': result['state'],
                         'completed': result['coverage']['completed'], 'total': result['coverage']['total'],
                         'correct': result['summary']['correct'],
                         'coverage_complete': result['coverage']['complete']})
            done = result['state'] == 'completed'
            return {'status': 'completed' if done else 'incomplete', 'owner_task': owner_task,
                    'success_criteria': success_criteria, 'measurement_suite': None,
                    'campaign': {'status': 'completed' if done else 'incomplete',
                                 'outcome': 'host-run-evaluation-saved' if done else 'evaluation-' + result['state'],
                                 'audit_status': None, 'controller_turns': 0, 'missing': [],
                                 'saved_evaluation_ids': [result['id']]},
                    'failure_code': None, 'failure_stage': None}

        confirmed = {'confirmed': True, 'locations': [
            {'key': key, 'backing': {'encrypted': True, 'persistent': True}}
            for key in ('models', 'profile', 'results', 'settings')]}
        startup = Startup(home)
        startup.model = model_tag
        controller = proctor_campaign.Controller(startup, home=home, runner=campaign,
                                                 storage_snapshot=lambda _home: confirmed)
        store = Store(home / '.local/share/argos-live/results')
        server = DashboardServer(port=0, benchmarks=View(store), proctor_campaign=controller)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        failures, round_reports = [], []
        try:
            for number in range(1, rounds + 1):
                watch_id, final, seen, facts = watch_round(server, number)
                if len(saved_ids) != number:
                    raise ValueError('evaluation-not-saved')
                run_id = saved_ids[-1]
                saved = store.load(run_id)
                status, raw = request(server, '/api/proctor-match/run/' + run_id)
                text = raw.decode('utf-8')
                match = json.loads(text) if status == 200 else {}
                view = match.get('round', {})
                status_recent, recent = request(server, '/api/proctor-match/recent')
                recent = json.loads(recent) if status_recent == 200 else {}
                status_record, record = request(server, '/api/proctor-match/campaign/' + watch_id)
                record = json.loads(record) if status_record == 200 else {}
                items = saved.get('items', [])
                checks = {
                    'campaign_finished': final.get('phase') in ('completed', 'incomplete'),
                    'run_completed': saved.get('state') == 'completed' and saved['coverage']['complete'] is True,
                    'one_watch_id_for_every_poll': facts['watch_ids'] == {watch_id},
                    'one_run_id_for_every_question': facts['run_ids'] == {run_id},
                    'every_question_seen': set(seen) == {item['item_id'] for item in items},
                    'every_question_shown_before_its_answer': all(
                        entry['question_shown'] and entry['thinking_polls'] > 0 for entry in seen.values()),
                    'clock_never_ran_backwards': all(
                        entry['clock'] == sorted(entry['clock']) for entry in seen.values()),
                    'clock_advanced_on_some_question': any(
                        len(entry['clock']) > 1 and entry['clock'][-1] > entry['clock'][0] for entry in seen.values()),
                    'no_fabricated_streaming': facts['answer_streaming'] is False,
                    'replay_matches_saved_score': status == 200 and view.get('correct') == saved['summary']['correct']
                    and view.get('scored_total') == saved['summary']['total'],
                    'replay_has_every_question': len(view.get('items', [])) == len(items) and
                    view.get('questions_available') is True,
                    'replay_omits_private_fields': status == 200 and not any(marker in text for marker in PRIVATE_MARKERS)
                    and str(home) not in text,
                    'round_listed_for_replay': run_id in [row.get('run_id') for row in recent.get('rounds', [])],
                    'campaign_record_saved': record.get('id') == watch_id and
                    [row.get('run_id') for row in record.get('rounds', [])] == [run_id],
                    'owner_clicks_counted': record.get('owner_action_count') == 1,
                }
                comparison = match.get('comparison', {})
                if number == 1:
                    checks['first_round_has_no_baseline'] = comparison == {'comparable': False, 'reason': 'no-baseline'}
                else:
                    checks['second_round_compared_with_first'] = (
                        comparison.get('comparable') is True and comparison.get('baseline_id') == saved_ids[0] and
                        comparison.get('same_instructions') is True and match.get('decision') is None)
                failures += [f'round-{number}:{name}' for name, passed in checks.items() if not passed]
                round_reports.append({
                    'round': number, 'run_id': run_id, 'watch_id': watch_id,
                    'saved_result_sha256': hashlib.sha256(
                        (home / '.local/share/argos-live/results' / (run_id + '.json')).read_bytes()).hexdigest(),
                    'state': saved.get('state'), 'coverage': saved.get('coverage'),
                    'correct': saved['summary']['correct'], 'total': saved['summary']['total'],
                    'median_latency_seconds': view.get('median_latency_seconds'),
                    'campaign_phase': final.get('phase'), 'campaign_elapsed_seconds': final.get('elapsed_seconds'),
                    'watch': {'polls': facts['polls'], 'phases': facts['phases'],
                              'questions_seen_on_the_clock': sum(1 for entry in seen.values() if entry['question_shown']),
                              'longest_observed_answer_seconds': max(
                                  (entry['clock'][-1] for entry in seen.values() if entry['clock']), default=None),
                              'stall_flags': sorted(facts['stall_flags']),
                              'answer_streaming': facts['answer_streaming']},
                    'comparison': {key: comparison.get(key) for key in (
                        'comparable', 'reason', 'baseline_id', 'baseline_correct', 'correct', 'correct_delta',
                        'wins', 'regressions', 'median_latency_delta_seconds', 'same_model', 'same_instructions')},
                    'item_scores': [{'item_id': item.get('item_id'), 'category': item.get('category'),
                                     'outcome': item.get('outcome'), 'score': item.get('score'),
                                     'latency_seconds': item.get('latency_seconds')} for item in items],
                    'checks': checks,
                })
        finally:
            server.shutdown()
            server.server_close()
            controller.close()
        receipt = {
            'schema': 'argos-proctor-match-real-watch/1',
            'model': 'ollama/' + model_tag, 'model_identity_sha256': identity_sha256,
            'suite_version': 'argos-openclaw-ability/' + SUITE + '/' + ability.load(SUITE)['version'],
            'rounds': round_reports, 'acceptance_failures': failures,
            'scope': ('Real model, real isolated runner, real scoring and saved results, real campaign controller and '
                      'dashboard watch routes on a disposable hosted VM. The host ran the evaluation directly; the '
                      'agent-led campaign, Toronado and the deployed model are not covered. Two rounds under the '
                      'same instructions show run-to-run variation, not an improvement.'),
            'practice_only': True, 'calibration_status': 'uncalibrated', 'tools_executed': False,
            'ci_commit': os.environ.get('GITHUB_SHA'),
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        if failures:
            raise ValueError('Real match watch failed acceptance: ' + ', '.join(failures))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ('openclaw', 'ollama', 'model-store', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--model-tag', required=True)
    parser.add_argument('--rounds', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    try:
        run(args.openclaw, args.ollama, args.model_store, args.model_tag, args.report, args.rounds)
    except BaseException as error:
        if not args.report.exists():
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({
                'schema': 'argos-proctor-match-real-watch-failure/1', 'failure_class': type(error).__name__,
                'practice_only': True, 'calibration_status': 'uncalibrated', 'tools_executed': False,
            }, indent=2) + '\n', encoding='utf-8')
        raise
