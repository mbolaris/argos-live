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
