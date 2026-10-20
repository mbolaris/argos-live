import errno
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from synthetic_http import SyntheticHTTPServer


@unittest.skipUnless(sys.platform == 'linux', 'Linux TCP listener and TIME_WAIT behavior')
class SyntheticPortTests(unittest.TestCase):
    def test_reuse_never_shares_or_replaces_a_live_listener(self):
        with SyntheticHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as original:
            address = original.server_address
            self.assertEqual(original.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT), 0)
            with self.assertRaises(OSError) as error:
                with SyntheticHTTPServer(address, BaseHTTPRequestHandler):
                    self.fail('A second listener shared the fixture port')
            self.assertEqual(error.exception.errno, errno.EADDRINUSE)
            with socket.create_connection(address, timeout=2) as client:
                connection, _ = original.get_request()
                connection.close()
                self.assertEqual(client.recv(1), b'')

    def test_stopped_fixture_time_wait_does_not_block_its_successor(self):
        with SyntheticHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as original:
            address = original.server_address
            with socket.create_connection(address, timeout=2) as client:
                connection, _ = original.get_request()
                # Server closes first, leaving its endpoint in TCP TIME_WAIT.
                connection.close()
                self.assertEqual(client.recv(1), b'')
        with SyntheticHTTPServer(address, BaseHTTPRequestHandler) as successor:
            self.assertEqual(successor.server_address, address)


if __name__ == '__main__':
    unittest.main()
