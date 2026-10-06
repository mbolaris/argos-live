import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import desktop


class SessionTests(unittest.TestCase):
    def test_model_lab_url_opens_results_section_and_only_known_view_is_allowed(self):
        base = 'http://127.0.0.1:12345/?token=' + 'a' * 43
        self.assertEqual(desktop.dashboard_url(base), base)
        self.assertEqual(desktop.dashboard_url(base, 'lab'),
                         base + '&view=lab#benchmarks-title')
        with self.assertRaises(ValueError):
            desktop.dashboard_url(base, 'arbitrary')
        with self.assertRaises(ValueError):
            desktop.dashboard_url('http://192.168.1.30/?token=' + 'a' * 43, 'lab')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux listener identity')
    def test_disappearing_unrelated_descriptor_does_not_hide_owned_listener(self):
        import socket
        from argoslive.owned_ollama import owns_port
        original = os.readlink
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            vanished = False
            def readlink(path):
                nonlocal vanished
                value = original(path)
                if not vanished and value != 'socket:[' + str(os.fstat(listener.fileno()).st_ino) + ']':
                    vanished = True
                    raise FileNotFoundError('Concurrent descriptor closed')
                return value
            with patch('argoslive.owned_ollama.os.readlink', side_effect=readlink):
                self.assertTrue(owns_port(os.getpid(), port))
            self.assertTrue(vanished)
            listener.close()
            self.assertFalse(owns_port(os.getpid(), port))

    def test_only_generated_loopback_session_endpoint_is_accepted(self):
        good = {'schema': 'argos-desktop-session/1', 'url': 'http://127.0.0.1:12345/?token=' + 'a' * 43}
        self.assertEqual(desktop.session_url(good), ('http://127.0.0.1:12345', 'a' * 43))
        for url in ('https://127.0.0.1:12345/?token=' + 'a' * 43,
                'http://192.168.1.30:12345/?token=' + 'a' * 43,
                'http://owner@127.0.0.1:12345/?token=' + 'a' * 43,
                'http://127.0.0.1:12345/chat?token=' + 'a' * 43,
                good['url'] + '&token=' + 'b' * 43,
                good['url'] + '&other=fixture', good['url'] + '#fixture',
                'http://127.0.0.1:12345/?token=short'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                desktop.session_url(dict(good, url=url))
        with self.assertRaises(ValueError): desktop.session_url(dict(good, schema='owner-data'))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux session process identity')
    def test_pid_reuse_or_unrelated_listener_never_opens_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / '.local/state/argos-live'
            root.mkdir(parents=True, mode=0o700)
            path = root / 'desktop-session.json'
            value = {'schema': 'argos-desktop-session/1', 'url': 'http://127.0.0.1:12345/?token=' + 'a' * 43,
                'pid': os.getpid(), 'process_start': 'wrong-fixture-start'}
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            opened = []
            with self.assertRaises(ValueError): desktop.reconnect(home, browser=opened.append)
            value['process_start'] = desktop.process_identity(os.getpid())
            path.write_text(json.dumps(value))
            with patch('argoslive.desktop.owns_port', return_value=False):
                with self.assertRaises(ValueError): desktop.reconnect(home, browser=opened.append)
            self.assertEqual(opened, [])
            self.assertEqual(json.loads(path.read_text()), value)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux session process identity')
    def test_reconnect_preserves_lab_view_for_existing_desktop_session(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / '.local/state/argos-live'
            root.mkdir(parents=True, mode=0o700)
            path = root / 'desktop-session.json'
            value = {'schema': 'argos-desktop-session/1',
                     'url': 'http://127.0.0.1:12345/?token=' + 'a' * 43,
                     'pid': os.getpid(), 'process_start': desktop.process_identity(os.getpid())}
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self, size): return b'{"schema":"argos-startup/1"}'
            class Opener:
                def open(self, request, timeout): return Response()
            opened = []
            with patch('argoslive.desktop.owns_port', return_value=True), \
                    patch('argoslive.desktop.build_opener', return_value=Opener()):
                desktop.reconnect(home, browser=opened.append, view='lab')
            self.assertEqual(opened, [desktop.dashboard_url(value['url'], 'lab')])

    @unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor cleanup')
    def test_failed_browser_start_cleans_descriptor_and_server_without_configuration_changes(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            owner = home / 'owner-data'
            owner.write_bytes(b'owner bytes')
            class Fixture:
                closed = False
                def start(self): self.fail = 'unexpected'
                def close(self): self.closed = True
                def snapshot(self): return {'schema': 'argos-startup/1'}
            controller = Fixture()
            def failed(url): raise ValueError('fixture browser unavailable')
            with self.assertRaisesRegex(ValueError, 'fixture browser'):
                desktop.serve(home, home, browser=failed, controller=controller, stop=threading.Event())
            self.assertTrue(controller.closed)
            self.assertFalse(hasattr(controller, 'fail'))
            self.assertFalse((home / 'desktop-session.json').exists())
            self.assertFalse((home / '.desktop-session-new').exists())
            self.assertEqual(owner.read_bytes(), b'owner bytes')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux desktop listener')
    def test_model_lab_launch_opens_results_view_without_changing_owner_files(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            owner = home / 'owner-data'
            owner.write_bytes(b'owner bytes')
            class Fixture:
                closed = False
                def start(self): self.started = True
                def close(self): self.closed = True
                def snapshot(self): return {'schema': 'argos-startup/1'}
            controller = Fixture()
            opened = []
            stop = threading.Event()
            stop.set()
            desktop.serve(home, home, browser=opened.append, controller=controller,
                          stop=stop, view='lab')
            self.assertEqual(len(opened), 1)
            self.assertIn('&view=lab#benchmarks-title', opened[0])
            self.assertTrue(controller.started)
            self.assertTrue(controller.closed)
            self.assertEqual(owner.read_bytes(), b'owner bytes')
            self.assertFalse((home / 'desktop-session.json').exists())
