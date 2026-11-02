import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


if __name__ == '__main__':
    unittest.main()
