import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

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
    def test_lab_readiness_waits_for_true_dom_gate_and_stops_at_deadline(self):
        session = module.FirefoxLabSession()
        session.connection = MagicMock()
        session.driver = MagicMock()
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        session.driver.command.side_effect = [{'value': False}, {'value': True}]
        with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(module.time, 'sleep', side_effect=sleep):
            session.wait_ready(2)
        self.assertEqual(clock[0], .5)
        session.driver.command.side_effect = None
        session.driver.command.return_value = {'value': 'true'}
        with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(module.time, 'sleep', side_effect=sleep):
            with self.assertRaisesRegex(ValueError, 'launch budget'):
                session.wait_ready(2)
        self.assertEqual(clock[0], 2)

    def test_lab_click_is_a_native_element_command_not_script_or_start_api(self):
        session = module.FirefoxLabSession()
        session.connection = MagicMock()
        session.driver = MagicMock()
        session.driver.command.side_effect = [
            {'value': {'element-6066-11e4-a52e-4f735466cecf': 'test-element'}}, {}]
        session.click_baseline()
        calls = session.driver.command.call_args_list
        self.assertEqual(calls[0].args, ('WebDriver:FindElement',
                         {'using': 'css selector', 'value': '#lab-start'}))
        self.assertEqual(calls[1].args, ('WebDriver:ElementClick', {'id': 'test-element'}))
        session.driver.command.side_effect = None
        session.driver.command.return_value = {'value': {}}
        with self.assertRaisesRegex(ValueError, 'handle missing'):
            session.click_baseline()

    def test_lab_session_cleans_owned_browser_and_profile_on_failure(self):
        session = module.FirefoxLabSession()
        session.browser, session.connection, session.profile = MagicMock(), MagicMock(), MagicMock()
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with session:
                raise ValueError('fixture')
        session.browser.terminate.assert_called_once()
        session.connection.close.assert_called_once()
        session.profile.cleanup.assert_called_once()

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
