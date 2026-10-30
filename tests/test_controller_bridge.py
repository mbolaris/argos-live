import json
import os
from pathlib import Path
import sys
import socket
import threading
import time
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import controller_bridge, workload
from argoslive.proctor import ProctorError
from argoslive.results import Store
from test_bench_openclaw import configure_fake


class ControllerBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        configure_fake(self.home, workspace)

    def begin(self, bridge):
        request = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'framework-run',
                   'session_id': 'framework-session', 'session_key': bridge.session_key, 'trigger': 'user'}
        value = bridge.dispatch(request)
        return request, {'auth': bridge.secret, 'run_id': request['run_id'], 'turn_token': value['turn_token']}

    def test_host_identity_and_secret_are_required_before_admission(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            base = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'framework-run',
                    'session_id': 'framework-session', 'session_key': 'agent:main:host-session', 'trigger': 'user'}
            for changes in ({'auth': 'wrong'}, {'session_key': 'agent:main:unrelated'}, {'trigger': 'heartbeat'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    bridge.dispatch({**base, **changes})
            self.assertIsNone(bridge.active)
            self.assertFalse(bridge.events.exists())
            parent.complete()  # No SDK worker or inference was started in this fixture.

    @unittest.skipUnless(sys.platform == 'linux', 'Linux host-owned worker drainage')
    def test_session_bound_incomplete_practice_turn_is_drained_and_retryable(self):
        exam = SimpleNamespace(tier='practice')
        with workload.reserve(self.home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:practice',
                                              exam_session=exam)
            request, _turn = self.begin(bridge)
            bridge.session_id = request['session_id']
            response = {'status': 'error', 'result': {'payloads': [], 'meta': {
                'agentMeta': {'sessionId': bridge.session_id},
                'error': {'kind': 'incomplete_turn', 'message': 'private message is not exported'}}}}
            bridge.worker = SimpleNamespace(returncode=1, pid=2**31 - 1, poll=lambda: 1,
                communicate=lambda timeout: (json.dumps(response), ''))
            result, stderr = bridge.finish(timeout=1, finalize=False)
            self.assertEqual(stderr, '')
            self.assertEqual(result['status'], 'error')
            self.assertTrue(bridge.verified)
            self.assertFalse(bridge.uncertain)
            self.assertEqual(bridge.worker_outcome, 'incomplete-turn')
            worker = json.loads((self.home / '.local/state/argos-live/workload/controller-worker.json').read_text())
            self.assertEqual(worker['turn_outcome'], 'incomplete-turn')
            self.assertEqual(worker['returncode'], 1)
            turn = json.loads(bridge.events.read_text())
            self.assertEqual(turn['worker_turns'], [{
                'turn': 1, 'outcome': 'incomplete-turn', 'returncode': 1,
                'stdout_bytes': len(json.dumps(response).encode()), 'stderr_bytes': 0,
                'process_group_drained': True, 'session_bound': True,
                'host_tool_requests': 0, 'host_tool_failures': 0,
                'response_status': 'error', 'sdk_error_kind': 'incomplete_turn'}])
            self.assertNotIn('private message', bridge.events.read_text())
            bridge.next_practice_turn('agent:main:practice-retry')
            self.assertIsNone(bridge.worker)
            self.assertFalse(bridge.verified)
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux host-owned worker drainage')
    def test_admitted_side_effect_free_hook_block_in_practice_is_drained_and_retryable(self):
        exam = SimpleNamespace(tier='practice')
        with workload.reserve(self.home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:practice-hook-block',
                                              exam_session=exam)
            request, _turn = self.begin(bridge)
            bridge.session_id = request['session_id']
            bridge.active['ended'] = True
            response = {'status': 'error', 'result': {'payloads': [], 'meta': {
                'agentMeta': {'sessionId': bridge.session_id},
                'error': {'kind': 'hook_block', 'message': 'private blocked-tool details'}}}}
            bridge.worker = SimpleNamespace(returncode=1, pid=2**31 - 1, poll=lambda: 1,
                communicate=lambda timeout: (json.dumps(response), ''))
            result, stderr = bridge.finish(timeout=1, finalize=False)
            self.assertEqual(stderr, '')
            self.assertEqual(result['status'], 'error')
            self.assertTrue(bridge.verified)
            self.assertFalse(bridge.uncertain)
            self.assertEqual(bridge.worker_outcome, 'blocked-turn')
            worker = json.loads((self.home / '.local/state/argos-live/workload/controller-worker.json').read_text())
            self.assertEqual(worker['turn_outcome'], 'blocked-turn')
            turn = json.loads(bridge.events.read_text())
            self.assertEqual(turn['worker_turns'], [{
                'turn': 1, 'outcome': 'blocked-turn', 'returncode': 1,
                'stdout_bytes': len(json.dumps(response).encode()), 'stderr_bytes': 0,
                'process_group_drained': True, 'session_bound': True,
                'host_tool_requests': 0, 'host_tool_failures': 0,
                'response_status': 'error', 'sdk_error_kind': 'hook_block'}])
            self.assertNotIn('private blocked-tool details', bridge.events.read_text())
            bridge.next_practice_turn('agent:main:practice-hook-block-retry')
            self.assertIsNone(bridge.worker)
            self.assertFalse(bridge.verified)
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux host-owned worker drainage')
    def test_practice_hook_block_after_host_tool_activity_is_not_retryable(self):
        exam = SimpleNamespace(tier='practice')
        with workload.reserve(self.home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:practice-hook-block-active',
                                              exam_session=exam)
            request, _turn = self.begin(bridge)
            bridge.session_id = request['session_id']
            bridge.active.update(ended=True, host_tool_requests=1)
            response = {'status': 'error', 'result': {'payloads': [], 'meta': {
                'agentMeta': {'sessionId': bridge.session_id},
                'error': {'kind': 'hook_block'}}}}
            bridge.worker = SimpleNamespace(returncode=1, pid=2**31 - 1, poll=lambda: 1,
                communicate=lambda timeout: (json.dumps(response), ''))
            with self.assertRaises(workload.Busy):
                bridge.finish(timeout=1, finalize=False)
            self.assertFalse(bridge.verified)
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux host-owned workload lifecycle')
    def test_prelaunch_gateway_failure_releases_unstarted_proctor_reservation(self):
        with controller_bridge.owned(self.home, session_key='agent:main:prelaunch',
                                     exam_session=object()) as (_bridge, _env):
            pass
        reservation = json.loads((self.home / '.local/state/argos-live/workload/reservation.json').read_text())
        self.assertEqual(reservation['kind'], 'proctor')
        self.assertEqual(reservation['state'], 'released')

    def test_end_hook_and_client_completion_claim_never_release_parent(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            request, turn = self.begin(bridge)
            self.assertEqual(bridge.dispatch(request)['turn_token'], turn['turn_token'])
            diagnostics = {'tool_hooks':14,'bound_calls':14,'executions':14,
                           'rejected':{'unknown_tool':0,'missing_admission':0,
                                       'invalid_call_id':0,'stale_binding':0}}
            bridge.dispatch({**turn, 'op': 'ended', 'diagnostics':diagnostics})
            self.assertEqual(json.loads(bridge.events.read_text())['admission_diagnostics'],diagnostics)
            for claim in ({**turn, 'op': 'complete', 'worker_exited': True},
                          {**request, 'run_id': 'next-run'}):
                with self.assertRaises(ValueError):
                    bridge.dispatch(claim)
            with self.assertRaises(workload.Busy):
                bridge._complete()
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'proctor'):
                    self.fail('SDK end event released the controller slot')
            saved = bridge.events.read_text()
            self.assertNotIn(bridge.secret, saved)
            self.assertNotIn(turn['turn_token'], saved)

    def test_campaign_compare_and_audit_results_are_host_recorded(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent,
                session_key='agent:main:argos_proctor_improvement_test')
            _, turn = self.begin(bridge)
            bridge.run_child = lambda kind, params, **kwargs: {
                'status': 'completed', 'value': {'status': 'empty', 'passed': True}}
            with patch.object(controller_bridge, 'Store') as store_type, \
                 patch.object(controller_bridge, 'compare', return_value={'delta': 0}):
                store_type.return_value.load.side_effect = [
                    {'id': 'base-run'}, {'id': 'candidate-run'}]
                compared = bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'compare-1',
                    'kind': 'compare', 'params': {'baseline_id': 'base-run',
                                                  'candidate_id': 'candidate-run'}})
                audited = bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'audit-1',
                    'kind': 'audit', 'params': {}})
            self.assertEqual(compared['value'], {'delta': 0})
            self.assertTrue(audited['value']['passed'])
            self.assertEqual(bridge.outcomes[-2], {'kind': 'compare', 'call_id': 'compare-1',
                'baseline_id': 'base-run', 'candidate_id': 'candidate-run'})
            self.assertEqual(bridge.outcomes[-1], {'kind': 'audit', 'call_id': 'audit-1',
                'status': 'empty', 'passed': True})
            parent.complete()

    def test_compare_rejection_returns_actionable_value_without_quarantining(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent,
                session_key='agent:main:argos_proctor_improvement_test')
            _, turn = self.begin(bridge)
            runs = [
                {'id': 'a' * 32, 'kind': 'ability', 'suite_version': 'suite/quick/1',
                 'settings': {'execution_path': 'openclaw embedded; ephemeral state; tools denied; v2'},
                 'items': [], 'coverage': {'complete': True}, 'restoration': {'succeeded': True}},
                {'id': 'b' * 32, 'kind': 'ability', 'suite_version': 'suite/tool-plan/1',
                 'settings': {'execution_path': 'openclaw embedded; ephemeral state; tools denied; v2'},
                 'items': [], 'coverage': {'complete': True}, 'restoration': {'succeeded': True}},
            ]
            with patch.object(controller_bridge, 'Store') as store_type, \
                 patch.object(controller_bridge, 'compare', side_effect=ValueError(
                     'Comparison requires the same benchmark kind, suite version and non-model settings')):
                store_type.return_value.load.side_effect = runs
                rejected = bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'compare-rejected',
                    'kind': 'compare', 'params': {'baseline_id': runs[0]['id'],
                                                  'candidate_id': runs[1]['id']}})
            self.assertEqual(rejected['status'], 'completed')
            self.assertEqual(rejected['value']['status'], 'rejected')
            self.assertFalse(rejected['value']['pair_checks']['same_suite_version'])
            self.assertEqual(bridge.outcomes[-1], {'kind': 'compare_rejected',
                'call_id': 'compare-rejected', 'baseline_id': runs[0]['id'],
                'candidate_id': runs[1]['id'], 'error_code': 'suite_or_settings_mismatch'})
            parent.complete()

    def test_host_campaign_turn_transition_keeps_the_same_reservation(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent,
                session_key='agent:main:argos_proctor_improvement_test')
            bridge.worker = SimpleNamespace(poll=lambda: 0)
            bridge.active = {'ended': True}
            bridge.verified = True
            with self.assertRaisesRegex(ValueError, 'Only the host-owned Proctor campaign'):
                bridge.next_campaign_turn('agent:main:unrelated')
            bridge.next_campaign_turn('agent:main:argos_proctor_improvement_followup_2')
            self.assertEqual(bridge.session_key, 'agent:main:argos_proctor_improvement_followup_2')
            self.assertIsNone(bridge.worker)
            self.assertIsNone(bridge.active)
            self.assertFalse(bridge.verified)
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()

    def test_host_campaign_completion_releases_only_a_verified_drained_turn(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent,
                session_key='agent:main:argos_proctor_improvement_followup_2')
            bridge.worker = SimpleNamespace(poll=lambda: 0)
            bridge.active = {'ended': True}
            bridge.verified = True
            bridge.complete_campaign()
            self.assertTrue(bridge.closed)
            self.assertTrue(parent.drained)

    def test_stale_turn_and_unknown_tools_cannot_dispatch(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            tool = {**turn, 'op': 'tool', 'call_id': 'call-1', 'kind': 'log', 'params': {'text': 'note'}}
            with self.assertRaises(workload.Busy):
                bridge.dispatch({**tool, 'turn_token': 'wrong'})
            with self.assertRaises(ValueError):
                bridge.dispatch({**tool, 'kind': 'exec', 'params': {'command': 'anything'}})
            self.assertEqual(bridge.active['host_tool_requests'],2)
            self.assertEqual(bridge.active['host_tool_failures'],[
                {'kind':'log','error_class':'Busy'}, {'kind':'other','error_class':'ValueError'}])
            self.assertFalse((self.home / '.openclaw/workspace/IMPROVEMENT-LOG.md').exists())

    def test_proctor_failures_record_only_allowlisted_error_codes(self):
        class Exam:
            errors = [ProctorError(422, 'INVALID_ANSWER_FORMAT'),
                      ProctorError(422, 'private raw error text')]
            def status(self):
                raise self.errors.pop(0)

        with workload.reserve(self.home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(self.home, parent,
                session_key='agent:main:host-session', exam_session=Exam())
            request, turn = self.begin(bridge)
            for call_id in ('format-error', 'untrusted-code'):
                with self.assertRaises(ProctorError):
                    bridge.dispatch({**turn, 'op': 'tool', 'call_id': call_id,
                        'kind': 'proctor_status', 'params': {}})
            self.assertEqual(bridge.active['host_tool_failures'], [
                {'kind': 'proctor_status', 'error_class': 'ProctorError',
                 'error_code': 'INVALID_ANSWER_FORMAT'},
                {'kind': 'proctor_status', 'error_class': 'ProctorError'}])
            self.assertNotIn('private raw error text', bridge.events.read_text())
            parent.complete()

    def test_proctor_wait_tool_is_observed_and_simulated_without_running_evaluation(self):
        class Exam:
            tier = 'practice'
            def __init__(self):
                self.engine = SimpleNamespace(cart=SimpleNamespace(items={
                    'q5': {'domain': 'tool_call_format'}}))
                self.calls = []
            def status(self):
                return {'state': 'ACTIVE', 'module_id': 'm1', 'item_ids': ['q5'],
                        'answer_revisions': {}}
            def host_record_tool_call(self, item_id, name, arguments, call_id):
                self.calls.append((item_id, name, arguments, call_id))
            def answer(self, *_args, **_kwargs):
                self.fail('Tool-call items cannot receive credit from typed answers')

        with workload.reserve(self.home, 'proctor') as parent:
            exam = Exam()
            bridge = controller_bridge.Bridge(self.home, parent,
                session_key='agent:main:proctor-tool-call-test', exam_session=exam)
            _, turn = self.begin(bridge)
            bridge.presented_proctor_items.add(('m1', 'q5'))
            with self.assertRaisesRegex(ValueError, 'must be completed through its observed tool call'):
                bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'typed-answer-bypass',
                    'kind': 'proctor_answer', 'params': {'item_id': 'q5',
                    'answer': '{"name":"argos_evaluate_wait","arguments":{"job_id":"0123456789abcdef0123456789abcdef"}}'}})
            bridge.wait_evaluation = lambda *_args, **_kwargs: self.fail(
                'Proctor simulation must not wait on or resume a real evaluation')
            with self.assertRaisesRegex(ValueError, 'Invalid evaluation job identity'):
                bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'invalid-wait-call',
                    'kind': 'evaluation_wait', 'params': {'job_id': 'not-a-job'}})
            result = bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'wait-call-1',
                'kind': 'evaluation_wait',
                'params': {'job_id': '0123456789abcdef0123456789abcdef'}})
            self.assertEqual(result['status'], 'completed')
            self.assertTrue(result['value']['proctor_simulation'])
            self.assertIn('no evaluation was started', result['value']['message'])
            self.assertEqual(exam.calls, [('q5', 'argos_evaluate_wait',
                {'job_id': '0123456789abcdef0123456789abcdef'}, 'wait-call-1')])
            self.assertEqual(bridge.outcomes[-1]['kind'], 'proctor_tool_call')
            self.assertIsNone(bridge.evaluation_job)
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_audit_tool_uses_scoped_maintenance_and_preserves_parent_and_instructions(self):
        instructions = self.home / '.openclaw/workspace/AGENTS.md'
        instructions.write_text('Owner instructions remain intact.\n', encoding='utf-8')
        before = instructions.read_bytes()
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            value = bridge.dispatch({**turn, 'op': 'tool', 'call_id': 'audit-empty-journal',
                                     'kind': 'audit', 'params': {}})
            self.assertEqual(value['value']['schema'], 'argos-instruction-audit/1')
            self.assertEqual(value['value']['status'], 'empty')
            self.assertTrue(value['value']['passed'])
            self.assertFalse(value['value']['independent_gain_verified'])
            self.assertEqual(instructions.read_bytes(), before)
            self.assertEqual(parent.record['phase'], 'running')
            self.assertIsNone(bridge.pending)
            self.assertFalse(bridge.uncertain)
            self.assertEqual(bridge.outcomes[-1]['kind'], 'audit')
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'evaluation'):
                    self.fail('Read-only audit released the parent reservation')
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_log_worker_is_one_use_and_cannot_release_controller(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            tool = {**turn, 'op': 'tool', 'call_id': 'call-1', 'kind': 'log', 'params': {'text': '--literal note'}}
            value = bridge.dispatch(tool)
            self.assertEqual(value['value']['status'], 'appended')
            with self.assertRaises(ValueError):
                bridge.dispatch(tool)
            self.assertEqual(parent.record['phase'], 'running')
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'proctor'):
                    self.fail('Tool completion released the parent')
            self.assertNotIn(bridge.secret, json.dumps(value))
            self.assertIsNone(bridge.pending)

    def test_host_records_only_validated_run_ids_from_appended_log_receipts(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            tool = {**turn, 'op': 'tool', 'call_id': 'receipt-log', 'kind': 'log',
                    'params': {'text': 'Saved baseline and next step.'}}
            run_id = 'a' * 32
            saved = {'id': run_id, 'created': '2026-10-29T00:00:00+00:00', 'model': 'provider/model',
                     'suite': 'openclaw-quick', 'state': 'completed', 'summary': {'correct': 20, 'total': 20}}
            valid_receipt = {key: saved.get(key) for key in
                             ('id', 'created', 'model', 'suite', 'state', 'summary')}
            nonexistent_receipt = {**valid_receipt, 'id': 'b' * 32}
            appended = {'status': 'completed', 'value': {'status': 'appended', 'receipts': [
                valid_receipt, nonexistent_receipt, {'id': 'not-a-run-id'}, None]}}

            def load_saved(run_id):
                if run_id == saved['id']:
                    return saved
                raise ValueError('Benchmark run not found')

            with patch.object(bridge, 'run_child', return_value=appended), \
                 patch.object(controller_bridge.Store, 'load', side_effect=load_saved):
                bridge.dispatch(tool)
            self.assertEqual(bridge.outcomes[-1]['logged_result_ids'], [run_id])
            parent.complete()

    def test_drained_log_failure_is_completed_without_claiming_append(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            tool = {**turn, 'op': 'tool', 'call_id': 'failed-log', 'kind': 'log',
                    'params': {'text': 'A log attempt with an unavailable receipt.'}}
            failed = {'status': 'completed', 'value': {'status': 'failed',
                      'message': 'Campaign log entry failed; the host workload remains available.',
                      'append_outcome': 'unconfirmed'}}
            with patch.object(bridge, 'run_child', return_value=failed):
                value = bridge.dispatch(tool)
            self.assertEqual(value, failed)
            self.assertEqual(bridge.outcomes[-1]['status'], 'failed')
            self.assertFalse(bridge.outcomes[-1]['appended'])
            self.assertEqual(bridge.outcomes[-1]['append_outcome'], 'unconfirmed')
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_failed_log_worker_resumes_only_after_its_child_is_released(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            missing_run_id = 'a' * 32
            tool = {**turn, 'op': 'tool', 'call_id': 'invalid-log', 'kind': 'log',
                    'params': {'text': f'Attempted run {missing_run_id}.'}}

            value = bridge.dispatch(tool)

            self.assertEqual(value['status'], 'completed')
            self.assertEqual(value['value']['status'], 'failed')
            self.assertEqual(value['value']['append_outcome'], 'unconfirmed')
            self.assertFalse(bridge.uncertain)
            self.assertEqual(parent.record['phase'], 'running')
            self.assertIsNone(parent.record.get('child_id'))
            self.assertIsNone(bridge.pending)
            self.assertFalse((self.home / '.openclaw/workspace/IMPROVEMENT-LOG.md').exists())
            self.assertEqual(bridge.outcomes[-1]['status'], 'failed')
            self.assertFalse(bridge.outcomes[-1]['appended'])
            self.assertEqual(bridge.outcomes[-1]['append_outcome'], 'unconfirmed')

            valid = {**turn, 'op': 'tool', 'call_id': 'valid-log', 'kind': 'log',
                     'params': {'text': 'A drained failed log attempt was safely reported.'}}
            self.assertEqual(bridge.dispatch(valid)['value']['status'], 'appended')
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_disconnected_evaluation_saves_during_aborted_host_scope_without_releasing_admission(self):
        binary = self.home / 'bin'
        binary.mkdir()
        gate = self.home / 'allow-evaluation'
        executable = binary / 'openclaw'
        executable.write_text('#!/usr/bin/env python3\nimport json,sys,time\nfrom pathlib import Path\n'
            f'gate=Path({str(gate)!r})\n'
            'deadline=time.monotonic()+10\n'
            'while not gate.exists() and time.monotonic()<deadline: time.sleep(.01)\n'
            'assert gate.exists()\n'
            'session=sys.argv[sys.argv.index("--session-id")+1]\n'
            'print(json.dumps({"payloads":[{"text":"synthetic answer"}],"meta":{"agentMeta":{'
            '"sessionId":session,"provider":"ollama","model":"qwen3:4b-instruct-2507-q4_K_M"}}}))\n')
        executable.chmod(0o700)
        failures = []
        releaser = None
        original_wait = controller_bridge.Bridge.wait_evaluation

        def short_wait(bridge, job_id, **kwargs):
            kwargs['seconds'] = .01
            return original_wait(bridge, job_id, **kwargs)

        try:
            with self.assertRaisesRegex(RuntimeError, 'agent turn aborted'), \
                 patch.object(controller_bridge.Bridge, 'wait_evaluation', short_wait):
                with controller_bridge.owned(self.home, session_key='agent:main:host-session',
                                             worker_timeout=15) as (bridge, env):
                    bridge.worker_path = str(binary) + os.pathsep + bridge.worker_path
                    _, turn = self.begin(bridge)
                    tool = {**turn, 'op': 'tool', 'call_id': 'eval-disconnected',
                            'kind': 'evaluation', 'params': {'suite': 'quick'}}
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(10)
                        client.connect(env['ARGOS_CONTROLLER_SOCKET'])
                        client.sendall((json.dumps(tool) + '\n').encode())
                        with client.makefile('rb') as reader:
                            response = json.loads(reader.readline())
                            while response['status'] == 'progress':
                                response = json.loads(reader.readline())
                            self.assertEqual(response['status'], 'running')
                        client.shutdown(socket.SHUT_RDWR)
                    deadline = time.monotonic() + 2
                    while bridge.tool_lock.locked() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertFalse(bridge.tool_lock.locked(), 'Short caller wait did not return')
                    self.assertTrue(bridge.evaluation_job['thread'].is_alive())
                    with self.assertRaises(workload.Busy):
                        bridge.dispatch({**tool, 'call_id': 'competing-evaluation'})

                    def release_after_teardown_begins():
                        try:
                            deadline = time.monotonic() + 5
                            while not bridge.closed and time.monotonic() < deadline:
                                time.sleep(.01)
                            self.assertTrue(bridge.closed)
                            time.sleep(.15)
                            self.assertIsNotNone(bridge.pending)
                            self.assertIsNone(bridge.pending.poll(), 'Teardown killed admitted evaluation')
                            with self.assertRaises(workload.Busy):
                                with workload.reserve(self.home, 'evaluation'):
                                    self.fail('Host released admission before saved result')
                        except BaseException as error:
                            failures.append(error)
                        finally:
                            gate.write_text('continue')
                    releaser = threading.Thread(target=release_after_teardown_begins)
                    releaser.start()
                    raise RuntimeError('agent turn aborted')
        finally:
            gate.touch()
            if releaser:
                releaser.join(timeout=10)
                self.assertFalse(releaser.is_alive())
        if failures:
            raise failures[0]
        store = Store(self.home / '.local/share/argos-live/results')
        listing = store.list()
        self.assertEqual(listing['rejected'], [])
        rows = listing['runs']
        self.assertEqual(len(rows), 1)
        saved = store.load(rows[0]['id'])
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(saved['coverage']['completed'], 20)
        self.assertEqual(bridge.outcomes[0]['result_id'], saved['id'])
        self.assertIsNone(bridge.pending)
        with self.assertRaises(workload.Busy) as caught:
            with workload.reserve(self.home, 'evaluation'):
                self.fail('Aborted controller quarantine was released')
        self.assertTrue(caught.exception.recovery)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_evaluation_progress_crosses_host_bridge_before_saved_result(self):
        binary = self.home / 'bin'
        binary.mkdir()
        executable = binary / 'openclaw'
        executable.write_text('#!/usr/bin/env python3\nimport json,sys\n'
            'session=sys.argv[sys.argv.index("--session-id")+1]\n'
            'print(json.dumps({"payloads":[{"text":"synthetic answer"}],"meta":{"agentMeta":{'
            '"sessionId":session,"provider":"ollama","model":"qwen3:4b-instruct-2507-q4_K_M"}}}))\n')
        executable.chmod(0o700)
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            bridge.worker_path = str(binary) + os.pathsep + bridge.worker_path
            _, turn = self.begin(bridge)
            updates = []
            tool = {**turn, 'op': 'tool', 'call_id': 'eval-call', 'kind': 'evaluation',
                    'params': {'suite': 'challenge'}}
            value = bridge.dispatch(tool, on_update=updates.append)
            self.assertEqual(value['status'], 'completed')
            self.assertEqual(value['value']['result']['state'], 'completed')
            self.assertTrue(updates)
            self.assertEqual(updates[0]['phase'], 'asking')
            self.assertEqual(updates[-1]['phase'], 'scored')
            self.assertEqual(value['value']['result']['suite'], 'openclaw-challenge')
            self.assertEqual(value['value']['result']['coverage']['completed'], 40)
            self.assertEqual(value['value']['result']['coverage']['total'], 40)
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_schema_grounded_suite_is_admitted_by_host_controller(self):
        binary = self.home / 'bin'
        binary.mkdir()
        executable = binary / 'openclaw'
        executable.write_text('#!/usr/bin/env python3\nimport json,sys\n'
            'session=sys.argv[sys.argv.index("--session-id")+1]\n'
            'print(json.dumps({"payloads":[{"text":"{}"}],"meta":{"agentMeta":{'
            '"sessionId":session,"provider":"ollama","model":"qwen3:4b-instruct-2507-q4_K_M"}}}))\n')
        executable.chmod(0o700)
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            bridge.worker_path = str(binary) + os.pathsep + bridge.worker_path
            _, turn = self.begin(bridge)
            request = {**turn, 'op': 'tool', 'call_id': 'schema-eval', 'kind': 'evaluation',
                       'params': {'suite': 'tool-schema'}}
            value = bridge.dispatch(request)
            self.assertEqual(value['status'], 'completed')
            result = value['value']['result']
            self.assertEqual(result['suite'], 'openclaw-tool-schema')
            self.assertEqual(result['coverage'], {'completed': 40, 'total': 40, 'complete': True})
            self.assertEqual(result['summary']['partitions']['practice']['total'], 20)
            self.assertEqual(result['summary']['partitions']['heldout']['total'], 20)
            parent.complete()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_multiconstraint_tool_plan_is_admitted_by_host_controller(self):
        binary = self.home / 'bin'
        binary.mkdir()
        executable = binary / 'openclaw'
        executable.write_text('#!/usr/bin/env python3\nimport json,sys\n'
            'session=sys.argv[sys.argv.index("--session-id")+1]\n'
            'print(json.dumps({"payloads":[{"text":"{}"}],"meta":{"agentMeta":{'
            '"sessionId":session,"provider":"ollama","model":"qwen3:4b-instruct-2507-q4_K_M"}}}))\n')
        executable.chmod(0o700)
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            bridge.worker_path = str(binary) + os.pathsep + bridge.worker_path
            _, turn = self.begin(bridge)
            request = {**turn, 'op': 'tool', 'call_id': 'plan-eval', 'kind': 'evaluation',
                       'params': {'suite': 'tool-plan'}}
            value = bridge.dispatch(request)
            self.assertEqual(value['status'], 'completed')
            result = value['value']['result']
            self.assertEqual(result['suite'], 'openclaw-tool-plan')
            self.assertEqual(result['coverage'], {'completed': 40, 'total': 40, 'complete': True})
            self.assertEqual(result['summary']['partitions']['practice']['total'], 20)
            self.assertEqual(result['summary']['partitions']['heldout']['total'], 20)
            parent.complete()

    def test_bounded_evaluation_wait_keeps_host_job_for_followup_after_turn_ends(self):
        started = threading.Event()
        release = threading.Event()
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')

            def slow_child(kind, params, *, on_update=None):
                self.assertEqual(kind, 'evaluation')
                started.set()
                release.wait(5)
                return {'status':'completed', 'value':{'result':{
                    'id':'a' * 32, 'state':'completed', 'suite':'openclaw-standard',
                    'suite_version':'argos-openclaw-ability/standard/test-version',
                    'coverage':{'completed':70,'total':70,'complete':True},
                    'summary':{'correct':70,'total':70,'format_errors':0}},
                    'path':'saved-result.json'}}

            bridge.run_child = slow_child
            value = bridge.start_evaluation({'suite':'standard'}, seconds=.01)
            self.assertEqual(value['status'], 'running')
            self.assertEqual(value['total'], 70)
            self.assertTrue(started.wait(1))
            _, turn = self.begin(bridge)
            status = bridge.dispatch({**turn, 'op':'tool', 'call_id':'recover-eval-job',
                'kind':'evaluation_status', 'params':{}})
            self.assertEqual(status['status'], 'running')
            self.assertEqual(status['job_id'], value['job_id'])
            with self.assertRaises(workload.Busy):
                bridge.start_evaluation({'suite':'quick'}, seconds=.01)
            # The caller can disappear here; the host worker still owns the slot.
            release.set()
            finished = bridge.wait_evaluation(value['job_id'], seconds=2)
            self.assertEqual(finished['result']['coverage']['completed'], 70)
            self.assertEqual(bridge.outcomes[0]['result_id'], 'a' * 32)
            self.assertEqual(bridge.outcomes[0]['suite'], 'openclaw-standard')
            self.assertTrue(bridge.outcomes[0]['coverage_complete'])
            self.assertEqual(bridge.outcomes[0]['correct'], 70)
            parent.complete()


if __name__ == '__main__':
    unittest.main()
