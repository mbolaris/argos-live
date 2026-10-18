# Cancellation test diagnosis

The descendant-cleanup change exposed a unit test that mocked subprocess.Popen
but left proc.pid as a MagicMock and did not mock the OS cleanup boundary.
Python's integer-index conversion turns that mock into 1. The production cleanup
called os.killpg with that mock, creating an unsafe process-group-1 signal path.

Guarded hosted run39089190467 at90377a8 reproduced the path and blocked its
SIGKILL before the kernel call. Its saved stack points to the cancellation test
in test_auto_climb.py and stop_group in owned_ollama.py. The runner remained
available and uploaded its diagnostic evidence. A separate local reproduction
replaced the kernel function with a recorder and observed index conversion to1
for both SIGTERM and SIGKILL. Earlier hosted runs lost communication; their
missing logs do not prove the exact historical kernel targets.

The correction rejects non-int/coerced, reserved, caller-group and caller-session
IDs before signalling. The unit test now mocks its platform cleanup boundary;
the real subprocess test separately verifies forked descendant termination,
saved cancelled JSON, terminal liveboard and quarantined admission with result ID.

Guarded run39089324657 at50504d1 passed2 process-group guards,6 workload tests,
48 assistant-trial tests and the targeted auto-climb cancellation unit test.
The full suite is restored only after this focused gate passes and has a bounded
watchdog. This is cancellation evidence, not a model benchmark, a complete host
admission service, hard-kill recovery or backend-drain proof. Toronado was not
changed. The full unattended-image acceptance ledger remains authoritative.
