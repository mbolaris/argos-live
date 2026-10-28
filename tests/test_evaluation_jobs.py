import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_openclaw, workload
from argoslive.evaluation_jobs import Jobs, WaitAborted
from test_bench_openclaw import FakeOpenClaw, configure_fake


class EvaluationJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        configure_fake(self.home, workspace)
        self.gate = threading.Event()
        self.jobs = None

    def tearDown(self):
        self.gate.set()
        if self.jobs:
            for thread in self.jobs.threads.values():
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive(), 'Host fixture did not drain')

    def make_jobs(self, *, dispatched=False):
        def evaluate(**options):
            if dispatched:
                options['progress']({'phase': 'asking', 'completed': 0, 'total': 20})
            while not self.gate.wait(.005):
                if options['cancel'].is_set():
                    break
            return bench_openclaw._run(**options, runner=FakeOpenClaw(suite=options.get('suite', 'quick')))
        self.jobs = Jobs(self.home, evaluate=evaluate)
        return self.jobs

    def test_bounded_wait_returns_running_then_saved_completion(self):
        jobs = self.make_jobs()
        started = jobs.start()
        job_id = started['job_id']
        self.assertEqual(started['status'], 'running')
        progress = []
        self.assertEqual(jobs.wait(job_id, seconds=.01, on_update=progress.append)['status'], 'running')
        self.assertEqual(progress[0]['job_id'], job_id)
        self.gate.set()
        finished = jobs.wait(job_id, seconds=10)
        self.assertEqual(finished['result']['coverage']['completed'], 20)
        self.assertEqual(finished['result']['state'], 'completed')
        self.assertTrue(Path(finished['path']).is_file())
        self.assertFalse(finished['recovery_required'])
        with self.assertRaises(ValueError):
            jobs.wait(job_id, seconds=601)

    def test_challenge_job_advertises_its_own_workload_size(self):
        jobs = self.make_jobs()
        started = jobs.start('challenge')
        self.assertEqual(started['total'], 40)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-challenge')
        self.assertEqual(finished['result']['coverage']['total'], 40)

    def test_tool_schema_job_runs_through_host_owned_evaluation(self):
        jobs = self.make_jobs()
        started = jobs.start('tool-schema')
        self.assertEqual(started['total'], 40)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-tool-schema')
        self.assertEqual(finished['result']['summary']['partitions']['heldout']['correct'], 20)

    def test_tool_plan_job_runs_through_host_owned_evaluation(self):
        jobs = self.make_jobs()
        started = jobs.start('tool-plan')
        self.assertEqual(started['total'], 40)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-tool-plan')
        self.assertEqual(finished['result']['summary']['partitions']['heldout']['correct'], 20)

    def test_aborted_wait_does_not_cancel_job_and_saves_without_polling(self):
        jobs = self.make_jobs()
        job_id = jobs.start()['job_id']
        aborted = threading.Event()
        aborted.set()
        with self.assertRaises(WaitAborted):
            jobs.wait(job_id, seconds=1, aborted=aborted)
        self.assertEqual(jobs.read(jobs.control(job_id)), {'action': 'run'})
        self.gate.set()
        jobs.threads[job_id].join(timeout=10)
        # A fresh host reader sees the saved run even though the original
        # caller never polled after losing its wait/turn.
        finished = Jobs(self.home).status(job_id)
        self.assertEqual(finished['result']['state'], 'completed')
        self.assertTrue(Path(finished['path']).exists())

    def test_second_host_refuses_evaluation_until_first_has_drained(self):
        jobs = self.make_jobs()
        job_id = jobs.start()['job_id']
        with self.assertRaises(ValueError):
            Jobs(self.home).start()
        self.assertEqual(jobs.status(job_id)['status'], 'running')
        self.gate.set()
        jobs.threads[job_id].join(timeout=10)
        with workload.reserve(self.home, 'maintenance') as slot:
            slot.complete()  # No inference in this fixture operation.

    def test_explicit_cancel_before_dispatch_can_release_without_model_work(self):
        jobs = self.make_jobs()
        job_id = jobs.start()['job_id']
        Jobs(self.home).cancel_owner(job_id)
        finished = jobs.wait(job_id, seconds=10)
        self.assertEqual(finished['result']['state'], 'cancelled')
        self.assertEqual(finished['result']['coverage']['completed'], 0)
        self.assertFalse(finished['recovery_required'])

    def test_cancel_after_dispatch_preserves_result_and_quarantine(self):
        jobs = self.make_jobs(dispatched=True)
        job_id = jobs.start()['job_id']
        # Wait for the host's dispatch record; this simulates a turn that was
        # interrupted without independent proof of backend cancellation.
        for _ in range(200):
            if jobs.read(jobs.path(job_id))['inference_dispatched']:
                break
            threading.Event().wait(.005)
        self.assertTrue(jobs.read(jobs.path(job_id))['inference_dispatched'])
        jobs.cancel_owner(job_id)
        finished = jobs.wait(job_id, seconds=10)
        self.assertEqual(finished['result']['state'], 'cancelled')
        self.assertTrue(finished['recovery_required'])
        marker = self.home / '.local/state/argos-live/workload/reservation.json'
        self.assertEqual(json.loads(marker.read_text())['state'], 'quarantined')
        with self.assertRaises(ValueError):
            Jobs(self.home).start()


if __name__ == '__main__':
    unittest.main()
