"""Storage routes: authenticated, bounded, and never able to write outside a listed choice."""
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.web.server import DashboardServer


class FakeStorage:
    def __init__(self):
        self.chosen = []
        self.checks = 0
        self.fail = False

    def snapshot(self):
        return {'schema': 'argos-storage-view/1', 'locations': [], 'candidates': []}

    def choose(self, candidate):
        if self.fail:
            raise ValueError('not eligible')
        self.chosen.append(candidate)
        return {'path': '/x', 'changed': True}

    def reboot_check(self):
        self.checks += 1
        return {'created': ['models']}


class StorageRouteTests(unittest.TestCase):
    def setUp(self):
        self.storage = FakeStorage()
        self.server = DashboardServer(port=0, storage=self.storage)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.worker.join(timeout=5)
        self.server.server_close()

    def request(self, path, method='GET', body=None, headers=None, token=True):
        h = {'X-Argos-Token': self.server.token} if token else {}
        h.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=h)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def post(self, path, payload, **headers):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.request(path, 'POST', raw, {'Content-Type': 'application/json', **headers})

    def test_get_requires_token_and_returns_view(self):
        self.assertEqual(self.request('/api/storage', token=False)[0], 403)
        status, body = self.request('/api/storage')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['schema'], 'argos-storage-view/1')

    def test_unavailable_without_controller(self):
        with DashboardServer(port=0) as other:
            worker = threading.Thread(target=other.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            connection = http.client.HTTPConnection('127.0.0.1', other.server_port, timeout=5)
            connection.request('GET', '/api/storage', headers={'X-Argos-Token': other.token})
            self.assertEqual(json.loads(connection.getresponse().read()), {'available': False})
            other.shutdown()
            worker.join(timeout=5)

    def test_choice_requires_header_token_and_exact_json_shape(self):
        self.assertEqual(self.post('/api/storage/choose', {'candidate': 'a' * 20}, **{'X-Argos-Token': 'wrong'})[0], 403)
        for bad in ({'candidate': 'a' * 20, 'path': '/etc'}, {'path': '/etc'}, [], 'x'):
            self.assertEqual(self.post('/api/storage/choose', bad)[0], 409)
        self.assertEqual(self.post('/api/storage/choose', b'not json')[0], 409)
        self.assertEqual(self.storage.chosen, [])
        status, body = self.post('/api/storage/choose', {'candidate': 'a' * 20})
        self.assertEqual(status, 200)
        self.assertEqual(self.storage.chosen, ['a' * 20])

    def test_choice_needs_json_content_type_and_bounded_length(self):
        status, _ = self.request('/api/storage/choose', 'POST', b'{"candidate":"' + b'a' * 20 + b'"}',
                                 {'Content-Type': 'text/plain'})
        self.assertEqual(status, 400)
        status, _ = self.post('/api/storage/choose', {'candidate': 'a' * 400})
        self.assertEqual(status, 400)
        self.assertEqual(self.storage.chosen, [])

    def test_ineligible_choice_returns_generic_error(self):
        self.storage.fail = True
        status, body = self.post('/api/storage/choose', {'candidate': 'a' * 20})
        self.assertEqual(status, 409)
        self.assertNotIn(b'eligible', body.replace(b'Refresh, then choose an eligible empty location.', b''))

    def test_reboot_check_requires_empty_post_with_header_token(self):
        self.assertEqual(self.request('/api/storage/reboot-check', 'POST', token=False)[0], 403)
        self.assertEqual(self.request('/api/storage/reboot-check', 'POST', b'x', {'Content-Length': '1'})[0], 400)
        self.assertEqual(self.storage.checks, 0)
        self.assertEqual(self.request('/api/storage/reboot-check', 'POST')[0], 200)
        self.assertEqual(self.storage.checks, 1)
        self.assertEqual(self.request('/api/storage/reboot-check?token=' + self.server.token, 'POST', token=False)[0], 403)


if __name__ == '__main__':
    unittest.main()
