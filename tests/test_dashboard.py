"""Disposable loopback HTTP fixture; no external network or owner services."""
import contextlib
import http.client
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.web.server import DashboardServer


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DashboardServer(port=0, status_provider=lambda: {'assistant': 'not-checked'})
        cls.worker = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={'poll_interval': 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.worker.join(timeout=5)
        cls.server.server_close()

    def request(self, path, method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_only_explicit_loopback_bind_allowed(self):
        for host in ('0.0.0.0', '192.168.1.30', 'localhost', '::1'):
            with self.assertRaisesRegex(ValueError, '127.0.0.1'):
                DashboardServer(host, 0)

    def test_each_session_gets_a_fresh_token(self):
        with DashboardServer(port=0) as other:
            self.assertNotEqual(other.token, self.server.token)
            self.assertGreaterEqual(len(other.token), 40)

    def test_missing_wrong_and_duplicate_tokens_rejected(self):
        for route in ('/', '/app.js', '/style.css', '/api/status', '/api/capabilities', '/api/assistant/chat', '/api/models'):
            self.assertEqual(self.request(route)[0], 403)
            self.assertEqual(self.request(route + '?token=wrong')[0], 403)
        route = '/api/status?token=' + self.server.token + '&token=' + self.server.token
        self.assertEqual(self.request(route)[0], 403)

    def test_static_routes_and_security_headers(self):
        for route, mime in [('/', 'text/html'), ('/app.js', 'text/javascript'), ('/style.css', 'text/css')]:
            status, headers, body = self.request(route + '?token=' + self.server.token)
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith(mime))
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertTrue(body)
            self.assertNotIn(b'__SESSION_TOKEN__', body)

    def test_api_auth_and_conservative_capability_response(self):
        headers = {'X-Argos-Token': self.server.token}
        status, _, body = self.request('/api/status', headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['assistant'], 'not-checked')
        status, _, body = self.request('/api/capabilities', headers=headers)
        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(report['schema'], 'argos-capabilities/1')
        self.assertTrue(all(not row['ready'] for row in report['capabilities']))
        self.assertNotIn(self.server.token, body.decode())

    def test_post_requires_header_and_does_not_mutate(self):
        route = '/api/status?token=' + self.server.token
        self.assertEqual(self.request(route, 'POST')[0], 403)
        self.assertEqual(self.request(route, 'POST', {'X-Argos-Token': self.server.token})[0], 405)
        for method in ('PUT', 'PATCH', 'DELETE', 'OPTIONS'):
            self.assertEqual(self.request('/api/status', method)[0], 403)

    def test_foreign_origin_and_host_rejected_even_with_token(self):
        auth = {'X-Argos-Token': self.server.token}
        self.assertEqual(self.request('/api/status', headers=dict(auth, Origin='https://foreign.invalid'))[0], 403)
        self.assertEqual(self.request('/api/status', headers=dict(auth, Host='foreign.invalid'))[0], 403)
        self.assertEqual(self.request('/api/status', headers=dict(auth, Origin=self.server.origin))[0], 200)

    def test_no_arbitrary_files_or_absolute_targets_served(self):
        auth = {'X-Argos-Token': self.server.token}
        for route in ('/../versions.env', '/%2e%2e/versions.env', '/openclaw.json', '/api/unknown'):
            self.assertEqual(self.request(route, headers=auth)[0], 404)
        absolute_headers = dict(auth, Host=f'127.0.0.1:{self.server.server_port}')
        self.assertEqual(self.request('http://foreign.invalid/api/status', headers=absolute_headers)[0], 400)

    def test_errors_are_generic_and_tokens_are_not_logged(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), patch('argoslive.web.server.addons.load', side_effect=OSError('private-path')):
            status, _, body = self.request('/api/capabilities?token=' + self.server.token)
        self.assertEqual(status, 503)
        self.assertNotIn(b'private-path', body)
        self.assertNotIn(self.server.token, stderr.getvalue())

    def test_head_has_no_body(self):
        status, headers, body = self.request('/?token=' + self.server.token, 'HEAD')
        self.assertEqual(status, 200)
        self.assertGreater(int(headers['Content-Length']), 0)
        self.assertEqual(body, b'')

    def test_chat_unavailable_returns_generic_error(self):
        with patch.object(self.server, 'chat_provider', side_effect=ValueError('fictional-secret')):
            code, _, body = self.request('/api/assistant/chat', headers={'X-Argos-Token': self.server.token})
        self.assertEqual(code, 409)
        self.assertNotIn(b'fictional-secret', body)

    def test_models_route_protected_read_only_projection(self):
        with patch.object(self.server, 'models_provider', return_value={'schema': 'argos-models-view/1', 'read_only': True}):
            code, _, body = self.request('/api/models', headers={'X-Argos-Token': self.server.token})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)['read_only'])
