import copy
from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, bench_ability, bench_speed, results
spec = importlib.util.spec_from_file_location('benchmark_cli', ROOT / 'runtime/argos.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
FIXTURE = json.loads((ROOT / 'tests/fixtures/ollama/responses.json').read_text())


class BenchCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        answers = {i['prompt']: i['reference'] for i in ability.load()['items']}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.respond({})
            def do_POST(self):
                self.respond(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            def respond(self, body):
                self.server.requests.append((self.path, body))
                key = self.path.removeprefix('/api/')
                value = copy.deepcopy(FIXTURE[key])
                if key == 'ps':
                    value = {'models': copy.deepcopy(self.server.loaded)}
                if key == 'generate':
                    if body.get('keep_alive') == 0:
                        self.server.loaded = []
                        value = FIXTURE['unload']
                    elif not body.get('prompt'):
                        self.server.loaded = [{'name': body['model'], 'context_length': body['options'].get('num_ctx')}]
                        value = [{'done': True}]
                    else:
                        self.server.loaded = [{'name': body['model'], 'size': 1000, 'size_vram': 0}]
                        text = answers.get(body['prompt'], 'An original coastline paragraph.')
                        value = [dict(FIXTURE['generate'][-1], response=text)]
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if isinstance(value, list):
                    for item in value:
                        self.wfile.write(json.dumps(item).encode() + b'\n')
                else:
                    self.wfile.write(json.dumps(value).encode())
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_all_cli_over_actual_fixture_http_without_setup(self):
        self.server.loaded = []
        self.server.requests = []
        speed_run, ability_run = bench_speed.run, bench_ability.run
        with tempfile.TemporaryDirectory() as temp:
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors), patch.object(
                    bench_speed, 'run', side_effect=lambda *args, **kw: speed_run(*args, hardware=lambda: {}, **kw)), patch.object(
                    bench_ability, 'run', side_effect=lambda *args, **kw: ability_run(*args, hardware=lambda: {}, **kw)):
                code = cli.main(['bench', 'all', '--model', 'fixture:latest', '--size', 'short',
                                 '--ollama', self.url, '--results-dir', temp, '--json'])
            self.assertEqual(code, 0)
            batch = json.loads(output.getvalue())
            self.assertEqual(batch['schema'], 'argos-bench-batch/1')
            self.assertEqual([run['kind'] for run in batch['runs']], ['speed', 'ability'])
            self.assertEqual(batch['runs'][1]['summary']['accuracy'], 1)
            self.assertEqual(errors.getvalue(), '')
            store = results.Store(temp)
            self.assertEqual(len(store.list()['runs']), 2)
            self.assertEqual(self.server.loaded, [])
            for run in batch['runs']:
                self.assertEqual(store.load(run['id']), run)
            generated = [body for path, body in self.server.requests if path == '/api/generate' and body.get('prompt')]
            self.assertEqual(len(generated), 24)
            self.assertTrue(all(body['think'] is False for body in generated))

    def test_hardware_default_is_readable_with_unknowns(self):
        snapshot = {'cpu': {'model': 'Fixture CPU', 'cores': 4, 'threads': 8},
                    'ram': {'total_bytes': 8 * 2**30, 'available_bytes': None},
                    'gpus': [{'name': 'Fixture GPU', 'vram_total_bytes': 4 * 2**30,
                              'vram_used_bytes': None, 'driver': 'fixture'}],
                    'model_directories': [{'path': '/fixture', 'free_bytes': None}],
                    'kernel': 'fixture', 'secure_boot': None}
        output = io.StringIO()
        with patch('argoslive.hw.snapshot', return_value=snapshot), redirect_stdout(output):
            cli.main(['hw'])
        self.assertIn('8.00 GiB', output.getvalue())
        self.assertIn('available unknown', output.getvalue())
        self.assertIn('driver fixture', output.getvalue())
        self.assertNotIn('{', output.getvalue())


if __name__ == '__main__':
    unittest.main()
