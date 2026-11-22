import json
import sys
import unittest
import threading
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.web.remote_monitor import tailscale_login, RemoteMonitorServer
from argoslive.web.telemetry import _hwmon_temperatures


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


class MonitorProjectionTests(unittest.TestCase):
    def test_hwmon_reports_labelled_cpu_and_nvme_sensors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for number, name, label, value in ((0, 'k10temp', 'Tctl', '69625'),
                                                (1, 'nvme', 'Composite', '54850'),
                                                (2, 'iwlwifi', 'Tctl', '47000')):
                device = root / f'hwmon{number}'
                device.mkdir()
                (device / 'name').write_text(name)
                (device / 'temp1_label').write_text(label)
                (device / 'temp1_input').write_text(value)
            cpu, nvme = _hwmon_temperatures(root)
            self.assertEqual(cpu, [{'sensor': 'k10temp Tctl', 'temperature_c': 69.6}])
            self.assertEqual(nvme, [{'sensor': 'nvme Composite', 'temperature_c': 54.9}])

    def test_private_monitor_exposes_only_selected_activity_and_speed_fields(self):
        class Campaign:
            def snapshot(self):
                return {'active': True, 'progress': {'campaign_steps': [
                    {'tool': 'edit', 'step_status': 'rejected', 'secret': 'never expose'}],
                    'current': {}, 'evaluation_runs': []}}
        class Startup:
            def snapshot(self):
                return {'phase': 'ready', 'model': 'local', 'metrics': {
                    'generation_tokens_per_second': 12.5, 'time_to_first_token_seconds': 2.0,
                    'secret': 'never expose'}}
        server = RemoteMonitorServer(proctor_campaign=Campaign(), startup=Startup(), store=None,
                                     port=0, allowed_login='owner@example.test')
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(worker.join, 3)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with self.assertRaises(HTTPError) as denied:
            urlopen(base + '/api/telemetry', timeout=3)
        self.assertEqual(denied.exception.code, 403)
        denied.exception.close()
        headers = {'Tailscale-User-Login': 'owner@example.test', 'X-Forwarded-Proto': 'https'}
        with patch('argoslive.web.remote_monitor.telemetry.snapshot', return_value={'schema': 'sample'}):
            with urlopen(Request(base + '/api/telemetry', headers=headers), timeout=3) as response:
                data = json.load(response)
        self.assertEqual(data['assistant']['generation_tokens_per_second'], 12.5)
        self.assertNotIn('secret', data['assistant'])
        with urlopen(Request(base + '/api/monitor/campaign', headers=headers), timeout=3) as response:
            data = json.load(response)
        self.assertEqual(data['steps'][0]['step_status'], 'rejected')
        self.assertNotIn('secret', data['steps'][0])


if __name__ == '__main__':
    unittest.main()
