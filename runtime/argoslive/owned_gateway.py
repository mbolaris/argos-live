"""Private Linux-owned OpenClaw gateway; never adopt an unrelated listener."""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

from . import addons
from .owned_ollama import owns_port, supervise, supervisor_pid
from .private_files import private_log
from .storage import safe_local
from .web.status import gateway, gateway_ready, read_json


def environment(home, config):
    # Do not override token/bind/state using inherited launcher variables.
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ') if key in os.environ}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / '.config'),
               XDG_DATA_HOME=str(home / '.local/share'), XDG_CACHE_HOME=str(home / '.cache'),
               OPENCLAW_CONFIG_PATH=str(config), OPENCLAW_STATE_DIR=str(config.parent), NO_COLOR='1')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    return env


def group_owns_port(group, port):
    # The Node host launcher may fork the actual gateway. Require a member of
    # our newly created process group, not simply a matching-version HTTP reply.
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            if int(fields[2]) == group and owns_port(int(entry.name), port):
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def settings(path):
    config = read_json(safe_local(path))
    value = config.get('gateway')
    if not isinstance(value, dict) or not isinstance(value.get('auth'), dict):
        raise ValueError('Gateway requires reviewed local token configuration')
    origin = gateway(config)
    token = value['auth'].get('token')
    if (value.get('mode') != 'local' or value.get('bind') != 'loopback' or
            value['auth'].get('mode') != 'token' or not isinstance(token, str) or not token or len(token) > 4096):
        raise ValueError('Gateway requires reviewed local token configuration')
    return origin, int(origin.rsplit(':', 1)[1])


@contextmanager
def owned(home=None, *, executable=None, config_path=None, timeout=180, cancel=None):
    if sys.platform != 'linux':
        raise ValueError('Owned gateway requires Linux')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise ValueError('Invalid gateway startup deadline')
    home = safe_local(Path.home() if home is None else Path(home))
    config_path = safe_local(config_path or home / '.openclaw/openclaw.json')
    origin, port = settings(config_path)
    # Fail before launching a CLI or creating a lease if any listener occupies it.
    with socket.socket() as reservation:
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reservation.bind(('127.0.0.1', port))
    executable = executable or shutil.which('openclaw')
    if not executable:
        raise ValueError('Pinned OpenClaw executable is unavailable')
    # npm and distro installs use a reviewed bin symlink; validate its resolved
    # executable, while owner state/log paths must remain unlinked.
    executable = str(safe_local(Path(executable).resolve(strict=True)))
    env = environment(home, config_path)
    version = subprocess.run([executable, '--version'], env=env, capture_output=True, timeout=30)
    expected = addons.load()['host_version']
    if version.returncode or expected not in re.findall(r'\d{4}\.\d+\.\d+', version.stdout.decode(errors='replace')):
        raise ValueError('OpenClaw version differs from the pinned runtime')
    root = safe_local(home / '.local/state/argos-live')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lease = safe_local(root / '.gateway-lease')
    lease.mkdir(mode=0o700, exist_ok=True)
    for path in (root, lease):
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise ValueError('Gateway runtime directories must be owner-only')
    # Supervisor alone holds the lease until the gateway group has stopped.
    deadline = time.monotonic() + timeout
    with private_log(root / 'gateway-supervisor.log') as supervisor_log:
        process = subprocess.Popen([sys.executable, '-m', 'argoslive.owned_gateway', '--supervise',
                                    executable, str(lease)], env=env, stdout=subprocess.PIPE,
                                   stderr=supervisor_log, text=True, start_new_session=True)
    try:
        group = supervisor_pid(process, deadline=deadline, cancel=cancel)
        while time.monotonic() < deadline:
            if cancel and cancel():
                raise ValueError('Owned gateway startup stopped')
            if process.poll() is not None:
                raise ValueError('Owned gateway failed to start; inspect private gateway.log')
            if group_owns_port(group, port) and gateway_ready(origin):
                yield origin
                return
            time.sleep(0.1)
        raise ValueError('Owned gateway startup timed out; inspect private gateway.log')
    finally:
        process.terminate()
        process.wait(timeout=25)
        process.stdout.close()


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--supervise':
        raise SystemExit(2)
    config = safe_local(Path(os.environ['OPENCLAW_CONFIG_PATH']))
    origin, port = settings(config)
    lease = safe_local(Path(sys.argv[3]))
    with private_log(lease.parent / 'gateway.log') as log:
        supervise(sys.argv[2], lease, arguments=['gateway', 'run', '--bind', 'loopback', '--port', str(port)], log=log)
