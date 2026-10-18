#!/usr/bin/env python3
"""Focused rootless hosted diagnosis; no real model or product deployment."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if (sys.platform != 'linux' or os.geteuid() == 0 or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise ValueError('Focused signal diagnosis requires a rootless disposable hosted runner')
    output = ROOT / 'work/signal-diagnosis'
    output.mkdir(parents=True, exist_ok=False)
    guard = ROOT / 'scripts/signal-guard'
    env = {**os.environ, 'PYTHONPATH': str(guard) + os.pathsep + str(ROOT / 'runtime'),
           'ARGOS_SIGNAL_GUARD_DIR': str(guard), 'ARGOS_SIGNAL_DIAG_DIR': str(output)}
    results = []
    for pattern in ('test_process_group.py', 'test_workload.py', 'test_workload_delegation.py',
                    'test_controller_bridge.py', 'test_instruction_changes.py', 'test_assistant_trial.py',
                    'test_auto_climb.TestAutoClimbCoordinator.test_openclaw_runner_child_process_termination_on_cancellation'):
        loader = (f'unittest.defaultTestLoader.discover("tests",pattern={pattern!r})' if pattern.endswith('.py') else
                  f'unittest.defaultTestLoader.loadTestsFromName({pattern!r})')
        code = ('import faulthandler,unittest,sys;'
                'faulthandler.dump_traceback_later(20,repeat=True);'
                'sys.path.insert(0,"tests");'
                f'suite={loader};'
                'result=unittest.TextTestRunner(verbosity=2).run(suite);'
                'sys.exit(0 if result.wasSuccessful() else 1)')
        print('Focused signal diagnosis: ' + pattern, flush=True)
        with (output / (pattern + '.log')).open('w') as log:
            try:
                result = subprocess.run([sys.executable, '-u', '-c', code], cwd=ROOT, env=env,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=90)
                status = result.returncode
            except subprocess.TimeoutExpired:
                status = 124
        results.append({'pattern': pattern, 'exit_code': status})
        print(json.dumps(results[-1]), flush=True)
        (output / 'summary.json').write_text(json.dumps({'tests': results}, indent=2) + '\n')
    return int(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
