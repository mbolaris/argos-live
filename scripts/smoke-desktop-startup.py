#!/usr/bin/env python3
"""Hosted managed startup/reopen/stop acceptance with actual pinned local services."""
import argparse
from contextlib import contextmanager
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, starter, storage
from argoslive.desktop import reconnect, serve, session_url
from argoslive.ollama import NoRedirect
from argoslive.owned_gateway import owned as gateway_owned
from argoslive.owned_ollama import owned as backend_owned, owns_port
from argoslive.startup import Controller


def run(cli, ollama, seed):
    scratch = storage.safe_local(Path(os.environ.get('RUNNER_TEMP', '/missing')).absolute())
    seed = storage.safe_local(seed.absolute())
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0 or
            scratch not in seed.parents):
        raise ValueError('Desktop smoke requires an unprivileged hosted public fixture')
    identity = starter.read_only(seed)
    with tempfile.TemporaryDirectory(prefix='argos-desktop-smoke-', dir=scratch) as temp:
        home = Path(temp)
        root = home / '.local/state/argos-live'
        root.mkdir(parents=True, mode=0o700)
        selected = home / 'managed-models'
        def configure(home, **options):
            return auto_setup.configure(home, planner=lambda required: {'path': str(selected),
                'kind': 'disk', 'encrypted': None}, verify_seed=lambda: starter.read_only(seed),
                probe_persistence=lambda: {'active': False, 'encrypted': None}, **options)
        controller = Controller(home, configure=configure,
            backend=lambda target, **options: backend_owned(target, executable=ollama, **options),
            gateway=lambda home, **options: gateway_owned(home, executable=cli, **options))
        stop = threading.Event()
        errors = []
        def launch():
            try:
                serve(home, root, controller=controller, stop=stop, no_browser=True)
            except Exception:
                errors.append('Managed desktop fixture failed')
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with patch.object(starter, 'ROOT', seed):
            thread = threading.Thread(target=launch, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 360
                while not (root / 'desktop-session.json').exists():
                    if errors or time.monotonic() >= deadline:
                        raise ValueError('Managed desktop descriptor was not published')
                    time.sleep(.1)
                origin, token = session_url(json.loads((root / 'desktop-session.json').read_text()))
                def request(path, method='GET'):
                    req = Request(origin + path, data=b'' if method == 'POST' else None,
                        method=method, headers={'X-Argos-Token': token, 'Origin': origin})
                    with opener.open(req, timeout=5) as response:
                        raw = response.read(65537)
                    if len(raw) > 65536:
                        raise ValueError('Managed desktop response exceeds the bound')
                    return json.loads(raw)
                while True:
                    report = request('/api/startup')
                    if report['phase'] == 'ready': break
                    if report['phase'] == 'failed' or errors or time.monotonic() >= deadline:
                        raise ValueError('Managed desktop did not reach native readiness: ' + json.dumps(report.get('failure')))
                    time.sleep(.5)
                if not report['model_reply_verified'] or report['metrics']['backend']['mode'] != 'CPU':
                    raise ValueError('Managed desktop model CPU reply was not established')
                original = (home / '.openclaw/openclaw.json').read_bytes()
                worker = controller.worker
                for _ in range(3): request('/api/startup/start', 'POST')
                if controller.worker is not worker:
                    raise ValueError('Repeated start replaced the active managed worker')
                opened = []
                reconnect(home, browser=opened.append)
                if len(opened) != 1 or controller.worker is not worker:
                    raise ValueError('Desktop reopen did not reuse the verified session')
                chat = urlsplit(request('/api/startup/chat', 'POST')['url'])
                if chat.hostname != '127.0.0.1' or chat.path != '/chat' or not chat.fragment.startswith('token='):
                    raise ValueError('Managed chat handoff did not use local token authentication')
                try:
                    request('/api/startup/chat', 'POST')
                except HTTPError as error:
                    if error.code != 409: raise
                else:
                    raise ValueError('Automatic chat handoff was claimed twice')
                request('/api/startup/stop', 'POST')
                controller.worker.join(timeout=30)
                if controller.snapshot()['phase'] != 'stopped' or controller.worker.is_alive():
                    raise ValueError('Managed service shutdown did not finish')
                if (home / '.openclaw/openclaw.json').read_bytes() != original:
                    raise ValueError('Managed controls changed owner configuration')
                if any(path.is_file() and path.name != '.argos-storage-id' for path in selected.rglob('*')):
                    raise ValueError('Managed startup copied model weights')
                entered = threading.Event()
                listener = []
                @contextmanager
                def blocked_backend(target, **options):
                    with backend_owned(target, executable=ollama, **options) as client:
                        # Pause only the listener validated by this fresh owned
                        # lease. A pidfd anchors the signal against PID reuse.
                        candidates = []
                        for path in Path('/proc').iterdir():
                            try:
                                if (path.name.isdigit() and path.stat().st_uid == os.geteuid()
                                        and owns_port(int(path.name), 11434)):
                                    candidates.append(int(path.name))
                            except (FileNotFoundError, ProcessLookupError):
                                continue
                        if len(candidates) != 1:
                            raise ValueError('Fixture-owned listener is not unique')
                        pid = candidates[0]
                        descriptor = os.pidfd_open(pid)
                        try:
                            if not owns_port(pid, 11434):
                                raise ValueError('Fixture-owned listener changed')
                            signal.pidfd_send_signal(descriptor, signal.SIGSTOP)
                            listener.append(pid)
                            original_open = client._open
                            def waiting_open(*args, **kwargs):
                                entered.set()
                                return original_open(*args, **kwargs)
                            client._open = waiting_open
                            yield client
                        finally:
                            os.close(descriptor)
                def unexpected_gateway(*args, **kwargs):
                    raise ValueError('Stopped warmup reached gateway startup')
                blocked = Controller(home, configure=configure, backend=blocked_backend,
                    gateway=unexpected_gateway)
                try:
                    blocked.start()
                    if not entered.wait(180) or blocked.snapshot()['phase'] != 'first-reply':
                        raise ValueError('Native blocked warmup was not established')
                    time.sleep(.2)
                    if not blocked.reply_worker.is_alive():
                        raise ValueError('Native warmup did not remain blocked')
                    began_stop = time.monotonic()
                    blocked.stop()
                    blocked.worker.join(timeout=30)
                    if blocked.reply_worker is not None:
                        blocked.reply_worker.join(timeout=5)
                    stopped = blocked.snapshot()
                    if (time.monotonic() - began_stop > 30 or stopped['phase'] != 'stopped'
                            or stopped['active'] or stopped['failure'] is not None
                            or not listener or owns_port(listener[0], 11434)):
                        raise ValueError('Native blocked warmup did not stop and clean up')
                    if (home / '.openclaw/openclaw.json').read_bytes() != original:
                        raise ValueError('Blocked warmup changed owner configuration')
                finally:
                    blocked.close()
            finally:
                stop.set()
                thread.join(timeout=30)
            if thread.is_alive() or errors or (root / 'desktop-session.json').exists():
                raise ValueError('Managed desktop session did not clean up')
    if starter.verify(seed) != identity:
        raise ValueError('Managed desktop altered immutable model weights')
    return {'schema': 'argos-desktop-startup-smoke/1', 'automatic_setup': True,
        'native_gateway': True, 'local_cpu_reply': True, 'reused_worker': True,
        'verified_session_reopen': True, 'once_only_chat_handoff': True, 'stop_cleanup': True,
        'blocked_warmup_stop_verified': True,
        'configuration_unchanged': True, 'weights_copied': False, 'startup_metrics': report['metrics'],
        'browser_conversation_verified': False, 'physical_acceptance': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', type=Path, required=True)
    parser.add_argument('--ollama', type=Path, required=True)
    parser.add_argument('--seed', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.openclaw.absolute(), args.ollama.absolute(), args.seed), indent=2))
