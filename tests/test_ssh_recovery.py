import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from argoslive import ssh_recovery
from argoslive.proctor.signing import Ed25519Signer, verify_envelope


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
    def test_socket_conflict_requires_systemd_listener_mapping_and_pid_one_ownership(self):
        outputs = iter([
            ('0.0.0.0:22 (Stream) ssh.socket ssh.service\n[::]:22 (Stream) ssh.socket ssh.service', None),
            ('LISTEN 0 4096 0.0.0.0:22 0.0.0.0:* users:(("systemd",pid=1,fd=63))\n'
             'LISTEN 0 4096 [::]:22 [::]:* users:(("systemd",pid=1,fd=64))', None),
        ])
        with patch.object(ssh_recovery, '_run', side_effect=lambda *a, **k: next(outputs)) as run:
            self.assertTrue(ssh_recovery._ssh_socket_owns_port22())
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ['/usr/bin/systemctl', 'list-sockets', '--no-legend', '--no-pager'],
            ['/usr/bin/ss', '-ltnpH'],
        ])

    def test_socket_conflict_rejects_other_socket_or_listener_owner(self):
        cases = (
            ('0.0.0.0:22 (Stream) other.socket other.service', None, False),
            ('0.0.0.0:22 (Stream) ssh.socket other.service', None, False),
            ('0.0.0.0:22 (Stream) ssh.socket ssh.service',
             'LISTEN 0 4096 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=80,fd=3))', False),
            ('0.0.0.0:22 (Stream) ssh.socket ssh.service',
             'LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*', None),
        )
        for sockets, listeners, expected in cases:
            with self.subTest(sockets=sockets, listeners=listeners), \
                    patch.object(ssh_recovery, '_run', side_effect=[(sockets, None),
                        (listeners, None)] if listeners is not None else [(sockets, None),
                        (None, 'preflight-unavailable')]):
                self.assertIs(ssh_recovery._ssh_socket_owns_port22(), expected)

    def test_snapshot_allows_only_verified_systemd_socket_conflict(self):
        with patch.object(ssh_recovery.ssh_boot, 'ready'), \
                patch.object(ssh_recovery, '_run', return_value=('enabled', None)), \
                patch.object(ssh_recovery, '_unit_active_state', side_effect=['inactive', 'active']), \
                patch.object(ssh_recovery, '_port22_listening', return_value=True), \
                patch.object(ssh_recovery, '_ssh_socket_owns_port22', return_value=True), \
                patch.object(ssh_recovery, '_boot_id', return_value='a' * 36):
            value = ssh_recovery.privileged_snapshot()
        self.assertEqual(value['failure_code'], 'socket-conflict')
        self.assertTrue(value['port22_listening'])
        self.assertTrue(value['restart_eligible'])
        self.assertTrue(ssh_recovery._safe_root_status(value)['restart_eligible'])

    def test_snapshot_blocks_unknown_listener_or_unavailable_listener_check(self):
        cases = ((['inactive', 'inactive'], True, False, 'listener-conflict'),
                 (['inactive', 'active'], True, False, 'listener-conflict'),
                 (['inactive', 'active'], True, None, 'listener-conflict'),
                 (['inactive', 'inactive'], None, False, 'preflight-unavailable'))
        for states, listening, socket_owner, failure in cases:
            with self.subTest(listening=listening), \
                    patch.object(ssh_recovery.ssh_boot, 'ready'), \
                    patch.object(ssh_recovery, '_run', return_value=('enabled', None)), \
                    patch.object(ssh_recovery, '_unit_active_state', side_effect=states), \
                    patch.object(ssh_recovery, '_port22_listening', return_value=listening), \
                    patch.object(ssh_recovery, '_ssh_socket_owns_port22', return_value=socket_owner), \
                    patch.object(ssh_recovery, '_boot_id', return_value='a' * 36):
                value = ssh_recovery.privileged_snapshot()
            self.assertEqual(value['failure_code'], failure)
            self.assertFalse(value['restart_eligible'])

    def test_approved_socket_recovery_stops_only_socket_then_starts_paired_service(self):
        before = status(eligible=True, listening=True)
        before['failure_code'] = 'socket-conflict'
        after_stop = status(eligible=True, listening=False)
        after = status(eligible=False, active=True, listening=True)
        snapshots = iter([before, after_stop, after])
        runs = iter([(None, None), (None, None), ('active', None)])
        with patch.object(ssh_recovery, 'privileged_snapshot', side_effect=lambda: next(snapshots)), \
                patch.object(ssh_recovery, '_run', side_effect=lambda *a, **k: next(runs)) as run, \
                patch.object(ssh_recovery, '_boot_id', return_value=before['boot_id']), \
                patch.object(ssh_recovery, '_port22_listening', return_value=True), \
                patch.object(ssh_recovery, '_unit_active_state', return_value='inactive'):
            result = ssh_recovery.privileged_restart()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ['/usr/bin/systemctl', 'stop', 'ssh.socket'],
            ['/usr/bin/systemctl', 'start', 'ssh.service'],
            ['/usr/bin/systemctl', 'is-active', 'ssh.service'],
        ])

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

    def test_proctor_status_is_signed_bounded_and_does_not_create_state(self):
        controller = self.controller()
        controller._persistent = lambda: True
        try:
            unavailable = controller.proctor_status()
            self.assertEqual(unavailable, {'schema': 'argos-proctor-ssh-status/1',
                                           'available': False,
                                           'failure_code': 'signed-status-unavailable'})
            self.assertFalse(controller.root.exists())

            controller.root.mkdir(mode=0o700, parents=True)
            ssh_recovery.generate_key(controller.root / 'receipt-ed25519.pem')
            before = {path.name for path in controller.root.iterdir()}
            value = controller.proctor_status()
            after = {path.name for path in controller.root.iterdir()}
            self.assertTrue(value['available'])
            self.assertEqual(value['schema'], 'argos-proctor-ssh-status/1')
            self.assertTrue(value['owner_approval_available'])
            self.assertEqual(value['recovery_job_state'], 'idle')
            self.assertEqual(before, after)
            self.assertEqual(value['status'], self.current)
            trusted = Ed25519Signer(controller.root / 'receipt-ed25519.pem').public_key_der
            self.assertTrue(verify_envelope(value['receipt'], trusted))
            self.assertTrue(controller.verify_proctor_status(value))
            payload = json.loads(value['receipt']['payload_json'])
            self.assertEqual(payload['status'], self.current)
            self.assertEqual(payload['owner_approval_available'], value['owner_approval_available'])
            self.assertEqual(payload['recovery_job_state'], value['recovery_job_state'])
            self.current.update(ssh_active=True, port22_listening=True, restart_eligible=False)
            healthy = controller.proctor_status()
            self.assertTrue(healthy['available'])
            self.assertFalse(healthy['owner_approval_available'])
            self.assertTrue(healthy['status']['ssh_active'])
            self.assertTrue(healthy['status']['port22_listening'])
            self.assertTrue(controller.verify_proctor_status(healthy))
            self.current.update(paired_policy_valid=False, restart_eligible=False,
                                failure_code='paired-policy-unready')
            unsafe = controller.proctor_status()
            self.assertTrue(unsafe['available'])
            self.assertFalse(unsafe['owner_approval_available'])
            self.assertFalse(unsafe['status']['restart_eligible'])
            self.assertEqual(unsafe['status']['failure_code'], 'paired-policy-unready')
            self.assertTrue(controller.verify_proctor_status(unsafe))
            tampered = json.loads(json.dumps(value))
            tampered['status']['ssh_active'] = True
            self.assertFalse(controller.verify_proctor_status(tampered))
            tampered = json.loads(json.dumps(value))
            tampered['owner_approval_available'] = False
            self.assertFalse(controller.verify_proctor_status(tampered))
        finally:
            controller.close()

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
            self.assertEqual(saved['approval_count'], 1)
            self.assertGreaterEqual(saved['approval_to_check_seconds'], 0)
            self.assertEqual(saved['timing_basis'], 'host-monotonic')
            self.assertIn('approved_at_utc', saved)
            self.assertIn('finished_at_utc', saved)
            signed_operation = saved['receipt']['payload']['operation']
            self.assertEqual(signed_operation['accepted_dashboard_approvals'], 1)
            self.assertEqual(signed_operation['approval_to_check_seconds'],
                             saved['approval_to_check_seconds'])
            self.assertEqual(signed_operation['timing_basis'], 'host-monotonic')
            self.assertTrue((controller.root / (saved['receipt']['payload']['receipt_id'] + '.json')).exists())
            self.assertEqual(self.calls, 1)
            with self.assertRaises(ValueError):
                controller.restart(snapshot['receipt']['payload']['receipt_id'], self.current['boot_id'])
        finally:
            controller.close()

    def test_records_host_observed_approval_availability_until_click(self):
        controller = self.controller()
        self.signed_storage(controller)
        now = [100.0]
        controller.clock = lambda: now[0]
        try:
            first = controller.snapshot()
            self.assertTrue(first['can_restart'])
            self.assertEqual(first['approval_available_seconds'], 0)
            first_seen = first['approval_available_since_utc']

            now[0] = 106.25
            refreshed = controller.snapshot()
            self.assertEqual(refreshed['approval_available_since_utc'], first_seen)
            self.assertAlmostEqual(refreshed['approval_available_seconds'], 6.25)

            job = controller.restart(refreshed['receipt']['payload']['receipt_id'], self.current['boot_id'])
            self.assertEqual(job['approval_available_since_utc'], first_seen)
            self.assertAlmostEqual(job['approval_availability_to_click_seconds'], 6.25)
            self.assertEqual(job['approval_availability_timing_basis'], 'host-monotonic')
            self.release.set()
            controller.close()
            saved = json.loads((controller.root / 'latest-job.json').read_text())
            operation = saved['receipt']['payload']['operation']
            self.assertEqual(operation['approval_available_since_utc'], first_seen)
            self.assertAlmostEqual(operation['approval_availability_to_click_seconds'], 6.25)
            self.assertEqual(operation['approval_availability_timing_basis'], 'host-monotonic')
        finally:
            self.release.set()
            controller.close()

    def test_availability_timer_restarts_when_safe_approval_disappears(self):
        controller = self.controller()
        self.signed_storage(controller)
        now = [200.0]
        controller.clock = lambda: now[0]
        try:
            first = controller.snapshot()
            now[0] = 205.0
            self.assertAlmostEqual(controller.snapshot()['approval_available_seconds'], 5.0)
            self.current.update(restart_eligible=False, ssh_active=True, port22_listening=True)
            unavailable = controller.snapshot()
            self.assertFalse(unavailable['can_restart'])
            self.assertIsNone(unavailable['approval_available_since_utc'])
            self.assertIsNone(unavailable['approval_available_seconds'])

            self.current.update(restart_eligible=True, ssh_active=False, port22_listening=False)
            now[0] = 220.0
            restored = controller.snapshot()
            self.assertTrue(restored['can_restart'])
            self.assertNotEqual(restored['approval_available_since_utc'],
                                first['approval_available_since_utc'])
            self.assertEqual(restored['approval_available_seconds'], 0)
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

    def test_orphaned_job_is_reconciled_from_saved_host_status(self):
        controller = self.controller()
        self.signed_storage(controller)
        controller.job = {'schema': 'argos-ssh-recovery-job/1', 'job_id': 'c' * 32,
                          'state': 'running', 'boot_id': self.current['boot_id'],
                          'approved_receipt_id': 'b' * 32, 'receipt': None,
                          'approved_at_utc': (datetime.now(timezone.utc) - timedelta(seconds=6)).isoformat(),
                          'approval_count': 1,
                          'failure_code': None}
        controller.root.mkdir(parents=True)
        controller.root.chmod(0o700)
        controller._save_job()
        controller.job = None  # simulate a desktop process that exited
        self.current.update(ssh_active=True, port22_listening=True, restart_eligible=False)
        try:
            snapshot = controller.snapshot()
            self.assertEqual(snapshot['job']['state'], 'completed')
            self.assertEqual(snapshot['job']['receipt']['signature_status'], 'signed')
            self.assertEqual(snapshot['job']['timing_basis'], 'reconciled-observation')
            self.assertGreaterEqual(snapshot['job']['approval_to_check_seconds'], 5)
            self.assertEqual(snapshot['job']['receipt']['payload']['operation'][
                'timing_basis'], 'reconciled-observation')
            saved = json.loads((controller.root / 'latest-job.json').read_text())
            self.assertEqual(saved['state'], 'completed')
        finally:
            controller.close()


if __name__ == '__main__':
    unittest.main()
