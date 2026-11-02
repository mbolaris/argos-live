import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from argoslive import ssh_recovery


def status(*, boot='a' * 36, eligible=True, active=False, listening=False,
           enabled=True, policy=True, persistence='verified'):
    return {
        'schema': ssh_recovery.STATUS_SCHEMA,
        'boot_id': boot,
        'persistence_state': persistence,
        'paired_policy_valid': policy,
        'ssh_enabled': enabled,
        'ssh_active': active,
        'port22_listening': listening,
        'restart_eligible': eligible,
        'failure_code': None,
    }


class PrivilegedRecoveryTests(unittest.TestCase):
    def test_refuses_when_any_start_gate_is_not_met(self):
        for value in (
            status(policy=False, eligible=False),
            status(persistence='unverified', policy=False, eligible=False),
            status(enabled=False, eligible=False),
            status(active=True, listening=True, eligible=False),
        ):
            with self.subTest(value=value), patch.object(ssh_recovery, 'privileged_snapshot', return_value=value), \
                    patch.object(ssh_recovery, '_run') as run:
                result = ssh_recovery.privileged_restart()
                self.assertIn(result['status'], {'refused', 'failed'})
                run.assert_not_called()

    def test_only_starts_fixed_service_and_requires_postcheck(self):
        before = status()
        after = status(active=True, listening=True, eligible=False)
        snapshots = iter([before, after])
        runs = iter([(None, None), ('active', None)])
        with patch.object(ssh_recovery, 'privileged_snapshot', side_effect=lambda: next(snapshots)), \
                patch.object(ssh_recovery, '_run', side_effect=lambda *a, **k: next(runs)) as run, \
                patch.object(ssh_recovery, '_boot_id', return_value=before['boot_id']), \
                patch.object(ssh_recovery, '_port22_listening', return_value=True):
            result = ssh_recovery.privileged_restart()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(run.call_args_list[0].args[0],
                         ['/usr/bin/systemctl', 'start', 'ssh.service'])

    def test_does_not_claim_success_without_listener(self):
        runs = iter([(None, None), ('active', None)])
        with patch.object(ssh_recovery, 'privileged_snapshot', return_value=status()), \
                patch.object(ssh_recovery, '_run', side_effect=lambda *a, **k: next(runs)), \
                patch.object(ssh_recovery, '_boot_id', return_value=status()['boot_id']), \
                patch.object(ssh_recovery, '_port22_listening', return_value=False), \
                patch.object(ssh_recovery.time, 'sleep'), \
                patch.object(ssh_recovery.time, 'monotonic', side_effect=[0, 9]):
            result = ssh_recovery.privileged_restart()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failure_code'], 'restart-not-verified')


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.current = status()
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = 0

    def tearDown(self):
        self.release.set()
        self.tmp.cleanup()

    def controller(self, restart=None):
        controller = ssh_recovery.Controller(
            home=self.home,
            status_provider=lambda: dict(self.current),
            restart_provider=restart or self.completed_restart,
        )
        controller._persistent = lambda: True
        return controller

    def signed_storage(self, controller):
        class Signer:
            def sign(self, payload):
                return {'algorithm': 'test', 'sig_base64': 'test'}

        controller._persistent = lambda: True
        controller._signer = lambda: Signer()

    def completed_restart(self):
        self.calls += 1
        self.current.update(ssh_active=True, port22_listening=True, restart_eligible=False)
        return {'status': 'completed', 'failure_code': None}

    def slow_completed_restart(self):
        self.started.set()
        self.release.wait(2)
        return self.completed_restart()

    def test_stale_approval_is_rejected(self):
        controller = self.controller()
        self.signed_storage(controller)
        try:
            result = controller.snapshot()
            self.assertTrue(result['can_restart'])
            with self.assertRaises(ValueError):
                controller.restart('0' * 32, self.current['boot_id'])
            self.assertEqual(self.calls, 0)
        finally:
            controller.close()

    def test_expired_approval_is_rejected_without_starting_work(self):
        controller = self.controller()
        self.signed_storage(controller)
        try:
            snapshot = controller.snapshot()
            snapshot['receipt']['payload']['created_utc'] = '2000-01-01T00:00:00+00:00'
            with self.assertRaises(ValueError):
                controller.restart(snapshot['receipt']['payload']['receipt_id'], self.current['boot_id'])
            self.assertEqual(self.calls, 0)
        finally:
            controller.close()

    def test_host_owned_job_completes_saves_signed_receipt(self):
        controller = self.controller(self.slow_completed_restart)
        # Create real signing storage while bypassing only the hardware persistence probe.
        self.signed_storage(controller)
        try:
            snapshot = controller.snapshot()
            self.assertEqual(snapshot['receipt']['signature_status'], 'signed')
            job = controller.restart(snapshot['receipt']['payload']['receipt_id'], self.current['boot_id'])
            self.assertEqual(job['state'], 'running')
            self.assertTrue(self.started.wait(1))
            self.release.set()
            controller.close()
            saved = json.loads((controller.root / 'latest-job.json').read_text())
            self.assertEqual(saved['state'], 'completed')
            self.assertEqual(saved['receipt']['signature_status'], 'signed')
            self.assertTrue((controller.root / (saved['receipt']['payload']['receipt_id'] + '.json')).exists())
            self.assertEqual(self.calls, 1)
            with self.assertRaises(ValueError):
                controller.restart(snapshot['receipt']['payload']['receipt_id'], self.current['boot_id'])
        finally:
            controller.close()

    def test_refuses_second_job_while_first_is_running(self):
        def slow_restart():
            self.calls += 1
            self.release.wait(2)
            self.current.update(ssh_active=True, port22_listening=True, restart_eligible=False)
            return {'status': 'completed', 'failure_code': None}

        controller = self.controller(slow_restart)
        self.signed_storage(controller)
        try:
            snapshot = controller.snapshot()
            approval = (snapshot['receipt']['payload']['receipt_id'], self.current['boot_id'])
            controller.restart(*approval)
            deadline = time.monotonic() + 1
            while self.calls == 0 and time.monotonic() < deadline:
                time.sleep(.01)
            with self.assertRaises(ValueError):
                controller.restart(*approval)
            self.assertEqual(self.calls, 1)
        finally:
            self.release.set()
            controller.close()


if __name__ == '__main__':
    unittest.main()
