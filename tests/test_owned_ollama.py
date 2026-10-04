import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.owned_ollama import owned, owns_port, PIN

FAKE = '''#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os
from pathlib import Path
root = Path(os.environ['OLLAMA_MODELS'])
(root / 'pid').write_text(str(os.getpid()))
(root / 'env.json').write_text(json.dumps({k: v for k, v in os.environ.items() if k.startswith('OLLAMA_')}))
host, port = os.environ['OLLAMA_HOST'].split(':')
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"version":"0.35.0"}')
HTTPServer((host, int(port)), Handler).serve_forever()
'''
FAKE = FAKE.replace('0.35.0', PIN)


@unittest.skipUnless(sys.platform == 'linux', 'Linux process/parent-death supervision')
class OwnedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / 'fake-ollama'
        self.binary.write_text(FAKE)
        self.binary.chmod(0o755)

    def stopped(self, pid):
        path = Path(f'/proc/{pid}/stat')
        try:
            return path.read_text().split(')')[1].strip().startswith('Z')
        except FileNotFoundError:
            # Reaping can remove /proc between observation and reading it.
            return True

    def test_loopback_owned_port_environment_and_cleanup_on_error(self):
        import json
        with self.assertRaisesRegex(ValueError, 'fixture body'):
            with owned(self.root, executable=self.binary, timeout=3) as client:
                self.assertEqual(client.version(), PIN)
                port = int(client.base_url.rsplit(':', 1)[1])
                pid = int((self.root / 'pid').read_text())
                self.assertTrue(owns_port(pid, port))
                self.assertFalse(owns_port(os.getpid(), port))
                env = json.loads((self.root / 'env.json').read_text())
                self.assertEqual(env['OLLAMA_MODELS'], str(self.root))
                self.assertEqual(env['OLLAMA_NOPRUNE'], '1')
                self.assertEqual(env['OLLAMA_NO_CLOUD'], '1')
                with self.assertRaises(ValueError):
                    with owned(self.root, executable=self.binary, timeout=3):
                        self.fail('A second daemon acquired the same store lease')
                raise ValueError('fixture body')
        self.assertTrue(self.stopped(pid))

    def test_parent_death_terminates_owned_daemon(self):
        script = self.root / 'worker.py'
        script.write_text('import sys, time\n'
                          f'sys.path.insert(0, {str(ROOT / "runtime")!r})\n'
                          'from argoslive.owned_ollama import owned\n'
                          f'with owned({str(self.root)!r}, executable={str(self.binary)!r}) as client:\n'
                          '    print("ready", flush=True)\n'
                          '    time.sleep(30)\n')
        worker = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
        try:
            import select
            self.assertTrue(select.select([worker.stdout], [], [], 5)[0])
            self.assertEqual(worker.stdout.readline().strip(), 'ready')
            pid = int((self.root / 'pid').read_text())
            worker.kill()
            worker.wait(timeout=5)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not self.stopped(pid):
                time.sleep(0.05)
            self.assertTrue(self.stopped(pid))
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
            worker.stdout.close()

    def test_separate_lease_store_keeps_lock_files_out_of_model_source(self):
        lease_store = self.root / 'writable-lease'
        lease_store.mkdir()
        with owned(self.root, executable=self.binary, timeout=3, lease_store=lease_store) as client:
            self.assertEqual(client.version(), PIN)
            self.assertFalse((self.root / '.argos-daemon-lease').exists())
            self.assertTrue((lease_store / '.argos-daemon-lease').is_dir())
            with self.assertRaises(ValueError):
                with owned(self.root, executable=self.binary, timeout=3, lease_store=lease_store):
                    self.fail('Same lease allowed a competing daemon')

    def test_fixed_loopback_port_context_and_busy_port_never_adopted(self):
        import json
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen()
            with self.assertRaises(OSError):
                with owned(self.root, executable=self.binary, port=port, timeout=3):
                    self.fail('Unrelated listener was adopted')
            self.assertFalse((self.root / 'pid').exists())
            self.assertFalse((self.root / '.argos-daemon-lease').exists())
        with owned(self.root, executable=self.binary, port=port, context_tokens=32768, timeout=3) as client:
            pid = int((self.root / 'pid').read_text())
            self.assertEqual(client.base_url, f'http://127.0.0.1:{port}')
            self.assertTrue(owns_port(pid, port))
            env = json.loads((self.root / 'env.json').read_text())
            self.assertEqual(env['OLLAMA_CONTEXT_LENGTH'], '32768')
        self.assertTrue(self.stopped(pid))

    def test_invalid_fixed_port_or_context_starts_no_process(self):
        for options in ({'port': True}, {'port': -1}, {'port': 65536}, {'port': '11434'},
                        {'context_tokens': True}, {'context_tokens': 0}, {'context_tokens': 1048577}):
            with self.assertRaises(ValueError):
                with owned(self.root, executable=self.binary, **options):
                    self.fail('Invalid options started a service')
        self.assertFalse((self.root / 'pid').exists())
