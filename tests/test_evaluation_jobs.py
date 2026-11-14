import json
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_openclaw, workload
from argoslive.evaluation_jobs import Jobs, WaitAborted
from argoslive.shakedown.lap import SLICE_VERSION
from test_bench_openclaw import (FakeDocumentOpenClaw, FakeOpenClaw,
                                 FakeOwnerRecoveryOpenClaw, configure_fake)


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
            suite = options.get('suite', 'quick')
            runner = (FakeDocumentOpenClaw() if suite == 'documents-short' else
                      FakeOwnerRecoveryOpenClaw() if suite == 'owner-recovery-decision' else
                      FakeOpenClaw(suite=suite))
            return bench_openclaw._run(**options, runner=runner)
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

    def test_documents_short_job_advertises_and_saves_its_own_workload(self):
        jobs = self.make_jobs()
        started = jobs.start('documents-short')
        self.assertEqual(started['total'], 24)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-documents-short')
        self.assertEqual(finished['result']['coverage']['total'], 24)
        self.assertTrue(finished['result']['qualification']['qualified'])

    def test_owner_recovery_job_is_bounded_and_saves_decision_only_measurements(self):
        jobs = self.make_jobs()
        started = jobs.start('owner-recovery-decision')
        self.assertEqual(started['total'], 8)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-owner-recovery-decision')
        self.assertEqual(finished['result']['coverage'], {'completed': 8, 'total': 8, 'complete': True})
        self.assertEqual(finished['result']['task_measurement']['owner_effort_correct'], 8)
        self.assertFalse(finished['result']['task_measurement']['recovery_completed'])

    def test_tool_schema_job_runs_through_host_owned_evaluation(self):
        jobs = self.make_jobs()
        started = jobs.start('tool-schema')
        self.assertEqual(started['total'], 40)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-tool-schema')
        self.assertEqual(finished['result']['summary']['partitions']['heldout']['correct'], 20)

    def test_fixed_slice_is_saved_with_its_name_version_and_lap_identity(self):
        jobs = self.make_jobs()
        lap_id = 'a' * 32
        started = jobs.start('quick', slice_name='quick', slice_version=SLICE_VERSION, lap_id=lap_id)
        self.assertEqual(started['total'], 10)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        run = finished['result']
        self.assertEqual((run['slice_name'], run['slice_version'], run['lap_id']),
                         ('quick', SLICE_VERSION, lap_id))
        self.assertEqual(run['suite_total'], 20)
        self.assertEqual(run['coverage'], {'completed': 10, 'total': 10, 'complete': True})
        self.assertEqual(len(run['items']), 10)

    def test_speed_jobs_share_the_host_owned_saved_job_lifecycle(self):
        jobs = self.make_jobs()
        jobs.speed_evaluate = lambda **_options: {
            'schema': 'argos-bench/1', 'id': secrets.token_hex(16),
            'created': datetime.now(timezone.utc).isoformat(), 'kind': 'speed',
            'suite_version': 'speed/1', 'model': 'fixture:model', 'settings': {},
            'hardware': {}, 'restoration': {'succeeded': True}, 'state': 'completed',
            'prompts': [{'size': 'short', 'skipped': True, 'runs': []}],
            'coverage': {'completed': 0, 'total': 0, 'complete': True}}
        started = jobs.start('speed', lap_id='b' * 32)
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['kind'], 'speed')
        self.assertEqual(finished['result']['lap_id'], 'b' * 32)
        self.assertFalse(finished['recovery_required'])

    def test_tool_plan_job_runs_through_host_owned_evaluation(self):
        jobs = self.make_jobs()
        started = jobs.start('tool-plan')
        self.assertEqual(started['total'], 40)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-tool-plan')
        self.assertEqual(finished['result']['summary']['partitions']['heldout']['correct'], 20)

    def test_tool_sequence_job_runs_through_host_owned_evaluation(self):
        jobs = self.make_jobs()
        started = jobs.start('tool-sequence')
        self.assertEqual(started['total'], 40)
        self.gate.set()
        finished = jobs.wait(started['job_id'], seconds=10)
        self.assertEqual(finished['result']['suite'], 'openclaw-tool-sequence')
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
