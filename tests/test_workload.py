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


if __name__ == '__main__':
    unittest.main()
