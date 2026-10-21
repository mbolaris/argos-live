import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))

from argoslive import bench_openclaw, evaluation_control as control, workload
from argoslive.results import Store
from test_bench_openclaw import FakeOpenClaw, configure_fake


class OwnerControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        (self.home / '.openclaw/workspace').mkdir(parents=True)
        configure_fake(self.home, self.home / '.openclaw/workspace')
        patcher = patch.object(Path, 'home', return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stale_generation_refused_and_request_does_not_release(self):
        with workload.reserve(self.home, 'evaluation') as slot:
            target = control.target(self.home)
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                control.request_stop(self.home, dict(target, generation=target['generation'] - 1))
            cancel = control.Cancellation(self.home)
            self.assertFalse(cancel.is_set())
            receipt = control.request_stop(self.home, target)
            self.assertEqual(receipt['status'], 'cancel_requested')
            self.assertTrue(cancel.is_set())
            self.assertFalse(slot.drained)
            slot.complete()  # No inference in this fixture.
        with workload.reserve(self.home, 'evaluation') as slot:
            self.assertFalse(control.Cancellation(self.home).is_set())
            slot.complete()

    def test_cli_stop_during_run_saves_cancelled_evidence_and_quarantine(self):
        home = self.home

        class Stopping(FakeOpenClaw):
            def turn(self, prompt):
                if self.calls == 2:
                    target = control.target(home)
                    completed = subprocess.run([sys.executable, str(ROOT / 'runtime/argos.py'),
                        'bench', 'control', 'stop', '--home', str(home),
                        '--id', target['id'], '--generation', str(target['generation'])],
                        capture_output=True, text=True, timeout=15)
                    self_test.assertEqual(completed.returncode, 0, completed.stderr)
                    self_test.assertEqual(json.loads(completed.stdout)['status'], 'cancel_requested')
                return super().turn(prompt)

        self_test = self
        value = bench_openclaw.run(home=home, runner=Stopping())
        self.assertEqual(value['state'], 'cancelled')
        saved = Store(home / '.local/share/argos-live/results').load(value['id'])
        self.assertEqual(saved['state'], 'cancelled')
        record = json.loads((control.root(home) / 'reservation.json').read_text())
        self.assertEqual(record['state'], 'quarantined')
        self.assertEqual(record['result_id'], value['id'])

    def test_non_evaluation_and_quarantine_are_refused(self):
        with workload.reserve(self.home, 'controller') as slot:
            with self.assertRaises(ValueError):
                control.target(self.home)
            slot.complete()
        with self.assertRaises(ValueError):
            control.target(self.home)

    def test_child_request_cannot_cancel_next_child(self):
        with workload.reserve(self.home, 'controller') as parent:
            capability = parent.delegate('evaluation')
            with workload.reserve(self.home, 'evaluation', delegation=capability) as child:
                result = bench_openclaw._run(home=self.home, runner=FakeOpenClaw())
                Store(self.home / '.local/share/argos-live/results').save(result)
                prior = control.target(self.home)
                cancel = control.Cancellation(self.home)
                control.request_stop(self.home, prior)
                self.assertTrue(cancel.is_set())
                child.complete(result['id'])
            parent.resume(capability, worker_drained=True)
            capability = parent.delegate('evaluation')
            with workload.reserve(self.home, 'evaluation', delegation=capability) as child:
                result = bench_openclaw._run(home=self.home, runner=FakeOpenClaw())
                Store(self.home / '.local/share/argos-live/results').save(result)
                self.assertFalse(control.Cancellation(self.home).is_set())
                with self.assertRaises(ValueError):
                    control.request_stop(self.home, prior)
                child.complete(result['id'])
            parent.resume(capability, worker_drained=True)
            parent.complete()
