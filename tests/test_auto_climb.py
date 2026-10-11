import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from argoslive import auto_climb
from argoslive.assistant_trial import (
    agents_path,
    read_text,
    write_text,
)


class FakeStartup:
    def __init__(self, home):
        self.home = home
        self.lock = threading.RLock()
        self.lab_active = False
        self.active = True
        self.stopped = False

    def snapshot(self):
        return {'active': self.active, 'phase': 'ready' if self.active else 'stopped', 'model': 'test-model'}

    def stop(self):
        self.active = False
        self.stopped = True

    def start(self, *, _reserved=False):
        self.active = True
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
        is_winning_practice = is_winning or (self.mode == 'practice_only' and self.home and ('quote-evidence' in (read_text(agents_path(self.home)) or '') or 'Show the source' in (read_text(agents_path(self.home)) or '')))

        # Default responses
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
        # Validation questions
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

            # Verify persisted file
            session_file = self.home / '.local/share/argos-live/auto-climb/session.json'
            self.assertTrue(session_file.exists())
            persisted = json.loads(session_file.read_text())
            self.assertEqual(persisted['schema'], auto_climb.SCHEMA)
            self.assertEqual(persisted['approved_envelope']['max_experiments'], 3)
        finally:
            controller.close()

    def test_duplicate_start_refused(self):
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            with self.assertRaises(auto_climb.Refused):
                controller.start()
        finally:
            controller.close()

    def test_countdown_and_try_now_override(self):
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            controller.start()
            # Wait for baseline assessment to finish and enter countdown
            worker = controller.worker
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'countdown')
            self.assertIsNotNone(snap['countdown'])
            action_id = snap['countdown']['action_id']

            # Test invalid action_id rejected
            with self.assertRaises(auto_climb.Refused):
                controller.try_now('wrong-id')

            # Test Try now proceeds
            override_snap = controller.try_now(action_id)
            self.assertTrue(controller.try_now_event.is_set())
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

    def test_pause_and_resume(self):
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

            pause_snap = controller.pause()
            self.assertEqual(pause_snap['phase'], 'paused')
            self.assertTrue(pause_snap['can_resume'])

            # Resume
            resume_snap = controller.resume()
            self.assertEqual(resume_snap['phase'], 'assess')
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

    def test_restart_recovery_rolls_back_interrupted_mutation(self):
        # Prepare session file as if interrupted during staging
        session_file = self.home / '.local/share/argos-live/auto-climb/session.json'
        session_file.parent.mkdir(parents=True, exist_ok=True)
        interrupted_state = {
            'schema': auto_climb.SCHEMA,
            'session_id': 'interrupted-uuid',
            'phase': 'staging',
            'raw_before': self.original_agents_content,
            'approved_envelope': auto_climb.DEFAULT_ENVELOPE,
            'budgets_used': {'duration_seconds': 10, 'completed_experiments': 0},
        }
        session_file.write_text(json.dumps(interrupted_state))

        # Corrupt AGENTS.md with partial edit
        self.agents_file.write_text('# Corrupted edit\n')

        # Creating controller must recover and restore original
        controller = auto_climb.Controller(
            self.startup, home=self.home, runner=self.runner,
            clock=self.clock.monotonic, sleep_fn=lambda s: None,
        )
        try:
            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'paused')
            self.assertIn('Pending mutation restored', snap['message'])
            # Verify AGENTS.md was restored byte-for-byte!
            self.assertEqual(self.agents_file.read_text(), self.original_agents_content)
        finally:
            controller.close()

    def test_automatic_restore_on_failed_practice(self):
        # Runner remains baseline -> no practice gain -> restore!
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
            # Fast-forward countdown
            deadline = time.time() + 5.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] == 'countdown':
                    controller.try_now(snap['countdown']['action_id'])
                    break
                time.sleep(0.05)

            # Wait for experiment completion
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(len(snap['history']), 1)
            self.assertEqual(snap['history'][0]['verdict'], 'restored')
            # AGENTS.md must be byte-for-byte the original!
            self.assertEqual(self.agents_file.read_text(), self.original_agents_content)
            self.assertEqual(snap['phase'], 'plateau')
            self.assertIn('Plateau within this session’s tested options', snap['stopping_reason'])
        finally:
            controller.close()

    def test_automatic_keep_when_practice_and_validation_both_improve(self):
        # Winning runner improves both practice and validation when candidate is staged!
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
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(len(snap['history']), 1)
            self.assertEqual(snap['history'][0]['verdict'], 'kept')
            # AGENTS.md must contain the kept change!
            self.assertIn('Show the source', self.agents_file.read_text())
        finally:
            controller.close()

    def test_budget_exhaustion_stopping(self):
        # Set max_experiments = 1
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
                if snap['phase'] in ('budget-exhausted', 'plateau', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(snap['phase'], 'budget-exhausted')
            self.assertIn('Session limit reached: 1 experiments completed', snap['stopping_reason'])
        finally:
            controller.close()

    def test_held_out_validation_failure_restores_original(self):
        # Candidate succeeds on practice, but fails held-out validation -> must restore!
        runner = FakeRunner(home=self.home, mode='practice_only')
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
            self.startup, home=self.home, runner=runner,
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
                if snap['phase'] in ('plateau', 'budget-exhausted', 'stopped'):
                    break
                time.sleep(0.05)

            snap = controller.snapshot()
            self.assertEqual(len(snap['history']), 1)
            # Must be RESTORED because validation did not confirm generalization!
            self.assertEqual(snap['history'][0]['verdict'], 'restored')
            self.assertIn('held-out validation did not confirm generalization', snap['history'][0]['reason'])
            self.assertEqual(self.agents_file.read_text(), self.original_agents_content)
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
            # Multiple snapshot calls simulate browser reconnect / polling
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

