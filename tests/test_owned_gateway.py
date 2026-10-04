import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import addons
from argoslive.owned_gateway import owned, settings, group_owns_port

FAKE = '''#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path
if '--version' in sys.argv:
    print('OpenClaw HOSTPIN')
    sys.exit()
config = Path(os.environ['OPENCLAW_CONFIG_PATH'])
port = json.loads(config.read_text())['gateway']['port']
if '--worker' not in sys.argv:
    config.parent.joinpath('leader-pid').write_text(str(os.getpid()))
    child = subprocess.Popen([sys.executable, __file__, '--worker'])
    child.wait()
    sys.exit()
from http.server import HTTPServer, BaseHTTPRequestHandler
config.parent.joinpath('worker-pid').write_text(str(os.getpid()))
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ready":true}')
print('fictional private gateway diagnostic', flush=True)
HTTPServer(('127.0.0.1', port), Handler).serve_forever()
'''.replace('HOSTPIN', addons.load()['host_version'])


class GatewaySettingsTests(unittest.TestCase):
    def test_nonlocal_missing_token_invalid_ports_and_shapes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            good = {'mode': 'local', 'bind': 'loopback', 'auth': {'mode': 'token', 'token': 'fictional'}}
            for field, value in (('mode', 'remote'), ('bind', 'lan'), ('port', True),
                    ('port', 0), ('auth', {}), ('auth', {'mode': 'none', 'token': 'fictional'})):
                path.write_text(json.dumps({'gateway': dict(good, **{field: value})}))
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    settings(path)
            path.write_text(json.dumps({'gateway': good}))
            self.assertEqual(settings(path), ('http://127.0.0.1:18789', 18789))
            for bad in (None, [], False):
                path.write_text(json.dumps({'gateway': bad}))
                with self.assertRaises(ValueError):
                    settings(path)


@unittest.skipUnless(sys.platform == 'linux', 'Linux owned gateway process groups')
class GatewayProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / '.openclaw'
        self.state.mkdir(mode=0o700)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        self.config = self.state / 'openclaw.json'
        self.config.write_text(json.dumps({'gateway': {'mode': 'local', 'bind': 'loopback',
            'port': self.port, 'auth': {'mode': 'token', 'token': 'fictional'}}}))
        self.binary = self.home / 'fake-openclaw'
        self.binary.write_text(FAKE)
        self.binary.chmod(0o755)

    def stopped(self, pid):
        try:
            raw = Path(f'/proc/{pid}/stat').read_text()
            return raw[raw.rfind(')') + 2:].split()[0] == 'Z'
        except FileNotFoundError:
            return True

    def test_launcher_child_owned_and_private_logs_cleanup_on_failure(self):
        original = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, 'fixture body'):
            with owned(self.home, executable=self.binary, timeout=5) as origin:
                leader = int((self.state / 'leader-pid').read_text())
                worker = int((self.state / 'worker-pid').read_text())
                self.assertNotEqual(leader, worker)
                self.assertTrue(group_owns_port(leader, self.port))
                self.assertFalse(group_owns_port(os.getpgrp(), self.port))
                self.assertEqual(origin, f'http://127.0.0.1:{self.port}')
                log = self.home / '.local/state/argos-live/gateway.log'
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                self.assertIn('fictional private', log.read_text())
                raise ValueError('fixture body')
        self.assertTrue(self.stopped(leader))
        self.assertTrue(self.stopped(worker))
        self.assertEqual(self.config.read_bytes(), original)

    def test_busy_port_never_adopted_or_killed(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', self.port))
            listener.listen()
            with self.assertRaises(OSError):
                with owned(self.home, executable=self.binary, timeout=5):
                    self.fail('An unrelated listener was adopted')
            self.assertEqual(listener.getsockname()[1], self.port)
            self.assertFalse((self.state / 'leader-pid').exists())
            self.assertFalse((self.home / '.local').exists())

    def test_parent_death_stops_launcher_and_gateway_child(self):
        script = self.home / 'owner.py'
        script.write_text('import sys,time\n'
            f'sys.path.insert(0, {str(ROOT / "runtime")!r})\n'
            'from argoslive.owned_gateway import owned\n'
            f'with owned({str(self.home)!r}, executable={str(self.binary)!r}, timeout=5):\n'
            '    print("ready", flush=True)\n    time.sleep(30)\n')
        worker = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
        try:
            import select
            self.assertTrue(select.select([worker.stdout], [], [], 10)[0])
            self.assertEqual(worker.stdout.readline().strip(), 'ready')
            pids = [int((self.state / name).read_text()) for name in ('leader-pid', 'worker-pid')]
            worker.kill()
            worker.wait(timeout=5)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not all(self.stopped(pid) for pid in pids):
                time.sleep(0.05)
            self.assertTrue(all(self.stopped(pid) for pid in pids))
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
            worker.stdout.close()

    def test_wrong_version_and_linked_log_start_no_gateway(self):
        self.binary.write_text(FAKE.replace(addons.load()['host_version'], '1999.1.1'))
        with self.assertRaisesRegex(ValueError, 'version'):
            with owned(self.home, executable=self.binary, timeout=5):
                self.fail('Unpinned gateway was accepted')
        self.assertFalse((self.state / 'leader-pid').exists())
        self.binary.write_text(FAKE)
        root = self.home / '.local/state/argos-live'
        root.mkdir(mode=0o700, parents=True)
        private = self.home / 'owner-file'
        private.write_bytes(b'owner bytes')
        (root / 'gateway.log').symlink_to(private)
        with self.assertRaises(ValueError):
            with owned(self.home, executable=self.binary, timeout=5):
                self.fail('Linked gateway log was accepted')
        self.assertEqual(private.read_bytes(), b'owner bytes')
        self.assertFalse((self.state / 'leader-pid').exists())
