import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.owned_ollama import owned, owns_port

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
        return not path.exists() or path.read_text().split(')')[1].strip().startswith('Z')

    def test_loopback_owned_port_environment_and_cleanup_on_error(self):
        import json
        with self.assertRaisesRegex(ValueError, 'fixture body'):
            with owned(self.root, executable=self.binary, timeout=3) as client:
                self.assertEqual(client.version(), '0.35.0')
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
