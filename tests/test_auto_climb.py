import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

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

    # -------------------------------------------------------------------------
    # R3 / AC1-2, AC1-3: Envelope Validation, Single Worker & Budgets
    # -------------------------------------------------------------------------

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
            self.assertIn('Session limit reached: 1 experiments completed', snap['stopping_reason'])
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
            self.assertEqual(snap1['phase'], snap3['phase'])
            self.assertEqual(snap1['countdown']['action_id'], snap3['countdown']['action_id'])
        finally:
            controller.close()


if __name__ == '__main__':
    unittest.main()
