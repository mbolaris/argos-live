"""Observe shipped autostart in an offline disposable guest; never start services."""
import json
import ctypes
import errno
from http.client import HTTPException
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError, URLError


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
        'node_warning': ('experimentalwarning', 'deprecationwarning'),
        'unsettled_await': ('unsettled top-level await',),
        'prewarm_failure': ('post-ready gateway data prewarm failed',),
        'plugin_service_failure': ('plugin services failed to start',),
        'hook_failure': ('failed to load hooks', 'gateway startup hook failed'),
        'channel_failure': ('channel startup failed',),
        'sidecar_failure': ('gateway sidecars failed to start', 'failed after gateway ready'),
        'authentication_failure': ('pairing required', 'token mismatch', 'unauthorized'),
        'javascript_type_error': ('typeerror:',),
        'javascript_reference_error': ('referenceerror:',),
        'network_timeout': ('etimedout', 'connect timeout', 'headers timeout'),
        'connection_refused': ('econnrefused',),
        'missing_file': ('enoent',),
        'database_error': ('sqlite_error', 'sqlite_cantopen', 'sqlite_busy'),
    }
    return {key: any(term in text for term in terms) for key, terms in groups.items()}


def startup_trace(raw):
    """Admit only known upstream stage names and bounded numeric timings."""
    # Fixed names reviewed in the integrity-verified pinned upstream package.
    # Never admit dynamic skills/agent IDs, filenames, metric strings or errors.
    stages = ('entry.bootstrap', 'entry.argv', 'entry.run-main-import', 'ready',
        'plugins.runtime-post-bind', 'post-attach.system-ca', 'post-attach.log',
        'sidecars.total', 'sidecars.internal-hooks', 'sidecars.model-runtime',
        'sidecars.model-auth', 'sidecars.reply-runtime', 'sidecars.chat-metadata',
        'sidecars.channels', 'sidecars.channel-start', 'sidecars.channel-skip',
        'sidecars.plugin-services', 'sidecars.main-session-recovery',
        'post-ready.gateway-data.connection', 'post-ready.gateway-data.chat.history',
        'post-ready.gateway-data.chat.send', 'post-ready.gateway-data.sessions.list',
        'post-ready.gateway-data.session-history-worker', 'post-ready.gateway-data.agent-events',
        'post-ready.gateway-data.session-key', 'post-ready.gateway-data.context-window-cache',
        'post-ready.gateway-data.memory-search', 'post-ready.gateway-data.plugins')
    records = {}
    pattern = re.compile(r'startup trace: ([a-z.-]+) ([0-9.]+)ms total=([0-9.]+)ms'
                         r'(?: eventLoopMax=([0-9.]+)ms)?')
    for stage, duration, total, event_loop in pattern.findall(raw.decode(errors='replace')):
        if stage not in stages:
            continue
        try:
            duration, total = float(duration), float(total)
            if not 0 <= duration <= total <= 3600000:
                continue
        except ValueError:
            continue
        records[stage] = {'duration_ms': duration, 'total_ms': total}
        if event_loop:
            try:
                delay = float(event_loop)
                if 0 <= delay <= 3600000:
                    records[stage]['event_loop_max_ms'] = delay
            except ValueError:
                pass
    return records


def owned_exit(raw):
    """Only a whole fixed numeric record; never expose arbitrary log fields."""
    result = None
    for value in re.findall(rb'^ARGOS_OWNED_EXIT returncode=(-?[0-9]{1,3})$', raw, re.MULTILINE):
        code = int(value)
        if -64 <= code <= 255:
            result = code
    return result


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
        return {'state': 'readable', 'nonempty': bool(raw), 'bytes': info.st_size,
                'flags': log_flags(raw), 'startup_trace': startup_trace(raw),
                'owned_exit_code': owned_exit(raw)}
    finally:
        os.close(fd)


def resource_observation(proc=Path('/proc')):
    """Fixed numeric guest facts; no paths, arguments or environment values."""
    memory = {key: None for key in ('MemAvailable', 'SwapTotal', 'SwapFree')}
    counters = {key: None for key in ('oom_kill', 'pgmajfault')}
    for filename, wanted, unit in (('meminfo', memory, 'kB'), ('vmstat', counters, None)):
        try:
            raw = (proc / filename).read_text()[:65536]
            for line in raw.splitlines():
                parts = line.split()
                key = parts[0].rstrip(':') if parts else ''
                if (key in wanted and len(parts) == (3 if unit else 2)
                        and parts[1].isdigit() and (unit is None or parts[2] == unit)):
                    wanted[key] = int(parts[1])
        except OSError:
            pass
    return {'memory_kib': memory, 'vm_counters': counters}


def node_observation(process):
    raw = (process / 'stat').read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    result = {'pid': int(process.name), 'state': fields[0],
        'cpu_ticks': int(fields[11]) + int(fields[12]),
        'major_faults': int(fields[9]), 'resident_pages': int(fields[21]),
        'read_bytes': None, 'read_chars': None}
    try:
        values = dict(line.split(':', 1) for line in (process / 'io').read_text().splitlines())
        for output, key in (('read_bytes', 'read_bytes'), ('read_chars', 'rchar')):
            value = values.get(key, '').strip()
            if value.isdigit(): result[output] = int(value)
    except OSError:
        pass
    return result


def probe_failure(error):
    """Fixed transport categories; no exception messages or response bodies."""
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, TimeoutError):
        return 'timeout'
    if isinstance(reason, OSError):
        return {errno.ECONNREFUSED: 'connection-refused', errno.ECONNRESET: 'connection-reset',
                errno.ETIMEDOUT: 'timeout', errno.ENETUNREACH: 'network-unreachable'}.get(
                    reason.errno, 'transport-error')
    if isinstance(reason, HTTPException):
        return 'http-protocol-error'
    return 'invalid-response'


def gateway_observation(home, opener):
    from argoslive.web.status import gateway, read_json
    try:
        origin = gateway(read_json(home / '.openclaw/openclaw.json'))
    except (OSError, ValueError, AttributeError, TypeError):
        return {'state': 'configuration_unavailable'}
    port = int(origin.rsplit(':', 1)[1])
    listener = False
    node_count = 0
    nodes = []
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
            if len(nodes) < 8:
                nodes.append(node_observation(process))
            from argoslive.owned_ollama import owns_port
            listener = listener or owns_port(int(process.name), port)
        except (OSError, ValueError, IndexError):
            continue
    health = {'reachable': False, 'status': None, 'ready': False, 'failure': None}
    probe_started = time.monotonic()
    try:
        with opener.open(origin + '/readyz', timeout=1) as response:
            health['reachable'], health['status'] = True, response.status
            raw = response.read(16385)
            if len(raw) <= 16384:
                health['ready'] = json.loads(raw).get('ready') is True
    except HTTPError as error:
        health['reachable'], health['status'] = True, error.code
        health['failure'] = 'http-status'
        error.close()
    except (OSError, ValueError, AttributeError, HTTPException) as error:
        health['failure'] = probe_failure(error)
    health['probe_seconds'] = round(min(30, max(0, time.monotonic() - probe_started)), 3)
    root = home / '.local/state/argos-live'
    return {'same_user_node_processes': min(node_count, 32),
        'same_user_gateway_listener': listener, 'health': health,
        'node_activity': nodes, 'guest_resources': resource_observation(),
        'gateway_log': private_log_observation(root / 'gateway.log'),
        'supervisor_log': private_log_observation(root / 'gateway-supervisor.log')}


def firefox_control_page_visible():
    """Observe the active shipped page title, never publish title or URL text.

    A TCP connection can precede navigation and still leave the dashboard visible.
    This is a capture gate, not proof of an authenticated conversation or reply.
    """
    env = dict(os.environ, DISPLAY=':0', XAUTHORITY=str(Path.home() / '.Xauthority'))
    try:
        active = subprocess.check_output(['xprop', '-root', '_NET_ACTIVE_WINDOW'],
                                         env=env, text=True, timeout=10)
        match = re.search(r'0x[0-9a-fA-F]+', active)
        if not match:
            return False
        kind = subprocess.check_output(['xprop', '-id', match[0], 'WM_CLASS'],
                                       env=env, text=True, timeout=10)
        if 'firefox' not in kind.lower():
            return False
        title = subprocess.check_output(['xprop', '-id', match[0], '_NET_WM_NAME'],
                                        env=env, text=True, timeout=10)
        # The initial HTML title changes after the shipped app renders a session.
        # Both remain capture hints; the resulting screen still needs review.
        return bool(re.search(
            r' = "(?:OpenClaw Control(?: — Mozilla Firefox)?|'
            r'[^"\r\n]{1,160} — OpenClaw(?: — Mozilla Firefox)?)"\s*$', title))
    except (OSError, subprocess.SubprocessError):
        return False


def firefox_model_lab_visible():
    """Recognize the active shipped Argos dashboard by its fixed page title."""
    env = dict(os.environ, DISPLAY=':0', XAUTHORITY=str(Path.home() / '.Xauthority'))
    try:
        active = subprocess.check_output(['xprop', '-root', '_NET_ACTIVE_WINDOW'],
                                         env=env, text=True, timeout=10)
        match = re.search(r'0x[0-9a-fA-F]+', active)
        if not match:
            return False
        kind = subprocess.check_output(['xprop', '-id', match[0], 'WM_CLASS'],
                                       env=env, text=True, timeout=10)
        if 'firefox' not in kind.lower():
            return False
        title = subprocess.check_output(['xprop', '-id', match[0], '_NET_WM_NAME'],
                                        env=env, text=True, timeout=10)
        return bool(re.search(r' = "Argos Live · Local workspace(?: — Mozilla Firefox)?"\s*$', title))
    except (OSError, subprocess.SubprocessError):
        return False


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


def click_model_lab_baseline():
    """Click the visible Lab action through X11, as a desktop user would."""
    x11 = ctypes.CDLL('libX11.so.6')
    xtst = ctypes.CDLL('libXtst.so.6')
    x11.XOpenDisplay.argtypes, x11.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
    x11.XDisplayWidth.argtypes, x11.XDisplayWidth.restype = [ctypes.c_void_p, ctypes.c_int], ctypes.c_int
    x11.XDisplayHeight.argtypes, x11.XDisplayHeight.restype = [ctypes.c_void_p, ctypes.c_int], ctypes.c_int
    x11.XFlush.argtypes, x11.XCloseDisplay.argtypes = [ctypes.c_void_p], [ctypes.c_void_p]
    xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeMotionEvent.restype = ctypes.c_int
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                          ctypes.c_ulong]
    xtst.XTestFakeButtonEvent.restype = ctypes.c_int
    display = x11.XOpenDisplay(b':0')
    if not display:
        raise ValueError('Model Lab input display is unavailable')
    try:
        # At the verified 1280x800 acceptance resolution, this targets the
        # visible "Pause chat and test this model" button in the Lab card.
        x = int(x11.XDisplayWidth(display, 0) * .23)
        y = int(x11.XDisplayHeight(display, 0) * .63)
        if (not xtst.XTestFakeMotionEvent(display, 0, x, y, 0) or
                not xtst.XTestFakeButtonEvent(display, 1, 1, 0)):
            raise ValueError('Model Lab button click could not be sent')
        x11.XFlush(display)
        time.sleep(.15)
        if not xtst.XTestFakeButtonEvent(display, 1, 0, 0):
            raise ValueError('Model Lab button release could not be sent')
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)


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
    last_gateway_at = 0
    last_gateway_phase = None
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
        if (phase in ('gateway', 'ready', 'reconnecting', 'failed') and
                (phase != last_gateway_phase or time.monotonic() - last_gateway_at >= 15)):
            observed = gateway_observation(home, opener)
            if observed != last_gateway:
                print('ARGOS_C3_GATEWAY ' + json.dumps(observed), flush=True)
                last_gateway = observed
            last_gateway_at, last_gateway_phase = time.monotonic(), phase
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
            if (report['auto_open_chat'] is False and firefox_connected(port)
                    and firefox_control_page_visible()):
                stable_since = stable_since or time.monotonic()
                # The pinned Control page paints a loading skeleton before its
                # JavaScript initializes in TCG. Keep observing the same active
                # page/connection before capture, within the existing deadline.
                # Visual review remains mandatory; this is not reply acceptance.
                if time.monotonic() - stable_since >= 120:
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
    # Exercise the exact command installed in the Applications menu. The live
    # desktop is already owned and ready, so this follows its authenticated
    # reconnect path and opens the dedicated Lab view in shipped Firefox.
    print('ARGOS_C3_STAGE model-lab-launch', flush=True)
    lab_env = dict(os.environ, DISPLAY=':0', XAUTHORITY=str(home / '.Xauthority'))
    subprocess.run(['argos', 'desktop', '--model-lab'], check=True, timeout=20,
                   env=lab_env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    print('ARGOS_C3_STAGE model-lab-command-returned', flush=True)
    lab_deadline = time.monotonic() + 30
    while not firefox_model_lab_visible():
        if time.monotonic() >= lab_deadline:
            raise ValueError('Model Lab command did not open its shipped Firefox view')
        time.sleep(.5)
    time.sleep(5)
    if not firefox_model_lab_visible():
        raise ValueError('Model Lab view did not remain open after assistant readiness')
    print('ARGOS_C3_STAGE model-lab-visible', flush=True)
    fullscreen_capture()
    print('ARGOS_C3_STAGE managed-browser', flush=True)
    # Give the host-side QMP capture a moment to save the idle Lab screen,
    # then exercise the actual visible button rather than calling its API.
    time.sleep(5)
    print('ARGOS_C3_STAGE model-lab-button-click', flush=True)
    click_model_lab_baseline()

    def dashboard_json(path):
        request = Request(origin + path, headers={'X-Argos-Token': token})
        with opener.open(request, timeout=10) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('Model Lab status exceeded the bounded response size')
        return json.loads(raw)

    lab_value = None
    click_deadline = time.monotonic() + 20
    while time.monotonic() < click_deadline:
        lab_value = dashboard_json('/api/lab')
        if lab_value.get('active') and lab_value.get('phase') in (
                'pausing', 'model-service', 'speed', 'ability', 'cancelling'):
            break
        time.sleep(.5)
    else:
        raise ValueError('Visible Model Lab button did not start the baseline')
    print('ARGOS_C3_LAB ' + json.dumps({'phase': lab_value['phase']}), flush=True)

    lab_deadline = time.monotonic() + 900
    last_lab_phase = lab_value['phase']
    while time.monotonic() < lab_deadline:
        lab_value = dashboard_json('/api/lab')
        phase = lab_value.get('phase')
        if phase != last_lab_phase:
            if phase in ('pausing', 'model-service', 'speed', 'ability', 'cancelling',
                         'completed', 'cancelled', 'failed'):
                print('ARGOS_C3_LAB ' + json.dumps({'phase': phase}), flush=True)
            last_lab_phase = phase
        if phase in ('completed', 'cancelled', 'failed'):
            break
        time.sleep(2)
    if not lab_value or lab_value.get('phase') != 'completed':
        raise ValueError('Visible Model Lab baseline did not complete successfully')
    run_ids = lab_value.get('runs')
    if not isinstance(run_ids, list) or len(run_ids) != 2 or any(
            not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id)
            for run_id in run_ids):
        raise ValueError('Model Lab did not save both baseline runs')
    benchmark_rows = dashboard_json('/api/benchmarks').get('runs')
    saved_rows = [row for row in benchmark_rows if row.get('id') in run_ids]
    if (len(saved_rows) != 2 or {row.get('kind') for row in saved_rows} != {'speed', 'ability'}
            or not lab_value.get('resume_requested')):
        raise ValueError('Model Lab results or assistant resume request are missing')
    print('ARGOS_C3_STAGE model-lab-results-saved', flush=True)

    resumed = False
    resume_deadline = time.monotonic() + 300
    while time.monotonic() < resume_deadline:
        startup_value = dashboard_json('/api/startup')
        if (startup_value.get('phase') == 'ready' and
                startup_value.get('model_reply_verified') is True and
                startup_value.get('auto_open_chat') is False):
            resumed = True
            break
        if startup_value.get('phase') in ('failed', 'stopped'):
            break
        time.sleep(2)
    if not resumed or not firefox_model_lab_visible():
        raise ValueError('Assistant did not resume while keeping Model Lab open')
    print('ARGOS_C3_STAGE model-lab-assistant-resumed', flush=True)
    print('ARGOS_C3_RESULT ' + json.dumps({'schema': 'argos-qemu-managed/1',
        'desktop_started': True, 'network_routes': False, 'dashboard_authenticated': True,
        'model_lab_launcher_available': True,
        'model_lab_launch_command_succeeded': True, 'model_lab_ui_visible': True,
        'model_lab_button_clicked': True, 'model_lab_baseline_completed': True,
        'model_lab_speed_result_saved': True, 'model_lab_ability_result_saved': True,
        'model_lab_assistant_resumed': True,
        'setup_mode': 'managed', 'automatic_first_boot': True, 'bundled_read_only_source': True,
        'model_reply_verified': True, 'startup_metrics': metrics, 'handoff_claimed': True,
        'firefox_gateway_connection': True, 'firefox_control_page_visible': True,
        'desktop_wait_seconds': desktop_seconds,
        'managed_elapsed_seconds': report['elapsed_seconds'],
        'ready_seconds': time.monotonic() - started, 'physical_acceptance': False,
        'browser_chat_reply_verified': False, 'requires_screenshot_review': True}), flush=True)
    # The host captures the actual shipped Firefox; no substitute test browser.
    time.sleep(30)
