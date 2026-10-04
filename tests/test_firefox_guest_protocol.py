import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('firefox_guest', ROOT / 'scripts/qemu-firefox-check.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def frame(value):
    raw = json.dumps(value).encode()
    return str(len(raw)).encode() + b':' + raw


class Connection:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = b''
    def recv(self, size):
        # Fragment every body as a real local socket may do.
        count = min(size, 2, len(self.incoming))
        value = bytes(self.incoming[:count])
        del self.incoming[:count]
        return value
    def sendall(self, value):
        self.sent += value


class FirefoxProtocolTests(unittest.TestCase):
    def test_fragmented_response_and_sequence(self):
        connection = Connection(frame({'marionetteProtocol': 3}) + frame([1, 1, None, {'value': True}]))
        driver = module.FirefoxDriver(connection)
        self.assertEqual(driver.command('WebDriver:ExecuteScript', {'script': 'return true;'}), {'value': True})
        _, payload = connection.sent.split(b':', 1)
        self.assertEqual(json.loads(payload)[:3], [0, 1, 'WebDriver:ExecuteScript'])

    def test_remote_errors_mismatches_and_oversized_frames_cannot_pass(self):
        for response in ([1, 2, None, {'value': True}],
                         [1, 1, {'message': 'fictional private URL token'}, None]):
            driver = module.FirefoxDriver(Connection(frame({'marionetteProtocol': 3}) + frame(response)))
            with self.assertRaises(ValueError) as error:
                driver.command('fixture')
            self.assertNotIn('private URL', str(error.exception))
        for incoming in (b'99999999:', b'abc:', b'10:{}', frame({'marionetteProtocol': 2})):
            with self.assertRaises(ValueError):
                module.FirefoxDriver(Connection(incoming))
