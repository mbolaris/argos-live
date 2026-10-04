import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.results import Store
from argoslive.web.benchmarks import View
from argoslive.web.server import DashboardServer
from test_results import ability_result


class DashboardBenchmarkTests(unittest.TestCase):
    def test_bounded_read_only_projection_comparison_and_download(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            first, second = ability_result(), ability_result('wrong')
            second['model'] = '<img src=x onerror=alert(1)>'
            store.save(first); store.save(second)
            (Path(temp) / 'corrupt.json').write_text('private invalid fixture')
            view = View(store)
            listing = view.listing()
            self.assertEqual(len(listing['runs']), 2)
            self.assertEqual(listing['invalid_count'], 1)
            self.assertNotIn('items', listing['runs'][0])
            self.assertNotIn('hardware', listing['runs'][0])
            with DashboardServer(port=0, benchmarks=view) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                def request(path, headers=None, method='GET'):
                    with http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5) as connection:
                        connection.request(method, path, headers=headers or {})
                        reply = connection.getresponse()
                        return reply.status, dict(reply.getheaders()), reply.read()
                auth = {'X-Argos-Token': server.token}
                query = f'run={first["id"]}&run={second["id"]}'
                try:
                    self.assertEqual(request('/api/benchmarks')[0], 403)
                    code, _, body = request('/api/benchmarks', auth)
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body)['invalid_count'], 1)
                    code, _, body = request('/api/benchmarks/compare?' + query, auth)
                    self.assertEqual(code, 200)
                    self.assertEqual([r['value'] for r in json.loads(body)['rows']], [1, 0])
                    code, headers, body = request('/api/benchmarks/compare.csv?' + query, auth)
                    self.assertEqual(code, 200)
                    self.assertIn('attachment;', headers['Content-Disposition'])
                    self.assertTrue(headers['Content-Type'].startswith('text/csv'))
                    self.assertIn(b'manifest_digest', body)
                    code, headers, body = request('/api/benchmarks/run/' + first['id'], auth)
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body)['id'], first['id'])
                    self.assertIn(first['id'] + '.json', headers['Content-Disposition'])
                    for path in ('/api/benchmarks/run/../../private', '/api/benchmarks/compare?run=bad',
                                 '/api/benchmarks/compare?run=' + first['id'] + '&run=' + first['id']):
                        code, _, body = request(path, auth)
                        self.assertEqual(code, 409)
                        self.assertNotIn(temp.encode(), body)
                    self.assertEqual(request('/api/benchmarks', auth, 'POST')[0], 405)
                    self.assertEqual(store.load(first['id']), first)
                finally:
                    server.shutdown(); worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
