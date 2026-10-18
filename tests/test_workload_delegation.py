from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_openclaw, workload
from argoslive.results import Store
from test_bench_openclaw import FakeOpenClaw, configure_fake


class DelegationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        configure_fake(self.home, workspace)

    def record(self):
        return json.loads((self.home / '.local/state/argos-live/workload/reservation.json').read_bytes())

    def test_nested_evaluation_saves_before_parent_can_resume(self):
        with workload.reserve(self.home, 'controller') as parent:
            capability = parent.delegate('evaluation')
            self.assertNotIn(capability.secret, repr(capability))
            self.assertNotIn(capability.secret, json.dumps(self.record()))
            for kind in ('controller', 'evaluation', 'proctor', 'maintenance', 'log'):
                with self.subTest(kind=kind), self.assertRaises(workload.Busy):
                    with workload.reserve(self.home, kind):
                        self.fail('Competing workload entered during delegated ownership')
            with self.assertRaises(workload.Busy):
                parent.complete()
            run = bench_openclaw.run(home=self.home, runner=FakeOpenClaw(), delegation=capability)
            self.assertEqual(Store(self.home / '.local/share/argos-live/results').load(run['id']), run)
            self.assertEqual(self.record()['phase'], 'delegated')
            with self.assertRaises(workload.Busy):
                parent.resume(capability)  # end/return alone is not a drain assertion
            child = parent.resume(capability, worker_drained=True)
            self.assertEqual(child['result_id'], run['id'])
            self.assertEqual(self.record()['phase'], 'running')
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'evaluation', delegation=capability):
                    self.fail('A used child authorization was replayed')
            parent.complete()
        self.assertEqual(self.record()['state'], 'released')

    def test_failed_child_retains_saved_outcome_and_quarantines_parent(self):
        with workload.reserve(self.home, 'controller') as parent:
            capability = parent.delegate('evaluation')
            run = bench_openclaw.run(home=self.home, runner=FakeOpenClaw(fail_at=3), delegation=capability)
            self.assertEqual(run['state'], 'failed')
            self.assertEqual(Store(self.home / '.local/share/argos-live/results').load(run['id']), run)
            with self.assertRaises(workload.Busy):
                parent.resume(capability, worker_drained=True)
            with self.assertRaises(workload.Busy):
                parent.complete()
        self.assertEqual(self.record()['state'], 'quarantined')
        with self.assertRaises(workload.Busy):
            with workload.reserve(self.home, 'proctor'):
                self.fail('Failed child silently reopened proctor admission')

    def test_concurrent_child_and_early_resume_cannot_enter(self):
        started, finish = threading.Event(), threading.Event()
        outcomes = []
        class Waiting(FakeOpenClaw):
            def turn(self, prompt):
                started.set()
                if not finish.wait(10):
                    raise RuntimeError('Test did not release child')
                return super().turn(prompt)
        with workload.reserve(self.home, 'controller') as parent:
            capability = parent.delegate('evaluation')
            def first():
                try:
                    outcomes.append(bench_openclaw.run(home=self.home, runner=Waiting(), delegation=capability))
                except BaseException as error:
                    outcomes.append(error)
            thread = threading.Thread(target=first)
            thread.start()
            try:
                self.assertTrue(started.wait(10))
                runner = FakeOpenClaw()
                with self.assertRaises(workload.Busy):
                    bench_openclaw.run(home=self.home, runner=runner, delegation=capability)
                self.assertEqual(runner.calls, 0)
                with self.assertRaises(workload.Busy):
                    parent.resume(capability, worker_drained=True)
                with self.assertRaises(workload.Busy):
                    parent.delegate('maintenance')
            finally:
                finish.set()
                thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes[0]['state'], 'completed')
            parent.resume(capability, worker_drained=True)
            parent.complete()

    def test_wrong_secret_kind_and_stale_generation_cannot_consume_grant(self):
        with workload.reserve(self.home, 'controller') as parent:
            capability = parent.delegate('log')
            for invalid in (replace(capability, secret='wrong'), replace(capability, generation=0)):
                with self.assertRaises(ValueError):
                    with workload.reserve(self.home, 'log', delegation=invalid):
                        self.fail('Forged capability admitted')
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'evaluation', delegation=capability):
                    self.fail('Capability used for a different operation')
            with workload.reserve(self.home, 'log', delegation=capability) as child:
                child.complete()
            parent.resume(capability, worker_drained=True)
            parent.complete()
        with workload.reserve(self.home, 'controller') as successor:
            before = self.record()
            with self.assertRaises(workload.Busy):
                parent.resume(capability, worker_drained=True)
            self.assertEqual(before, self.record())
            successor.complete()

    def test_publication_failure_never_releases_admission(self):
        with patch.object(bench_openclaw.Store, 'save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                bench_openclaw.run(home=self.home, runner=FakeOpenClaw())
        self.assertEqual(self.record()['state'], 'quarantined')

    def test_api_keeps_admission_during_result_publication(self):
        save = Store.save
        def publish(store, result):
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'proctor'):
                    self.fail('API released admission before publishing its result')
            return save(store, result)
        with patch.object(Store, 'save', publish):
            run = bench_openclaw.run(home=self.home, runner=FakeOpenClaw())
        self.assertEqual(self.record()['result_id'], run['id'])
        with workload.reserve(self.home, 'proctor') as slot:
            slot.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process birth identity')
    def test_killed_child_never_resumes_parent_or_allows_proctor(self):
        script = ('from argoslive.workload import reserve,Delegation\n'
                  'import json,sys\n'
                  'cap=Delegation(**json.loads(sys.stdin.readline()))\n'
                  'with reserve(sys.argv[1], "evaluation", delegation=cap):\n'
                  ' print("READY",flush=True)\n'
                  ' sys.stdin.read()\n')
        from dataclasses import asdict
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'runtime')}
        with workload.reserve(self.home, 'controller') as parent:
            capability = parent.delegate('evaluation')
            with subprocess.Popen([sys.executable, '-c', script, str(self.home)], env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
                try:
                    process.stdin.write(json.dumps(asdict(capability)) + '\n')
                    process.stdin.flush()
                    self.assertEqual(process.stdout.readline().strip(), 'READY')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
            with self.assertRaises(workload.Busy):
                parent.resume(capability, worker_drained=True)
            with self.assertRaises(workload.Busy):
                parent.complete()
        self.assertEqual(self.record()['state'], 'quarantined')
        with self.assertRaises(workload.Busy):
            with workload.reserve(self.home, 'proctor'):
                self.fail('Killed child silently admitted a proctor')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process birth identity')
    def test_killed_parent_grant_cannot_start_a_child_or_be_reclaimed(self):
        script = ('from argoslive.workload import reserve; from dataclasses import asdict\n'
                  'import json,sys\n'
                  'with reserve(sys.argv[1], "controller") as p:\n'
                  ' print(json.dumps(asdict(p.delegate("evaluation"))),flush=True)\n'
                  ' sys.stdin.read()\n')
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'runtime')}
        with subprocess.Popen([sys.executable, '-c', script, str(self.home)], env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
            capability = workload.Delegation(**json.loads(process.stdout.readline()))
            process.kill()
            process.wait(timeout=10)
        runner = FakeOpenClaw()
        with self.assertRaises(workload.Busy):
            bench_openclaw.run(home=self.home, runner=runner, delegation=capability)
        self.assertEqual(runner.calls, 0)
        with self.assertRaises(workload.Busy):
            with workload.reserve(self.home, 'proctor'):
                self.fail('Dead parent was automatically reclaimed')


if __name__ == '__main__':
    unittest.main()
