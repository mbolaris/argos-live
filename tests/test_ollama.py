from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.ollama import Client, Cancelled, Interrupted, ModelMissing, NotRunning, OllamaError

FIXTURES = json.loads((ROOT / 'tests/fixtures/ollama/responses.json').read_text())


class OllamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.respond(None)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.respond(body)

            def respond(self, body):
                self.server.requests.append((self.path, body))
                model = (body or {}).get('model')
                if model in ('missing', 'failure'):
                    self.send_response(404 if model == 'missing' else 500)
                    self.end_headers()
                    self.wfile.write(b'{"error":"private-server-detail"}')
                    return
                key = self.path.removeprefix('/api/')
                key = {'tags': 'tags'}.get(key, key)
                if body and body.get('keep_alive') == 0:
                    key = 'unload'
                result = FIXTURES[key]
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if isinstance(result, list) and key in ('pull', 'generate', 'chat'):
                    if model == 'interrupted':
                        result = result[:1]
                    if model == 'bad-json':
                        self.wfile.write(b'not-json\n')
                        return
                    if model == 'stream-error':
                        result = [{'error': 'private-server-detail'}]
                    for event in result:
                        try:
                            self.wfile.write(json.dumps(event).encode() + b'\n')
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            return
                else:
                    self.wfile.write(json.dumps(result).encode())
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.requests = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.server.requests.clear()
        self.client = Client(self.url, timeout=2)

    def test_metadata_version_show_and_loaded_models(self):
        self.assertEqual(self.client.version(), '0.35.0')
        self.assertEqual(self.client.list()['models'][0]['size'], 1000)
        model = self.client.show('fixture')
        self.assertEqual(model['details']['quantization_level'], 'Q4_K_M')
        self.assertEqual(model['model_info']['fixture.context_length'], 4096)
        self.assertIn('thinking', model['capabilities'])
        self.assertEqual(self.client.ps()['models'][0]['size_vram'], 900)

    def test_pull_progress_requires_success(self):
        events = []
        result = self.client.pull('fixture', callback=events.append)
        self.assertEqual(events[1]['completed'], 500)
        self.assertEqual(events[1]['total'], 1000)
        self.assertEqual(result['final']['status'], 'success')
        self.assertIsNone(result['time_to_first_token_seconds'])
        self.assertEqual(self.server.requests[-1][1], {'model': 'fixture', 'stream': True})

    def test_generate_timings_and_reasoning_first_token(self):
        times = iter([10.0, 10.2, 11.0])
        client = Client(self.url, clock=lambda: next(times))
        result = client.generate('fixture', 'hello', options={'seed': 1}, think=False)
        self.assertEqual(result['text'], 'Hello!')
        self.assertEqual(result['thinking'], 'Consider')
        self.assertAlmostEqual(result['time_to_first_token_seconds'], 0.2)
        self.assertEqual(result['elapsed_seconds'], 1.0)
        self.assertEqual(result['final']['eval_duration'], 500000000)
        self.assertEqual(result['final']['eval_count'], 2)
        self.assertFalse(self.server.requests[-1][1]['think'])

    def test_chat_and_unload(self):
        result = self.client.chat('fixture', [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['text'], 'Hi there')
        self.assertNotIn('think', self.server.requests[-1][1])
        self.assertEqual(self.client.unload('fixture')['done_reason'], 'unload')
        self.assertEqual(self.server.requests[-1][1]['keep_alive'], 0)
        self.assertFalse(self.server.requests[-1][1]['stream'])

    def test_cancel_before_request_and_during_callback(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.client.pull('fixture', cancel=cancel)
        self.assertEqual(self.server.requests, [])
        cancel.clear()
        events = []
        def callback(event):
            events.append(event)
            cancel.set()
        with self.assertRaises(Cancelled):
            self.client.pull('fixture', callback=callback, cancel=cancel)
        self.assertEqual(len(events), 1)

    def test_interrupted_pull_and_generation_do_not_report_success(self):
        with self.assertRaises(Interrupted):
            self.client.pull('interrupted')
        with self.assertRaises(Interrupted):
            self.client.generate('interrupted', 'hello')

    def test_http_errors_and_malformed_streams(self):
        with self.assertRaises(ModelMissing):
            self.client.show('missing')
        for model in ('failure', 'bad-json', 'stream-error'):
            with self.assertRaises(OllamaError) as raised:
                self.client.generate(model, 'hello')
            self.assertNotIn('private-server-detail', str(raised.exception))

    def test_unreachable_and_unsafe_urls(self):
        with patch.object(self.client.opener, 'open', side_effect=URLError('refused')):
            with self.assertRaises(NotRunning):
                self.client.version()
        for url in ('file:///tmp/socket', 'http://user:password@localhost',
                    'http://localhost/api', 'http://localhost?token=secret'):
            with self.assertRaises(ValueError):
                Client(url)
