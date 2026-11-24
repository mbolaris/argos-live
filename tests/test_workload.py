import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import signal
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_openclaw, workload
from test_bench_openclaw import FakeOpenClaw, configure_fake


class WorkloadTests(unittest.TestCase):
    def test_owner_approved_drained_readonly_incomplete_controller_recovers_same_boot(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            boot_id, parent_id, generation = '11111111-1111-4111-8111-111111111111', 'a' * 32, 9
            owner_pid, worker_pid, watch_id = 12345, 2_000_000_000, 'b' * 32
            root = home / '.local/state/argos-live/workload'
            (root / 'child').mkdir(parents=True)
            identity = {'boot_id': boot_id, 'start_ticks': '10'}
            reservation = {'schema': 'argos-workload/1', 'id': parent_id, 'generation': generation,
                           'kind': 'controller', 'pid': owner_pid, 'worker_identity': identity,
                           'state': 'quarantined', 'phase': 'running'}
            session_id, session_key = 'session-9', 'agent:main:argos_proctor_improvement_x'
            worker = {'parent_id': parent_id, 'generation': generation, 'state': 'starting', 'pid': worker_pid,
                      'session_id': session_id, 'session_key': session_key}
            failure = {'parent_id': parent_id, 'generation': generation, 'worker_pid': worker_pid,
                       'session_id': session_id,
                       'failure': {'code': 'worker-exit', 'returncode': 1,
                                   'worker_response': {'status': 'error', 'session_bound': True,
                                                       'error_kind': 'incomplete_turn'}}}
            turn = {'parent_id': parent_id, 'generation': generation, 'ended': True, 'uncertain': False,
                    'session_id': session_id, 'session_key': session_key,
                    'worker_turns': [], 'host_tool_failures': [], 'host_tool_requests': 1,
                    'tools': [{'call_id': 'call-inspect', 'kind': 'inspect'}]}
            child = {'parent_id': parent_id, 'generation': generation, 'state': 'released'}
            for name, value in (('reservation.json', reservation), ('controller-worker.json', worker),
                                ('controller-failure.json', failure), ('controller-turn.json', turn),
                                ('child/' + 'c' * 32 + '.json', child)):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            watch = {'id': watch_id, 'phase': 'incomplete', 'failure_code': 'campaign-invalid-state',
                     'result': {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
                                'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                                             'saved_evaluation_ids': []}},
                     'campaign_steps': [{'step_id': 'call-inspect', 'tool': 'inspect',
                                         'status': 'completed', 'step_status': 'completed'}]}
            with patch.object(workload.sys, 'platform', 'linux'), \
                    patch.object(workload, 'current_boot_id', return_value=boot_id), \
                    patch.object(workload, 'worker_identity', return_value=identity), \
                    patch.object(workload, '_process_group_drained', return_value=True):
                outcome = workload.recover_owner_approved_readonly_incomplete_controller(
                    home, watch, owner_pid=owner_pid)
            self.assertEqual(outcome, {'status': 'recovered', 'reason': 'drained-readonly-incomplete-turn',
                                       'watch_id': watch_id})
            current = json.loads((root / 'reservation.json').read_text())
            self.assertEqual(current['state'], 'released')
            self.assertEqual(current['phase'], 'recovered-owner-approved-readonly-incomplete')
            receipts = list((root / 'recovered').glob('*.json'))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text())
            self.assertEqual(receipt['schema'], 'argos-workload-recovery/3')
            self.assertEqual(receipt['reason'], 'owner-approved-drained-readonly-incomplete-turn')

    def test_owner_approved_drained_readonly_inspect_audit_chain_recovers_same_boot(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            boot_id, parent_id, generation = '11111111-1111-4111-8111-111111111111', 'a' * 32, 10
            owner_pid, worker_pid, watch_id = 12345, 2_000_000_000, 'c' * 32
            root = home / '.local/state/argos-live/workload'
            (root / 'child').mkdir(parents=True)
            identity = {'boot_id': boot_id, 'start_ticks': '10'}
            reservation = {'schema': 'argos-workload/1', 'id': parent_id, 'generation': generation,
                           'kind': 'controller', 'pid': owner_pid, 'worker_identity': identity,
                           'state': 'quarantined', 'phase': 'running'}
            session_id, session_key = 'session-10', 'agent:main:argos_proctor_improvement_chain'
            worker = {'parent_id': parent_id, 'generation': generation, 'state': 'starting', 'pid': worker_pid,
                      'session_id': session_id, 'session_key': session_key}
            failure = {'parent_id': parent_id, 'generation': generation, 'worker_pid': worker_pid,
                       'session_id': session_id,
                       'failure': {'code': 'worker-exit', 'returncode': 1,
                                   'worker_response': {'status': 'error', 'session_bound': True,
                                                       'error_kind': 'incomplete_turn'}}}
            ids = ['call-inspect-1', 'call-audit-1', 'call-inspect-2', 'call-audit-2']
            kinds = ['inspect', 'audit', 'inspect', 'audit']
            turn = {'parent_id': parent_id, 'generation': generation, 'ended': True, 'uncertain': False,
                    'session_id': session_id, 'session_key': session_key,
                    'worker_turns': [{'turn': 1, 'outcome': 'completed', 'response_status': 'ok',
                                      'process_group_drained': True, 'session_bound': True,
                                      'host_tool_failures': 0, 'host_tool_requests': 2, 'returncode': 0}],
                    'host_tool_failures': [], 'host_tool_requests': 3,
                    'tools': [{'call_id': call_id, 'kind': kind} for call_id, kind in zip(ids, kinds)]}
            child = {'parent_id': parent_id, 'generation': generation, 'state': 'released'}
            for name, value in (('reservation.json', reservation), ('controller-worker.json', worker),
                                ('controller-failure.json', failure), ('controller-turn.json', turn),
                                ('child/' + 'd' * 32 + '.json', child)):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            steps = [
                {'step_id': ids[0], 'tool': 'inspect', 'status': 'completed', 'step_status': 'completed'},
                {'step_id': ids[1], 'tool': 'audit', 'status': 'completed', 'step_status': 'verified',
                 'passed': True},
                {'step_id': ids[2], 'tool': 'inspect', 'status': 'completed', 'step_status': 'completed'},
                {'step_id': ids[3], 'tool': 'audit', 'status': 'completed', 'step_status': 'verified',
                 'passed': True},
            ]
            watch = {'id': watch_id, 'phase': 'incomplete', 'failure_code': 'campaign-invalid-state',
                     'result': {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
                                'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                                             'saved_evaluation_ids': []}},
                     'campaign_steps': steps}
            with patch.object(workload.sys, 'platform', 'linux'), \
                    patch.object(workload, 'current_boot_id', return_value=boot_id), \
                    patch.object(workload, 'worker_identity', return_value=identity), \
                    patch.object(workload, '_process_group_drained', return_value=True):
                outcome = workload.recover_owner_approved_readonly_incomplete_controller(
                    home, watch, owner_pid=owner_pid)
            self.assertEqual(outcome, {'status': 'recovered',
                                       'reason': 'drained-readonly-chain-incomplete-turn',
                                       'watch_id': watch_id})
            current = json.loads((root / 'reservation.json').read_text())
            self.assertEqual(current['state'], 'released')
            self.assertEqual(current['phase'], 'recovered-owner-approved-readonly-chain-incomplete')
            receipt = json.loads((root / 'recovered' / f'{generation}-{parent_id}.json').read_text())
            self.assertEqual(receipt['schema'], 'argos-workload-recovery/4')
            self.assertEqual(receipt['reason'], 'owner-approved-drained-readonly-chain-incomplete-turn')

    def test_owner_approved_readonly_chain_recovery_rejects_evaluation_or_unverified_audit(self):
        watch = {'id': 'c' * 32, 'phase': 'incomplete', 'failure_code': 'campaign-invalid-state',
                 'result': {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
                            'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                                         'saved_evaluation_ids': []}},
                 'campaign_steps': [
                     {'step_id': 'call-inspect', 'tool': 'inspect', 'status': 'completed',
                      'step_status': 'completed'},
                     {'step_id': 'call-audit', 'tool': 'audit', 'status': 'completed',
                      'step_status': 'verified', 'passed': True},
                 ]}
        for changed in ('evaluation', 'unverified-audit'):
            with self.subTest(changed=changed):
                candidate = json.loads(json.dumps(watch))
                if changed == 'evaluation':
                    candidate['campaign_steps'][1].update(tool='evaluation', step_status='completed')
                else:
                    candidate['campaign_steps'][1]['passed'] = False
                with self.assertRaises(workload.Busy):
                    workload.recover_owner_approved_readonly_incomplete_controller(
                        Path.cwd(), candidate, owner_pid=12345)

    def test_owner_approved_incomplete_controller_recovery_fails_closed_on_mutation_or_bad_exit(self):
        base_watch = {'id': 'b' * 32, 'phase': 'incomplete', 'failure_code': 'campaign-invalid-state',
                      'result': {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
                                 'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                                              'saved_evaluation_ids': []}},
                      'campaign_steps': [{'step_id': 'call-inspect', 'tool': 'inspect',
                                          'status': 'completed', 'step_status': 'completed'}]}
        for mutation in ('evaluation', 'edit', 'bad-status'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                boot_id, parent_id, generation = '11111111-1111-4111-8111-111111111111', 'a' * 32, 9
                owner_pid, worker_pid = 12345, 2_000_000_000
                root = home / '.local/state/argos-live/workload'
                (root / 'child').mkdir(parents=True)
                identity = {'boot_id': boot_id, 'start_ticks': '10'}
                files = {
                    'reservation.json': {'id': parent_id, 'generation': generation, 'kind': 'controller',
                                         'pid': owner_pid, 'worker_identity': identity,
                                         'state': 'quarantined', 'phase': 'running'},
                    'controller-worker.json': {'parent_id': parent_id, 'generation': generation,
                        'state': 'starting', 'pid': worker_pid, 'session_id': 'session-9',
                        'session_key': 'agent:main:argos_proctor_improvement_x'},
                    'controller-failure.json': {'parent_id': parent_id, 'generation': generation,
                        'worker_pid': worker_pid, 'session_id': 'session-9',
                        'failure': {'code': 'worker-exit',
                        'returncode': 0 if mutation == 'bad-status' else 1,
                        'worker_response': {'status': 'error', 'session_bound': True,
                                            'error_kind': 'incomplete_turn'}}},
                    'controller-turn.json': {'parent_id': parent_id, 'generation': generation,
                        'ended': True, 'uncertain': False, 'session_id': 'session-9',
                        'session_key': 'agent:main:argos_proctor_improvement_x',
                        'host_tool_requests': 1, 'worker_turns': [], 'host_tool_failures': [],
                        'tools': [{'call_id': 'call-inspect', 'kind': 'inspect'}]},
                }
                if mutation in {'evaluation', 'edit'}:
                    base_watch['campaign_steps'] = [{'step_id': 'call-inspect', 'tool': mutation,
                                                     'status': 'completed', 'step_status': 'completed'}]
                for name, value in files.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(value))
                with patch.object(workload.sys, 'platform', 'linux'), \
                        patch.object(workload, 'current_boot_id', return_value=boot_id), \
                        patch.object(workload, 'worker_identity', return_value=identity), \
                        patch.object(workload, '_process_group_drained', return_value=True):
                    with self.assertRaises(workload.Busy):
                        workload.recover_owner_approved_readonly_incomplete_controller(
                            home, base_watch, owner_pid=owner_pid)
                self.assertEqual(json.loads((root / 'reservation.json').read_text())['state'], 'quarantined')
                self.assertFalse((root / 'recovered').exists())
                if mutation in {'evaluation', 'edit'}:
                    base_watch['campaign_steps'] = [{'step_id': 'call-inspect', 'tool': 'inspect',
                                                     'status': 'completed', 'step_status': 'completed'}]

    # A drained campaign whose evaluation calls the host refused while
    # validating them (as when the installed plugin lacked the owner's suite),
    # followed by a completed campaign-log note and an incomplete final turn.
    REFUSED_BOOT = '11111111-1111-4111-8111-111111111111'
    REFUSED_IDENTITY = {'boot_id': REFUSED_BOOT, 'start_ticks': '10'}

    def _write_refused_evaluation_quarantine(self, home, *, refusal_code=None, log=True, mutate=None):
        parent_id, generation = 'a' * 32, 12
        owner_pid, worker_pid, watch_id = 12345, 2_000_000_000, 'e' * 32
        root = home / '.local/state/argos-live/workload'
        (root / 'child').mkdir(parents=True)
        session_id, session_key = 'session-12', 'agent:main:argos_proctor_improvement_docs'
        ledger = [('call-inspect', 'inspect'), ('call-audit', 'audit')]
        if log:
            ledger.append(('call-log', 'log'))
        refused_ids = ['call-eval-1', 'call-eval-2']
        failure_entry = {'kind': 'evaluation', 'error_class': 'ValueError'}
        refused_step = {'tool': 'evaluation', 'status': 'failed', 'error_class': 'ValueError'}
        if refusal_code is not None:
            failure_entry.update(refusal_code=refusal_code, requested_suite='omitted',
                                 owner_suite='documents-long')
            refused_step.update(refusal_code=refusal_code, requested_suite='omitted',
                                owner_suite='documents-long')
        tools = [{'call_id': call_id, 'kind': kind} for call_id, kind in ledger]
        for tool in tools:
            if tool['kind'] == 'log':
                tool.update(status='appended', appended=True, logged_result_ids=[])
            if tool['kind'] == 'audit':
                tool.update(status='verified', passed=True)
        files = {
            'reservation.json': {'schema': 'argos-workload/1', 'id': parent_id, 'generation': generation,
                                 'kind': 'controller', 'pid': owner_pid,
                                 'worker_identity': self.REFUSED_IDENTITY,
                                 'state': 'quarantined', 'phase': 'running'},
            'controller-worker.json': {'parent_id': parent_id, 'generation': generation, 'state': 'starting',
                                       'pid': worker_pid, 'session_id': session_id,
                                       'session_key': session_key},
            'controller-failure.json': {'parent_id': parent_id, 'generation': generation,
                                        'worker_pid': worker_pid, 'session_id': session_id,
                                        'failure': {'code': 'worker-exit', 'returncode': 1,
                                                    'worker_response': {'status': 'error',
                                                                        'session_bound': True,
                                                                        'error_kind': 'incomplete_turn'}}},
            'controller-turn.json': {
                'parent_id': parent_id, 'generation': generation, 'ended': True, 'uncertain': False,
                'session_id': session_id, 'session_key': session_key,
                'worker_turns': [{'turn': 1, 'outcome': 'incomplete-turn', 'response_status': 'error',
                                  'returncode': 1, 'process_group_drained': True, 'session_bound': True,
                                  'host_tool_failures': 0, 'host_tool_requests': 2}],
                'host_tool_failures': [dict(failure_entry), dict(failure_entry)],
                'host_tool_requests': len(ledger) + len(refused_ids) - 2,
                'sdk_runs_started': 1, 'sdk_run_history': [],
                'tools': tools},
        }
        children = {'1' * 32: 'maintenance', '2' * 32: 'maintenance'}
        if log:
            children['3' * 32] = 'log'
        for child_id, kind in children.items():
            files[f'child/{child_id}.json'] = {'schema': 'argos-workload-child/1', 'id': child_id,
                                               'parent_id': parent_id, 'generation': generation,
                                               'kind': kind, 'state': 'released'}
        steps = [
            {'step_id': 'call-inspect', 'tool': 'inspect', 'status': 'completed', 'step_status': 'completed'},
            {'step_id': 'call-audit', 'tool': 'audit', 'status': 'completed', 'step_status': 'verified',
             'passed': True},
            {'step_id': refused_ids[0], **refused_step},
            {'step_id': refused_ids[1], **refused_step},
        ]
        if log:
            steps.append({'step_id': 'call-log', 'tool': 'log', 'status': 'completed',
                          'step_status': 'appended'})
        watch = {'schema': 'argos-proctor-watch/1', 'id': watch_id, 'phase': 'incomplete',
                 'failure_code': 'campaign-invalid-state',
                 'result': {'status': 'incomplete', 'failure_code': 'campaign-invalid-state',
                            'campaign': {'status': 'failed', 'outcome': 'campaign-runtime-failed',
                                         'saved_evaluation_ids': []}},
                 'campaign_steps': steps}
        if mutate is not None:
            mutate(files, watch)
        for name, value in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        return root, watch, owner_pid

    def _recover_refused(self, home, watch, owner_pid):
        with patch.object(workload.sys, 'platform', 'linux'), \
                patch.object(workload, 'current_boot_id', return_value=self.REFUSED_BOOT), \
                patch.object(workload, 'worker_identity', return_value=self.REFUSED_IDENTITY), \
                patch.object(workload, '_process_group_drained', return_value=True):
            return workload.recover_owner_approved_readonly_incomplete_controller(
                home, watch, owner_pid=owner_pid)

    def test_owner_approved_recovery_accepts_host_refused_evaluations_and_appended_log(self):
        # Older runtimes recorded no refusal code; newer ones record a fixed one.
        for refusal_code in (None, 'owner-suite-mismatch', 'no-owner-suite'):
            with self.subTest(refusal_code=refusal_code), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                root, watch, owner_pid = self._write_refused_evaluation_quarantine(
                    home, refusal_code=refusal_code)
                self.assertTrue(workload.quarantined_controller_watch_binding(home, watch))
                outcome = self._recover_refused(home, watch, owner_pid)
                self.assertEqual(outcome, {'status': 'recovered',
                                           'reason': 'drained-refused-evaluation-chain-incomplete-turn',
                                           'watch_id': watch['id']})
                current = json.loads((root / 'reservation.json').read_text())
                self.assertEqual(current['state'], 'released')
                self.assertEqual(current['phase'],
                                 'recovered-owner-approved-refused-evaluation-chain-incomplete')
                receipt = json.loads((root / 'recovered' / f"12-{'a' * 32}.json").read_text())
                self.assertEqual(receipt['schema'], 'argos-workload-recovery/6')
                self.assertEqual(receipt['reason'],
                                 'owner-approved-drained-refused-evaluation-chain-incomplete-turn')
                self.assertEqual(receipt['refused_evaluation_steps'], 2)
                self.assertEqual(receipt['appended_log_steps'], 1)
                self.assertEqual(receipt['watch_id'], watch['id'])
                # A recovered reservation no longer binds any watch record.
                self.assertFalse(workload.quarantined_controller_watch_binding(home, watch))

    def test_owner_approved_readonly_chain_with_appended_log_recovers(self):
        def drop_refusals(files, watch):
            watch['campaign_steps'] = [step for step in watch['campaign_steps']
                                       if step['tool'] != 'evaluation']
            files['controller-turn.json']['host_tool_failures'] = []
            files['controller-turn.json']['worker_turns'][0].update(
                outcome='completed', response_status='ok', returncode=0)

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root, watch, owner_pid = self._write_refused_evaluation_quarantine(home, mutate=drop_refusals)
            outcome = self._recover_refused(home, watch, owner_pid)
            self.assertEqual(outcome['reason'], 'drained-readonly-chain-incomplete-turn')
            receipt = json.loads((root / 'recovered' / f"12-{'a' * 32}.json").read_text())
            self.assertEqual(receipt['schema'], 'argos-workload-recovery/4')
            self.assertEqual(receipt['appended_log_steps'], 1)

    def test_owner_approved_refused_evaluation_recovery_fails_closed_without_durable_proof(self):
        def turn(files):
            return files['controller-turn.json']

        def child(child_id, kind, state='released'):
            return {'schema': 'argos-workload-child/1', 'id': child_id, 'parent_id': 'a' * 32,
                    'generation': 12, 'kind': kind, 'state': state}

        mutations = {
            # Any trace that an evaluation job or worker existed for the generation.
            'evaluation-job-published': lambda files, watch: turn(files).update(
                evaluation_job={'job_id': 'f' * 32, 'suite': 'documents-long', 'state': 'failed',
                                'completed': 0, 'total': 40}),
            'evaluation-child-released': lambda files, watch: files.update(
                {f"child/{'4' * 32}.json": child('4' * 32, 'evaluation')}),
            'evaluation-child-cancelled': lambda files, watch: files.update(
                {f"child/{'4' * 32}.json": {**child('4' * 32, 'evaluation'),
                                            'outcome': 'cancelled-before-start'}}),
            'child-without-kind': lambda files, watch: files.update(
                {f"child/{'4' * 32}.json": {key: value for key, value in child('4' * 32, 'log').items()
                                            if key != 'kind'}}),
            'maintenance-child-active': lambda files, watch: files.update(
                {f"child/{'1' * 32}.json": child('1' * 32, 'maintenance', 'active')}),
            'evaluation-outcome-in-ledger': lambda files, watch: turn(files)['tools'].append(
                {'call_id': 'call-eval-1', 'kind': 'evaluation', 'result_id': 'f' * 32}),
            # Failures outside admission validation carry extra ledger fields.
            'busy-failure-stage': lambda files, watch: turn(files)['host_tool_failures'][0].update(
                tool_stage='host-operation'),
            'child-failure-stage': lambda files, watch: turn(files)['host_tool_failures'][1].update(
                child_failure_stage='reservation'),
            'failure-not-value-error': lambda files, watch: turn(files)['host_tool_failures'][0].update(
                error_class='RuntimeError'),
            'failure-other-tool': lambda files, watch: turn(files)['host_tool_failures'][0].update(
                kind='evaluation_wait'),
            'failure-count-short': lambda files, watch: turn(files)['host_tool_failures'].pop(),
            'failure-count-extra': lambda files, watch: turn(files)['host_tool_failures'].append(
                {'kind': 'evaluation', 'error_class': 'ValueError'}),
            'failure-code-mismatch': lambda files, watch: turn(files)['host_tool_failures'][0].update(
                refusal_code='evaluation-limit-reached'),
            'earlier-sdk-run-failure': lambda files, watch: turn(files).update(
                sdk_run_history=[{'run_id': 'run-0', 'ended': True, 'host_tool_requests': 1,
                                  'host_tool_failures': 1}]),
            'earlier-worker-failure': lambda files, watch: turn(files).update(worker_turns=[
                {'turn': 1, 'outcome': 'completed', 'response_status': 'ok', 'returncode': 0,
                 'process_group_drained': True, 'session_bound': True, 'host_tool_failures': 1,
                 'host_tool_requests': 1},
                {**turn(files)['worker_turns'][0], 'turn': 2}]),
            'last-turn-completed': lambda files, watch: turn(files)['worker_turns'][0].update(
                outcome='completed', response_status='ok', returncode=0),
            # Watch steps that show an evaluation was admitted or produced output.
            'step-has-result': lambda files, watch: watch['campaign_steps'][2].update(result_id='f' * 32),
            'step-has-run-state': lambda files, watch: watch['campaign_steps'][2].update(run_state='failed'),
            'step-has-progress': lambda files, watch: watch['campaign_steps'][3].update(completed=1, total=40),
            'step-busy': lambda files, watch: watch['campaign_steps'][2].update(error_class='Busy'),
            'step-unknown-refusal': lambda files, watch: watch['campaign_steps'][2].update(
                refusal_code='made-up'),
            'step-evaluation-completed': lambda files, watch: watch['campaign_steps'][2].update(
                status='completed', step_status='completed'),
            'saved-evaluation': lambda files, watch: watch['result']['campaign'].update(
                saved_evaluation_ids=['f' * 32]),
            # The log note must be a confirmed append from its own drained log child.
            'log-unconfirmed': lambda files, watch: turn(files)['tools'][2].update(
                status='failed', appended=False, append_outcome='unconfirmed'),
            'log-step-failed': lambda files, watch: watch['campaign_steps'][4].update(step_status='failed'),
            'log-child-missing': lambda files, watch: files.pop(f"child/{'3' * 32}.json"),
            'log-child-active': lambda files, watch: files.update(
                {f"child/{'3' * 32}.json": child('3' * 32, 'log', 'active')}),
            'no-audit': lambda files, watch: watch['campaign_steps'].pop(1) and turn(files)['tools'].pop(1),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                root, watch, owner_pid = self._write_refused_evaluation_quarantine(home, mutate=mutate)
                with self.assertRaises(workload.Busy) as failure:
                    self._recover_refused(home, watch, owner_pid)
                self.assertTrue(failure.exception.recovery)
                self.assertEqual(json.loads((root / 'reservation.json').read_text())['state'], 'quarantined')
                self.assertFalse((root / 'recovered').exists())

    def test_watch_binding_requires_the_current_quarantined_controller_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root, watch, _owner_pid = self._write_refused_evaluation_quarantine(home)
            self.assertTrue(workload.quarantined_controller_watch_binding(home, watch))
            # An older campaign: eligible on its own, but its calls are not this ledger's.
            older = json.loads(json.dumps(watch))
            older['id'] = '1ef43210' + '0' * 24
            older['campaign_steps'] = [
                {'step_id': 'old-inspect', 'tool': 'inspect', 'status': 'completed',
                 'step_status': 'completed'}]
            self.assertFalse(workload.quarantined_controller_watch_binding(home, older))
            turn_path = root / 'controller-turn.json'
            turn = json.loads(turn_path.read_text())
            turn['generation'] = 11
            turn_path.write_text(json.dumps(turn))
            self.assertFalse(workload.quarantined_controller_watch_binding(home, watch))
            turn['generation'] = 12
            turn_path.write_text(json.dumps(turn))
            receipt = root / 'recovered' / f"12-{'a' * 32}.json"
            receipt.parent.mkdir()
            receipt.write_text('{}')
            self.assertFalse(workload.quarantined_controller_watch_binding(home, watch))
            receipt.unlink()
            reservation_path = root / 'reservation.json'
            reservation = json.loads(reservation_path.read_text())
            reservation['state'] = 'released'
            reservation_path.write_text(json.dumps(reservation))
            self.assertFalse(workload.quarantined_controller_watch_binding(home, watch))

    def _write_completed_controller_quarantine(self, home, *, final_audit=True, child_state='released'):
        boot_id = '11111111-1111-4111-8111-111111111111'
        parent_id = 'a' * 32
        root = home / '.local/state/argos-live/workload'
        (root / 'child').mkdir(parents=True)
        reservation = {'schema': 'argos-workload/1', 'id': parent_id, 'generation': 8,
                       'kind': 'controller', 'pid': 12345,
                       'worker_identity': {'boot_id': boot_id, 'start_ticks': '10'},
                       'state': 'quarantined', 'phase': 'running', 'last_child_id': 'c' * 32}
        worker = {'parent_id': parent_id, 'generation': 8, 'state': 'completed',
                  'process_group_drained': True, 'sdk_end_observed': True,
                  'turn_outcome': 'incomplete-turn', 'returncode': 1, 'pid': 2_000_000_000,
                  'session_id': 'session-4', 'session_key': 'agent:main:argos_proctor_improvement_x',
                  'run_id': 'run-4', 'turn_number': 4}
        tools = [
            {'kind': 'inspect'},
            {'kind': 'audit', 'status': 'verified', 'passed': True},
            {'kind': 'evaluation', 'state': 'completed', 'result_id': '1' * 32,
             'suite_version': 'argos-openclaw-ability/owner-recovery-decision/0.5.0',
             'coverage_complete': True, 'correct': 3, 'total': 8, 'format_errors': 0},
            {'kind': 'evaluation', 'state': 'completed', 'result_id': '2' * 32,
             'suite_version': 'argos-openclaw-ability/owner-recovery-decision/0.5.0',
             'coverage_complete': True, 'correct': 3, 'total': 8, 'format_errors': 2},
            {'kind': 'compare', 'baseline_id': '1' * 32, 'candidate_id': '2' * 32},
            {'kind': 'audit', 'status': 'verified', 'passed': True, 'host_final': final_audit},
        ]
        turns = [{'turn': number, 'outcome': 'incomplete-turn', 'process_group_drained': True,
                  'session_bound': True, 'host_tool_failures': 0, 'returncode': 1}
                 for number in range(1, 5)]
        turn = {'parent_id': parent_id, 'generation': 8, 'uncertain': False,
                'worker_turns': turns, 'run_id': 'run-4', 'session_id': 'session-4',
                'session_key': 'agent:main:argos_proctor_improvement_x',
                'ended': True, 'host_tool_failures': [], 'tools': tools}
        child = {'parent_id': parent_id, 'generation': 8, 'state': child_state}
        for name, value in (('reservation.json', reservation), ('controller-worker.json', worker),
                            ('controller-turn.json', turn), ('child/' + 'c' * 32 + '.json', child)):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        result_rows = {run_id: {'state': 'completed', 'kind': 'ability',
                        'coverage': {'complete': True, 'completed': 8, 'total': 8},
                        'suite_version': 'argos-openclaw-ability/owner-recovery-decision/0.5.0',
                        'summary': {'correct': correct, 'format_errors': errors}}
                       for run_id, correct, errors in (('1' * 32, 3, 0), ('2' * 32, 3, 2))}
        return boot_id, root, result_rows

    def test_evidence_complete_drained_controller_quarantine_recovers_same_boot(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            boot_id, root, result_rows = self._write_completed_controller_quarantine(home)
            with patch.object(workload, 'current_boot_id', return_value=boot_id), \
                    patch('argoslive.results.Store.load', side_effect=result_rows.__getitem__):
                with workload.reserve(home, 'controller') as slot:
                    self.assertEqual(slot.record['generation'], 9)
                    self.assertEqual(slot.record['kind'], 'controller')
                    slot.complete()
            receipts = list((root / 'recovered').glob('*.json'))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text())
            self.assertEqual(receipt['schema'], 'argos-workload-recovery/2')
            self.assertEqual(receipt['reason'], 'evidence-complete-drained-controller')
            self.assertEqual(receipt['reservation_id'], 'a' * 32)

    def test_evidence_recovery_fails_closed_without_final_audit_or_drained_child(self):
        for final_audit, child_state in ((False, 'released'), (True, 'active')):
            with self.subTest(final_audit=final_audit, child_state=child_state), \
                    tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                boot_id, root, result_rows = self._write_completed_controller_quarantine(
                    home, final_audit=final_audit, child_state=child_state)
                with patch.object(workload, 'current_boot_id', return_value=boot_id), \
                        patch('argoslive.results.Store.load', side_effect=result_rows.__getitem__):
                    with self.assertRaises(workload.Busy) as failure:
                        with workload.reserve(home, 'controller'):
                            self.fail('Incomplete same-boot evidence reopened admission')
                self.assertTrue(failure.exception.recovery)
                reservation = json.loads((root / 'reservation.json').read_text())
                self.assertEqual(reservation['state'], 'quarantined')
                self.assertFalse((root / 'recovered').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'POSIX signal and executable fixture')
    def test_sigterm_drains_real_child_and_saves_cancelled_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True)
            configure_fake(home, workspace)
            binary = root / 'bin'
            binary.mkdir()
            ready = root / 'child-ready'
            executable = binary / 'openclaw'
            executable.write_text('#!/usr/bin/env python3\nimport os,time,json,subprocess,sys\nfrom pathlib import Path\n'
                                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],'
                                  'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n'
                                  f'Path({str(ready)!r}).write_text(json.dumps({{"pid":os.getpid(),"child":child.pid}}))\n'
                                  'time.sleep(60)\n')
            executable.chmod(0o700)
            env = {**os.environ, 'PYTHONPATH': str(ROOT / 'runtime'),
                   'PATH': str(binary) + os.pathsep + os.environ['PATH']}
            output = root / 'results'
            process = subprocess.Popen([sys.executable, '-m', 'argoslive.bench_openclaw',
                                        '--home', str(home), '--results-dir', str(output), '--json'],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            child_pid = None
            descendant = None
            try:
                deadline = time.monotonic() + 20
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(ready.exists(), 'Embedded child never started')
                identity = json.loads(ready.read_text())
                child_pid, descendant = identity['pid'], identity['child']
                process.terminate()
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                result = json.loads(stdout)['result']
                self.assertEqual((result['state'], result['failure_code']), ('cancelled', 'cancelled'))
                self.assertFalse(result['coverage']['complete'])
                self.assertEqual(json.loads((output / (result['id'] + '.json')).read_bytes()), result)
                state = home / '.local/state/argos-live'
                board = json.loads((state / 'assistant-bench-live.json').read_bytes())
                self.assertEqual(board['phase'], 'cancelled')
                reservation = json.loads((state / 'workload/reservation.json').read_bytes())
                self.assertEqual(reservation['state'], 'quarantined')
                self.assertEqual(reservation['result_id'], result['id'])
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
                # A killed orphan can briefly remain a zombie pending init's
                # reap; it cannot execute or retain inference connections.
                status = Path(f'/proc/{descendant}/stat')
                try:
                    self.assertEqual(status.read_text().split(') ', 1)[1].split()[0], 'Z')
                except FileNotFoundError:
                    pass
                with self.assertRaises(workload.Busy):
                    with workload.reserve(home, 'proctor'):
                        self.fail('Cancellation silently reopened admission')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5)
                if child_pid is not None:
                    command = Path(f'/proc/{child_pid}/cmdline')
                    try:
                        if str(executable).encode() in command.read_bytes().split(b'\0'):
                            os.kill(child_pid, signal.SIGKILL)
                    except FileNotFoundError:
                        pass
                process.stdout.close()
                process.stderr.close()

    def test_only_one_benchmark_can_reach_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.openclaw/workspace').mkdir(parents=True)
            configure_fake(home, home / '.openclaw/workspace')
            started, resume = threading.Event(), threading.Event()
            outcomes = []
            class Waiting(FakeOpenClaw):
                def turn(self, prompt):
                    started.set()
                    if not resume.wait(10):
                        raise RuntimeError('Test did not release runner')
                    return super().turn(prompt)
            def first():
                try:
                    outcomes.append(bench_openclaw.run(home=home, runner=Waiting()))
                except BaseException as error:
                    outcomes.append(error)
            thread = threading.Thread(target=first)
            thread.start()
            try:
                self.assertTrue(started.wait(10))
                second = FakeOpenClaw()
                with self.assertRaises(workload.Busy):
                    bench_openclaw.run(home=home, runner=second)
                self.assertEqual(second.calls, 0)
                with self.assertRaises(workload.Busy):
                    with workload.reserve(home, 'proctor'):
                        self.fail('Proctor overlapped the campaign')
            finally:
                resume.set()
                thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes[0]['state'], 'completed')
            with workload.reserve(home, 'proctor') as slot:
                slot.complete()

    def test_busy_cli_does_not_publish_live_board_or_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            output = io.StringIO()
            with workload.reserve(home, 'evaluation') as slot:
                with patch.object(bench_openclaw, 'LiveBoard') as board, patch.object(bench_openclaw, '_run') as run:
                    with contextlib.redirect_stdout(output):
                        code = bench_openclaw.main(['--home', str(home), '--json'])
                    self.assertEqual(code, 75)
                    board.assert_not_called()
                    run.assert_not_called()
                slot.complete()
            self.assertEqual(json.loads(output.getvalue())['status'], 'busy')

    def test_killed_worker_does_not_allow_reuse_on_lock_expiry(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            env = {**os.environ, 'PYTHONPATH': str(ROOT / 'runtime')}
            script = ('from argoslive.workload import reserve; import sys\n'
                      'with reserve(sys.argv[1], "evaluation"):\n'
                      ' print("READY", flush=True)\n'
                      ' sys.stdin.read()\n')
            with subprocess.Popen([sys.executable, '-c', script, str(home)], env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
                self.assertEqual(child.stdout.readline().strip(), 'READY')
                child.kill()
                child.wait(timeout=10)
            with self.assertRaises(workload.Busy) as failure:
                with workload.reserve(home, 'evaluation'):
                    self.fail('Abandoned worker was automatically reclaimed')
            self.assertTrue(failure.exception.recovery)

    def test_cli_holds_admission_until_result_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            result = {'id': 'a' * 32, 'state': 'completed'}
            def save(value):
                self.assertIs(value, result)
                with self.assertRaises(workload.Busy):
                    with workload.reserve(home, 'proctor'):
                        self.fail('Released before saving the run')
                return home / 'saved.json'
            with patch.object(bench_openclaw, '_run', return_value=result), \
                    patch.object(bench_openclaw, 'LiveBoard'), \
                    patch.object(bench_openclaw.Store, 'save', side_effect=save):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(bench_openclaw.main(['--home', str(home), '--json']), 0)
            with workload.reserve(home, 'proctor') as slot:
                slot.complete()

    def test_uncertain_exit_quarantines_instead_of_claiming_completion(self):
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaisesRegex(RuntimeError, 'lost child'):
                with workload.reserve(home, 'evaluation'):
                    raise RuntimeError('lost child')
            with self.assertRaises(workload.Busy) as failure:
                with workload.reserve(home, 'maintenance'):
                    pass
            self.assertTrue(failure.exception.recovery)

    def test_quarantine_recovers_only_after_a_verified_kernel_reboot(self):
        with tempfile.TemporaryDirectory() as home:
            old_boot = '11111111-1111-4111-8111-111111111111'
            new_boot = '22222222-2222-4222-8222-222222222222'
            result_id = 'a' * 32
            with patch.object(workload, 'current_boot_id', return_value=old_boot), \
                    patch.object(workload, 'worker_identity', return_value={
                        'boot_id': old_boot, 'start_ticks': '10'}):
                with self.assertRaisesRegex(RuntimeError, 'lost owner'):
                    with workload.reserve(home, 'evaluation') as slot:
                        slot.record_result(result_id)
                        raise RuntimeError('lost owner')
                with self.assertRaises(workload.Busy):
                    with workload.reserve(home, 'proctor'):
                        self.fail('Same-boot quarantine was reclaimed')
            root = Path(home) / '.local/state/argos-live/workload'
            prior_id = json.loads((root / 'reservation.json').read_text())['id']

            with patch.object(workload, 'current_boot_id', return_value=new_boot), \
                    patch.object(workload, 'worker_identity', return_value={
                        'boot_id': new_boot, 'start_ticks': '20'}):
                with workload.reserve(home, 'proctor') as slot:
                    self.assertEqual(slot.record['generation'], 2)
                    self.assertEqual(slot.record['kind'], 'proctor')

            # The receipt uses the quarantined generation's ID, not the new one.
            receipt_files = list((root / 'recovered').glob('*.json'))
            self.assertEqual(len(receipt_files), 1)
            receipt = json.loads(receipt_files[0].read_text())
            self.assertEqual(receipt['schema'], 'argos-workload-recovery/1')
            self.assertEqual(receipt['reservation_id'], prior_id)
            self.assertEqual(receipt['generation'], 1)
            self.assertEqual(receipt['result_id'], result_id)
            self.assertEqual(receipt['previous_boot_id'], old_boot)
            self.assertEqual(receipt['current_boot_id'], new_boot)
            self.assertEqual(receipt['reason'], 'verified-kernel-reboot-boundary')

    def test_quarantine_without_a_verified_boot_boundary_stays_closed(self):
        with tempfile.TemporaryDirectory() as home:
            old_boot = '11111111-1111-4111-8111-111111111111'
            with patch.object(workload, 'current_boot_id', return_value=old_boot), \
                    patch.object(workload, 'worker_identity', return_value={
                        'boot_id': old_boot, 'start_ticks': '10'}):
                with self.assertRaises(RuntimeError):
                    with workload.reserve(home, 'evaluation'):
                        raise RuntimeError('unknown drain')

            for unverified_boot in (None, 'not-a-boot-id'):
                with self.subTest(current_boot_id=unverified_boot), \
                        patch.object(workload, 'current_boot_id', return_value=unverified_boot):
                    with self.assertRaises(workload.Busy) as failure:
                        with workload.reserve(home, 'evaluation'):
                            self.fail('Missing or malformed boot identity released quarantine')
                    self.assertTrue(failure.exception.recovery)

    def test_reboot_recovery_receipt_must_publish_before_admission_reopens(self):
        with tempfile.TemporaryDirectory() as home:
            old_boot = '11111111-1111-4111-8111-111111111111'
            new_boot = '22222222-2222-4222-8222-222222222222'
            with patch.object(workload, 'current_boot_id', return_value=old_boot), \
                    patch.object(workload, 'worker_identity', return_value={
                        'boot_id': old_boot, 'start_ticks': '10'}):
                with self.assertRaises(RuntimeError):
                    with workload.reserve(home, 'evaluation'):
                        raise RuntimeError('lost owner')

            write_json = workload.write_json
            def fail_recovery(path, value):
                if Path(path).parent.name == 'recovered':
                    raise OSError('recovery receipt disk failure')
                return write_json(path, value)
            with patch.object(workload, 'current_boot_id', return_value=new_boot), \
                    patch.object(workload, 'worker_identity', return_value={
                        'boot_id': new_boot, 'start_ticks': '20'}), \
                    patch.object(workload, 'write_json', side_effect=fail_recovery):
                with self.assertRaisesRegex(OSError, 'receipt disk failure'):
                    with workload.reserve(home, 'proctor'):
                        self.fail('Admission reopened without a recovery receipt')

            record = json.loads((Path(home) / '.local/state/argos-live/workload/reservation.json').read_text())
            self.assertEqual(record['state'], 'quarantined')
            self.assertEqual(list((Path(home) / '.local/state/argos-live/workload/recovered').glob('*.json')), [])


if __name__ == '__main__':
    unittest.main()
