"""Regression tests for J5 mission-first home corrections:
1. "Start: Read this brief" is the single primary action for ready first-time users.
2. Truthful assistant recovery status reporting (delayed recovering, failed, ready, not-running).
3. Qualification tri-state handling (qualified, criteria not met, not assessed).
4. Single documents workload execution and concurrent workload prevention.
5. Cancellation with retained partial answers and truthful recovery state.
"""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))

from argoslive import bench_speed, command_center, doc_trial, lab, mission_report
from argoslive.results import Store
from test_bench_speed import Backend
from test_doc_trial import DocBackend
from test_results import ability_result


class MockStartup:
    def __init__(self, home, active=True, phase='ready'):
        self.home = Path(home)
        self.active = active
        self.phase = phase
        self.lab_active = False
        self.chat_claimed = False
        self.lock = threading.RLock()
        self.start_called = 0
        self.stop_called = 0

    def snapshot(self):
        return {
            'managed': True,
            'phase': self.phase,
            'message': f'Mock startup {self.phase}',
            'active': self.active,
        }

    def stop(self):
        self.stop_called += 1
        self.active = False
        self.phase = 'stopped'

    def start(self):
        self.start_called += 1
        self.active = True
        self.phase = 'setup'

    def resolve_source(self, home):
        return home / 'models', 'fixture:latest'

    @contextlib.contextmanager
    def backend(self, target, **options):
        yield DocBackend()


class MissionFirstHomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config/argos-live').mkdir(parents=True)
        self.store = Store(self.home / 'results')
        self.startup = MockStartup(self.home, active=True)

    def test_ready_first_time_user_recommends_documents_as_primary_action(self):
        """First-time user with ready starter is guided directly to 'Read this brief'."""
        storage_view = {
            'state': 'available',
            'confirmed': True,
            'locations': [{'key': 'models', 'reboot': {'state': 'retained'}}],
        }
        snap = command_center.snapshot(
            self.home, self.store, view=storage_view,
            selected={'model': 'fixture:latest', 'digest': 'f' * 64},
        )
        action = snap['next_action']
        self.assertEqual(action['id'], 'documents')
        self.assertEqual(action['title'], 'Read this brief')
        self.assertEqual(action['action'], 'documents')
        self.assertIn('qualifies short-document reading', action['reason'])

        # Build path rung 1 is documents ("Read this brief")
        steps = snap['build_path']['steps']
        self.assertEqual(steps[0]['id'], 'documents')
        self.assertEqual(steps[0]['title'], 'Read this brief')
        self.assertEqual(steps[0]['state'], 'current')

        # Baseline is still on the ladder at rung 3
        self.assertEqual(steps[2]['id'], 'baseline')
        self.assertEqual(steps[2]['title'], 'Measure this build')
        self.assertEqual(steps[2]['state'], 'untested')

    def test_qualification_tri_state_in_mission_report(self):
        """Qualification produces True (Qualified), False (Criteria not met), or None (Not assessed)."""
        speed_run = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {})

        # 1. Baseline trial (ability run without document qualification)
        base_ability = ability_result()
        base_receipt = mission_report.summarize([speed_run, base_ability])
        self.assertIsNone(base_receipt['ability']['qualified'],
                          'Baseline ability must have qualified: None (Not assessed)')

        # 2. Document trial with met criteria
        doc_passed = {
            'id': 'doc-pass-1', 'kind': 'ability', 'suite': 'documents/short',
            'model': 'fixture:latest', 'manifest_digest': 'd' * 64,
            'created': '2026-10-08T12:00:00Z', 'state': 'completed',
            'coverage': {'complete': True},
            'summary': {'correct': 8, 'total': 8, 'format_errors': 0, 'wrong_answers': 0,
                        'categories': {'answer': {'correct': 8, 'total': 8}}},
            'qualification': {'qualified': True, 'checks': [{'name': 'answers', 'met': True}]},
            'items': [{'id': '1', 'category': 'answer', 'score': 1, 'outcome': 'correct',
                       'format_valid': True, 'latency_seconds': 0.5, 'output': 'valid'}],
        }
        passed_receipt = mission_report.summarize([speed_run, doc_passed])
        self.assertIs(passed_receipt['ability']['qualified'], True,
                      'Qualified document trial must report True')

        # 3. Document trial with failed criteria
        doc_failed = {
            'id': 'doc-fail-1', 'kind': 'ability', 'suite': 'documents/short',
            'model': 'fixture:latest', 'manifest_digest': 'd' * 64,
            'created': '2026-10-08T12:00:00Z', 'state': 'completed',
            'coverage': {'complete': True},
            'summary': {'correct': 5, 'total': 8, 'format_errors': 2, 'wrong_answers': 1,
                        'categories': {'answer': {'correct': 5, 'total': 8}}},
            'qualification': {'qualified': False, 'checks': [{'name': 'answers', 'met': False}]},
            'items': [{'id': '1', 'category': 'answer', 'score': 0, 'outcome': 'wrong_answer',
                       'format_valid': True, 'latency_seconds': 0.5, 'output': 'wrong'}],
        }
        failed_receipt = mission_report.summarize([speed_run, doc_failed])
        self.assertIs(failed_receipt['ability']['qualified'], False,
                      'Disqualified document trial must report False')

    def test_lab_recovery_status_truthful_states(self):
        """Recovery state accurately reflects startup phase without premature 'ready' claims."""
        ctrl = lab.Controller(self.startup, store=self.store)
        self.addCleanup(ctrl.close)

        # 1. When assistant was not running before the trial
        ctrl.resume = False
        ctrl.resume_requested = False
        self.assertEqual(ctrl.recovery_status()['state'], 'not-running')
        self.assertIn('not running', ctrl.recovery_status()['message'])

        # 2. Delayed recovery: startup is active / in setup phase
        ctrl.resume = True
        ctrl.resume_requested = True
        self.startup.active = True
        self.startup.phase = 'setup'
        self.assertEqual(ctrl.recovery_status()['state'], 'recovering')
        self.assertIn('in progress', ctrl.recovery_status()['message'])

        # Delayed recovery in model-service phase
        self.startup.phase = 'model-service'
        self.assertEqual(ctrl.recovery_status()['state'], 'recovering')

        # 3. Failed recovery
        self.startup.active = False
        self.startup.phase = 'failed'
        self.assertEqual(ctrl.recovery_status()['state'], 'failed')
        self.assertIn('failed', ctrl.recovery_status()['message'])

        # 4. Ready recovery
        self.startup.active = False
        self.startup.phase = 'ready'
        self.assertEqual(ctrl.recovery_status()['state'], 'ready')
        self.assertIn('ready', ctrl.recovery_status()['message'])

    def test_documents_starts_single_workload_and_rejects_concurrent(self):
        """Document start initiates exactly one workload and rejects parallel attempts."""
        ctrl = lab.Controller(self.startup, store=self.store)
        self.addCleanup(ctrl.close)

        gate = threading.Event()
        def slow_runner(*args, **kwargs):
            gate.wait(timeout=2)
            return ability_result()

        ctrl.speed = lambda client, model, **kw: bench_speed.run(client, model, hardware=lambda: {}, **kw)
        ctrl.documents = slow_runner

        snap = ctrl.start_documents()
        self.assertTrue(snap['active'])
        self.assertEqual(snap['plan'], 'documents')

        # Attempting a second workload while active must raise ValueError
        with self.assertRaisesRegex(ValueError, 'Another desktop workload is already active'):
            ctrl.start_documents()

        with self.assertRaisesRegex(ValueError, 'Another desktop workload is already active'):
            ctrl.start('baseline')

        gate.set()
        ctrl.worker.join(timeout=5)
        self.assertFalse(ctrl.snapshot()['active'])

    def test_cancellation_retains_partial_receipts_and_marks_incomplete(self):
        """Cancelling mid-run retains evaluated challenge receipts and reports truthful recovery."""
        ctrl = lab.Controller(self.startup, store=self.store)
        self.addCleanup(ctrl.close)

        item_scored = threading.Event()
        def mock_documents(client, model, cancel=None, progress=None, **options):
            if progress:
                # Emit first scored item
                progress({
                    'phase': 'scored', 'item_id': 'item-1', 'category': 'answer',
                    'completed': 1, 'total': 8,
                    'receipt': {'score': 1, 'outcome': 'correct', 'format_valid': True,
                                'latency_seconds': 0.4, 'output': 'Target Answer 1'},
                })
                item_scored.set()
                # Emit generating for second item
                progress({
                    'phase': 'generating', 'item_id': 'item-2', 'category': 'quote',
                    'completed': 1, 'total': 8, 'prompt': 'Question 2',
                })
                progress({'phase': 'answer-delta', 'item_id': 'item-2', 'delta': 'Partial output token'})
            # Wait for cancellation
            while not cancel.is_set():
                time.sleep(0.01)
            from argoslive.ollama import Cancelled
            raise Cancelled('Trial cancelled')

        ctrl.speed = lambda client, model, **kw: bench_speed.run(client, model, hardware=lambda: {}, **kw)
        ctrl.documents = mock_documents

        ctrl.start_documents()
        self.assertTrue(item_scored.wait(timeout=3))

        # Cancel while item 2 is in progress
        ctrl.cancel()
        ctrl.worker.join(timeout=5)

        snap = ctrl.snapshot()
        self.assertEqual(snap['phase'], 'cancelled')
        arena = snap['arena']
        self.assertEqual(arena['phase'], 'cancelled')

        # Partial receipt for item 1 is retained
        self.assertEqual(len(arena['receipts']), 1)
        self.assertEqual(arena['receipts'][0]['item_id'], 'item-1')
        self.assertEqual(arena['receipts'][0]['score'], 1)

        # In-progress item 2 is marked with [Stopped · incomplete]
        current_item = arena['current_item']
        self.assertIsNotNone(current_item)
        self.assertIn('[Stopped · incomplete]', current_item['answer'])

        # Recovery status is truthful: startup was restarted into 'setup' phase (recovering)
        self.assertEqual(arena['recovery']['state'], 'recovering')
        self.assertNotIn('Assistant resumption ready', json.dumps(arena))

    def test_concurrent_polling_and_cleanup_no_deadlock(self):
        """Concurrent lab.snapshot() polling and workload cleanup do not deadlock."""
        ctrl = lab.Controller(self.startup, store=self.store)
        self.addCleanup(ctrl.close)

        ctrl.speed = lambda client, model, **kw: bench_speed.run(client, model, hardware=lambda: {}, **kw)
        ctrl.ability = lambda *args, **kw: ability_result()
        ctrl.documents = lambda *args, **kw: ability_result()

        stop_event = threading.Event()
        errors = []

        def poller():
            while not stop_event.is_set():
                try:
                    s = ctrl.snapshot()
                    _ = s.get('recovery')
                    _ = ctrl.events_after(0)
                    _ = ctrl.recovery_status()
                except Exception as e:
                    errors.append(e)

        def runner():
            for _ in range(8):
                if stop_event.is_set():
                    break
                try:
                    ctrl.start('documents')
                    time.sleep(0.01)
                    ctrl.cancel()
                    if ctrl.worker:
                        ctrl.worker.join(timeout=2.0)
                except Exception as e:
                    errors.append(e)

        poll_threads = [threading.Thread(target=poller, daemon=True, name=f'poller-{i}') for i in range(4)]
        run_thread = threading.Thread(target=runner, daemon=True, name='workload-runner')

        for t in poll_threads:
            t.start()
        run_thread.start()

        run_thread.join(timeout=5.0)
        self.assertFalse(run_thread.is_alive(), "Workload runner deadlocked during concurrent execution")
        stop_event.set()

        for t in poll_threads:
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive(), f"Poller thread {t.name} deadlocked")

        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
