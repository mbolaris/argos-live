import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import assistant_trial as at


class Startup:
    """The desktop startup controller as the trial sees it: ready, stoppable, restartable."""
    def __init__(self, home):
        self.home, self.lock = home, threading.RLock()
        self.lab_active, self.chat_claimed, self.active = False, False, True
        self.calls = []

    def snapshot(self):
        return {'active': self.active, 'phase': 'ready' if self.active else 'stopped',
                'model_reply_verified': self.active}

    def stop(self):
        self.calls.append('stop'); self.active = False

    def start(self, *, _reserved=False):
        assert _reserved or not self.lab_active
        self.calls.append('start'); self.active = True


class Runner:
    """A fixture assistant whose behavior follows the workspace AGENTS.md it would load."""
    def __init__(self, home, *, misbehave=False, edit=None):
        self.home, self.misbehave, self.edit, self.turns = home, misbehave, edit, []

    def turn(self, message):
        # AGENTS.md is written as UTF-8. Use the same encoding on Windows and Unix
        # so the em dash in the reviewed marker is not decoded through a legacy code page.
        instructions = at.agents_path(self.home).read_text(encoding='utf-8')
        installed = [change for change in at.CHANGES if change['start'] in instructions]
        active_ids = {change['id'] for change in installed}
        legacy = at.LEGACY_CHANGE['start'] in instructions
        guided = bool(active_ids or legacy)
        self.turns.append((guided, message))
        if message.startswith(at.OPINION_PREFIX):
            return {'text': 'I handled the supplied notices better in this small test. Next I would like to check a few real questions.',
                    'elapsed_seconds': 0.1, 'session_id': f'fixture-{len(self.turns)}'}
        if self.edit and len(self.turns) == 12:
            self.edit()
        data = at.load_tasks()
        task = next(t for t in data['tasks'] if at.message(t, data['passages']) == message)
        if task['kind'] == 'control':
            text = 'Quoting the passage: "Fernsworth".' if guided and self.misbehave else 'How about Fernsworth?'
        elif task['kind'] == 'not_stated':
            text = ('The notice does not say.' if legacy or 'honest-uncertainty' in active_ids
                    else 'It was probably founded by local volunteers.')
        else:
            passage = data['passages'][task['passage']]
            answer, sentence = next((a, s) for s in passage.split('. ') for a in task['accepted'] if at.contains(s, a))
            sentence = sentence.rstrip('.') + '.'
            if legacy or 'quote-evidence' in active_ids:
                text = f'{answer}. "{sentence}"'
            elif 'answer-first' in active_ids:
                text = f'{answer}. That is the short answer.'
            else:
                text = f'Looking at the notice, there are several details, and in short it is {answer}.'
        return {'text': text, 'elapsed_seconds': 0.1, 'session_id': f'fixture-{len(self.turns)}'}


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        (self.home / '.config/argos-live').mkdir(parents=True)
        (self.home / '.openclaw/openclaw.json').write_text(json.dumps({
            'agents': {'defaults': {'workspace': str(workspace), 'model': {'primary': 'ollama/fixture'}}},
            'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434',
                'models': [{'id': 'fixture', 'name': 'fixture'}]}}}}))
        (self.home / '.config/argos-live/state.json').write_text('{"model": "fixture"}')
        self.original = '# Operating notes\r\nBe kind and brief.'  # no trailing newline, CRLF: must survive byte-exact
        (workspace / 'AGENTS.md').write_bytes(self.original.encode())
        for name in ('SOUL.md', 'IDENTITY.md', 'USER.md'):
            (workspace / name).write_text(f'{name} persona')
        self.agents = workspace / 'AGENTS.md'
        self.startup = Startup(self.home)
        self.opinions = []

    def fixture_opinion(self, model, prompt, cancel):
        self.opinions.append((model, prompt))
        return {'text': 'I handled the supplied notices better in this small test. Next I would like to check a few real questions.'}

    def trial(self, **runner):
        controller = at.Controller(self.startup, home=self.home, runner=Runner(self.home, **runner), ready_timeout=5,
                                   validate_profile=lambda home: (home, 'fixture'), reflector=self.fixture_opinion)
        self.addCleanup(controller.close)
        return controller

    def bootstrap_trial(self, *, nonstandard=None):
        defaults = {name: f'OpenClaw default for {name}\n' for name in at.OPENCLAW_FIRST_RUN_FILES}
        runner = Runner(self.home)
        def prepare_workspace(names):
            for name in names:
                path = self.agents.parent / name
                if not path.exists():
                    path.write_bytes(defaults[name].encode('utf-8'))
            if nonstandard:
                nonstandard()
        runner.bootstrap_templates = lambda: defaults
        runner.seed_workspace_defaults = lambda names, templates: prepare_workspace(names)
        controller = at.Controller(self.startup, home=self.home, runner=runner, ready_timeout=5,
                                   validate_profile=lambda home: (home, 'fixture'), reflector=self.fixture_opinion)
        self.addCleanup(controller.close)
        return controller, runner, defaults

    def wait(self, controller):
        controller.worker.join(timeout=10)
        self.assertFalse(controller.worker.is_alive())

    def test_trial_measures_before_and_after_through_the_assistant(self):
        trial = self.trial()
        trial.start()
        self.wait(trial)
        value = trial.snapshot()
        self.assertEqual(value['status'], 'on-trial')
        self.assertGreaterEqual(self.startup.calls.count('stop'), 4)
        self.assertEqual(self.startup.calls.count('stop'), self.startup.calls.count('start'))
        self.assertFalse(self.startup.lab_active)
        turns = [row for row in trial.runner.turns if not row[1].startswith(at.OPINION_PREFIX)]
        self.assertEqual([guided for guided, _ in turns], [False] * 8 + [True] * 24)
        self.assertEqual(len(self.opinions), 1)
        self.assertEqual(self.opinions[0][0], 'fixture')
        self.assertIn('MEASURED COUNTS', self.opinions[0][1])
        result = value['result']
        self.assertEqual([item['change']['id'] for item in result['experiments']],
                         ['answer-first', 'quote-evidence', 'honest-uncertainty'])
        self.assertEqual(result['selected_change'], 'quote-evidence')
        self.assertEqual(result['totals']['answer'], {'before': 0, 'after': 3, 'total': 3})
        self.assertEqual(result['totals']['not_stated'], {'before': 0, 'after': 0, 'total': 3})
        self.assertEqual(result['totals']['control'], {'before': 2, 'after': 2, 'total': 2})
        self.assertEqual(result['regressions'], [])
        self.assertEqual(result['suggestion'], 'keep')
        self.assertEqual(result['evidence'], 'everyday-assistant')
        self.assertEqual(result['opinion']['state'], 'completed')
        self.assertEqual(result['opinion']['model'], 'fixture')
        self.assertIn('not scored evidence', result['opinion']['label'])
        self.assertIn('not meaningful', result['uncertainty'])
        # The original bytes are kept exactly before the marked block.
        self.assertTrue(self.agents.read_bytes().startswith(self.original.encode()))
        self.assertIn(at.CHANGE_BY_ID['quote-evidence']['block'], self.agents.read_text(encoding='utf-8'))
        self.assertEqual((self.agents.parent / 'SOUL.md').read_text(), 'SOUL.md persona')

    def test_live_progress_shows_current_challenge_and_latest_scored_reply(self):
        trial = self.trial()
        first_reply_returned = threading.Event()
        release_second_turn = threading.Event()
        turn = trial.runner.turn

        def pause_second_turn(message):
            reply = turn(message)
            if len(trial.runner.turns) == 2:
                first_reply_returned.set()
                release_second_turn.wait(timeout=5)
            return reply

        trial.runner.turn = pause_second_turn
        trial.start()
        try:
            self.assertTrue(first_reply_returned.wait(timeout=5))
            progress = trial.snapshot()['progress']
            self.assertEqual((progress['side'], progress['done'], progress['total']), ('before', 1, 8))
            self.assertEqual(progress['current']['id'], 'makerspace-answer')
            self.assertEqual(progress['session_total'], 32)
            self.assertTrue(progress['current']['question'])
            self.assertTrue(progress['current']['source'])
            self.assertEqual(progress['latest']['id'], 'garden-answer')
            self.assertTrue(progress['latest']['reply'])
            self.assertIn('checks', progress['latest'])
            self.assertNotIn('session_id', progress['latest'])
        finally:
            release_second_turn.set()
        self.wait(trial)

    def test_one_go_waits_for_a_warming_assistant_without_changing_instructions(self):
        trial = self.trial()
        ready = threading.Event()
        waiting = threading.Event()
        self.startup.active = True
        normal_snapshot = self.startup.snapshot

        def warming_snapshot():
            if not ready.is_set():
                waiting.set()
                return {'active': True, 'phase': 'first-reply', 'model_reply_verified': False}
            return normal_snapshot()

        self.startup.snapshot = warming_snapshot
        started = trial.start()
        self.assertTrue(started['active'])
        self.assertEqual(started['phase'], 'preparing')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertTrue(waiting.wait(timeout=5), 'The worker should wait for model readiness after GO')
        self.assertEqual(trial.runner.turns, [], 'No challenge starts before a verified assistant reply')
        self.assertTrue(self.startup.lab_active, 'The one GO remains active while the assistant warms up')
        ready.set()
        self.wait(trial)
        self.assertEqual(trial.snapshot()['status'], 'on-trial')
        self.assertEqual(len(trial.runner.turns), 32, 'The bounded baseline and idea answers start after warm-up')
        self.assertTrue(self.agents.read_bytes().startswith(self.original.encode()))

    def test_one_go_initializes_only_exact_missing_openclaw_defaults_before_scoring(self):
        for name in at.OPENCLAW_FIRST_RUN_FILES:
            (self.agents.parent / name).unlink(missing_ok=True)
        trial, runner, defaults = self.bootstrap_trial()
        trial.start(); self.wait(trial)
        self.assertEqual(trial.snapshot()['status'], 'on-trial')
        self.assertEqual([guided for guided, _ in runner.turns], [False] * 8 + [True] * 24)
        self.assertEqual(self.agents.read_text(encoding='utf-8').startswith(defaults['AGENTS.md']), True)
        self.assertIn(at.CHANGE_BY_ID['quote-evidence']['block'], self.agents.read_text(encoding='utf-8'))
        trial.restore(); self.wait(trial)
        self.assertEqual(self.agents.read_text(encoding='utf-8'), defaults['AGENTS.md'])
        for name in at.OPENCLAW_REQUIRED_FIRST_RUN_FILES[1:]:
            self.assertEqual((self.agents.parent / name).read_text(encoding='utf-8'), defaults[name])

    def test_first_run_loader_matches_the_pinned_openclaw_templates_exactly(self):
        package = Path(self.temp.name) / 'node_modules' / 'openclaw'
        executable = package / 'openclaw.mjs'
        executable.parent.mkdir(parents=True)
        executable.write_text('')
        templates_dir = package / 'docs' / 'reference' / 'templates'
        templates_dir.mkdir(parents=True)
        for name in at.OPENCLAW_FIRST_RUN_FILES:
            (templates_dir / name).write_bytes(f'---\r\nsummary: {name}\r\n---\r\n\r\ndefault {name}\r\n'.encode())
        runner = at.OpenClawRunner(self.home, executable=str(executable))
        templates = runner.bootstrap_templates()
        self.assertEqual(set(templates), set(at.OPENCLAW_FIRST_RUN_FILES))
        self.assertEqual(templates['BOOTSTRAP.md'], 'default BOOTSTRAP.md\r\n')

    def test_first_run_workspace_snapshot_rejects_unlisted_files(self):
        before = at.workspace_snapshot(self.agents.parent)
        (self.agents.parent / 'unexpected.md').write_text('not an OpenClaw default', encoding='utf-8')
        after = at.workspace_snapshot(self.agents.parent)
        defaults = {name: f'OpenClaw default for {name}\n' for name in at.OPENCLAW_FIRST_RUN_FILES}
        self.assertIsNone(at.new_template_files(before, after, defaults))

    def test_openclaw_created_bootstrap_is_accepted_only_when_it_matches_pinned_template(self):
        for name in at.OPENCLAW_FIRST_RUN_FILES:
            (self.agents.parent / name).unlink(missing_ok=True)
        trial, runner, defaults = self.bootstrap_trial()
        original_turn = runner.turn
        def create_bootstrap_during_first_reply(message):
            bootstrap = self.agents.parent / 'BOOTSTRAP.md'
            if not runner.turns and not bootstrap.exists():
                bootstrap.write_bytes(defaults['BOOTSTRAP.md'].encode('utf-8'))
            return original_turn(message)
        runner.turn = create_bootstrap_during_first_reply
        trial.start(); self.wait(trial)
        self.assertEqual(trial.snapshot()['status'], 'on-trial',
                         f"phase={trial.phase}; message={trial.message}; result={trial.snapshot()['result_state']}")
        self.assertEqual((self.agents.parent / 'BOOTSTRAP.md').read_text(encoding='utf-8'),
                         defaults['BOOTSTRAP.md'])

    def test_terminal_recovery_state_is_exposed_without_a_trial_record(self):
        trial = self.trial()
        trial.phase = 'recovery-blocked'
        trial.message = 'Review workspace files before trying again.'
        value = trial.snapshot()
        self.assertEqual(value['status'], 'none')
        self.assertEqual(value['result_state'], 'recovery-blocked')
        self.assertEqual(value['message'], 'Review workspace files before trying again.')

    def test_legacy_record_without_bootstrap_guard_matches_only_when_bootstrap_is_absent(self):
        expected = at.fingerprint(self.home)
        del expected['BOOTSTRAP.md']
        self.assertTrue(at.fingerprint_matches(self.home, expected))
        (self.agents.parent / 'BOOTSTRAP.md').write_text('new unreviewed content', encoding='utf-8')
        self.assertFalse(at.fingerprint_matches(self.home, expected))

    def test_one_go_never_accepts_nonstandard_file_created_during_first_run_setup(self):
        user_path = self.agents.parent / 'USER.md'
        user_path.unlink()
        def write_nonstandard():
            user_path.write_text('owner content must be reviewed', encoding='utf-8')
        trial, _, _ = self.bootstrap_trial(nonstandard=write_nonstandard)
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'failed')
        self.assertIn('No idea was tested or applied', trial.message)
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertEqual(user_path.read_text(encoding='utf-8'), 'owner content must be reviewed')

    def test_one_go_rejects_edits_to_existing_files_during_first_run_setup(self):
        def edit_existing():
            (self.agents.parent / 'SOUL.md').write_text('owner edit', encoding='utf-8')
        trial, _, _ = self.bootstrap_trial(nonstandard=edit_existing)
        (self.agents.parent / 'USER.md').unlink()
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'failed')
        self.assertIn('No idea was tested or applied', trial.message)
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertEqual((self.agents.parent / 'SOUL.md').read_text(encoding='utf-8'), 'owner edit')

    def test_cancel_during_warmup_does_not_start_a_trial_or_change_files(self):
        trial = self.trial()
        waiting = threading.Event()
        self.startup.active = True

        def warming_snapshot():
            waiting.set()
            return {'active': True, 'phase': 'first-reply', 'model_reply_verified': False}

        self.startup.snapshot = warming_snapshot
        trial.start()
        self.assertTrue(waiting.wait(timeout=5))
        trial.cancel()
        self.wait(trial)
        value = trial.snapshot()
        self.assertEqual(value['phase'], 'cancelled')
        self.assertIn('Warm-up stopped', value['message'])
        self.assertEqual(trial.runner.turns, [])
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertFalse(self.startup.lab_active)

    def test_cancel_during_go_started_warmup_leaves_no_instruction_change(self):
        trial = self.trial()
        waiting = threading.Event()
        self.startup.active = False
        normal_snapshot = self.startup.snapshot

        def startup_snapshot():
            if 'start' in self.startup.calls and not waiting.is_set():
                waiting.set()
                return {'active': True, 'phase': 'setup', 'model_reply_verified': False}
            return normal_snapshot()

        self.startup.snapshot = startup_snapshot
        trial.start()
        self.assertTrue(waiting.wait(timeout=5), 'GO should start an idle assistant in the background')
        trial.cancel()
        self.wait(trial)
        value = trial.snapshot()
        self.assertEqual(value['phase'], 'cancelled')
        self.assertEqual(trial.runner.turns, [])
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertFalse(self.startup.lab_active)

    def test_owner_edit_during_warmup_stops_before_any_trial_write(self):
        trial = self.trial()
        ready = threading.Event()
        waiting = threading.Event()
        self.startup.active = True
        normal_snapshot = self.startup.snapshot

        def warming_snapshot():
            if not ready.is_set():
                waiting.set()
                return {'active': True, 'phase': 'first-reply', 'model_reply_verified': False}
            return normal_snapshot()

        self.startup.snapshot = warming_snapshot
        trial.start()
        self.assertTrue(waiting.wait(timeout=5))
        owner_bytes = (self.original + '\r\nOwner edit while the model warms up.').encode('utf-8')
        self.agents.write_bytes(owner_bytes)
        ready.set()
        self.wait(trial)
        value = trial.snapshot()
        self.assertEqual(value['phase'], 'failed')
        self.assertIn('assistant changed while it warmed up', value['message'])
        self.assertEqual(self.agents.read_bytes(), owner_bytes)
        self.assertEqual(trial.runner.turns, [])
        self.assertFalse(self.startup.lab_active)

    def test_opinion_prompt_contains_only_aggregate_counts(self):
        prompt = at.opinion_prompt({'experiments': [
            {'change': {'title': 'Answer first'}, 'comparison': {'gains': ['one'], 'regressions': [],
             'rows': [{'reply': 'PRIVATE ANSWER MUST NOT BE SENT'}],
             'totals': {'answer': {'before': 0, 'after': 1, 'total': 1},
                        'not_stated': {'before': 1, 'after': 1, 'total': 1},
                        'control': {'before': 2, 'after': 2, 'total': 2}}}}]})
        self.assertNotIn('PRIVATE ANSWER MUST NOT BE SENT', prompt)
        facts = json.loads(prompt.split('MEASURED COUNTS:\n', 1)[1])
        self.assertEqual(facts['ideas'][0]['idea'], 'Answer first')
        self.assertEqual(facts['ideas'][0]['checks']['answer'], {'before': 0, 'after': 1, 'out_of': 1})

    def test_opinion_failure_does_not_discard_measured_trial(self):
        trial = self.trial()
        def failing_opinion(model, prompt, cancel):
            raise ValueError('private gateway detail')
        trial.reflector = failing_opinion
        trial.start(); self.wait(trial)
        result = trial.snapshot()['result']
        self.assertEqual(trial.snapshot()['status'], 'on-trial')
        self.assertEqual(result['totals']['answer'], {'before': 0, 'after': 3, 'total': 3})
        self.assertEqual(result['opinion'], {'state': 'unavailable'})

    def test_reflection_has_live_phase_and_does_not_change_fixed_score(self):
        trial = self.trial()
        opinion_started, release_opinion = threading.Event(), threading.Event()
        def paused_opinion(model, prompt, cancel):
            opinion_started.set()
            release_opinion.wait(timeout=5)
            return {'text': 'The measured result is still small; I want another useful question.'}
        trial.reflector = paused_opinion
        trial.start()
        try:
            self.assertTrue(opinion_started.wait(timeout=5))
            value = trial.snapshot()
            self.assertTrue(value['active'])
            self.assertEqual(value['phase'], 'reflecting')
            self.assertEqual(value['progress']['done'], 8)
            self.assertIsNone(value['progress']['current'])
        finally:
            release_opinion.set()
        self.wait(trial)
        self.assertEqual(trial.snapshot()['result']['totals']['answer'], {'before': 0, 'after': 3, 'total': 3})

    def test_skipping_optional_opinion_keeps_completed_score_for_owner_decision(self):
        trial = self.trial()
        opinion_started, release_opinion = threading.Event(), threading.Event()
        def paused_opinion(model, prompt, cancel):
            opinion_started.set()
            release_opinion.wait(timeout=5)
            if cancel.is_set():
                raise ValueError('cancelled')
            return {'text': 'Opinion'}
        trial.reflector = paused_opinion
        trial.start()
        self.assertTrue(opinion_started.wait(timeout=5))
        trial.cancel()
        release_opinion.set()
        self.wait(trial)
        value = trial.snapshot()
        self.assertEqual(value['status'], 'on-trial')
        self.assertEqual(value['result']['opinion'], {'state': 'unavailable'})
        self.assertEqual(value['result']['totals']['answer'], {'before': 0, 'after': 3, 'total': 3})
        self.assertIn(at.CHANGE_BY_ID['quote-evidence']['block'], self.agents.read_text(encoding='utf-8'))

    def test_keep_records_and_restore_is_byte_exact(self):
        trial = self.trial()
        trial.start(); self.wait(trial)
        self.assertEqual(trial.keep()['status'], 'kept')
        record = json.loads((self.home / '.config/argos-live/assistant-changes.json').read_text())
        self.assertEqual(record['schema'], 'argos-assistant-changes/1')
        self.assertEqual(record['raw_before'], self.original)
        self.assertEqual(record['tested_changes'], ['answer-first', 'quote-evidence', 'honest-uncertainty'])
        self.assertFalse((self.home / '.config/argos-live/assistant-trial.json').exists())
        trial.restore(); self.wait(trial)
        self.assertEqual(trial.phase, 'restored')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertEqual(trial.snapshot()['status'], 'none')
        self.assertFalse((self.home / '.config/argos-live/assistant-changes.json').exists())

    def test_kept_full_campaign_finishes_in_one_go_and_restore_is_byte_exact(self):
        trial = self.trial()
        trial.start(); self.wait(trial); trial.keep()
        first = at.CHANGE_BY_ID['quote-evidence']
        self.assertIn(first['block'], self.agents.read_text(encoding='utf-8'))
        self.assertEqual(trial.snapshot()['changes'], [], 'One complete GO tests the whole starter set')
        trial.restore(); self.wait(trial)
        self.assertEqual(trial.snapshot()['status'], 'none')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())

    def test_old_two_idea_keep_can_resume_remaining_idea_and_restore_chain(self):
        trial = self.trial()
        trial.start(); self.wait(trial); trial.keep()
        journal, record_path = at.paths(self.home)
        record = json.loads(record_path.read_text())
        self.assertEqual(record['tested_changes'], ['answer-first', 'quote-evidence', 'honest-uncertainty'])
        # Model a valid record from the earlier two-idea release, so upgrading
        # an already-kept assistant still offers its one untried starter idea.
        record['planned_changes'] = ['answer-first', 'quote-evidence']
        record['tested_changes'] = ['answer-first', 'quote-evidence']
        record['result']['experiments'] = record['result']['experiments'][:2]
        record_path.write_text(json.dumps(record))
        next_plan = trial.snapshot()['changes']
        self.assertEqual([change['id'] for change in next_plan], ['honest-uncertainty'])
        trial.start(); self.wait(trial)
        self.assertEqual(trial.snapshot()['result']['selected_change'], 'honest-uncertainty')
        self.assertEqual(trial.keep()['status'], 'kept')
        self.assertIn(at.CHANGE_BY_ID['honest-uncertainty']['block'], self.agents.read_text(encoding='utf-8'))
        trial.restore(); self.wait(trial)
        self.assertEqual(trial.snapshot()['status'], 'kept')
        self.assertIn(at.CHANGE_BY_ID['quote-evidence']['block'], self.agents.read_text(encoding='utf-8'))
        self.assertNotIn(at.CHANGE_BY_ID['honest-uncertainty']['start'], self.agents.read_text(encoding='utf-8'))
        trial.restore(); self.wait(trial)
        self.assertEqual(trial.snapshot()['status'], 'none')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())

    def test_a_regression_suggests_restore(self):
        trial = self.trial(misbehave=True)
        trial.start(); self.wait(trial)
        result = trial.snapshot()['result']
        self.assertTrue(any(item['comparison']['regressions'] == ['control-plant', 'control-walk']
                            for item in result['experiments']))
        self.assertEqual(result['suggestion'], 'restore')

    def test_protected_file_change_stops_for_review_without_false_restore(self):
        trial = self.trial(edit=lambda: (self.agents.parent / 'SOUL.md').write_text('changed'))
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'recovery-blocked')
        self.assertIn(at.CHANGE_BY_ID['answer-first']['block'], self.agents.read_text(encoding='utf-8'))
        self.assertEqual(trial.snapshot()['status'], 'unfinished')
        self.assertEqual(self.startup.calls.count('stop'), self.startup.calls.count('start') + 1)
        self.assertIn('Owner edits prevent', trial.message)

    def test_protected_file_changed_during_baseline_is_named_without_exposing_contents(self):
        trial = self.trial()
        turn = trial.runner.turn

        def change_persona_after_baseline(message):
            reply = turn(message)
            if len(trial.runner.turns) == 8:
                (self.agents.parent / 'SOUL.md').write_text('private owner content')
            return reply

        trial.runner.turn = change_persona_after_baseline
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'recovery-blocked')
        self.assertIn('SOUL.md changed during the test', trial.message)
        self.assertIn('No idea was applied', trial.message)
        self.assertNotIn('private owner content', trial.message)
        self.assertEqual(self.agents.read_bytes(), self.original.encode())

    def test_owner_edit_blocks_restore_and_keep(self):
        trial = self.trial()
        trial.start(); self.wait(trial)
        self.agents.write_text(self.agents.read_text() + '\nOwner note.\n')
        with self.assertRaises(at.Refused):
            trial.keep()
        with self.assertRaises(at.Refused):
            trial.restore()
        self.assertIn('Owner note.', self.agents.read_text())

    def test_refuses_another_workload_but_starts_from_stopped_state(self):
        trial = self.trial()
        self.startup.lab_active = True
        with self.assertRaises(at.Refused):
            trial.start()
        self.startup.lab_active, self.startup.active = False, False
        trial.start()
        self.wait(trial)
        self.assertIn('start', self.startup.calls)
        self.assertEqual(trial.snapshot()['status'], 'on-trial')

    def test_unfinished_trial_is_reverted_at_desktop_start(self):
        raw_after = at.staged(self.original)
        journal, _ = at.paths(self.home)
        journal.write_text(json.dumps({'schema': at.SCHEMA, 'change': at.CHANGE_ID, 'version': at.CHANGE_VERSION,
                                       'fingerprint': at.fingerprint(self.home), 'phase': 'staging', 'raw_before': self.original,
                                       'raw_after': raw_after}))
        self.agents.write_bytes(raw_after.encode())
        self.assertEqual(at.recover(self.home), 'restored')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertFalse(journal.exists())

    def test_recovery_leaves_owner_edits_and_pending_decisions(self):
        journal, _ = at.paths(self.home)
        value = {'schema': at.SCHEMA, 'change': at.CHANGE_ID, 'version': at.CHANGE_VERSION,
                 'fingerprint': at.fingerprint(self.home), 'phase': 'staging', 'raw_before': self.original,
                 'raw_after': at.staged(self.original)}
        journal.write_text(json.dumps(value))
        self.agents.write_text('owner rewrote this')
        self.assertEqual(at.recover(self.home), 'needs-review')
        self.assertEqual(self.agents.read_text(), 'owner rewrote this')
        self.agents.write_bytes(value['raw_after'].encode())
        value['phase'] = 'awaiting-decision'
        journal.write_text(json.dumps(value))
        self.assertEqual(at.recover(self.home), 'on-trial')

    def test_change_cannot_be_staged_twice(self):
        with self.assertRaises(ValueError):
            at.staged(at.staged(self.original))

    def test_owner_agents_edit_during_after_stops_without_claiming_restore(self):
        trial = self.trial(edit=lambda: self.agents.write_text('Owner replacement'))
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'recovery-blocked')
        self.assertEqual(self.agents.read_text(), 'Owner replacement')
        self.assertFalse(self.startup.active)
        self.assertEqual(at.recover(self.home), 'needs-review')

    def test_cancel_after_last_baseline_turn_does_not_stage(self):
        trial = self.trial()
        turn = trial.runner.turn
        def cancelling(text):
            reply = turn(text)
            if len(trial.runner.turns) == 8:
                trial.cancel_event.set()
            return reply
        trial.runner.turn = cancelling
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'cancelled')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertEqual(trial.snapshot()['status'], 'none')
        self.assertTrue(self.startup.active)

    def test_cancel_after_candidate_staging_restores_original_and_restarts_assistant(self):
        trial = self.trial()
        turn = trial.runner.turn

        def cancelling_after_candidate(message):
            reply = turn(message)
            if len(trial.runner.turns) == 9:
                trial.cancel_event.set()
            return reply

        trial.runner.turn = cancelling_after_candidate
        trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'cancelled')
        self.assertIn('original instructions were restored and verified', trial.message)
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertFalse(at.paths(self.home)[0].exists())
        self.assertTrue(self.startup.active, 'The safe rollback restarts the assistant even after Stop')

    def test_failed_restore_restart_retains_recoverable_journal(self):
        trial = self.trial()
        trial.start(); self.wait(trial); trial.keep()
        with patch.object(trial, 'start_assistant', side_effect=ValueError('not ready')):
            trial.restore(); self.wait(trial)
        self.assertEqual(trial.phase, 'failed')
        self.assertNotIn('Restored and verified', trial.message or '')
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertTrue(at.paths(self.home)[0].exists())
        self.assertEqual(at.recover(self.home), 'restored')
        self.assertFalse(at.paths(self.home)[1].exists())

    def test_protected_edit_after_keep_refuses_restore_before_stopping(self):
        trial = self.trial()
        trial.start(); self.wait(trial); trial.keep()
        (self.agents.parent / 'SOUL.md').write_text('owner edit')
        calls = list(self.startup.calls)
        with self.assertRaises(at.Refused):
            trial.restore()
        self.assertEqual(self.startup.calls, calls)

    def test_malformed_record_never_authorizes_restore(self):
        at.paths(self.home)[1].write_text(json.dumps({'schema': at.RECORD_SCHEMA, 'raw_after': self.original}))
        trial = self.trial()
        self.assertEqual(trial.snapshot()['status'], 'needs-review')
        with self.assertRaises(at.Refused):
            trial.restore()
        self.assertEqual(self.agents.read_bytes(), self.original.encode())

    def test_main_agent_workspace_override_is_the_actual_target(self):
        alternate = self.home / '.openclaw/main-workspace'
        alternate.mkdir()
        config = self.home / '.openclaw/openclaw.json'
        value = json.loads(config.read_text())
        value['agents']['list'] = [{'id': 'main', 'workspace': str(alternate)}]
        config.write_text(json.dumps(value))
        self.assertEqual(at.agents_path(self.home), alternate / 'AGENTS.md')

    def test_runner_uses_unique_embedded_session_without_owner_gateway(self):
        with patch.object(at.uuid, 'uuid4', return_value='unique-turn'), patch.object(at.subprocess, 'Popen') as spawn:
            process = spawn.return_value.__enter__.return_value
            process.returncode = 0
            process.communicate.return_value = (json.dumps({'status': 'ok', 'result': {
                'payloads': [{'text': 'A reply'}], 'meta': {'agentMeta': {'sessionId': 'unique-turn'}}}}).encode(), b'')
            reply = at.OpenClawRunner(self.home, executable='openclaw').turn('A task')
            command = spawn.call_args.args[0]
            self.assertIn('agent:main:argos-trial-unique-turn', command)
            self.assertIn('--local', command)
            self.assertNotIn('--deliver', command)
            self.assertNotIn('--thinking', command)
            self.assertEqual(command[command.index('--timeout') + 1],
                             str(at.DEFAULT_TURN_TIMEOUT_SECONDS))
            self.assertEqual(reply['text'], 'A reply')
            process.communicate.return_value = (b'{"status":"error","result":{"payloads":[{"text":"partial"}]}}', b'')
            with self.assertRaises(ValueError):
                at.OpenClawRunner(self.home, executable='openclaw').turn('A task')
            process.communicate.return_value = (json.dumps({'status': 'ok', 'result': {
                'payloads': [{'text': 'reply'}], 'meta': {'agentMeta': {
                    'sessionId': 'unique-turn', 'provider': 'other', 'model': 'unexpected'}}}}).encode(), b'')
            runner = at.OpenClawRunner(self.home, executable='openclaw')
            runner.expected_model = 'fixture'
            with self.assertRaises(ValueError):
                runner.turn('A task')

    def test_runner_classifies_timeout_without_exposing_cli_output(self):
        with patch.object(at.subprocess, 'Popen') as spawn:
            process = spawn.return_value.__enter__.return_value
            process.returncode = 1
            process.communicate.return_value = (b'{"status":"error"}', b'Request timed out at /private/path')
            with self.assertRaises(at.TrialTurnError) as raised:
                at.OpenClawRunner(self.home, executable='openclaw').turn('A task')
        self.assertEqual(raised.exception.code, 'turn-timeout')
        self.assertNotIn('/private/path', str(raised.exception))

    def test_pinned_embedded_empty_reply_is_wrong_answer_not_infrastructure_failure(self):
        decision = (b'[model-fallback/decision] model fallback decision: decision=candidate_failed '
                    b'requested=ollama/qwen3.8:27b candidate=ollama/qwen3.8:27b reason=format '
                    b'next=none detail=ollama/qwen3.8:27b ended without a visible assistant reply\n')
        with patch.object(at.subprocess, 'Popen') as spawn:
            process = spawn.return_value.__enter__.return_value
            process.returncode = 1
            process.communicate.return_value = (b'', decision + b'[openclaw] The CLI command failed.\n')
            with self.assertRaises(at.TrialTurnError) as raised:
                at.OpenClawRunner(self.home, executable='openclaw').turn('A task')
            self.assertEqual(raised.exception.code, 'empty-reply')
        for unconfirmed in (b'ended without a visible assistant reply',
                            decision.replace(b'next=none', b'next=another'),
                            decision.replace(b'candidate=ollama/qwen3.8:27b', b'candidate=ollama/other'),
                            decision + b'[model-fallback/decision] decision=candidate_failed reason=timeout\n'):
            self.assertFalse(at.model_gave_no_answer(b'', unconfirmed))

    def test_runner_reports_a_turn_with_no_answer_as_empty_reply(self):
        with patch.object(at.subprocess, 'Popen') as spawn, patch(
                'argoslive.owned_gateway.private_log', side_effect=lambda path: path.open('wb')):
            process = spawn.return_value.__enter__.return_value
            process.returncode = 1
            process.communicate.return_value = (json.dumps({'status': 'error', 'result': {'payloads': [], 'meta': {
                'error': {'kind': 'incomplete_turn', 'message': "Agent couldn't generate a response."}}}}).encode(),
                b'The CLI command failed.')
            with self.assertRaises(at.TrialTurnError) as raised:
                at.OpenClawRunner(self.home, executable='openclaw').turn('A task')
        self.assertEqual(raised.exception.code, 'empty-reply')

    def test_failed_cli_evidence_is_retained_only_in_private_log(self):
        with patch.object(at.subprocess, 'Popen') as spawn, patch(
                'argoslive.owned_gateway.private_log', side_effect=lambda path: path.open('wb')):
            process = spawn.return_value.__enter__.return_value
            process.returncode = 7
            process.communicate.return_value = (b'', b'Private failure details')
            with self.assertRaises(at.TrialTurnError) as raised:
                at.OpenClawRunner(self.home, executable='openclaw').turn('A task')
        self.assertEqual(raised.exception.code, 'assistant-error')
        self.assertNotIn('Private failure details', str(raised.exception))
        log = self.home / '.local/state/argos-live/trial-turn-failure.log'
        self.assertIn(b'CLI exit: 7', log.read_bytes())
        self.assertIn(b'Private failure details', log.read_bytes())

    def test_reviewed_profile_refuses_agent_behavior_overrides(self):
        config = self.home / '.openclaw/openclaw.json'
        value = json.loads(config.read_text())
        value['agents']['list'] = [{'id': 'main', 'tools': {'profile': 'full'}}]
        config.write_text(json.dumps(value))
        with patch('argoslive.startup.source', return_value=(self.home, 'fixture')):
            with self.assertRaises(ValueError):
                at.reviewed_profile(self.home)

    def test_before_turn_failure_releases_gateway_without_applying_change(self):
        trial = self.trial()
        with patch.object(trial.runner, 'turn', side_effect=ValueError('lost CLI reply')):
            trial.start(); self.wait(trial)
        self.assertEqual(trial.phase, 'failed')
        self.assertEqual(trial.snapshot()['failure_code'], 'assistant-error')
        self.assertIn('could not finish its first test answer', trial.message)
        self.assertNotIn('lost CLI reply', trial.message)
        private_error = json.loads((self.home / '.config/argos-live/assistant-trial-error.json').read_text())
        self.assertEqual(private_error['failure_code'], 'assistant-error')
        self.assertIn('lost CLI reply', private_error['traceback'])
        self.assertTrue(self.startup.active)
        self.assertEqual(self.startup.calls, ['stop', 'start'])
        self.assertEqual(self.agents.read_bytes(), self.original.encode())
        self.assertEqual(trial.snapshot()['status'], 'none')
        trial.start(); self.wait(trial)
        self.assertIsNone(trial.snapshot()['failure_code'], 'A retry clears the previous run reason')
        self.assertIn(trial.phase, ('awaiting-decision', 'no-improvement'))


class RouteTests(unittest.TestCase):
    setUp, trial = TrialTests.setUp, TrialTests.trial
    fixture_opinion = staticmethod(lambda model, prompt, cancel: {'text': 'A fixture opinion.'})

    def test_routes_bind_go_to_the_reviewed_plan_and_other_actions_stay_empty_bodied(self):
        import http.client
        from contextlib import closing
        from argoslive.web.server import DashboardServer
        trial = self.trial()
        with DashboardServer(port=0, assistant_trial=trial) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            def request(path, method='GET', headers=None, body=None):
                with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                    connection.request(method, path, body=body, headers=headers or {})
                    reply = connection.getresponse()
                    return reply.status, reply.read()
            auth = {'X-Argos-Token': server.token}
            try:
                self.assertEqual(request('/api/assistant-trial')[0], 403)
                code, body = request('/api/assistant-trial', headers=auth)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)['change']['file'], 'AGENTS.md')
                self.assertEqual(request('/api/assistant-trial/start', 'POST')[0], 403)
                code, _ = request('/api/assistant-trial/start', 'POST', {**auth, 'Content-Type': 'application/json'}, b'{"x":1}')
                self.assertEqual(code, 400)
                code, body = request('/api/assistant-trial/start', 'POST', {**auth, 'Content-Type': 'application/json'},
                                     b'{"changes":["answer-first"]}')
                self.assertEqual(code, 409, 'A stale or substituted plan needs review before any test begins')
                self.assertIn(b'Review the updated ideas', body)
                self.assertFalse(trial.snapshot()['active'])
                self.assertEqual(self.agents.read_bytes(), self.original.encode())
                code, body = request('/api/assistant-trial/keep', 'POST', auth)
                self.assertEqual(code, 409)
                self.assertNotIn(str(self.home).encode(), body)
                self.assertIn(b'Nothing on trial to keep', body)
                self.assertEqual(self.agents.read_bytes(), self.original.encode())
            finally:
                server.shutdown(); worker.join(timeout=5)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.data = at.load_tasks()
        self.tasks = {t['id']: t for t in self.data['tasks']}

    def check(self, task_id, reply):
        return at.score(self.tasks[task_id], self.data['passages'], reply)

    def test_answer_checks_are_separate(self):
        quote = '"Each plot rents for $40 per season."'
        self.assertEqual(self.check('garden-answer', f'$40 per season. {quote}')['checks'],
                         {'answer_present': True, 'answer_first': True, 'exact_quote': True})
        late = self.check('garden-answer', ' '.join(['word'] * 30) + ' it is $40.')
        self.assertEqual(late['checks'], {'answer_present': True, 'answer_first': False, 'exact_quote': False})
        invented = self.check('garden-answer', '$40. "Plots cost $40 for each season."')
        self.assertFalse(invented['checks']['exact_quote'])
        unrelated = self.check('garden-answer', '$40. "The waiting list opens on 1 February."')
        self.assertFalse(unrelated['checks']['exact_quote'])
        wrong_answer_right_quote = self.check('garden-answer', f'$50. {quote}')
        self.assertEqual(wrong_answer_right_quote['checks'],
                         {'answer_present': False, 'answer_first': False, 'exact_quote': True})

    def test_not_stated_and_controls(self):
        self.assertTrue(self.check('garden-missing', "The notice doesn't say who founded it.")['passed'])
        self.assertFalse(self.check('garden-missing', 'It was founded by Maria Lopez.')['passed'])
        self.assertTrue(self.check('control-plant', 'Call it Fernsworth.')['passed'])
        self.assertFalse(self.check('control-plant', 'Here is a quote from the passage: Fernsworth.')['passed'])

    def test_one_task_gain_is_not_enough_to_suggest_keep(self):
        before = [{'id': 'one', 'kind': 'answer', 'passed': False, 'checks': {'answer_first': False}}]
        after = [{'id': 'one', 'kind': 'answer', 'passed': True, 'checks': {'answer_first': True}}]
        self.assertEqual(at.compare(before, after)['suggestion'], 'restore')

    def test_tasks_are_independent_of_the_document_suite(self):
        from argoslive import doc_trial
        suite = doc_trial.load()
        suite_text = ' '.join(i['prompt'] for i in suite['items']).lower()
        for passage in self.data['passages'].values():
            self.assertNotIn(passage.lower()[:40], suite_text)
        for task in self.data['tasks']:
            for answer in task.get('accepted', []):
                self.assertNotIn(answer.lower(), at.INSTRUCTION.lower())


if __name__ == '__main__':
    unittest.main()
