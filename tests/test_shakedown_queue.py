import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive.results import Store
from argoslive.shakedown import loadout
from argoslive.shakedown.queue import QueueController
from test_bench_openclaw import configure_fake
from test_shakedown_scorecard import ability_run


MODEL = 'qwen3:4b-instruct-2507-q4_K_M'


class ModelInventory:
    def __init__(self, tags):
        self.tags = tags

    def list(self):
        return {'models': [{'name': tag} for tag in self.tags]}


class SerialJobs:
    def __init__(self, _home):
        self.calls = []
        self.active = False

    def start(self, suite, **options):
        if self.active:
            raise AssertionError('more than one evaluation became active')
        self.active = True
        self.calls.append((suite, options))
        return {'status': 'running', 'job_id': str(len(self.calls))}

    def wait(self, job_id, **_options):
        self.active = False
        return {'status': 'completed', 'job_id': job_id,
                'result': {'id': 'f' * 32, 'state': 'completed'}}

    def cancel_owner(self, _job_id):
        raise AssertionError('unexpected cancellation')


class FailingFirstJobs(SerialJobs):
    def wait(self, job_id, **_options):
        self.active = False
        outcome = 'failed' if len(self.calls) == 1 else 'completed'
        return {'status': 'completed', 'job_id': job_id,
                'result': {'id': 'f' * 32, 'state': outcome}}


class CancellableJobs:
    def __init__(self, _home):
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.calls = []

    def start(self, suite, **options):
        self.calls.append((suite, options))
        self.started.set()
        return {'status': 'running', 'job_id': 'one'}

    def wait(self, job_id, **_options):
        self.cancelled.wait(3)
        return {'status': 'completed', 'job_id': job_id,
                'result': {'id': 'f' * 32, 'state': 'cancelled'}}

    def cancel_owner(self, _job_id):
        self.cancelled.set()


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.workspace = self.home / '.openclaw/workspace'
        self.workspace.mkdir(parents=True)
        configure_fake(self.home, self.workspace)
        self.config_path = self.home / '.openclaw/openclaw.json'
        self.original_config = self.config_path.read_bytes()
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.store.save(ability_run('a' * 32, 'ollama/' + MODEL, [1] * 8))
        run = self.store.load('a' * 32)
        self.loadout_id = loadout.snapshot(run)['id']
        self.jobs = None

    def make_controller(self, tags=None):
        def jobs_factory(home):
            self.jobs = SerialJobs(home)
            return self.jobs
        inventory_tags = [MODEL] if tags is None else tags
        return QueueController(self.home, self.store, jobs_factory=jobs_factory,
                               model_client_factory=lambda: ModelInventory(inventory_tags))

    def test_three_entries_run_sequentially_and_leave_owner_configuration_unchanged(self):
        controller = self.make_controller()
        controller.start([{'loadout_id': self.loadout_id, 'size': 'quick'},
                          {'loadout_id': self.loadout_id, 'size': 'standard'},
                          {'loadout_id': self.loadout_id, 'size': 'full'}])
        controller.worker.join(timeout=10)
        self.assertFalse(controller.worker.is_alive())
        snapshot = controller.snapshot()
        self.assertEqual(snapshot['state'], 'completed')
        self.assertEqual(snapshot['position'], 3)
        self.assertEqual([entry['state'] for entry in snapshot['entries']],
                         ['completed', 'completed', 'completed'])
        self.assertEqual(len(self.jobs.calls), 3 * 7)
        self.assertEqual(self.config_path.read_bytes(), self.original_config)
        self.assertEqual(self.jobs.calls[0][1]['model_tag'], MODEL)

    def test_missing_download_is_reported_before_a_queue_is_started(self):
        controller = self.make_controller(tags=[])
        with self.assertRaisesRegex(ValueError, 'not downloaded'):
            controller.start([{'loadout_id': self.loadout_id, 'size': 'quick'}])
        self.assertEqual(controller.snapshot()['state'], 'idle')
        self.assertIsNone(controller.worker)

    def test_failed_entry_is_listed_and_queue_continues(self):
        def jobs_factory(home):
            self.jobs = FailingFirstJobs(home)
            return self.jobs
        controller = QueueController(self.home, self.store, jobs_factory=jobs_factory,
                                     model_client_factory=lambda: ModelInventory([MODEL]))
        controller.start([{'loadout_id': self.loadout_id, 'size': 'quick'},
                          {'loadout_id': self.loadout_id, 'size': 'standard'}])
        controller.worker.join(timeout=10)
        self.assertFalse(controller.worker.is_alive())
        self.assertEqual(controller.snapshot()['state'], 'completed-with-failures')
        self.assertEqual([entry['state'] for entry in controller.snapshot()['entries']],
                         ['incomplete', 'completed'])
        self.assertEqual(len(self.jobs.calls), 1 + 7)

    def test_cancel_cancels_current_entry_and_clears_the_remaining_queue(self):
        def jobs_factory(home):
            self.jobs = CancellableJobs(home)
            return self.jobs
        controller = QueueController(self.home, self.store, jobs_factory=jobs_factory,
                                     model_client_factory=lambda: ModelInventory([MODEL]))
        controller.start([{'loadout_id': self.loadout_id, 'size': 'quick'},
                          {'loadout_id': self.loadout_id, 'size': 'standard'}])
        for _ in range(300):
            if self.jobs is not None:
                break
            threading.Event().wait(.01)
        self.assertIsNotNone(self.jobs)
        self.assertTrue(self.jobs.started.wait(3))
        controller.cancel()
        controller.worker.join(timeout=10)
        self.assertFalse(controller.worker.is_alive())
        self.assertEqual(controller.snapshot()['state'], 'cancelled')
        self.assertEqual([entry['state'] for entry in controller.snapshot()['entries']],
                         ['cancelled', 'cancelled'])
        self.assertEqual(len(self.jobs.calls), 1)

    def test_a_saved_active_queue_is_marked_interrupted_and_never_resumed(self):
        controller = self.make_controller()
        controller.root.mkdir(parents=True, exist_ok=True)
        controller.path.write_text(json.dumps({
            'schema': 'argos-shakedown-queue/1', 'state': 'running', 'position': 1,
            'entries': [{'state': 'running'}, {'state': 'queued'}]}), encoding='utf-8')
        recovered = self.make_controller()
        snapshot = recovered.snapshot()
        self.assertEqual(snapshot['state'], 'interrupted')
        self.assertEqual(snapshot['entries'][0]['state'], 'interrupted')
        self.assertEqual(snapshot['entries'][1]['state'], 'skipped')
        self.assertIsNone(recovered.worker)


if __name__ == '__main__':
    unittest.main()
