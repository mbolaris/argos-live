import json
from contextlib import closing
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from argoslive import proctor_campaign, proctor_service
from argoslive.web.server import DashboardServer


class FakeStartup:
    def __init__(self, home):
        self.home = home
        self.lock = threading.RLock()
        self.lab_active = False
        self.chat_claimed = False
        self.active = True
        self.phase = 'ready'
        self.recovery_fails = False

    def snapshot(self):
        return {'active': self.active, 'phase': self.phase, 'model': 'qwen-test',
                'model_reply_verified': self.phase == 'ready'}

    def stop(self):
        self.active = False
        self.phase = 'stopped'

    def start(self, *, _reserved=False):
        if self.recovery_fails:
            self.active = False
            self.phase = 'failed'
        else:
            self.active = True
            self.phase = 'ready'


def result():
    return {'status': 'completed',
            'campaign': {'status': 'completed', 'outcome': 'no_change_audited',
                         'audit_status': 'empty', 'controller_turns': 2,
                         'saved_evaluation_ids': ['run-a', 'run-b'], 'missing': [],
                         'tool_outcomes': ['private tool payload is excluded']}}


class ProctorCampaignControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        config = self.home / '.config/argos-live'
        config.mkdir(parents=True)
        (config / 'state.json').write_text(json.dumps({'model': 'qwen-test', 'storage': str(self.home / 'models'),
            'storage_id': 'disk-test', 'storage_confirmed': {'path': str(self.home / 'models'),
            'storage_id': 'disk-test', 'at': 'now'}}))
        self.startup = FakeStartup(self.home)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.selected_task = None
        self.selected_criteria = None
        self.storage_status = self.persistent_storage

        def runner(home, *, owner_task, success_criteria, on_phase, on_progress):
            self.selected_task = owner_task
            self.selected_criteria = success_criteria
            on_phase('campaign')
            on_progress({'phase': 'campaign', 'stage': 'turn-start', 'turn': 1, 'total': 4,
                         'saved_evaluation_count': 2, 'audit_status': 'pending',
                         'agent_text': 'must never be exposed'})
            self.entered.set()
            self.release.wait(2)
            return result()

        self.controller = proctor_campaign.Controller(self.startup, runner=runner,
                                                       storage_snapshot=lambda _home: self.storage_status())

    @staticmethod
    def persistent_storage():
        return {'confirmed': True, 'locations': [
            {'key': key, 'backing': {'encrypted': True, 'persistent': True}}
            for key in ('models', 'profile', 'results', 'settings')]}

    def tearDown(self):
        self.release.set()
        self.controller.close()
        self.temp.cleanup()

    def wait_finished(self):
        worker = self.controller.worker
        if worker is not None:
            worker.join(timeout=3)
        self.assertFalse(worker and worker.is_alive())

    def test_start_requires_bounded_owner_task_and_success_criteria(self):
        with self.assertRaisesRegex(proctor_campaign.Refused, 'Describe the owner task'):
            self.controller.start('', 'ready')
        with self.assertRaisesRegex(proctor_campaign.Refused, 'under 1,200 characters'):
            self.controller.start('x' * 1201, 'ready')
        self.assertEqual(proctor_campaign.validate_measurement_suite('documents-short'), 'documents-short')
        self.assertEqual(proctor_campaign.validate_measurement_suite('owner-recovery-decision'),
                         'owner-recovery-decision')
        with self.assertRaises(proctor_campaign.Refused):
            proctor_campaign.validate_measurement_suite('documents-long')
        self.assertFalse(self.startup.lab_active)
        self.assertIsNone(self.controller.worker)

    def test_dashboard_exposes_document_suite_with_its_narrow_scope(self):
        dashboard = (Path(__file__).resolve().parents[1] /
                     'runtime/argoslive/web/static/index.html').read_text(encoding='utf-8')
        self.assertIn('value="documents-short"', dashboard)
        self.assertIn('value="owner-recovery-decision"', dashboard)
        self.assertIn('Read this brief” covers only its short passages', dashboard)
        self.assertIn('does not measure long-document or file-reading work', dashboard)

    def test_owner_start_reserves_resources_runs_and_restores_verified_assistant(self):
        started = self.controller.start('recover Argos after reboot',
                                        'ready after unlock with no terminal command')
        self.assertTrue(self.startup.lab_active)
        self.assertEqual(started['phase'], 'pausing')
        self.assertTrue(self.entered.wait(1))
        self.assertTrue(self.startup.lab_active)
        self.release.set()
        self.wait_finished()
        status = self.controller.snapshot()
        self.assertEqual(status['phase'], 'completed')
        self.assertEqual(self.selected_task, 'recover Argos after reboot')
        self.assertEqual(self.selected_criteria, 'ready after unlock with no terminal command')
        self.assertEqual(status['progress'], {'phase': 'campaign', 'stage': 'turn-start',
                                              'turn': 1, 'total': 4, 'saved_evaluation_count': 2,
                                              'audit_status': 'pending'})
        self.assertEqual(status['result']['campaign']['saved_evaluation_ids'], ['run-a', 'run-b'])
        self.assertNotIn('owner_task', status)
        self.assertTrue(status['assistant_ready'])
        self.assertFalse(self.startup.lab_active)
        self.assertNotIn('practice', status['result'])
        self.assertNotIn('tool_outcomes', status['result']['campaign'])

    def test_campaign_receives_only_the_bound_read_only_ssh_status_provider(self):
        captured = {}
        recovery = type('Recovery', (), {
            'proctor_status': lambda _self: {'available': True},
            'verify_proctor_status': lambda _self, _value: True,
        })()

        def runner(_home, **options):
            captured.update(options)
            return result()

        controller = proctor_campaign.Controller(
            self.startup, home=self.home, runner=runner, ssh_recovery=recovery,
            storage_snapshot=lambda _home: self.storage_status())
        try:
            controller.start('recover Argos after boot', 'ready without terminal commands')
            worker = controller.worker
            self.assertTrue(worker)
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(captured['ssh_status_provider'](), {'available': True})
            self.assertTrue(captured['ssh_status_verifier']({'available': True}))
            self.assertEqual(captured['owner_task'], 'recover Argos after boot')
        finally:
            controller.close()

    def test_refuses_unconfirmed_storage_and_other_workload(self):
        task = 'recover Argos after reboot'
        criteria = 'ready after unlock with no terminal command'
        self.storage_status = lambda: {'confirmed': False, 'locations': []}
        with self.assertRaises(proctor_campaign.Refused):
            self.controller.start(task, criteria)
        self.storage_status = lambda: {'confirmed': True, 'locations': [
            {'key': key, 'backing': {'encrypted': key != 'results', 'persistent': True}}
            for key in ('models', 'profile', 'results', 'settings')]}
        with self.assertRaises(proctor_campaign.Refused):
            self.controller.start(task, criteria)
        self.storage_status = self.persistent_storage
        self.startup.lab_active = True
        with self.assertRaises(proctor_campaign.Refused):
            self.controller.start(task, criteria)

    def test_task_not_measured_is_explained_without_calling_it_a_failure(self):
        self.controller.runner = lambda _home, **_callbacks: {
            'status': 'incomplete',
            'campaign': {'status': 'incomplete', 'outcome': 'task-not-measured',
                         'audit_status': None, 'controller_turns': 1, 'missing':
                         ['No task-specific measurement was run.'],
                         'saved_evaluation_ids': []},
        }
        self.controller.start('restore paired SSH after boot',
                              'report healthy state or recover with no terminal commands')
        self.wait_finished()
        status = self.controller.snapshot()
        self.assertEqual(status['phase'], 'incomplete')
        self.assertIn('No task-specific measurement was run', status['message'])
        self.assertIn('no score or improvement is claimed', status['message'])
        self.assertNotIn('campaign stopped without all required evidence', status['message'])
        app = (Path(__file__).resolve().parents[1] /
               'runtime/argoslive/web/static/app.js').read_text(encoding='utf-8')
        self.assertIn("data.result?.campaign?.outcome === 'task-not-measured'", app)
        self.assertIn("taskNotMeasured ? 'Task not measured'", app)

    def test_failed_campaign_still_restarts_argos(self):
        self.controller.runner = lambda home, **_callbacks: (_ for _ in ()).throw(ValueError('private detail'))
        self.controller.start('recover Argos after reboot', 'ready after unlock with no terminal command')
        self.wait_finished()
        status = self.controller.snapshot()
        self.assertEqual(status['phase'], 'failed')
        self.assertEqual(status['failure_code'], 'campaign-invalid-state')
        self.assertEqual(status['failure_stage'], 'campaign')
        self.assertTrue(status['assistant_ready'])
        self.assertFalse(self.startup.lab_active)

    def test_failed_restart_keeps_shared_workload_reservation_closed(self):
        self.startup.recovery_fails = True
        self.controller.runner = lambda home, **_callbacks: result()
        self.controller.start('recover Argos after reboot', 'ready after unlock with no terminal command')
        self.wait_finished()
        self.assertEqual(self.controller.snapshot()['phase'], 'recovery-failed')
        self.assertTrue(self.startup.lab_active)
        self.assertFalse(self.controller.snapshot()['can_start'])
        self.assertTrue(self.controller.snapshot()['can_recover'])
        self.startup.recovery_fails = False
        self.controller.recover()
        self.wait_finished()
        self.assertEqual(self.controller.snapshot()['phase'], 'completed')
        self.assertFalse(self.startup.lab_active)

    def test_dashboard_route_is_token_protected_and_requires_task_json_for_start(self):
        server = DashboardServer(port=0, proctor_campaign=self.controller)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        worker.start()

        def request(path, method='GET', *, token=True, body=None):
            headers = {'X-Argos-Token': server.token} if token else {}
            if method == 'POST' and body is not None and path.endswith('/start'):
                headers['Content-Type'] = 'application/json'
            with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)) as connection:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}

        try:
            self.assertEqual(request('/api/proctor-campaign', token=False)[0], 403)
            self.assertEqual(request('/api/proctor-campaign/start', 'POST', token=False, body=b'{}')[0], 403)
            self.assertEqual(request('/api/proctor-campaign/start', 'POST', body=b'{}', token=True)[0], 400)
            code, state = request('/api/proctor-campaign', token=True)
            self.assertEqual(code, 200)
            self.assertTrue(state['available'])
            payload = json.dumps({'owner_task': 'recover Argos after reboot',
                                  'success_criteria': 'ready after unlock with no terminal command'})
            code, started = request('/api/proctor-campaign/start', 'POST', body=payload)
            self.assertEqual(code, 200)
            self.assertEqual(started['phase'], 'pausing')
            self.assertTrue(self.entered.wait(1))
            self.assertEqual(request('/api/proctor-campaign/start', 'POST', body=payload)[0], 409)
            self.release.set()
            self.wait_finished()
        finally:
            server.shutdown()
            worker.join(timeout=3)
            server.server_close()


class ProctorServiceProgressTests(unittest.TestCase):
    def test_run_improvement_skips_unrelated_practice_and_runs_owner_task_campaign(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            config = home / '.config/argos-live'
            config.mkdir(parents=True)
            (config / 'state.json').write_text('{"model":"qwen-test"}')
            campaign = {'status': 'incomplete', 'outcome': 'no_change_audited', 'saved_evaluation_ids': []}
            phases = []
            with patch.object(proctor_service, 'run_practice') as practice, \
                    patch.object(proctor_service.startup, 'source', return_value=('target', 'qwen-test')), \
                    patch.object(proctor_service, 'run_campaign', return_value=campaign):
                value = proctor_service.run_improvement(home, on_phase=phases.append,
                    owner_task='recover Argos after reboot',
                    success_criteria='ready after unlock with no terminal command')
            self.assertEqual(phases, ['campaign'])
            self.assertEqual(value['status'], 'incomplete')
            self.assertNotIn('practice', value)
            practice.assert_not_called()

    def test_campaign_exception_returns_safe_failure_without_running_practice(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            config = home / '.config/argos-live'
            config.mkdir(parents=True)
            (config / 'state.json').write_text('{"model":"qwen-test"}')
            phases = []
            with patch.object(proctor_service, 'run_practice') as practice, \
                    patch.object(proctor_service.startup, 'source', return_value=('target', 'qwen-test')), \
                    patch.object(proctor_service, 'run_campaign', side_effect=PermissionError('private path')):
                value = proctor_service.run_improvement(home, on_phase=phases.append,
                    owner_task='recover Argos after reboot',
                    success_criteria='ready after unlock with no terminal command')
            self.assertEqual(phases, ['campaign'])
            self.assertEqual(value['status'], 'incomplete')
            self.assertNotIn('practice', value)
            self.assertEqual(value['campaign']['saved_evaluation_ids'], [])
            self.assertEqual(value['failure_stage'], 'campaign')
            self.assertEqual(value['failure_code'], 'campaign-permission-denied')
            self.assertNotIn('private path', json.dumps(value))
            practice.assert_not_called()


if __name__ == '__main__':
    unittest.main()
