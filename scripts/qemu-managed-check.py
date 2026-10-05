"""Observe shipped autostart in an offline disposable guest; never start services."""
import json
import ctypes
from http.client import HTTPException
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError


def log_flags(raw):
    """Publish fixed diagnostic indicators, never log text or extracted values."""
    text = raw.decode(errors='replace').lower()
    groups = {
        'listening_reported': ('listening on', 'gateway listening'),
        'configuration_error': ('invalid config', 'config invalid', 'unrecognized key'),
        'address_in_use': ('eaddrinuse', 'address already in use'),
        'permission_error': ('eacces', 'permission denied'),
        'missing_dependency': ('cannot find module', 'module not found', 'err_module_not_found'),
        'memory_failure': ('out of memory', 'heap limit', 'allocation failed'),
        'instruction_failure': ('illegal instruction', 'sigill'),
        'error_reported': ('"level":"error"', '"level":"fatal"', 'unhandled', 'error:'),
        'plugin_activity': ('plugin', 'extension'),
    }
    return {key: any(term in text for term in terms) for key, terms in groups.items()}


def private_log_observation(path):
    """Inspect only an owner-only regular log; emit a bounded fixed vocabulary."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {'state': 'absent'}
    except OSError:
        return {'state': 'unavailable'}
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            return {'state': 'unsafe'}
        os.lseek(fd, max(0, info.st_size - 65536), os.SEEK_SET)
        raw = os.read(fd, 65536)
        return {'state': 'readable', 'nonempty': bool(raw), 'flags': log_flags(raw)}
    finally:
        os.close(fd)


def gateway_observation(home, opener):
    from argoslive.web.status import gateway, read_json
    try:
        origin = gateway(read_json(home / '.openclaw/openclaw.json'))
    except (OSError, ValueError, AttributeError, TypeError):
        return {'state': 'configuration_unavailable'}
    port = int(origin.rsplit(':', 1)[1])
    listener = False
    node_count = 0
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            comm = (process / 'comm').read_text().strip()
            if comm not in ('node', 'openclaw', 'openclaw-gatewa'):
                continue
            node_count += 1
            from argoslive.owned_ollama import owns_port
            listener = listener or owns_port(int(process.name), port)
        except OSError:
            continue
    health = {'reachable': False, 'status': None, 'ready': False}
    try:
        with opener.open(origin + '/readyz', timeout=1) as response:
            health['reachable'], health['status'] = True, response.status
            raw = response.read(16385)
            if len(raw) <= 16384:
                health['ready'] = json.loads(raw).get('ready') is True
    except HTTPError as error:
        health['reachable'], health['status'] = True, error.code
        error.close()
    except (OSError, ValueError, AttributeError, HTTPException):
        pass
    root = home / '.local/state/argos-live'
    return {'same_user_node_processes': min(node_count, 32),
        'same_user_gateway_listener': listener, 'health': health,
        'gateway_log': private_log_observation(root / 'gateway.log'),
        'supervisor_log': private_log_observation(root / 'gateway-supervisor.log')}


def fullscreen_capture():
    """Test-only F11 on the verified Firefox window hides tokenized browser chrome."""
    env = dict(os.environ, DISPLAY=':0', XAUTHORITY=str(Path.home() / '.Xauthority'))
    def property_text(window, name):
        return subprocess.check_output(['xprop', '-id', window, name], env=env, text=True, timeout=10)
    active = subprocess.check_output(['xprop', '-root', '_NET_ACTIVE_WINDOW'], env=env, text=True, timeout=10)
    match = re.search(r'0x[0-9a-fA-F]+', active)
    if not match or 'firefox' not in property_text(match[0], 'WM_CLASS').lower():
        raise ValueError('Shipped Firefox is not the active capture window')
    window = match[0]
    if '_NET_WM_STATE_FULLSCREEN' not in property_text(window, '_NET_WM_STATE'):
        x11 = ctypes.CDLL('libX11.so.6')
        xtst = ctypes.CDLL('libXtst.so.6')
        x11.XOpenDisplay.argtypes, x11.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
        x11.XKeysymToKeycode.argtypes, x11.XKeysymToKeycode.restype = [ctypes.c_void_p, ctypes.c_ulong], ctypes.c_ubyte
        x11.XFlush.argtypes = x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        display = x11.XOpenDisplay(b':0')
        if not display:
            raise ValueError('Guest capture display is unavailable')
        try:
            key = x11.XKeysymToKeycode(display, 0xffc8)
            if not key or not xtst.XTestFakeKeyEvent(display, key, 1, 0) or not xtst.XTestFakeKeyEvent(display, key, 0, 0):
                raise ValueError('Guest fullscreen capture key failed')
            x11.XFlush(display)
        finally:
            x11.XCloseDisplay(display)
        deadline = time.monotonic() + 15
        while '_NET_WM_STATE_FULLSCREEN' not in property_text(window, '_NET_WM_STATE'):
            if time.monotonic() >= deadline:
                raise ValueError('Firefox browser chrome was not hidden for capture')
            time.sleep(.5)
    time.sleep(5)


def firefox_connected(port):
    """An actual Firefox process must hold a gateway TCP connection."""
    remote = f'0100007F:{port:04X}'
    connections = {row.split()[9] for row in Path('/proc/net/tcp').read_text().splitlines()[1:]
                   if row.split()[2] == remote and row.split()[3] == '01'}
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid() or 'firefox' not in Path(os.readlink(process / 'exe')).name:
                continue
            for descriptor in (process / 'fd').iterdir():
                try:
                    if os.readlink(descriptor) in {'socket:[' + inode + ']' for inode in connections}:
                        return True
                except (FileNotFoundError, ProcessLookupError):
                    continue
        except (OSError, IndexError):
            continue
    return False


def backend_observation(opener):
    """Bounded fixture-only diagnostics: no command lines, environment or logs."""
    from argoslive.owned_ollama import PIN
    items = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid() or (process / 'comm').read_text().strip() != 'ollama':
                continue
            inodes = set()
            readable = True
            try:
                for descriptor in (process / 'fd').iterdir():
                    try: inodes.add(os.readlink(descriptor))
                    except (FileNotFoundError, ProcessLookupError): continue
            except PermissionError:
                readable = False
            listeners = {}
            for table in ('tcp', 'tcp6'):
                rows = (process / 'net' / table).read_text().splitlines()[1:]
                listeners[table] = any(row.split()[1].endswith(':2CAA') and row.split()[3] == '0A'
                    and 'socket:[' + row.split()[9] + ']' in inodes for row in rows)
            items.append({'pid': int(process.name), 'fd_readable': readable, 'owned_listener': listeners})
            if len(items) >= 8: break
        except (OSError, IndexError):
            continue
    reachable = False
    try:
        with opener.open('http://127.0.0.1:11434/api/version', timeout=1) as response:
            reachable = json.load(response).get('version') == PIN
    except OSError:
        pass
    return {'processes': items, 'pinned_api_reachable': reachable}


def managed_check(started, desktop_seconds):
    from argoslive.desktop import session_url
    from argoslive.ollama import NoRedirect
    from argoslive import starter
    from argoslive.web.status import gateway
    home = Path.home()
    descriptor = home / '.local/state/argos-live/desktop-session.json'
    deadline = time.monotonic() + 1200
    print('ARGOS_C3_STAGE managed-startup', flush=True)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    last = None
    stable_since = None
    last_backend = None
    last_gateway = None
    while time.monotonic() < deadline:
        if not descriptor.exists():
            time.sleep(2)
            continue
        origin, token = session_url(json.loads(descriptor.read_text()))
        request = Request(origin + '/api/startup', headers={'X-Argos-Token': token})
        with opener.open(request, timeout=15) as response:
            report = json.load(response)
        phase = report['phase']
        if phase != last:
            print('ARGOS_C3_MANAGED ' + json.dumps({'phase': phase, 'failure': report.get('failure')}), flush=True)
            last = phase
        if phase in ('gateway', 'ready', 'failed'):
            observed = gateway_observation(home, opener)
            if observed != last_gateway:
                print('ARGOS_C3_GATEWAY ' + json.dumps(observed), flush=True)
                last_gateway = observed
        if phase in ('failed', 'stopped'):
            raise ValueError('Shipped automatic startup failed')
        if phase == 'model-service':
            observed = backend_observation(opener)
            if observed != last_backend:
                print('ARGOS_C3_BACKEND ' + json.dumps(observed), flush=True)
                last_backend = observed
        if phase == 'ready':
            config = json.loads((home / '.openclaw/openclaw.json').read_text())
            # Public first-boot configuration uses OpenClaw's default port.
            # Resolve it through the same validator as the shipped launcher.
            port = int(gateway(config).rsplit(':', 1)[1])
            metrics = report.get('metrics')
            if not report['model_reply_verified'] or metrics['backend']['mode'] != 'CPU':
                raise ValueError('Automatic startup did not establish a measured CPU reply')
            if report['auto_open_chat'] is False and firefox_connected(port):
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 5:
                    break
            else:
                stable_since = None
        time.sleep(2)
    else:
        raise ValueError('Automatic browser/gateway startup exceeded the guest deadline')
    state = json.loads((home / '.config/argos-live/state.json').read_text())
    if state.get('mode') != 'try' or state.get('model_source') != 'bundled':
        raise ValueError('Automatic setup did not use immutable try-mode starter')
    starter.read_only()
    if any(path.name != '.argos-storage-id' for path in Path(state['storage']).iterdir()):
        raise ValueError('Automatic setup copied model files')
    fullscreen_capture()
    print('ARGOS_C3_STAGE managed-browser', flush=True)
    print('ARGOS_C3_RESULT ' + json.dumps({'schema': 'argos-qemu-managed/1',
        'desktop_started': True, 'network_routes': False, 'dashboard_authenticated': True,
        'setup_mode': 'managed', 'automatic_first_boot': True, 'bundled_read_only_source': True,
        'model_reply_verified': True, 'startup_metrics': metrics, 'handoff_claimed': True,
        'firefox_gateway_connection': True, 'desktop_wait_seconds': desktop_seconds,
        'managed_elapsed_seconds': report['elapsed_seconds'],
        'ready_seconds': time.monotonic() - started, 'physical_acceptance': False,
        'browser_chat_reply_verified': False, 'requires_screenshot_review': True}), flush=True)
    # The host captures the actual shipped Firefox; no substitute test browser.
    time.sleep(30)
