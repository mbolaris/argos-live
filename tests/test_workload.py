import contextlib
import io
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
from test_bench_openclaw import FakeOpenClaw


class WorkloadTests(unittest.TestCase):
    def test_only_one_benchmark_can_reach_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.openclaw/workspace').mkdir(parents=True)
            (home / '.openclaw/openclaw.json').write_text('{}', encoding='utf-8')
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
