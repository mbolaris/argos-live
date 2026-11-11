from contextlib import closing
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, auto_setup, bench_openclaw, proctor_campaign, proctor_match
from argoslive.assistant_trial import TrialTurnError
from argoslive.results import Store
from argoslive.web.benchmarks import View
from argoslive.web.server import DashboardServer

MODEL = 'qwen3:4b-instruct-2507-q4_K_M'


class Model:
    """Answers from the suite's references, with chosen misses and a recorded reply time."""

    def __init__(self, misses=(), seconds=1.0, fail_at=None):
        self.tasks = {item['prompt']: item for item in ability.load('quick')['items']}
        self.misses, self.seconds, self.fail_at = set(misses), seconds, fail_at
        self.calls, self.now = 0, 0.0

    def clock(self):
        return self.now

    def turn(self, prompt):
        self.calls += 1
        if self.calls == self.fail_at:
            raise TrialTurnError('assistant-error')
        item = self.tasks[prompt]
        self.now += self.seconds
        return {'text': 'not sure' if item['id'] in self.misses else item['reference'],
                'elapsed_seconds': self.seconds, 'session_id': f'private-session-{self.calls}',
                'provider': 'ollama', 'model': MODEL}


class Startup:
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


def storage(_home):
    return {'confirmed': True, 'locations': [
        {'key': key, 'backing': {'encrypted': True, 'persistent': True}}
        for key in ('models', 'profile', 'results', 'settings')]}


class MatchCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        (workspace / 'AGENTS.md').write_text('Private instructions\n', encoding='utf-8')
        (self.home / '.openclaw/openclaw.json').write_text(
            json.dumps(auto_setup.conversation_config(MODEL, workspace)), encoding='utf-8')
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.items = [item['id'] for item in ability.load('quick')['items']]

    def save(self, **options):
        model = Model(**options)
        run = bench_openclaw._run(suite='quick', home=self.home, runner=model, clock=model.clock)
        self.store.save(run)
        return run

    def journal(self, action, baselines, candidates, name='20261110T000000Z-trial'):
        directory = self.home / '.local/state/argos-live/instruction-changes' / name
        directory.mkdir(parents=True)
        (directory / 'intent.json').write_text(json.dumps({'id': name}), encoding='utf-8')
        (directory / 'resolved.json').write_text(json.dumps({
            'observed': '2026-11-10T00:00:00+00:00', 'action': action, 'baseline_ids': baselines,
            'candidate_ids': candidates, 'qualified_experiment': True,
            'independent_gain_verified': False}), encoding='utf-8')


class ProctorMatchTests(MatchCase):
    def test_round_replay_shows_questions_answers_and_verdicts_without_private_fields(self):
        run = self.save(misses=self.items[:1])
        view = proctor_match.round_view(self.store.load(run['id']))
        self.assertEqual((view['correct'], view['scored_total'], view['state']), (19, 20, 'completed'))
        self.assertTrue(view['questions_available'])
        first = view['items'][0]
        self.assertEqual(first['question'], ability.load('quick')['items'][0]['prompt'])
        self.assertEqual((first['answer'], first['score']), ('not sure', 0))
        self.assertIn(first['outcome'], ('wrong_answer', 'format_error'))
        self.assertTrue(first['reason'])
        self.assertAlmostEqual(view['median_latency_seconds'], 1.0)
        text = json.dumps(proctor_match.match(self.home, self.store, run['id']))
        for private in ('"reference"', '"expected"', '"scorer"', 'private-session', 'session_id', 'hardware',
                        'Private instructions', '"_instructions"', 'sha256', str(self.home)):
            self.assertNotIn(private, text)

    def test_comparison_lists_wins_regressions_and_reply_times(self):
        baseline = self.save(misses=self.items[:3], seconds=2.0)
        candidate = self.save(misses=self.items[-1:], seconds=1.5)
        value = proctor_match.match(self.home, self.store, candidate['id'])
        comparison = value['comparison']
        self.assertTrue(comparison['comparable'])
        self.assertEqual(comparison['baseline_source'], 'previous-same-test')
        self.assertEqual(comparison['baseline_id'], baseline['id'])
        self.assertEqual((comparison['baseline_correct'], comparison['correct'], comparison['correct_delta']),
                         (17, 19, 2))
        self.assertEqual(comparison['wins'], self.items[:3])
        self.assertEqual(comparison['regressions'], self.items[-1:])
        self.assertAlmostEqual(comparison['median_latency_delta_seconds'], -0.5)
        self.assertIs(comparison['same_instructions'], True)
        self.assertIs(comparison['same_model'], True)
        self.assertNotIn('"_instructions"', json.dumps(value))
        self.assertIsNone(value['decision'])
        # The earliest round has nothing before it and says so.
        first = proctor_match.match(self.home, self.store, baseline['id'])
        self.assertEqual(first['comparison'], {'comparable': False, 'reason': 'no-baseline'})

    def test_unfinished_round_is_replayable_but_never_compared(self):
        self.save()
        failed = self.save(fail_at=5)
        value = proctor_match.match(self.home, self.store, failed['id'])
        self.assertEqual(value['round']['state'], 'failed')
        self.assertEqual((value['round']['completed'], value['round']['total']), (4, 20))
        self.assertFalse(value['round']['complete'])
        self.assertEqual(value['comparison'], {'comparable': False, 'reason': 'incomplete-round'})
        self.assertIsNone(value['baseline'])
        # A later complete round does not use the unfinished one as its baseline.
        later = self.save(misses=self.items[:1])
        self.assertNotEqual(proctor_match.match(self.home, self.store, later['id'])['comparison']['baseline_id'],
                            failed['id'])

    def test_rollback_comes_from_the_host_journal_and_keeps_its_evidence_standard(self):
        baselines = [self.save(misses=self.items[:2])['id'] for _ in range(2)]
        candidates = [self.save(misses=self.items[-1:])['id'] for _ in range(2)]
        self.journal('restore', baselines, candidates)
        value = proctor_match.match(self.home, self.store, candidates[1])
        decision = value['decision']
        self.assertEqual((decision['action'], decision['role']), ('restore', 'candidate'))
        self.assertEqual((decision['baseline_ids'], decision['candidate_ids']), (baselines, candidates))
        self.assertEqual(decision['required_correct_delta'], 2)
        self.assertFalse(decision['independent_gain_verified'])
        self.assertEqual([run['correct'] for run in decision['runs']], [18, 18, 19, 19])
        self.assertNotIn('_policy', decision)
        # The journal's baseline wins over the nearest earlier round (the other candidate).
        self.assertEqual(value['comparison']['baseline_source'], 'journal')
        self.assertEqual(value['comparison']['baseline_id'], baselines[0])
        self.assertEqual(value['comparison']['correct_delta'], 1)
        self.assertEqual(proctor_match.match(self.home, self.store, baselines[0])['decision']['role'], 'baseline')

    def test_journal_is_read_only_and_tolerates_damage(self):
        run = self.save()
        root = self.home / '.local/state/argos-live/instruction-changes'
        self.assertIsNone(proctor_match.decision(self.home, run['id']))
        self.assertFalse(root.exists())
        broken = root / 'broken'
        broken.mkdir(parents=True)
        (broken / 'resolved.json').write_text('{not json', encoding='utf-8')
        self.journal('rewrite-history', [run['id']], [], name='unknown-action')
        self.assertIsNone(proctor_match.decision(self.home, run['id']))

    def test_recent_lists_saved_rounds_newest_first(self):
        first, second = self.save(), self.save(fail_at=3)
        rounds = proctor_match.recent(self.store)
        self.assertEqual([item['run_id'] for item in rounds], [second['id'], first['id']])
        self.assertEqual(rounds[0]['state'], 'failed')
        self.assertNotIn('items', rounds[0])

    def test_dashboard_routes_serve_replays_and_refuse_unknown_runs(self):
        run = self.save(misses=self.items[:1])
        controller = proctor_campaign.Controller(Startup(self.home), home=self.home, storage_snapshot=storage,
                                                 runner=lambda *_a, **_k: None)
        server = DashboardServer(port=0, benchmarks=View(self.store), proctor_campaign=controller)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def get(path, token=True):
            with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                connection.request('GET', path, headers={'X-Argos-Token': server.token} if token else {})
                response = connection.getresponse()
                return response.status, json.loads(response.read())

        status, body = get('/api/proctor-match/run/' + run['id'])
        self.assertEqual((status, body['schema'], body['round']['correct']), (200, 'argos-proctor-match/1', 19))
        status, body = get('/api/proctor-match/recent')
        self.assertEqual((status, [item['run_id'] for item in body['rounds']], body['campaigns']),
                         (200, [run['id']], []))
        self.assertEqual(get('/api/proctor-match/run/' + run['id'], token=False)[0], 403)
        for path in ('/api/proctor-match/run/' + '0' * 32, '/api/proctor-match/run/..%2F..%2Fstate',
                     '/api/proctor-match/campaign/' + '0' * 32, '/api/proctor-match/campaign/nope',
                     '/api/proctor-match/elsewhere'):
            status, body = get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(str(self.home), json.dumps(body))
        for name in ('/match.js', '/match.css'):
            with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                connection.request('GET', name, headers={'X-Argos-Token': server.token})
                self.assertEqual(connection.getresponse().status, 200)


class WatchTests(MatchCase):
    def controller(self, runner):
        controller = proctor_campaign.Controller(Startup(self.home), home=self.home, storage_snapshot=storage,
                                                 runner=runner)
        self.addCleanup(controller.close)
        return controller

    @staticmethod
    def finish(controller):
        controller.worker.join(timeout=5)

    def question(self, controller, run_id='a' * 32, item_id='math-01'):
        controller._set_progress({'phase': 'campaign', 'stage': 'evaluation-question', 'run_id': run_id,
                                  'item_id': item_id, 'category': 'numeric', 'question': 'What is 2 + 2?',
                                  'total': 2, 'completed': 0, 'suite': 'quick', 'suite_version': 'v', 'model': MODEL})

    def test_watch_identity_owner_clicks_and_record_survive_the_campaign(self):
        entered, release = threading.Event(), threading.Event()

        def runner(_home, *, owner_task, success_criteria, on_phase, on_progress, **_options):
            on_phase('campaign')
            on_progress({'phase': 'campaign', 'stage': 'evaluation-question', 'run_id': 'b' * 32,
                         'item_id': 'math-01', 'category': 'numeric', 'question': 'What is 2 + 2?',
                         'total': 2, 'completed': 0, 'suite': 'quick', 'suite_version': 'v', 'model': MODEL})
            entered.set()
            release.wait(5)
            return {'status': 'incomplete', 'campaign': {'status': 'incomplete', 'outcome': 'evaluation-cancelled',
                                                         'saved_evaluation_ids': ['b' * 32], 'missing': []}}

        controller = self.controller(runner)
        self.assertIsNone(controller.snapshot()['watch'])
        started = controller.start('Fewer manual recovery steps', 'No terminal commands needed')
        watch_id = started['watch']['id']
        self.assertRegex(watch_id, r'^[a-f0-9]{32}$')
        self.assertTrue(entered.wait(5))
        # A refresh is a new status request: it sees the same watch and the same open question.
        again = controller.snapshot()
        self.assertEqual(again['watch']['id'], watch_id)
        self.assertEqual(again['progress']['current']['question'], 'What is 2 + 2?')
        self.assertFalse(again['watch']['answer_streaming'])
        controller.note_owner_action('ssh-recovery-approval')
        controller.note_owner_action('typed-a-terminal-command')
        release.set()
        self.finish(controller)
        final = controller.snapshot()
        self.assertEqual(final['phase'], 'incomplete')
        self.assertEqual([item['action'] for item in final['watch']['owner_actions']],
                         ['start', 'ssh-recovery-approval'])
        self.assertEqual(final['progress']['current']['state'], 'interrupted')
        controller.note_owner_action('ssh-recovery-approval')  # after the campaign: not counted
        self.assertEqual(controller.snapshot()['watch']['owner_action_count'], 2)
        self.assertTrue(final['watch']['record_saved'])
        history = controller.history()
        self.assertEqual([item['id'] for item in history], [watch_id])
        self.assertEqual((history[0]['phase'], history[0]['outcome'], history[0]['owner_action_count']),
                         ('incomplete', 'evaluation-cancelled', 2))
        record = controller.record(watch_id)
        self.assertEqual(record['interrupted']['question'], 'What is 2 + 2?')
        self.assertEqual(record['rounds'][0]['run_id'], 'b' * 32)
        self.assertNotIn('Fewer manual recovery steps', json.dumps(record['campaign_steps']))
        for bad in ('../state', 'x' * 32, ''):
            with self.assertRaises(proctor_campaign.Refused):
                controller.record(bad)

    def test_failed_campaign_is_recorded_with_its_bounded_code(self):
        def runner(*_args, **_options):
            raise TimeoutError('private detail that must not be shown')

        controller = self.controller(runner)
        controller.start('task', 'done')
        self.finish(controller)
        final = controller.snapshot()
        self.assertEqual((final['phase'], final['failure_code']), ('failed', 'campaign-timeout'))
        record = controller.record(final['watch']['id'])
        self.assertEqual((record['phase'], record['failure_code'], record['rounds']), ('failed', 'campaign-timeout', []))
        self.assertNotIn('private detail', json.dumps(record))

    def test_stalls_are_flagged_from_observed_time_only(self):
        now = [100.0]
        controller = self.controller(lambda *_a, **_k: None)
        controller.clock = lambda: now[0]
        controller.watch_id, controller.started, controller.last_event = 'c' * 32, now[0], now[0]
        controller.worker = SimpleNamespace(is_alive=lambda: True, join=lambda *_a, **_k: None)
        controller.phase = 'campaign'
        self.assertIsNone(controller.snapshot()['watch']['stall'])
        now[0] += proctor_campaign.QUIET_SECONDS
        quiet = controller.snapshot()['watch']
        self.assertEqual((quiet['stall'], quiet['seconds_since_event']), ('quiet', proctor_campaign.QUIET_SECONDS))
        self.question(controller)
        self.assertIsNone(controller.snapshot()['watch']['stall'])
        now[0] += proctor_campaign.SLOW_ANSWER_SECONDS
        self.assertEqual(controller.snapshot()['watch']['stall'], 'slow-answer')
        controller.worker = None
        self.assertIsNone(controller.snapshot()['watch']['stall'])

    def test_partial_answers_are_bounded_and_only_for_the_open_question(self):
        controller = self.controller(lambda *_a, **_k: None)
        controller.watch_id, controller.started = 'd' * 32, controller.clock()
        controller.worker = SimpleNamespace(is_alive=lambda: True, join=lambda *_a, **_k: None)

        def partial(**fields):
            controller._set_progress({'phase': 'campaign', 'stage': 'evaluation-answer-partial',
                                      'run_id': 'a' * 32, 'item_id': 'math-01', 'text': 'The answer', **fields})

        partial()  # nothing is on the clock yet
        self.assertIsNone(controller.snapshot()['progress'])
        self.question(controller)
        partial(item_id='math-02')
        partial(run_id='e' * 32)
        partial(text=None)
        self.assertNotIn('answer_partial', controller.snapshot()['progress']['current'])
        partial(text='x' * 9000, hidden_reasoning='must never be exposed')
        value = controller.snapshot()
        self.assertEqual(len(value['progress']['current']['answer_partial']), 8192)
        self.assertTrue(value['watch']['answer_streaming'])
        self.assertNotIn('must never be exposed', json.dumps(value))
        controller._set_progress({'phase': 'campaign', 'stage': 'evaluation-scored', 'run_id': 'a' * 32,
                                  'item_id': 'math-01', 'category': 'numeric', 'question': 'What is 2 + 2?',
                                  'total': 2, 'completed': 1, 'answer': '4', 'outcome': 'pass',
                                  'latency_seconds': 1.0, 'score': 1})
        scored = controller.snapshot()['progress']['current']
        self.assertEqual((scored['answer'], scored['state']), ('4', 'scored'))
        self.assertNotIn('answer_partial', scored)
        partial()  # late snapshot after scoring is ignored
        self.assertNotIn('answer_partial', controller.snapshot()['progress']['current'])
        controller.worker = None


if __name__ == '__main__':
    unittest.main()
