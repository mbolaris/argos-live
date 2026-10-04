#!/usr/bin/env python3
"""Hosted native gateway ownership/health/UI smoke with disposable public state."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import addons, storage
from argoslive.auto_setup import conversation_config
from argoslive.owned_gateway import environment, owned
from argoslive.web.status import gateway_ready
from argoslive.ollama import NoRedirect


def run(cli):
    scratch = storage.safe_local(Path(os.environ.get('RUNNER_TEMP', '/missing')).absolute())
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Native gateway smoke requires an unprivileged hosted fixture')
    with tempfile.TemporaryDirectory(prefix='argos-native-gateway-', dir=scratch) as temp:
        home = Path(temp)
        state = home / '.openclaw'
        state.mkdir(mode=0o700)
        workspace = state / 'workspace'
        workspace.mkdir(mode=0o700)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        config = conversation_config('qwen3:0.6b', workspace)
        config['gateway']['port'] = port
        config['gateway']['auth']['token'] = 'fictional-public-gateway-health-fixture'
        path = state / 'openclaw.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        original = path.read_bytes()
        with owned(home, executable=cli) as origin:
            if not gateway_ready(origin):
                raise ValueError('Owned native gateway did not remain ready')
            health = subprocess.run([str(cli), 'gateway', 'health', '--json', '--timeout', '10000'],
                env=environment(home, path), capture_output=True, timeout=30)
            if health.returncode or len(health.stdout) > 1024**2:
                raise ValueError('Authenticated native gateway health failed')
            value = json.loads(health.stdout)
            if not isinstance(value, dict) or value.get('ok') is not True:
                raise ValueError('Native gateway health did not report success')
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(origin + '/chat', timeout=5) as response:
                html = response.read(1024**2 + 1)
                if response.status != 200 or len(html) > 1024**2 or b'<!doctype html' not in html.lower():
                    raise ValueError('Native chat UI document unavailable')
            # A second launcher must leave this gateway running.
            try:
                with owned(home, executable=cli, timeout=5):
                    raise ValueError('A second gateway unexpectedly acquired ownership')
            except OSError:
                pass
            if not gateway_ready(origin):
                raise ValueError('Competing launcher stopped the owned gateway')
        # A closed TCP connection can leave TIME_WAIT after the gateway exits;
        # that does not mean a listener is still alive. Probe new connections.
        with socket.socket() as probe:
            probe.settimeout(2)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise ValueError('Native gateway listener survived cleanup')
        if gateway_ready(origin):
            raise ValueError('Native gateway remained ready after cleanup')
        if path.read_bytes() != original:
            raise ValueError('Native startup altered the reviewed fixture configuration')
        return {'schema': 'argos-native-gateway-smoke/1', 'host_version': addons.load()['host_version'],
            'authenticated_health': True, 'ui_document': True, 'competing_launch_refused': True,
            'clean_shutdown': True, 'configuration_unchanged': True, 'model_reply_verified': False,
            'native_browser_chat_verified': False, 'physical_acceptance': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.openclaw.absolute()), indent=2))
