import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.web.remote_monitor import tailscale_login


class TailscaleIdentityTests(unittest.TestCase):
    def test_uses_status_profile_when_available(self):
        status = {'BackendState': 'Running', 'Self': {'UserProfile': {'LoginName': 'owner@example.test'}}}
        with patch('argoslive.web.remote_monitor.shutil.which', return_value='/usr/bin/tailscale'), \
             patch('argoslive.web.remote_monitor.subprocess.run', return_value=type('Result', (), {
                 'stdout': json.dumps(status), 'stderr': '', 'returncode': 0})()):
            self.assertEqual(tailscale_login(), 'owner@example.test')

    def test_resolves_missing_status_profile_with_whois(self):
        status = {'BackendState': 'Running', 'Self': {'TailscaleIPs': ['100.64.0.1']}}
        whois = {'UserProfile': {'LoginName': 'owner@example.test'}}
        results = [
            type('Result', (), {'stdout': json.dumps(status), 'stderr': '', 'returncode': 0})(),
            type('Result', (), {'stdout': json.dumps(whois), 'stderr': '', 'returncode': 0})(),
        ]
        with patch('argoslive.web.remote_monitor.shutil.which', return_value='/usr/bin/tailscale'), \
             patch('argoslive.web.remote_monitor.subprocess.run', side_effect=results) as run:
            self.assertEqual(tailscale_login(), 'owner@example.test')
        self.assertEqual(run.call_args_list[1].args[0],
                         ['/usr/bin/tailscale', 'whois', '--json', '100.64.0.1'])

    def test_fails_closed_when_tailscale_is_not_running(self):
        status = {'BackendState': 'NeedsLogin', 'Self': {'TailscaleIPs': ['100.64.0.1']}}
        with patch('argoslive.web.remote_monitor.shutil.which', return_value='/usr/bin/tailscale'), \
             patch('argoslive.web.remote_monitor.subprocess.run', return_value=type('Result', (), {
                 'stdout': json.dumps(status), 'stderr': '', 'returncode': 0})()) as run:
            self.assertIsNone(tailscale_login())
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
