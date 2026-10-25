import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from argoslive import assistant_trial, auto_climb
from argoslive.assistant_trial import (
    agents_path,
    read_text,
    write_text,
)


class FakeStartup:
    def __init__(self, home, active=True, phase='ready', fail=False):
        self.home = home
        self.lock = threading.RLock()
        self.lab_active = False
        self.active = active
        self.phase = phase
        self.fail = fail
        self.stopped = False

    def snapshot(self):
        if self.fail:
            return {
                'active': False,
                'phase': 'failed',
                'failure': 'Model startup crashed',
                'model': 'test-model',
                'model_reply_verified': False,
                'gateway_ready': False,
            }
        return {
            'active': self.active,
            'phase': self.phase if self.active else 'stopped',
            'model': 'test-model',
            'model_reply_verified': True,
            'gateway_ready': self.phase == 'ready' and self.active,
        }

    def stop(self):
        self.active = False
        self.stopped = True

    def start(self, *, _reserved=False):
        if not self.fail:
            self.active = True
            self.phase = 'ready'
            self.stopped = False


class FakeRunner:
    def __init__(self, home=None, mode='baseline'):
        self.home = home
        self.mode = mode
        self.turns = []

    def turn(self, prompt):
        self.turns.append(prompt)
        is_winning = self.mode == 'winning'
        if self.mode == 'dynamic' and self.home:
            text = read_text(agents_path(self.home)) or ''
            is_winning = 'quote-evidence' in text or 'Show the source' in text
        is_winning_practice = is_winning or (
            self.mode == 'practice_only' and self.home and (
                'quote-evidence' in (read_text(agents_path(self.home)) or '') or
                'Show the source' in (read_text(agents_path(self.home)) or '')
            )
        )

        # Default responses (practice tasks)
        if 'How much does a plot cost per season?' in prompt:
            if is_winning_practice:
                return '$40. "Each plot rents for $40 per season."'
            return 'It costs $40.'
        if 'How long can I book the laser cutter for?' in prompt:
            if is_winning_practice:
                return '90 minutes. "Members book the laser cutter in 90-minute blocks."'
            return 'You can book it for 90 minutes.'
        if 'Where do the buses stop during the detour?' in prompt:
            if is_winning_practice:
                return 'Cedar Street. "During the detour, buses stop on Cedar Street instead."'
            return 'They stop at Cedar Street.'
        if 'Who founded the garden?' in prompt:
            return 'The passage does not state who founded the garden.'
        if 'What brand are the 3D printers?' in prompt:
            return 'The text does not mention the brand of the 3D printers.'
        if 'How much does the bridge repair cost?' in prompt:
            return 'The provided text does not say how much the bridge repair costs.'
        if 'Suggest one name for a houseplant' in prompt:
            return 'Fern.'
        if 'Give me one tip for a short walk on a cold morning' in prompt:
            return 'Wear warm gloves.'

        # Partition 1 (val-p1)
        if 'How much is general admission for adults?' in prompt:
            if is_winning:
                return '$18. "General admission is $18 for adults and $10 for children under 12."'
            return 'General admission is $18.'
        if 'How much are monthly dues?' in prompt:
            if is_winning:
                return '$35. "Monthly dues are $35, payable on the first of each month."'
            return 'Monthly dues are $35.'
        if 'How often does the downtown connector shuttle depart?' in prompt:
            if is_winning:
                return 'Every 20 minutes. "The downtown connector shuttle departs every 20 minutes from Central Station."'
            return 'Every 20 minutes.'
        if 'Who is the director of the aquarium?' in prompt:
            return 'The text does not state who the director is.'
        if 'What brand of table saw does the studio use?' in prompt:
            return 'The text does not say what brand of table saw is used.'
        if 'What is the speed limit of the shuttle?' in prompt:
            return 'The text does not mention the speed limit.'
        if 'Suggest one ingredient for a winter vegetable soup' in prompt:
            return 'Carrots.'
        if 'Give one tip for identifying backyard birds' in prompt:
            return 'Note the shape of the beak.'

        # Partition 2 (val-p2)
        if 'How much does a sourdough loaf cost?' in prompt:
            if is_winning:
                return '$8. "Sourdough loaves cost $8 each, and croissants are $4."'
            return '$8.'
        if 'How much is the copay for insured patients?' in prompt:
            if is_winning:
                return '$15. "Copays for insured patients are $15, while self-pay visits are $25."'
            return '$15.'
        if 'How long can laptops be loaned for?' in prompt:
            if is_winning:
                return '3 hours. "The local branch library loans laptops for three hours per visit."'
            return '3 hours.'
        if 'Who is the head baker?' in prompt:
            return 'The text does not state who the head baker is.'
        if 'What brand of thermometer is used?' in prompt:
            return 'The text does not state what brand is used.'
        if 'What is the library wifi password?' in prompt:
            return 'The text does not state the password.'
        if 'Name one tool commonly used for weeding' in prompt:
            return 'Hoe.'
        if 'Mention one planet that has rings' in prompt:
            return 'Saturn.'

        # Partition 3 (val-p3)
        if 'How much does an adult ticket cost?' in prompt:
            if is_winning:
                return '$12. "The Heritage Museum charges $12 for adult tickets and $6 for seniors."'
            return '$12.'
        if 'How much does a guest pass cost per day?' in prompt:
            if is_winning:
                return '$10. "Guest passes cost $10 per day."'
            return '$10.'
        if 'How often does the harbor ferry run?' in prompt:
            if is_winning:
                return 'Every 30 minutes. "The harbor ferry runs every 30 minutes from Pier 7."'
            return 'Every 30 minutes.'
        if 'Who donated the diamond collection?' in prompt:
            return 'The text does not state who donated the collection.'
        if 'What brand of treadmill is in Studio B?' in prompt:
            return 'The text does not say.'
        if 'Who is the captain of the ferry?' in prompt:
            return 'The text does not mention the captain.'
        if 'Name one string instrument' in prompt:
            return 'Violin.'
        if 'Describe what a barometer measures' in prompt:
            return 'Atmospheric pressure.'

        return 'I do not have enough information.'


class ControllableClock:
    def __init__(self, start=1000.0):
        self.current = start

    def monotonic(self):
        return self.current

    def advance(self, seconds):
        self.current += seconds


class TestAutoClimbCoordinator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        # Create workspace and initial AGENTS.md
        ws = self.home / '.openclaw/workspace'
        ws.mkdir(parents=True)
        (self.home / '.openclaw/openclaw.json').write_text(
            json.dumps({'agents': {'defaults': {'workspace': str(ws)}}})
        )
        (self.home / '.config/argos-live').mkdir(parents=True)
        (self.home / '.config/argos-live/state.json').write_text('{"model": "test-model"}')

        self.agents_file = ws / 'AGENTS.md'
        self.original_agents_content = '# Operating notes\nBe concise and direct.\n'
        self.agents_file.write_text(self.original_agents_content)
        (ws / 'SOUL.md').write_text('Test soul\n')
        (ws / 'IDENTITY.md').write_text('Test identity\n')
        (ws / 'USER.md').write_text('Test user\n')

        self.startup = FakeStartup(self.home)
        self.clock = ControllableClock()
        self.runner = FakeRunner(mode='baseline')

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # R1 / AC1-1: Production Composition & Verified Warmup
    # -------------------------------------------------------------------------

    def test_production_composition_wires_openclaw_runner(self):
        """Production desktop initialization wires OpenClawRunner by default without injected runner."""
        controller = auto_climb.Controller(self.startup, home=self.home)
        try:
            self.assertIsNotNone(controller.runner)
            self.assertIsInstance(controller.runner, assistant_trial.OpenClawRunner)
            self.assertEqual(controller.runner.home, self.home)
        finally:
            controller.close()

    def test_missing_runner_or_empty_reply_fails_closed(self):
        """Execution fails closed when runner is missing or returns empty strings."""
        controller = auto_climb.Controller(self.startup, home=self.home, runner=None)
        controller.runner = None  # simulate missing runner
        try:
            with self.assertRaises(assistant_trial.TrialTurnError):
                controller._run_task_suite('practice', controller.practice_tasks, 'practice')

            class EmptyRunner:
                def turn(self, prompt):
                    return ''  # empty reply

            controller.runner = EmptyRunner()
            with self.assertRaises(assistant_trial.TrialTurnError):
                controller._run_task_suite('practice', controller.practice_tasks, 'practice')
        finally:
            controller.close()

    def test_task_suite_saves_a_traceable_run_id_and_checksum_checked_receipts(self):
        controller = auto_climb.Controller(self.startup, home=self.home, runner=self.runner)
        controller.session = {
            'session_id': 'suite-run-test',
            'active_model': {'model': 'test-model', 'digest': 'a' * 64},
            'suite_runs': {},
        }
        self.runner.expected_model = 'test-model'
        try:
            suite = copy.deepcopy(controller.practice_tasks)
            suite['tasks'] = suite['tasks'][:2]
            results = controller._run_task_suite('practice', suite, 'practice')
            run_id = controller.latest_suite_run_id
            persisted = json.loads(controller.session_path.read_text())
            record = persisted['suite_runs'][run_id]

            self.assertEqual(run_id, record['run_id'])
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(record['completed_task_count'], 2)
            self.assertEqual([item['task_id'] for item in record['items']], [task['id'] for task in suite['tasks']])
            self.assertTrue(all(len(item['answer_sha256']) == 64 for item in record['items']))
            self.assertTrue(auto_climb._suite_run_is_valid(record))
            self.assertEqual(record['integrity_scheme'], 'sha256-unkeyed')
            public_record = controller.snapshot()['suite_runs'][run_id]
            self.assertTrue(public_record['checksum_valid'])
            self.assertNotIn('integrity_valid', public_record)
            self.assertEqual(record['model_identity']['session_active_model']['digest'], 'a' * 64)
            self.assertEqual(record['model_identity']['runner_expected_model'], 'test-model')
            self.assertNotIn(results[0]['reply']['text'], json.dumps(record))

            structurally_incomplete = copy.deepcopy(record)
            structurally_incomplete['items'].pop()
            structurally_incomplete['record_sha256'] = auto_climb._suite_run_digest(structurally_incomplete)
            controller.session['suite_runs']['incomplete-but-checksummed'] = structurally_incomplete
            self.assertFalse(controller._suite_run_refs_valid(['incomplete-but-checksummed']))
        finally:
            controller.close()

    def test_restart_marks_running_suite_record_interrupted_without_scoring_it(self):
        run_id = 'suite-run-interrupted'
        record = {
            'schema': 'argos-auto-climb-suite-run/1',
            'integrity_scheme': 'sha256-unkeyed',
            'run_id': run_id,
            'status': 'running',
            'task_count': 2,
            'completed_task_count': 1,
            'task_ids': ['a', 'b'],
            'items': [{'task_id': 'a', 'passed': True, 'checks': {'ok': True},
                       'answer_sha256': 'b' * 64, 'elapsed_seconds': 1, 'assistant_session_id': 's1'}],
            'started_at': '2026-10-25T00:00:00+00:00',
            'finished_at': None,
        }
        record['record_sha256'] = auto_climb._suite_run_digest(record)
        state_path = self.home / '.local/share/argos-live/auto-climb/session.json'
        state_path.parent.mkdir(parents=True, exist_ok=True)
        auto_climb.write_json(state_path, {
            'schema': auto_climb.SCHEMA,
            'session_id': 'interrupted-campaign',
            'phase': 'retest',
            'raw_before': self.original_agents_content,
            'suite_runs': {run_id: record},
        })

        recovered = auto_climb.Controller(self.startup, home=self.home, runner=self.runner)
        try:
            saved = json.loads(state_path.read_text())
            self.assertEqual(recovered.session['phase'], 'paused')
            self.assertEqual(saved['suite_runs'][run_id]['status'], 'interrupted')
            self.assertEqual(saved['suite_runs'][run_id]['completed_task_count'], 1)
            self.assertTrue(auto_climb._suite_run_is_valid(saved['suite_runs'][run_id]))
            self.assertEqual(saved['suite_runs'][run_id]['interruption'],
                             'Controller restarted before the suite run completed.')
        finally:
            recovered.close()

    def test_restart_assistant_verified_ready_and_failure(self):
        """_restart_assistant requires verified readiness and raises on startup failure."""
        startup = FakeStartup(self.home, active=True, phase='ready')
        controller = auto_climb.Controller(startup, home=self.home, runner=self.runner)
        try:
            # Succeeded ready
            controller._restart_assistant(timeout=5)

            # Failure raises
            failing_startup = FakeStartup(self.home, active=False, fail=True)
            controller.startup = failing_startup
            with self.assertRaises(RuntimeError):
                controller._restart_assistant(timeout=2)
        finally:
            controller.close()

    def test_restart_waits_for_asynchronous_shutdown_before_start(self):
        class AsyncStartup(FakeStartup):
            polls = 0
            def stop(self):
                self.phase = 'stopping'
                self.polls = 3
            def snapshot(self):
                if self.polls:
                    self.polls -= 1
                    self.active = self.polls > 0
                return super().snapshot()
            def start(self, **kwargs):
                if self.active:
                    raise AssertionError('Start attempted before shutdown finished')
                return super().start(**kwargs)
        startup = AsyncStartup(self.home)
        controller = auto_climb.Controller(startup, home=self.home, runner=self.runner)
        try:
            controller._restart_assistant(timeout=5)
            self.assertEqual(startup.phase, 'ready')
            self.assertTrue(startup.active)
        finally:
            controller.close()

    # -------------------------------------------------------------------------
    # R3 / AC1-2, AC1-3: Envelope Validation, Single Worker & Budgets
    # -------------------------------------------------------------------------

    def test_answer_error_blocks_with_safe_explanation_and_specific_code(self):
        controller = auto_climb.Controller(self.startup, home=self.home, runner=self.runner,
                                            clock=self.clock.monotonic, sleep_fn=lambda s: None)
        try:
            with mock.patch.object(controller, '_run_task_suite',
                                   side_effect=assistant_trial.TrialTurnError('assistant-error')):
                controller.start()
                controller.worker.join(timeout=3)
            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'blocked')
            self.assertEqual(snap['failure_code'], 'assistant-error')
            self.assertIn('No gain was accepted', snap['message'])
            self.assertNotIn('TrialTurnError', snap['message'])
        finally:
            controller.close()

    def test_envelope_strict_validation(self):
        """Envelope validation strictly enforces limits and permissions."""
        with self.assertRaises(auto_climb.Refused):
            auto_climb.validate_envelope({'max_duration_seconds': 10})  # below 60s
        with self.assertRaises(auto_climb.Refused):
            auto_climb.validate_envelope({'max_experiments': 0})
        with self.assertRaises(auto_climb.Refused):
            auto_climb.validate_envelope({'permissions': 'root'})  # must be 'none'
        with self.assertRaises(auto_climb.Refused):
            auto_climb.validate_envelope({'unknown_param': 123})

        valid = auto_climb.validate_envelope({'max_experiments': 4, 'max_duration_seconds': 1800})
        self.assertEqual(valid['max_experiments'], 4)
        self.assertEqual(valid['max_duration_seconds'], 1800)

    def test_start_creates_durable_session_with_envelope(self):
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            snap = controller.start({'max_experiments': 3, 'max_duration_seconds': 1800})
            self.assertTrue(snap['available'])
            self.assertEqual(snap['approved_envelope']['max_experiments'], 3)
            self.assertEqual(snap['approved_envelope']['max_duration_seconds'], 1800)
            self.assertIsNotNone(snap['session_id'])

            session_file = self.home / '.local/share/argos-live/auto-climb/session.json'
            self.assertTrue(session_file.exists())
            persisted = json.loads(session_file.read_text())
            self.assertEqual(persisted['schema'], auto_climb.SCHEMA)
            self.assertEqual(persisted['approved_envelope']['max_experiments'], 3)
        finally:
            controller.close()

    def test_single_worker_and_cumulative_duration_across_resume(self):
        """Single worker ownership is maintained, and duration budget accumulates monotonically."""
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    break
                time.sleep(0.05)

            # Advance clock
            self.clock.advance(120)
            pause_snap = controller.pause()
            self.assertEqual(pause_snap['phase'], 'paused')

            # Advance clock while paused (paused time does not count toward active budget)
            self.clock.advance(600)

            resume_snap = controller.resume()
            self.assertEqual(resume_snap['phase'], 'assess')

            # Advance active time
            self.clock.advance(60)
            controller.pause()

            budgets = controller.session.get('budgets_used', {})
            # Cumulative active duration must be >= 120s and not reset to 0
            self.assertGreaterEqual(budgets.get('duration_seconds', 0), 120)
        finally:
            controller.close()

    # -------------------------------------------------------------------------
    # R2 / AC1-4: Guarded Mutation, Owner Edit Protection & Verified Undo
    # -------------------------------------------------------------------------

    def test_restart_recovery_preserves_owner_edit_without_overwriting(self):
        """Recovery detects an owner edit in AGENTS.md, preserves it without overwriting, and marks blocked."""
        session_file = self.home / '.local/share/argos-live/auto-climb/session.json'
        session_file.parent.mkdir(parents=True, exist_ok=True)
        interrupted_state = {
            'schema': auto_climb.SCHEMA,
            'session_id': 'interrupted-uuid',
            'phase': 'retest',
            'mutation': {
                'kind': 'instruction',
                'raw_before': self.original_agents_content,
                'expected_after': self.original_agents_content + '\n# Staged rule\n',
            },
            'raw_before': self.original_agents_content,
            'approved_envelope': auto_climb.DEFAULT_ENVELOPE,
            'budgets_used': {'duration_seconds': 10, 'completed_experiments': 1},
        }
        session_file.write_text(json.dumps(interrupted_state))

        # Owner edited AGENTS.md with their own custom text!
        custom_owner_content = '# Custom owner text\nDo not overwrite me!\n'
        self.agents_file.write_text(custom_owner_content)

        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'blocked')
            self.assertEqual(snap['failure_code'], 'owner-edit-conflict')
            self.assertIn('Owner edit detected', snap['message'])
            # Verify owner edit was preserved untouched!
            self.assertEqual(self.agents_file.read_text(), custom_owner_content)
        finally:
            controller.close()

    def test_restart_recovery_rolls_back_interrupted_mutation_matching_staged(self):
        """Recovery rolls back cleanly if AGENTS.md matches the staged expected_after."""
        session_file = self.home / '.local/share/argos-live/auto-climb/session.json'
        session_file.parent.mkdir(parents=True, exist_ok=True)
        staged_content = self.original_agents_content + '\n# Staged rule\n'
        interrupted_state = {
            'schema': auto_climb.SCHEMA,
            'session_id': 'interrupted-uuid',
            'phase': 'retest',
            'mutation': {
                'kind': 'instruction',
                'raw_before': self.original_agents_content,
                'expected_after': staged_content,
            },
            'raw_before': self.original_agents_content,
            'approved_envelope': auto_climb.DEFAULT_ENVELOPE,
            'budgets_used': {'duration_seconds': 10, 'completed_experiments': 1},
        }
        session_file.write_text(json.dumps(interrupted_state))
        self.agents_file.write_text(staged_content)

        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'paused')
            self.assertIn('Pending mutation restored', snap['message'])
            self.assertEqual(self.agents_file.read_text(), self.original_agents_content)
        finally:
            controller.close()

    def test_restart_recovery_blocks_when_interrupted_model_restore_fails(self):
        """A failed model rollback remains blocked and keeps the workload reserved."""
        from argoslive import model_selection
        session_file = self.home / '.local/share/argos-live/auto-climb/session.json'
        session_file.parent.mkdir(parents=True, exist_ok=True)
        config_file = self.home / '.openclaw/openclaw.json'
        config = json.loads(config_file.read_text())
        config['agents']['defaults'] = {'model': {'primary': 'ollama/qwen3:4b'}}
        config_file.write_text(json.dumps(config))
        session_file.write_text(json.dumps({
            'schema': auto_climb.SCHEMA,
            'session_id': 'interrupted-model-session',
            'phase': 'stage',
            'mutation': {'kind': 'model', 'candidate_id': 'model-qwen3-4b'},
            'active_model': {'model': 'test-model', 'digest': None},
            'approved_envelope': auto_climb.DEFAULT_ENVELOPE,
            'budgets_used': {'duration_seconds': 0, 'completed_experiments': 1},
        }))
        with mock.patch.object(model_selection, 'restore', side_effect=RuntimeError('restore failed')):
            controller = auto_climb.Controller(self.startup, home=self.home, runner=self.runner)
        try:
            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'blocked')
            self.assertEqual(snap['failure_code'], 'model-restore-failed')
            self.assertIn('mutation', controller.session)
            self.assertTrue(self.startup.lab_active)
        finally:
            controller.close()

    def test_verified_undo_reverts_kept_changes(self):
        """Verified Undo restores workspace to initial baseline if unedited, and refuses if owner edited."""
        winning_runner = FakeRunner(home=self.home, mode='dynamic')
        single_candidate = [{
            'id': 'quote-evidence',
            'kind': 'instruction',
            'title': 'Show the source',
            'change': 'Test change',
            'rationale': 'Test rationale',
            'cost': '0 MB',
            'verification': 'Practice checks',
            'change_id': 'quote-evidence',
        }]
        clock = ControllableClock()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=winning_runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            candidates=single_candidate,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('options-exhausted', 'plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['history'][0]['verdict'], 'kept')
            self.assertTrue(snap['can_undo'])

            # Undo reverts to baseline!
            undo_snap = controller.undo()
            self.assertEqual(undo_snap['phase'], 'stopped')
            self.assertEqual(self.agents_file.read_text(), self.original_agents_content)

            # Further undo refused
            with self.assertRaises(auto_climb.Refused):
                controller.undo()
        finally:
            controller.close()

    # -------------------------------------------------------------------------
    # R4 / AC2-1, AC2-2: Fresh Validation, Rebased Comparisons & Stopping
    # -------------------------------------------------------------------------

    def test_automatic_keep_when_practice_and_both_validation_partitions_improve(self):
        """Candidate is kept only when practice improves AND confirmed on two disjoint fresh partitions."""
        winning_runner = FakeRunner(home=self.home, mode='dynamic')
        single_candidate = [{
            'id': 'quote-evidence',
            'kind': 'instruction',
            'title': 'Show the source',
            'change': 'Test change',
            'rationale': 'Test rationale',
            'cost': '0 MB',
            'verification': 'Practice checks',
            'change_id': 'quote-evidence',
        }]
        clock = ControllableClock()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=winning_runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            candidates=single_candidate,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('options-exhausted', 'plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(len(snap['history']), 1)
            self.assertEqual(snap['history'][0]['verdict'], 'kept')
            self.assertIn('Show the source', self.agents_file.read_text())

            refs = snap['history'][0]['evidence_run_ids']
            required_run_ids = [
                refs['kept_practice_baseline'], refs['candidate_practice'],
                *refs['fresh_validation_baselines'].values(),
                *refs['candidate_validation'].values(),
            ]
            self.assertEqual(len(required_run_ids), 6)
            self.assertEqual(len(set(required_run_ids)), 6)
            self.assertTrue(all(run_id in controller.session['suite_runs'] for run_id in required_run_ids))
            self.assertTrue(all(auto_climb._suite_run_is_valid(controller.session['suite_runs'][run_id])
                                for run_id in required_run_ids))
            self.assertTrue(controller._suite_run_evidence_matches(refs, 'quote-evidence', ('val-p1', 'val-p2')))
            cross_wired = copy.deepcopy(refs)
            cross_wired['candidate_validation']['val-p1'], cross_wired['candidate_validation']['val-p2'] = (
                refs['candidate_validation']['val-p2'], refs['candidate_validation']['val-p1'])
            self.assertFalse(controller._suite_run_evidence_matches(
                cross_wired, 'quote-evidence', ('val-p1', 'val-p2')))
            self.assertEqual(controller.session['practice_baseline_run_id'], refs['candidate_practice'])

            # Exposure ledger consumed both val-p1 and val-p2
            consumed = controller.session.get('exposure_ledger', {}).get('consumed_partitions', [])
            self.assertIn('val-p1', consumed)
            self.assertIn('val-p2', consumed)
        finally:
            controller.close()

    def test_rebased_current_kept_comparisons_and_subsequent_regression(self):
        """Subsequent candidate compares against rebased kept build; regression is restored."""
        winning_runner = FakeRunner(home=self.home, mode='dynamic')
        candidates = [
            {
                'id': 'quote-evidence',
                'kind': 'instruction',
                'title': 'Show the source',
                'change': 'Test change 1',
                'rationale': 'Test rationale',
                'cost': '0 MB',
                'verification': 'Practice checks',
                'change_id': 'quote-evidence',
            },
            {
                'id': 'answer-first',
                'kind': 'instruction',
                'title': 'Answer first',
                'change': 'Test change 2',
                'rationale': 'Test rationale',
                'cost': '0 MB',
                'verification': 'Practice checks',
                'change_id': 'answer-first',
            },
        ]
        clock = ControllableClock()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=winning_runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            candidates=candidates,
        )
        try:
            controller.start()
            # 1st experiment: quote-evidence (kept)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Wait for 1st experiment to finish and record in history
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if len(snap['history']) >= 1:
                    break
                time.sleep(0.05)

            # Wait for 2nd experiment countdown
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Wait for finish
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('options-exhausted', 'plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(len(snap['history']), 2)
            self.assertEqual(snap['history'][0]['verdict'], 'kept')
            # 2nd candidate compared against 1st candidate's newly kept baseline -> not improved -> restored!
            self.assertEqual(snap['history'][1]['verdict'], 'restored')
        finally:
            controller.close()

    def test_plateau_vs_options_exhausted_stop_reasons(self):
        """Stops with options-exhausted when < 3 experiments tried, and plateau only after >= 3 non-improving experiments."""
        single_candidate = [{
            'id': 'answer-first',
            'kind': 'instruction',
            'title': 'Answer first',
            'change': 'Test change',
            'rationale': 'Test rationale',
            'cost': '0 MB',
            'verification': 'Practice checks',
            'change_id': 'answer-first',
        }]
        clock = ControllableClock()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            candidates=single_candidate,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('options-exhausted', 'plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            # Since only 1 candidate was tried, stop reason is options-exhausted, NOT plateau!
            self.assertEqual(snap['phase'], 'options-exhausted')
            self.assertIn('Options exhausted within approved session', snap['stopping_reason'])
        finally:
            controller.close()

    def test_countdown_skip_override(self):
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'countdown')
            action_id = snap['countdown']['action_id']

            controller.skip(action_id)
            self.assertTrue(controller.skip_event.is_set())
        finally:
            controller.close()

    def test_stop_action(self):
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            snap = controller.stop()
            self.assertEqual(snap['phase'], 'stopped')
            self.assertEqual(snap['stopping_reason'], 'Stopped by owner')
        finally:
            controller.close()

    def test_budget_exhaustion_stopping(self):
        clock = ControllableClock()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start({'max_experiments': 1})
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('budget-exhausted', 'plateau', 'options-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'budget-exhausted')
            self.assertIn('Session limit reached: 1 attempts used', snap['stopping_reason'])
            self.assertEqual(len(snap['history']), 1, 'The final reserved attempt must actually finish')
        finally:
            controller.close()

    def test_reconnect_does_not_mutate_state(self):
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    break
                time.sleep(0.05)

            snap1 = controller.snapshot()
            snap2 = controller.snapshot()
            snap3 = controller.snapshot()
            self.assertEqual(snap1['session_id'], snap2['session_id'])
            self.assertEqual(snap2['session_id'], snap3['session_id'])
            self.assertEqual(snap1['countdown']['action_id'], snap3['countdown']['action_id'])
        finally:
            controller.close()

    def test_swallowed_restoration_failure_propagates_and_blocks_session(self):
        """Restoration failures are never swallowed; session blocks with failure_code='restore-failed'."""
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    break
                time.sleep(0.05)

            # Stage a mutation in session
            controller.session['phase'] = 'stage'
            controller.session['mutation'] = {
                'kind': 'instruction',
                'raw_before': self.original_agents_content,
                'expected_after': self.original_agents_content + '\n# Some staged candidate\n',
            }
            # Set workspace file to staged text
            self.agents_file.write_text(self.original_agents_content + '\n# Some staged candidate\n')

            # Force restoration failure (mock write_text to raise error)
            import unittest.mock as mock
            with mock.patch('argoslive.auto_climb.write_text', side_effect=OSError('Simulated disk error')):
                snap = controller.stop()
                self.assertEqual(snap['phase'], 'blocked')
                self.assertEqual(snap['failure_code'], 'restore-failed')
                self.assertIn('restoration failed', snap['message'].lower())
        finally:
            controller.close()

    def test_validation_partitions_not_reused_across_sessions_or_after_interruption(self):
        """Partitions are consumed in global inventory before baseline; failed candidate, new session, or reboot never reuses them."""
        # FakeRunner in baseline mode fails practice (0 gains), so candidate 1 will be restored
        failing_runner = FakeRunner(home=self.home, mode='baseline')
        clock = ControllableClock()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=failing_runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Wait for candidate 1 experiment to finish
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if len(snap['history']) >= 1:
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['history'][0]['verdict'], 'restored')

            # Check that val-p1 and val-p2 are recorded as globally consumed in exposure-inventory.json
            inventory_file = self.home / '.local/share/argos-live/auto-climb/exposure-inventory.json'
            self.assertTrue(inventory_file.exists())
            inv_data = json.loads(inventory_file.read_text())
            self.assertIn('val-p1', inv_data['consumed_partitions'])
            self.assertIn('val-p2', inv_data['consumed_partitions'])

            # Candidate 2 will be proposed; verify it reserves fresh partitions (val-p3 and val-p4), NOT val-p1 or val-p2!
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Wait for candidate 2 experiment to finish
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if len(snap['history']) >= 2:
                    break
                time.sleep(0.05)

            inv_data2 = json.loads(inventory_file.read_text())
            self.assertIn('val-p3', inv_data2['consumed_partitions'])
            self.assertIn('val-p4', inv_data2['consumed_partitions'])
        finally:
            controller.close()

        # Now start a completely NEW session in a new Controller instance (simulating restart / reboot)
        new_controller = auto_climb.Controller(
            self.startup, home=self.home, runner=failing_runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
        )
        # Exercise exhaustion of an explicitly bounded four-pack fixture even
        # when production adds fresh, disjoint validation packs.
        new_controller.validation_partitions = new_controller.validation_partitions[:4]
        try:
            new_controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = new_controller.snapshot()
                if snap['phase'] == 'countdown':
                    new_controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Since all 4 partitions (val-p1..p4) were already consumed in exposure-inventory.json,
            # new session refuses to reuse them and halts honestly due to fresh inventory exhaustion!
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = new_controller.snapshot()
                if snap['phase'] in ('options-exhausted', 'blocked', 'stopped'):
                    break
                time.sleep(0.05)

            snap = new_controller.snapshot()
            self.assertIn('Fresh validation inventory exhausted', snap['stopping_reason'])
            new_controller.worker.join(timeout=1)
            self.assertFalse(new_controller.worker.is_alive())
            self.assertFalse(self.startup.lab_active)
            self.assertEqual(new_controller.snapshot()['budgets_used']['completed_experiments'], 1)
        finally:
            new_controller.close()

    def test_recommend_hardware_model_selects_curated_upgrade(self):
        (self.home / '.config/argos-live/state.json').write_text('{"model": "qwen3:0.6b"}')
        fake_hw = lambda: {'ram': {'available_bytes': 16 * 1024**3}, 'gpus': [{'vram_total_bytes': 8 * 1024**3, 'vram_used_bytes': 1024**3}]}
        rec = auto_climb.recommend_hardware_model(
            self.home,
            envelope={'max_model_downloads': 1, 'max_download_bytes': 8 * 1024**3},
            budgets={'model_downloads': 0, 'download_bytes': 0},
            hardware_fn=fake_hw,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec['kind'], 'model')
        self.assertEqual(rec['tag'], 'qwen3:4b-instruct-2507-q4_K_M')
        self.assertTrue(rec['needs_download'])
        self.assertIn('MB download', rec['cost'])
        self.assertEqual(rec['verification'], '8 practice challenges + 8 independent validation challenges')

    def test_recommend_hardware_model_advances_after_completed_model(self):
        (self.home / '.config/argos-live/state.json').write_text('{"model": "qwen3:0.6b"}')
        hardware = lambda: {'ram': {'available_bytes': 64 * 1024**3},
                             'gpus': [{'vram_total_bytes': 32 * 1024**3, 'vram_used_bytes': 0}]}
        first = auto_climb.recommend_hardware_model(self.home, hardware_fn=hardware)
        self.assertIsNotNone(first)
        second = auto_climb.recommend_hardware_model(
            self.home, hardware_fn=hardware, excluded_candidates={first['id']})
        self.assertIsNotNone(second)
        self.assertNotEqual(first['id'], second['id'])

    def test_recommend_hardware_model_respects_download_budget(self):
        (self.home / '.config/argos-live/state.json').write_text('{"model": "qwen3:0.6b"}')
        fake_hw = lambda: {'ram': {'available_bytes': 16 * 1024**3}, 'gpus': [{'vram_total_bytes': 8 * 1024**3, 'vram_used_bytes': 1024**3}]}
        # Exhausted download count
        rec1 = auto_climb.recommend_hardware_model(
            self.home,
            envelope={'max_model_downloads': 1, 'max_download_bytes': 8 * 1024**3},
            budgets={'model_downloads': 1, 'download_bytes': 0},
            hardware_fn=fake_hw,
        )
        self.assertIsNone(rec1)

        # Exhausted download bytes
        rec2 = auto_climb.recommend_hardware_model(
            self.home,
            envelope={'max_model_downloads': 1, 'max_download_bytes': 1024 * 1024},
            budgets={'model_downloads': 0, 'download_bytes': 0},
            hardware_fn=fake_hw,
        )
        self.assertIsNone(rec2)

    def test_recommend_hardware_model_flags_unconfirmed_storage(self):
        (self.home / '.config/argos-live/state.json').write_text('{"model": "qwen3:0.6b"}')
        fake_hw = lambda: {'ram': {'available_bytes': 16 * 1024**3}, 'gpus': [{'vram_total_bytes': 8 * 1024**3, 'vram_used_bytes': 1024**3}]}
        rec = auto_climb.recommend_hardware_model(
            self.home,
            envelope={'max_model_downloads': 1, 'max_download_bytes': 8 * 1024**3},
            budgets={'model_downloads': 0, 'download_bytes': 0},
            hardware_fn=fake_hw,
        )
        self.assertIsNotNone(rec)
        self.assertTrue(rec['storage_needed'])

    def test_model_upgrade_successful_keep(self):
        clock = ControllableClock()
        switched = []
        restored = []
        downloaded = []

        fake_model_cand = {
            'id': 'model-upgrade-test',
            'kind': 'model',
            'tag': 'qwen3:4b-instruct-2507-q4_K_M',
            'title': 'Upgrade model to qwen3:4b-instruct-2507-q4_K_M',
            'change': 'Switch assistant primary model',
            'rationale': 'Curated upgrade with confirmed memory headroom.',
            'cost': '2,492 MB download · ~5 min test',
            'verification': '8 practice challenges + 8 independent validation challenges',
            'needs_download': True,
            'download_bytes': 2492088096,
            'storage_needed': False,
        }

        # Dynamic runner: responds as winning when model is switched
        class ModelRunner:
            def turn(self, prompt):
                if switched:
                    if 'How much does a plot cost per season?' in prompt:
                        return '$40. "Each plot rents for $40 per season."'
                    if 'How long can I book the laser cutter for?' in prompt:
                        return '90 minutes. "Members book the laser cutter in 90-minute blocks."'
                    if 'How much is general admission for adults?' in prompt:
                        return '$18. "General admission is $18 for adults and $10 for children under 12."'
                    if 'How much does a sourdough loaf cost?' in prompt:
                        return '$8. "Sourdough loaves cost $8 each, and croissants are $4."'
                if 'How much does a plot cost per season?' in prompt:
                    return 'It costs $40.'
                if 'How long can I book the laser cutter for?' in prompt:
                    return '90 minutes.'
                if 'How much is general admission for adults?' in prompt:
                    return '$18.'
                if 'How much does a sourdough loaf cost?' in prompt:
                    return 'It costs $8.'
                return 'Answer.'

        runner = ModelRunner()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            model_recommender=lambda *a, **k: fake_model_cand if not switched else None,
            download_runner=lambda tag: downloaded.append(tag) or True,
            model_switcher=lambda tag: switched.append(tag) or True,
            model_restorer=lambda: restored.append(True),
        )
        try:
            controller.start()
            # Fast-forward past baseline to countdown
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Wait for experiment to finish
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped', 'paused', 'options-exhausted'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(downloaded, ['qwen3:4b-instruct-2507-q4_K_M'])
            self.assertEqual(switched, ['qwen3:4b-instruct-2507-q4_K_M'])
            self.assertEqual(restored, [])
            self.assertEqual(snap['active_model']['model'], 'qwen3:4b-instruct-2507-q4_K_M')
            self.assertEqual(snap['budgets_used']['model_downloads'], 1)
            self.assertEqual(snap['budgets_used']['download_bytes'], 2492088096)
            self.assertEqual(snap['history'][0]['verdict'], 'kept')
        finally:
            controller.close()

    def test_model_upgrade_validation_regression_restores_previous(self):
        clock = ControllableClock()
        switched = []
        restored = []

        fake_model_cand = {
            'id': 'model-upgrade-test',
            'kind': 'model',
            'tag': 'qwen3:4b-instruct-2507-q4_K_M',
            'title': 'Upgrade model to qwen3:4b-instruct-2507-q4_K_M',
            'change': 'Switch assistant primary model',
            'rationale': 'Curated upgrade with confirmed memory headroom.',
            'cost': '0 MB download · ~2 min test',
            'verification': '8 practice challenges + 8 independent validation challenges',
            'needs_download': False,
            'download_bytes': 0,
            'storage_needed': False,
        }

        # Runner improves on practice, but fails on validation!
        class RegressingModelRunner:
            def turn(self, prompt):
                if switched:
                    # Practice gains
                    if 'How much does a plot cost per season?' in prompt:
                        return '$40. "Each plot rents for $40 per season."'
                    if 'How long can I book the laser cutter for?' in prompt:
                        return '90 minutes. "Members book the laser cutter in 90-minute blocks."'
                    # Validation regression!
                    if 'How much is general admission for adults?' in prompt:
                        return 'I think it might be free.'
                # Baseline
                if 'How much does a plot cost per season?' in prompt:
                    return 'It costs $40.'
                if 'How long can I book the laser cutter for?' in prompt:
                    return '90 minutes.'
                if 'How much is general admission for adults?' in prompt:
                    return '$18.'
                return 'Answer.'

        runner = RegressingModelRunner()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            model_recommender=lambda *a, **k: fake_model_cand if not restored else None,
            model_switcher=lambda tag: switched.append(tag) or True,
            model_restorer=lambda: restored.append(True),
        )
        try:
            controller.start({'max_experiments': 1})
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped', 'paused', 'options-exhausted'):
                    break
                time.sleep(0.05)

            worker = controller.worker
            self.assertIsNotNone(worker)
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive(), 'Auto Climb worker did not reach a terminal state')
            snap = controller.snapshot()
            self.assertTrue(len(restored) > 0)
            self.assertEqual(snap['history'][0]['verdict'], 'restored')
            self.assertNotIn('mutation', controller.session)
            recovered = controller._load_or_recover_session()
            self.assertEqual(recovered['phase'], snap['phase'])
        finally:
            controller.close()

    def test_model_upgrade_failed_download_counts_toward_budget_and_falls_back(self):
        clock = ControllableClock()
        switched = []

        fake_model_cand = {
            'id': 'model-upgrade-test',
            'kind': 'model',
            'tag': 'qwen3:4b-instruct-2507-q4_K_M',
            'title': 'Upgrade model to qwen3:4b-instruct-2507-q4_K_M',
            'change': 'Switch assistant primary model',
            'rationale': 'Curated upgrade with confirmed memory headroom.',
            'cost': '2,492 MB download · ~5 min test',
            'verification': '8 practice challenges + 8 independent validation challenges',
            'needs_download': True,
            'download_bytes': 2492088096,
            'storage_needed': False,
        }

        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner, candidates=[],
            clock=clock.monotonic, sleep_fn=lambda s: None,
            model_recommender=lambda *a, **k: fake_model_cand if not switched else None,
            download_runner=lambda tag: False,  # Download fails!
            model_switcher=lambda tag: switched.append(tag) or True,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped', 'paused', 'options-exhausted'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            # No model switch was attempted because download failed
            self.assertEqual(switched, [])
            # Failed download counted toward download attempts budget and bytes
            self.assertEqual(snap['budgets_used']['model_downloads'], 1)
            self.assertEqual(snap['budgets_used']['download_bytes'], 2492088096)
            self.assertEqual(snap['history'][0]['verdict'], 'failed')
            self.assertIn('Download failed', snap['history'][0]['reason'])
        finally:
            controller.close()

    def test_model_restoration_failure_propagates_and_blocks_session(self):
        """Model restoration failure is never swallowed; propagates and marks phase='blocked', failure_code='restore-failed'."""
        clock = ControllableClock()
        fake_model_cand = {
            'id': 'model-upgrade-test',
            'kind': 'model',
            'tag': 'qwen3:4b-instruct-2507-q4_K_M',
            'title': 'Upgrade model to qwen3:4b-instruct-2507-q4_K_M',
            'change': 'Switch assistant primary model',
            'rationale': 'Curated upgrade with confirmed memory headroom.',
            'cost': '0 MB download · ~2 min test',
            'verification': '8 practice challenges + 8 independent validation challenges',
            'needs_download': False,
            'download_bytes': 0,
            'storage_needed': False,
        }

        def failing_restorer():
            raise RuntimeError('Simulated hardware model restoration failure')

        # Baseline runner: fails practice retest, prompting restoration
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner, candidates=[],
            clock=clock.monotonic, sleep_fn=lambda s: None,
            model_recommender=lambda *a, **k: fake_model_cand,
            model_switcher=lambda tag: True,
            model_restorer=failing_restorer,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('blocked', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'blocked')
            self.assertEqual(snap['failure_code'], 'restore-failed')
            self.assertIn('restoration failed', snap['message'].lower())
        finally:
            controller.close()

    def test_model_upgrade_undo_restores_initial_model(self):
        """Model Undo restores the initial model and updates active_model."""
        clock = ControllableClock()
        switched = []
        restored = []

        fake_model_cand = {
            'id': 'model-upgrade-test',
            'kind': 'model',
            'tag': 'qwen3:4b-instruct-2507-q4_K_M',
            'title': 'Upgrade model to qwen3:4b-instruct-2507-q4_K_M',
            'change': 'Switch assistant primary model',
            'rationale': 'Curated upgrade with confirmed memory headroom.',
            'cost': '0 MB download · ~2 min test',
            'verification': '8 practice challenges + 8 independent validation challenges',
            'needs_download': False,
            'download_bytes': 0,
            'storage_needed': False,
        }

        class WinningModelRunner:
            def turn(self, prompt):
                if switched:
                    if 'How much does a plot cost per season?' in prompt:
                        return '$40. "Each plot rents for $40 per season."'
                    if 'How long can I book the laser cutter for?' in prompt:
                        return '90 minutes. "Members book the laser cutter in 90-minute blocks."'
                    if 'How much is general admission for adults?' in prompt:
                        return '$18. "General admission is $18 for adults and $10 for children under 12."'
                    if 'How much does a sourdough loaf cost?' in prompt:
                        return '$8. "Sourdough loaves cost $8 each, and croissants are $4."'
                if 'How much does a plot cost per season?' in prompt:
                    return 'It costs $40.'
                if 'How long can I book the laser cutter for?' in prompt:
                    return '90 minutes.'
                if 'How much is general admission for adults?' in prompt:
                    return '$18.'
                if 'How much does a sourdough loaf cost?' in prompt:
                    return 'It costs $8.'
                return 'Answer.'

        runner = WinningModelRunner()
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=runner,
            clock=clock.monotonic, sleep_fn=lambda s: None,
            candidates=[],
            model_recommender=lambda *a, **k: fake_model_cand if not switched else None,
            model_switcher=lambda tag: switched.append(tag) or True,
            model_restorer=lambda: restored.append(True),
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped', 'options-exhausted'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['active_model']['model'], 'qwen3:4b-instruct-2507-q4_K_M')
            self.assertTrue(snap['can_undo'])

            undo_snap = controller.undo()
            self.assertEqual(undo_snap['phase'], 'stopped')
            self.assertEqual(undo_snap['active_model']['model'], 'test-model')
            self.assertTrue(len(restored) > 0)
        finally:
            controller.close()

    def test_model_undo_releases_startup_lock_for_transaction_worker(self):
        """Production-style Undo lets the journaled model selector acquire startup's workload lock."""
        current_tag = 'qwen3:4b'
        initial_tag = 'test-model'
        state_path = self.home / '.config/argos-live/state.json'
        config_path = self.home / '.openclaw/openclaw.json'
        state_path.write_text(json.dumps({'model': current_tag}))
        config = json.loads(config_path.read_text())
        config.setdefault('agents', {}).setdefault('defaults', {}).setdefault('model', {})[
            'primary'] = f'ollama/{current_tag}'
        config_path.write_text(json.dumps(config))

        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner, candidates=[],
        )

        class LockSensitiveSelection:
            def __init__(self):
                self.worker = None
                self.phase = 'idle'

            def start(self, *, tag, _delegated=False):
                if not _delegated:
                    raise AssertionError('Auto Climb must delegate its owned model transaction')
                self.phase = 'switching'

                def switch():
                    with controller.startup.lock:
                        state_path.write_text(json.dumps({'model': tag}))
                        current = json.loads(config_path.read_text())
                        current['agents']['defaults']['model']['primary'] = f'ollama/{tag}'
                        config_path.write_text(json.dumps(current))
                        self.phase = 'completed'

                self.worker = threading.Thread(target=switch, daemon=True)
                self.worker.start()

            def snapshot(self):
                return {'phase': self.phase}

            def keep_current(self):
                return True

        selection = LockSensitiveSelection()
        controller.selection = selection
        controller.session = {
            'schema': auto_climb.SCHEMA,
            'session_id': 'undo-lock-test',
            'phase': 'plateau',
            'initial_raw_before': self.original_agents_content,
            'current_kept_raw': self.original_agents_content,
            'initial_model': {'model': initial_tag, 'digest': None},
            'active_model': {'model': current_tag, 'digest': None},
            'history': [],
            'budgets_used': {},
            'approved_envelope': auto_climb.DEFAULT_ENVELOPE,
        }
        try:
            result = controller.undo()
            self.assertEqual(result['phase'], 'stopped')
            self.assertEqual(result['active_model']['model'], initial_tag)
            self.assertEqual(json.loads(state_path.read_text())['model'], initial_tag)
            self.assertEqual(json.loads(config_path.read_text())['agents']['defaults']['model']['primary'],
                             f'ollama/{initial_tag}')
            self.assertFalse(controller.startup.lab_active)
        finally:
            if selection.worker is not None:
                selection.worker.join(timeout=1)
            controller.close()

    def test_corrupt_exposure_inventory_blocks_validation_rather_than_resetting(self):
        """Corrupt exposure inventory blocks validation rather than resetting it and allowing reuse."""
        inv_path = self.home / '.local/share/argos-live/auto-climb/exposure-inventory.json'
        inv_path.parent.mkdir(parents=True, exist_ok=True)
        inv_path.write_text('{"schema": "invalid-or-corrupt-data", "broken": true}')

        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('blocked', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'blocked')
            self.assertEqual(snap['failure_code'], 'corrupt-inventory')
            self.assertIn('corrupt exposure inventory', snap['message'].lower())
        finally:
            controller.close()

    def test_child_worker_timeout_triggers_cancellation_and_raises(self):
        """Child worker timeout triggers cancellation function and raises RuntimeError."""
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            stop_evt = threading.Event()
            cancelled = []

            def worker_loop():
                stop_evt.wait(5.0)

            th = threading.Thread(target=worker_loop)
            th.daemon = True
            th.start()

            def cancel_fn():
                cancelled.append(True)
                stop_evt.set()

            with self.assertRaises(RuntimeError) as ctx:
                controller._settle_child(th, cancel_fn=cancel_fn, timeout=0.02)
            self.assertIn('cancelled', str(ctx.exception))
            self.assertEqual(cancelled, [True])
            self.assertFalse(th.is_alive())
        finally:
            controller.close()

    def test_openclaw_runner_child_process_termination_on_cancellation(self):
        """Cancellation invokes the platform cleanup boundary, without real OS signals."""
        import subprocess
        from unittest.mock import patch, MagicMock
        cancel_evt = threading.Event()
        config_path = self.home / '.openclaw/openclaw.json'
        config = json.loads(config_path.read_text())
        config['agents']['defaults']['model'] = {'primary': 'ollama/test-model'}
        config['models'] = {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434',
            'models': [{'id': 'test-model', 'name': 'test-model'}]}}}
        config_path.write_text(json.dumps(config))
        runner = assistant_trial.OpenClawRunner(self.home, executable='openclaw')
        runner.cancel_event = cancel_evt
        cancel_evt.set()
        with patch('subprocess.Popen') as popen_mock, \
                patch.object(assistant_trial, 'drain_embedded_group') as drain:
            proc = MagicMock()
            popen_mock.return_value.__enter__.return_value = proc
            # Cancellation is already set before launch; after the mocked
            # drain, collecting its pipes must finish without a new timeout.
            proc.communicate.return_value = (b'', b'')
            with self.assertRaises(assistant_trial.TrialTurnError) as raised:
                runner.turn('A test task')
            self.assertEqual(raised.exception.code, 'cancelled')
            if assistant_trial.sys.platform == 'linux':
                drain.assert_called_once_with(proc)
                proc.terminate.assert_not_called()
            else:
                proc.terminate.assert_called_once()

    def test_workload_ownership_delegation_retains_lab_active(self):
        """Delegated execution retains startup.lab_active and refuses competing non-delegated workloads."""
        from argoslive import lab, model_selection, catalog
        self.startup.lab_active = True

        # Competing non-delegated workloads are refused while lab_active is True
        lab_ctrl = lab.Controller(self.startup)
        with self.assertRaises(ValueError):
            lab_ctrl.start('baseline')

        sel_ctrl = model_selection.Controller(self.startup)
        first_tag = catalog.load()['models'][0]['tag']
        with self.assertRaises(ValueError):
            sel_ctrl.start(tag=first_tag, _delegated=False)

        # Delegated start accepts _delegated=True without raising workload contention error
        from unittest.mock import patch
        with patch.object(lab.Controller, 'start', return_value={'phase': 'running'}) as mock_start:
            sel_ctrl.start(tag=first_tag, _delegated=True)
            mock_start.assert_called_once_with(_delegated=True)

        # Delegation retains lab_active=True when child finishes
        lab_child = lab.Controller(self.startup)
        lab_child._delegated = True
        with lab_child._order_locks():
            if not getattr(lab_child, '_delegated', False):
                self.startup.lab_active = False
        self.assertTrue(self.startup.lab_active)

    def test_recommend_hardware_model_enforces_curated_and_context_window(self):
        """Model recommendations exclude curated candidates below the actual 32k execution context."""
        (self.home / '.config/argos-live/state.json').write_text('{"model": "qwen3:0.6b"}')
        fake_hw = lambda: {'ram': {'available_bytes': 32 * 1024**3}, 'gpus': [{'vram_total_bytes': 16 * 1024**3, 'vram_used_bytes': 1024**3}]}
        custom_catalog = auto_climb.catalog.load()
        too_small = next(entry for entry in custom_catalog['models'] if entry['tag'] == 'qwen3:1.7b')
        too_small['context_tokens'] = 4096
        rec = auto_climb.recommend_hardware_model(
            self.home,
            envelope={'max_model_downloads': 1, 'max_download_bytes': 8 * 1024**3},
            budgets={'model_downloads': 0, 'download_bytes': 0},
            hardware_fn=fake_hw,
            catalog_data=custom_catalog,
        )
        self.assertIsNotNone(rec)
        self.assertNotEqual(rec['tag'], 'qwen3:1.7b')
        self.assertGreaterEqual(rec['entry']['context_tokens'], 32768)


if __name__ == '__main__':
    unittest.main()


class EvidenceProposalTests(unittest.TestCase):
    def controller(self):
        c = auto_climb.Controller.__new__(auto_climb.Controller)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        c.home = Path(temp.name)
        (c.home / '.openclaw').mkdir()
        (c.home / '.openclaw/openclaw.json').write_text('{}')
        c.candidate_pool = copy.deepcopy(auto_climb.INSTRUCTION_CANDIDATES)
        c.model_recommender = mock.Mock(return_value={'id': 'bigger-model'})
        c.session = {'practice_baseline': [
            {'kind': 'answer', 'passed': False, 'checks': {
                'answer_present': True, 'answer_first': True, 'exact_quote': False}}
            for _ in range(3)]}
        return c

    def test_quote_only_misses_propose_instruction_before_download(self):
        c = self.controller()
        self.assertEqual(c._select_next_candidate()['id'], 'quote-evidence')
        c.model_recommender.assert_not_called()

    def test_mixed_misses_keep_normal_model_policy(self):
        c = self.controller()
        c.session['practice_baseline'][0]['checks']['answer_present'] = False
        self.assertEqual(c._select_next_candidate()['id'], 'bigger-model')

    def test_existing_instruction_is_not_proposed_again(self):
        c = self.controller()
        with mock.patch.object(auto_climb, 'read_text', return_value=assistant_trial.CHANGE_BY_ID['quote-evidence']['block']):
            self.assertEqual(c._select_next_candidate()['id'], 'bigger-model')

    def test_completed_quote_candidate_is_not_repeated(self):
        c = self.controller()
        c.session['completed_candidates'] = ['quote-evidence']
        self.assertEqual(c._select_next_candidate()['id'], 'bigger-model')


class FreshValidationPackTests(unittest.TestCase):
    def test_new_packs_are_disjoint_and_retain_scoring_contract(self):
        packs = auto_climb.load_validation_partitions(auto_climb.VALIDATION_TASKS_PATH)
        ids = [t['id'] for p in packs for t in p['tasks']]
        self.assertEqual(len(ids), len(set(ids)))
        passages = [v for p in packs for v in p['passages'].values()]
        self.assertEqual(len(passages), len(set(passages)))
        for pack in packs[4:]:
            self.assertEqual(len(pack['tasks']), 8)
            for task in pack['tasks']:
                if task['kind'] != 'answer': continue
                source = pack['passages'][task['passage']]
                answer = task['accepted'][0]
                # The unchanged scorer still requires both an answer and quote.
                reply = answer + '. "' + source + '"'
                self.assertTrue(assistant_trial.score(task, pack['passages'], reply)['passed'])
                self.assertFalse(assistant_trial.score(task, pack['passages'], answer)['passed'])
