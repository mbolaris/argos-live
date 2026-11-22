import json
from contextlib import closing
import http.client
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
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
                         'evaluation_limit': 2,
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

        def runner(home, *, owner_task, success_criteria, evaluation_limit, stop_event, on_phase, on_progress):
            self.selected_task = owner_task
            self.selected_criteria = success_criteria
            self.selected_evaluation_limit = evaluation_limit
            self.selected_stop_event = stop_event
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
        self.assertEqual(proctor_campaign.validate_measurement_suite('documents-long'), 'documents-long')
        with self.assertRaisesRegex(proctor_campaign.Refused, 'limit from 1 to 8'):
            self.controller.start('recover Argos after reboot', 'ready', evaluation_limit=9)
        self.assertFalse(self.startup.lab_active)
        self.assertIsNone(self.controller.worker)

    def test_owner_limit_and_stop_event_reach_runner(self):
        self.controller.start('recover Argos after reboot', 'ready', evaluation_limit=2)
        self.assertTrue(self.entered.wait(1))
        self.assertEqual(self.controller.snapshot()['evaluation_limit'], 2)
        stopped = self.controller.stop()
        self.assertEqual(stopped['phase'], 'stopping')
        self.assertTrue(self.selected_stop_event.is_set())
        self.release.set()
        self.wait_finished()
        final = self.controller.snapshot()
        self.assertEqual(final['phase'], 'completed')
        self.assertTrue(final['assistant_ready'])
        self.assertFalse(self.startup.lab_active)

    def test_live_evaluation_watch_shows_question_answer_score_and_elapsed_time(self):
        now = [10.0]
        self.controller.clock = lambda: now[0]
        self.controller.worker = SimpleNamespace(is_alive=lambda: True, join=lambda **_kwargs: None)
        self.controller._set_progress({
            'phase': 'campaign', 'stage': 'evaluation-question', 'run_id': 'a' * 32,
            'item_id': 'fact-1', 'category': 'grounded-recall',
            'question': 'What did the note say?', 'total': 2, 'completed': 0,
            'suite': 'documents-short', 'suite_version': 'documents-short/v1',
            'model': 'qwen-test', 'expected_answer': 'must never be exposed',
        })
        now[0] += 4.25
        waiting = self.controller.snapshot()['progress']
        self.assertEqual(waiting['current']['question'], 'What did the note say?')
        self.assertEqual(waiting['current']['state'], 'thinking')
        self.assertAlmostEqual(waiting['current_elapsed_seconds'], 4.25)
        self.assertNotIn('_current_started_at', waiting)
        self.assertNotIn('expected_answer', waiting)

        self.controller._set_progress({
            'phase': 'campaign', 'stage': 'evaluation-scored', 'run_id': 'a' * 32,
            'item_id': 'fact-1', 'category': 'grounded-recall',
            'question': 'What did the note say?', 'total': 2, 'completed': 1,
            'suite': 'documents-short', 'suite_version': 'documents-short/v1',
            'model': 'qwen-test', 'answer': 'It said the package arrived Tuesday.',
            'outcome': 'pass', 'latency_seconds': 4.25, 'score': 1,
        })
        scored = self.controller.snapshot()['progress']
        self.assertEqual(scored['current']['answer'], 'It said the package arrived Tuesday.')
        self.assertEqual(scored['current']['outcome'], 'pass')
        self.assertEqual(scored['current']['latency_seconds'], 4.25)
        self.assertEqual(scored['evaluation_runs'][0]['completed'], 1)
        self.assertEqual(scored['evaluation_runs'][0]['items'][0]['score'], 1)
        self.assertNotIn('expected_answer', scored)

    def test_live_campaign_timeline_omits_agent_arguments_and_private_paths(self):
        self.controller.worker = SimpleNamespace(is_alive=lambda: True, join=lambda **_kwargs: None)
        self.controller._set_progress({
            'phase': 'campaign', 'stage': 'campaign-step', 'step_id': 'call-1',
            'tool': 'evaluation', 'status': 'completed', 'step_status': 'completed',
            'result_id': 'b' * 32, 'suite': 'documents-short', 'completed': 2,
            'total': 2, 'correct': 2, 'coverage_complete': True,
            'private_path': 'C:/private/results.json', 'arguments': {'secret': 'hidden'},
        })
        progress = self.controller.snapshot()['progress']
        self.assertEqual(progress['campaign_steps'][0]['correct'], 2)
        self.assertEqual(progress['campaign_steps'][0]['result_id'], 'b' * 32)
        self.assertNotIn('private_path', progress['campaign_steps'][0])
        self.assertNotIn('arguments', progress['campaign_steps'][0])
        self.assertNotIn('secret', json.dumps(progress))

    def test_dashboard_exposes_document_suite_with_its_narrow_scope(self):
        dashboard = (Path(__file__).resolve().parents[1] /
                     'runtime/argoslive/web/static/index.html').read_text(encoding='utf-8')
        self.assertIn('value="documents-short"', dashboard)
        self.assertIn('value="owner-recovery-decision"', dashboard)
        self.assertIn('id="proctor-evaluation-limit" type="number" min="1" max="8"', dashboard)
        self.assertIn('id="proctor-campaign-stop"', dashboard)
        self.assertIn('Read this brief” covers only its short passages', dashboard)
        self.assertIn('does not measure long-document or file-reading work', dashboard)
        app = (Path(__file__).resolve().parents[1] /
               'runtime/argoslive/web/static/app.js').read_text(encoding='utf-8')
        self.assertIn("fetch('/api/proctor-campaign/stop'", app)
        self.assertIn('evaluation_limit: evaluationLimit', app)

    def test_owner_start_reserves_resources_runs_and_restores_verified_assistant(self):
        started = self.controller.start('recover Argos after reboot',
                                        'ready after unlock with no terminal command',
                                        evaluation_limit=2)
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
        self.assertEqual(self.selected_evaluation_limit, 2)
        self.assertEqual(status['progress'], {'phase': 'campaign', 'stage': 'turn-start',
                                              'turn': 1, 'total': 4, 'saved_evaluation_count': 2,
                                              'audit_status': 'pending'})
        self.assertEqual(status['result']['campaign']['saved_evaluation_ids'], ['run-a', 'run-b'])
        self.assertEqual(status['result']['campaign']['evaluation_limit'], 2)
        saved = self.controller.record(status['watch']['id'])
        self.assertEqual(saved['evaluation_limit'], 2)
        self.assertEqual(saved['result']['campaign']['evaluation_limit'], 2)
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

    def test_exhausted_unmeasured_campaign_reports_safe_release_without_claim(self):
        self.controller.runner = lambda _home, **_callbacks: {
            'status': 'incomplete',
            'campaign': {'status': 'incomplete', 'outcome': 'agent-turn-incomplete',
                         'audit_status': None, 'controller_turns': 4,
                         'missing': ['The agent exhausted bounded turns before completing required reads.'],
                         'saved_evaluation_ids': []},
        }
        self.controller.start('resume Argos after boot',
                              'ready without terminal commands')
        self.wait_finished()
        status = self.controller.snapshot()
        self.assertEqual(status['phase'], 'incomplete')
        self.assertIn('reservation was released', status['message'])
        self.assertIn('no evaluation or improvement is claimed', status['message'])
        result = proctor_campaign.Controller._public_result(self.controller.result)
        self.assertEqual(result['campaign']['outcome'], 'agent-turn-incomplete')
        self.assertEqual(result['campaign']['saved_evaluation_ids'], [])

    def test_public_campaign_keeps_signed_live_observation_separate_from_measurement(self):
        observation = {
            'schema': 'argos-host-observation/1', 'system': 'paired-ssh',
            'verified': True, 'state': 'ready', 'persistence_state': 'verified',
            'paired_policy_valid': True, 'ssh_enabled': True, 'ssh_active': True,
            'port22_listening': True, 'restart_eligible': False,
            'owner_approval_available': False, 'recovery_job_state': 'idle', 'failure_code': None,
        }
        value = {'status': 'incomplete', 'owner_task': 'restore paired SSH',
                 'success_criteria': 'ready without terminal typing',
                 'campaign': {'status': 'incomplete', 'outcome': 'task-not-measured',
                              'audit_status': None, 'controller_turns': 1, 'missing': [],
                              'saved_evaluation_ids': [], 'agent_summary': [],
                              'host_observation': observation}}
        result = proctor_campaign.Controller._public_result(value)
        self.assertEqual(result['campaign']['outcome'], 'task-not-measured')
        self.assertEqual(result['campaign']['host_observation'], observation)
        self.assertNotIn('tool_outcomes', result['campaign'])
        self.assertNotIn('boot_id', result['campaign']['host_observation'])
        self.assertNotIn('receipt_id', result['campaign']['host_observation'])
        self.assertIsNone(proctor_campaign._public_host_observation({**observation, 'boot_id': 'private'}))
        self.assertIsNone(proctor_campaign._public_host_observation({**observation, 'failure_code': {}}))
        app = (Path(__file__).resolve().parents[1] /
               'runtime/argoslive/web/static/app.js').read_text(encoding='utf-8')
        self.assertIn('Verified live host observation:', app)
        self.assertIn('not proof of a recovery action, owner-time savings, or model improvement.', app)

    def test_public_host_observation_accepts_verified_socket_conflict(self):
        observation = {
            'schema': 'argos-host-observation/1', 'system': 'paired-ssh',
            'verified': True, 'state': 'not-ready', 'persistence_state': 'verified',
            'paired_policy_valid': True, 'ssh_enabled': True, 'ssh_active': False,
            'port22_listening': True, 'restart_eligible': True,
            'owner_approval_available': True, 'recovery_job_state': 'idle',
            'failure_code': 'socket-conflict',
        }
        self.assertEqual(proctor_campaign._public_host_observation(observation), observation)

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

    def test_owner_recovery_button_releases_only_the_saved_readonly_incomplete_attempt(self):
        watch_id = 'a' * 32
        self.controller.phase = 'idle'
        self.controller.failure_code = None
        self.controller.failure_stage = None
        self.controller.watch_id = None
        self.controller.record_saved = None
        self.controller.progress = None
        self.controller.result = None
        self.controller.records_root.mkdir(parents=True)
        result_value = {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
            'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                         'saved_evaluation_ids': []}}
        steps = [{'step_id': 'call-inspect', 'tool': 'inspect', 'status': 'completed',
                  'step_status': 'completed'}]
        record = {'schema': 'argos-proctor-watch/1', 'id': watch_id, 'phase': 'incomplete',
                  'failure_code': 'campaign-invalid-state', 'result': result_value,
                  'campaign_steps': steps}
        (self.controller.records_root / f'{watch_id}.json').write_text(json.dumps(record))
        reservation = self.home / '.local/state/argos-live/workload/reservation.json'
        reservation.parent.mkdir(parents=True)
        reservation.write_text(json.dumps({'state': 'quarantined'}))
        with patch.object(proctor_campaign.workload,
                          'recover_owner_approved_readonly_incomplete_controller',
                          return_value={'status': 'recovered'}) as as_recovered:
            state = self.controller.snapshot()
            self.assertTrue(state['can_recover'])
            self.assertEqual(state['recovery_kind'], 'read-only-incomplete-turn')
            self.assertEqual(state['recovery_watch_id'], watch_id)
            self.assertFalse(state['can_start'])
            recovered = self.controller.recover(watch_id)
        self.assertEqual(recovered['recovery_status'], 'read-only-attempt-recovered')
        self.assertIn('no evaluation or score', recovered['message'])
        as_recovered.assert_called_once_with(self.home, record)

    def test_readonly_recovery_watch_accepts_only_completed_inspect_audit_chains(self):
        watch = {'id': 'a' * 32, 'phase': 'incomplete', 'failure_code': 'campaign-invalid-state',
                 'result': {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
                            'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                                         'saved_evaluation_ids': []}},
                 'campaign_steps': [
                     {'step_id': 'call-inspect', 'tool': 'inspect', 'status': 'completed',
                      'step_status': 'completed'},
                     {'step_id': 'call-audit', 'tool': 'audit', 'status': 'completed',
                      'step_status': 'verified', 'passed': True},
                 ]}
        self.assertTrue(proctor_campaign._readonly_incomplete_recovery_watch(watch))
        changed = json.loads(json.dumps(watch))
        changed['campaign_steps'][1]['passed'] = False
        self.assertFalse(proctor_campaign._readonly_incomplete_recovery_watch(changed))
        changed = json.loads(json.dumps(watch))
        changed['campaign_steps'][1].update(tool='evaluation', step_status='completed')
        self.assertFalse(proctor_campaign._readonly_incomplete_recovery_watch(changed))
        changed = json.loads(json.dumps(watch))
        changed['result']['campaign']['saved_evaluation_ids'] = ['f' * 32]
        self.assertFalse(proctor_campaign._readonly_incomplete_recovery_watch(changed))

    def test_dashboard_route_is_token_protected_and_requires_task_json_for_start(self):
        server = DashboardServer(port=0, proctor_campaign=self.controller)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        worker.start()

        def request(path, method='GET', *, token=True, body=None):
            headers = {'X-Argos-Token': server.token} if token else {}
            if method == 'POST' and body is not None:
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
            self.assertEqual(request('/api/proctor-campaign/recover', 'POST',
                                     body=json.dumps({'watch_id': 'a' * 32}))[0], 409)
            invalid_limit = json.dumps({'owner_task': 'recover Argos after reboot',
                                        'success_criteria': 'ready after unlock with no terminal command',
                                        'evaluation_limit': 9})
            self.assertEqual(request('/api/proctor-campaign/start', 'POST', body=invalid_limit)[0], 409)
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
            code, stopped = request('/api/proctor-campaign/stop', 'POST')
            self.assertEqual(code, 200)
            self.assertEqual(stopped['phase'], 'stopping')
            self.assertTrue(self.controller.stop_requested.is_set())
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

    def test_campaign_exception_cause_goes_to_an_owner_only_log(self):
        # November 18, 2026: the cause behind campaign-invalid-state was recorded nowhere.
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            config = home / '.config/argos-live'
            config.mkdir(parents=True)
            (config / 'state.json').write_text('{"model":"qwen-test"}')
            (home / '.local/state/argos-live').mkdir(parents=True)
            error = ValueError('Owned gateway failed to start; inspect private gateway.log')
            with patch.object(proctor_service.startup, 'source', return_value=('target', 'qwen-test')), \
                    patch.object(proctor_service, 'run_campaign', side_effect=error):
                value = proctor_service.run_improvement(home, owner_task='recover Argos after reboot',
                    success_criteria='ready after unlock with no terminal command')
            self.assertEqual(value['failure_code'], 'campaign-invalid-state')
            self.assertNotIn('gateway.log', json.dumps(value))
            entry = proctor_service.record_campaign_failure(home, error)
            self.assertEqual(entry['type'], 'ValueError')
            self.assertIn('Owned gateway failed to start', entry['message'])
            log = home / '.local/state/argos-live/campaign-failure.log'
            if sys.platform == 'linux':  # private_log is Linux-only by design
                rows = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(rows[0]['type'], 'ValueError')
                self.assertIn('Owned gateway failed to start', rows[0]['message'])
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            else:
                self.assertFalse(log.exists())

    def test_failure_log_problems_never_change_the_result(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(proctor_service, 'private_log', side_effect=OSError('read-only')):
                entry = proctor_service.record_campaign_failure(Path(root), KeyError('x'))
            self.assertEqual(entry['type'], 'KeyError')


if __name__ == '__main__':
    unittest.main()
