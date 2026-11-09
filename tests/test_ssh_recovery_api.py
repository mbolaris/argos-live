import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from argoslive import ssh_recovery
from argoslive.proctor.signing import verify_envelope
from argoslive.web.server import DashboardServer


class FakeRecovery:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {'available': True, 'status': {'boot_id': 'a' * 36}, 'can_restart': True,
                'active': False, 'job': None,
                'receipt': {'payload': {'receipt_id': 'b' * 32}}}

    def restart(self, receipt_id, boot_id):
        self.calls.append((receipt_id, boot_id))
        return {'schema': 'argos-ssh-recovery-job/1', 'state': 'running'}


class SshRecoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.recovery = FakeRecovery()
        self.server = DashboardServer(port=0, ssh_recovery=self.recovery)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def request(self, path, data=None, *, token=True, extra_headers=None):
        headers = {}
        if token:
            headers['X-Argos-Token'] = self.server.token
        if data is not None:
            headers['Content-Type'] = 'application/json'
        headers.update(extra_headers or {})
        payload = None if data is None else json.dumps(data).encode()
        req = Request(self.server.origin + path, data=payload, headers=headers,
                      method='GET' if data is None else 'POST')
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            finally:
                error.close()

    def test_status_is_readable_but_mutation_requires_token(self):
        code, body = self.request('/api/ssh-recovery')
        self.assertEqual(code, 200)
        self.assertTrue(body['can_restart'])
        code, _ = self.request('/api/ssh-recovery/start', {
            'receipt_id': 'b' * 32, 'boot_id': 'a' * 36,
        }, token=False)
        self.assertEqual(code, 403)
        self.assertEqual(self.recovery.calls, [])

    def test_start_requires_exact_bounded_approval_fields(self):
        code, _ = self.request('/api/ssh-recovery/start', {'receipt_id': 'b' * 32})
        self.assertEqual(code, 409)
        code, body = self.request('/api/ssh-recovery/start', {
            'receipt_id': 'b' * 32, 'boot_id': 'a' * 36,
        })
        self.assertEqual(code, 202)
        self.assertEqual(body['state'], 'running')
        self.assertEqual(self.recovery.calls, [('b' * 32, 'a' * 36)])

    def test_signed_status_owner_approval_and_same_boot_completion(self):
        """Exercise the complete dashboard/controller path in disposable state."""
        temp = tempfile.TemporaryDirectory()
        home = Path(temp.name)
        boot_id = '00000000-0000-4000-8000-000000000001'
        current = {'schema': ssh_recovery.STATUS_SCHEMA, 'boot_id': boot_id,
            'persistence_state': 'verified', 'paired_policy_valid': True,
            'ssh_enabled': True, 'ssh_active': False, 'port22_listening': False,
            'restart_eligible': True, 'failure_code': None}
        entered, release = threading.Event(), threading.Event()
        restart_calls = []

        def restart():
            restart_calls.append(True)
            before = dict(current)
            entered.set()
            if not release.wait(3):
                return {'status': 'failed', 'failure_code': 'restart-failed', 'before': before}
            current.update(ssh_active=True, port22_listening=True, restart_eligible=False)
            return {'status': 'completed', 'failure_code': None,
                    'before': before, 'after': dict(current)}

        controller = ssh_recovery.Controller(home=home, status_provider=lambda: dict(current),
                                               restart_provider=restart)
        controller._persistent = lambda: True  # Explicitly simulated encrypted fixture gate.
        controller.root.mkdir(mode=0o700, parents=True)
        ssh_recovery.generate_key(controller.root / 'receipt-ed25519.pem')
        dashboard = DashboardServer(port=0, ssh_recovery=controller)
        thread = threading.Thread(target=dashboard.serve_forever,
                                  kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()

        def request(path, data=None):
            headers = {'X-Argos-Token': dashboard.token}
            if data is not None:
                headers.update({'Content-Type': 'application/json', 'Origin': dashboard.origin})
            payload = None if data is None else json.dumps(data).encode()
            req = Request(dashboard.origin + path, data=payload, headers=headers,
                          method='GET' if data is None else 'POST')
            try:
                with urlopen(req, timeout=3) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as error:
                try:
                    return error.code, json.loads(error.read())
                finally:
                    error.close()

        try:
            code, initial = request('/api/ssh-recovery')
            self.assertEqual(code, 200)
            self.assertTrue(initial['available'])
            self.assertTrue(initial['can_restart'])
            self.assertEqual(initial['status']['boot_id'], boot_id)
            self.assertTrue(initial['receipt']['signature_status'] == 'signed')
            proctor_status = controller.proctor_status()
            self.assertTrue(controller.verify_proctor_status(proctor_status))
            self.assertTrue(proctor_status['owner_approval_available'])

            approval = {'receipt_id': initial['receipt']['payload']['receipt_id'],
                        'boot_id': boot_id}
            code, started = request('/api/ssh-recovery/start', approval)
            self.assertEqual(code, 202)
            self.assertEqual(started['state'], 'running')
            self.assertTrue(entered.wait(1))
            duplicate_code, _ = request('/api/ssh-recovery/start', approval)
            self.assertEqual(duplicate_code, 409)
            self.assertEqual(len(restart_calls), 1)

            release.set()
            final = None
            for _ in range(60):
                code, final = request('/api/ssh-recovery')
                self.assertEqual(code, 200)
                if (final.get('job', {}).get('state') == 'completed' and
                        isinstance(final.get('job', {}).get('receipt'), dict)):
                    break
                threading.Event().wait(0.05)
            self.assertEqual(final['job']['state'], 'completed')
            self.assertEqual(final['job']['boot_id'], boot_id)
            self.assertTrue(final['status']['ssh_active'])
            self.assertTrue(final['status']['port22_listening'])
            self.assertFalse(final['can_restart'])

            operation = final['job']['receipt']
            payload_json = json.dumps(operation['payload'], sort_keys=True,
                                      separators=(',', ':'), ensure_ascii=True)
            signer = controller._signer(create=False)
            self.assertTrue(verify_envelope({
                'envelope_version': 'argos.proctor.envelope.v1',
                'payload_json': payload_json, 'signature': operation['signature']},
                signer.public_key_der))
            self.assertEqual(operation['payload']['status']['boot_id'], boot_id)
            self.assertEqual(operation['payload']['operation']['status'], 'completed')
            self.assertEqual(operation['payload']['operation']['accepted_dashboard_approvals'], 1)
            self.assertGreaterEqual(operation['payload']['operation']['approval_to_check_seconds'], 0)
            self.assertEqual(operation['payload']['operation']['timing_basis'], 'host-monotonic')
            fresh_proctor = controller.proctor_status()
            self.assertTrue(controller.verify_proctor_status(fresh_proctor))
            self.assertFalse(fresh_proctor['owner_approval_available'])
            self.assertTrue(fresh_proctor['status']['ssh_active'])
            self.assertEqual(fresh_proctor['status']['boot_id'], boot_id)
        finally:
            release.set()
            controller.close()
            dashboard.shutdown()
            dashboard.server_close()
            thread.join(timeout=2)
            temp.cleanup()


if __name__ == '__main__':
    unittest.main()
