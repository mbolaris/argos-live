from contextlib import closing
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
from urllib.parse import urlsplit, urlencode


def log_flags(raw):
    """Publish fixed diagnostic indicators, never log text or extracted values."""
    text = raw.decode(errors='replace').lower()
    groups = {
        'listening_reported': ('listening on', 'gateway listening'),
        'configuration_error': ('invalid config', 'config invalid', 'unrecognized key'),
        'address_in_use': ('eaddrinuse', 'address already in use'),
        'permission_error': ('eacces', 'permission denied'),
        'missing_dependency': ('cannot find module', 'module not found', 'err_module_not_found',
                               'modulenotfounderror'),
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


def gateway_log_observations(root):
    """Classify the private startup traceback alongside gateway subprocess logs."""
    return {'startup_log': private_log_observation(root / 'startup.log'),
            'gateway_log': private_log_observation(root / 'gateway.log'),
            'supervisor_log': private_log_observation(root / 'gateway-supervisor.log')}


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


def report_http_failure(check, error):
    """Emit only a fixed check label and HTTP status, never body, headers or URL."""
    allowed_checks = {'assistant-chat-availability'}
    check = check if check in allowed_checks else 'other'
    status = getattr(error, 'code', None)
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    print('ARGOS_C3_HTTP_FAILURE ' + json.dumps({'check': check, 'status': status}), flush=True)
    error.close()


def assistant_chat_target(opener, origin, token, home, *, ready_timeout=120):
    """Resolve the local chat target while the shipped gateway settles."""
    request = Request(origin + '/api/assistant/chat', headers={'X-Argos-Token': token})
    deadline = time.monotonic() + ready_timeout
    while True:
        try:
            with opener.open(request, timeout=10) as response:
                return urlsplit(json.load(response).get('url', ''))
        except HTTPError as error:
            if error.code == 409 and time.monotonic() < deadline:
                error.close()
                time.sleep(.5)
                continue
            report_http_failure('assistant-chat-availability', error)
            print('ARGOS_C3_CHAT_PREFLIGHT ' + json.dumps(
                assistant_chat_preconditions(home)), flush=True)
            raise


def assistant_chat_preconditions(home):
    """Report only booleans used by the shipped chat-destination preflight."""
    from argoslive.web.status import gateway, gateway_ready, read_json
    result = {'config_readable': False, 'gateway_config_valid': False,
              'token_mode': False,
              'token_present': False, 'token_length_valid': False,
              'gateway_ready': False}
    try:
        config = read_json(home / '.openclaw/openclaw.json')
        result['config_readable'] = True
        config_gateway = config.get('gateway', {})
        if not isinstance(config_gateway, dict):
            return result
        configured_origin = gateway(config)
        auth = config_gateway.get('auth', {})
        if not isinstance(auth, dict):
            return result
        token = auth.get('token')
        result.update({
            'gateway_config_valid': True,
            'token_mode': auth.get('mode', 'token') == 'token',
            'token_present': isinstance(token, str) and bool(token),
            'token_length_valid': isinstance(token, str) and 0 < len(token) <= 4096,
            'gateway_ready': gateway_ready(configured_origin),
        })
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return result


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
        **gateway_log_observations(root)}


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


def firefox_dashboard_window():
    """Find the shipped dashboard window without exposing its private URL."""
    env = dict(os.environ, DISPLAY=':0', XAUTHORITY=str(Path.home() / '.Xauthority'))
    try:
        clients = subprocess.check_output(['xprop', '-root', '_NET_CLIENT_LIST'],
                                          env=env, text=True, timeout=10)
        for window in re.findall(r'0x[0-9a-fA-F]+', clients):
            kind = subprocess.check_output(['xprop', '-id', window, 'WM_CLASS'],
                                           env=env, text=True, timeout=10)
            if 'firefox' not in kind.lower():
                continue
            title = subprocess.check_output(['xprop', '-id', window, '_NET_WM_NAME'],
                                            env=env, text=True, timeout=10)
            if re.search(r' = "Argos Live · Local workspace(?: — Mozilla Firefox)?"\s*$', title):
                return int(window, 16)
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def focus_firefox_dashboard():
    """Raise and focus only the exact shipped Argos Firefox window."""
    window = firefox_dashboard_window()
    if window is None:
        return False
    display = None
    try:
        x11 = ctypes.CDLL('libX11.so.6')
        x11.XOpenDisplay.argtypes, x11.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
        x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        display = x11.XOpenDisplay(b':0')
        if not display:
            return False
        x11.XRaiseWindow(display, window)
        x11.XSetInputFocus(display, window, 2, 0)
        x11.XFlush(display)
    except (OSError, AttributeError):
        return False
    finally:
        if display:
            x11.XCloseDisplay(display)
    return wait_for_active_firefox()


def wait_for_active_firefox(timeout=5):
    """Allow a short desktop focus handoff after opening the shipped dashboard."""
    deadline = time.monotonic() + timeout
    while True:
        if firefox_model_lab_visible():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.25)


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


def managed_stage(name):
    globals()['ARGOS_C3_LAST_STAGE'] = name
    print('ARGOS_C3_STAGE ' + name, flush=True)


def ready_cpu_metrics(report, *, vm_has_no_compute_gpu_passthrough=False):
    """Explain a rejected startup measurement without publishing guest text."""
    metrics = report.get('metrics')
    backend = metrics.get('backend') if isinstance(metrics, dict) else None
    backend = backend if isinstance(backend, dict) else {}
    mode = backend.get('mode')
    cpu_path = mode == 'CPU' or (vm_has_no_compute_gpu_passthrough and mode == 'split')
    if report.get('model_reply_verified') is not True or not cpu_path:
        print('ARGOS_C3_STARTUP_CHECK ' + json.dumps({
            'model_reply_verified': report.get('model_reply_verified') is True,
            'metrics_present': isinstance(metrics, dict),
            'backend_mode': mode if mode in ('CPU', 'GPU', 'split') else None,
            'backend_bytes': {key: backend[key] for key in ('size_bytes', 'vram_bytes')
                              if type(backend.get(key)) in (int, float) and
                              0 <= backend[key] <= 10**15},
            'backend_size_recorded': type(backend.get('size_bytes')) in (int, float),
            'zero_vram_recorded': type(backend.get('vram_bytes')) in (int, float)
                and backend['vram_bytes'] == 0,
            'qemu_has_no_compute_gpu_passthrough': bool(vm_has_no_compute_gpu_passthrough)}), flush=True)
        raise ValueError('Automatic startup did not establish a measured CPU reply')
    return metrics


def managed_check(started, desktop_seconds):
    with FirefoxLabSession() as native_lab:
        return managed_check_body(started, desktop_seconds, native_lab)


def proctor_session_shape(home):
    """Inspect private session structure without exporting prompts or responses."""
    rows = []
    names = {'argos_proctor_' + name for name in
             ('start', 'status', 'item', 'answer', 'continue', 'submit', 'feedback')}
    # State-directory overrides differ between SDK and gateway versions. Read
    # bounded session files in this disposable home, never publish their paths.
    for path in sorted(Path(home).rglob('*.jsonl'))[:16]:
        if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        for line in path.read_text().splitlines()[-128:]:
            try:
                value = json.loads(line).get('message', {})
                if not isinstance(value, dict) or value.get('role') not in ('assistant', 'toolResult'):
                    continue
                content = value.get('content', [])
                blocks = content if isinstance(content, list) else []
                text = '\n'.join(block.get('text', '') for block in blocks
                                 if isinstance(block, dict) and isinstance(block.get('text'), str))
                reason = value.get('stopReason')
                rows.append({'role': value['role'],
                    'stop_reason': reason if reason in ('stop', 'toolUse', 'length', 'error', 'aborted') else 'other',
                    'text_chars': len(text),
                    'text_tool_names': sorted(name for name in names if name in text),
                    'tool_calls': sorted({block['name'] if block.get('name') in names else 'other'
                        for block in blocks if isinstance(block, dict) and block.get('type') == 'toolCall'}),
                    'is_error': value.get('isError') is True})
            except (ValueError, TypeError, AttributeError):
                continue
    return rows[-64:]


def proctor_failure_diagnostics(home):
    """Publish only bounded host lifecycle facts, never arbitrary text or answers."""
    import sqlite3
    root = Path(home) / '.local/state/argos-live'
    def metadata(name):
        try:
            path = root / 'workload' / name
            if path.stat().st_size > 1024 * 1024:
                return {}
            value = json.loads(path.read_bytes())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
    turn = metadata('controller-turn.json')
    worker = metadata('controller-worker.json')
    reservation = metadata('reservation.json')
    names = {'proctor_start', 'proctor_status', 'proctor_item', 'proctor_answer',
             'proctor_continue', 'proctor_submit', 'proctor_host_submit', 'proctor_feedback', 'proctor_finalize'}
    tools = turn.get('tools', [])
    tools = tools if isinstance(tools, list) else []
    count = turn.get('host_tool_requests')
    receipt = {'turn_recorded': bool(turn), 'worker_recorded': bool(worker),
        'session_shape': proctor_session_shape(home),
        'worker_drained': worker.get('process_group_drained') is True,
        'sdk_end_observed': worker.get('sdk_end_observed') is True,
        'tool_requests': count if type(count) is int and 0 <= count <= 10000 else None,
        'tool_kinds': sorted({row.get('kind') for row in tools[:10000]
                              if isinstance(row, dict) and isinstance(row.get('kind'), str) and row['kind'] in names}),
        'reservation_state': reservation.get('state') if reservation.get('state') in
                             {'active', 'released', 'quarantined'} else 'unknown'}
    failures = turn.get('host_tool_failures', [])
    classes = {'Busy', 'ValueError', 'TypeError', 'KeyError', 'OSError', 'ProctorError',
               'OperationalError', 'TimeoutExpired', 'RuntimeError'}
    receipt['tool_failures'] = []
    if isinstance(failures, list):
        for row in failures[:32]:
            if not isinstance(row, dict):
                continue
            kind, error = row.get('kind'), row.get('error_class')
            receipt['tool_failures'].append({
                'kind': kind if isinstance(kind, str) and kind in names else 'other',
                'error_class': error if isinstance(error, str) and error in classes else 'other'})
    receipt['worker_state'] = (worker.get('state') if worker.get('state') in
                               ('starting', 'completed') else 'unknown')
    stats = turn.get('admission_diagnostics', {})
    receipt['admission_counters'] = {}
    if isinstance(stats, dict):
        rejected = stats.get('rejected', {})
        allowed = {key: stats.get(key) for key in ('tool_hooks', 'bound_calls', 'executions')}
        if isinstance(rejected, dict):
            allowed.update({key: rejected.get(key) for key in
                ('unknown_tool', 'missing_admission', 'invalid_call_id', 'stale_binding')})
        receipt['admission_counters'] = {key: value for key, value in allowed.items()
                                       if type(value) is int and 0 <= value <= 10000}
    database = root / 'proctor/state.sqlite3'
    states = {'READY', 'ACTIVE', 'BREAK', 'COMPLETED', 'ABANDONED', 'TIMED_OUT', 'INVALIDATED'}
    receipt['exam_states'] = {}
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            for state, count in db.execute('SELECT state, COUNT(*) FROM sessions GROUP BY state LIMIT 20'):
                if state in states and type(count) is int:
                    receipt['exam_states'][state] = min(count, 10000)
    except (OSError, sqlite3.Error):
        pass
    print('ARGOS_PROCTOR_DIAGNOSTICS ' + json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


def real_proctor_practice(home, opener, origin, token, dashboard_json, model_tag):
    """Verify one real bundled-model Proctor practice, then return to ready state."""
    import sqlite3
    from argoslive import startup
    from argoslive.proctor.signing import Ed25519Signer, verify_envelope

    def dashboard_post(path):
        request = Request(origin + path, data=b'', method='POST', headers={
            'X-Argos-Token': token, 'Origin': origin})
        with opener.open(request, timeout=15) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('Proctor startup control returned oversized status')
        return json.loads(raw)

    managed_stage('proctor-smoke-stop-assistant')
    dashboard_post('/api/startup/stop')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = dashboard_json('/api/startup')
        if state.get('phase') == 'stopped':
            break
        if state.get('phase') == 'failed':
            raise ValueError('Assistant did not stop cleanly for Proctor practice')
        time.sleep(1)
    else:
        raise ValueError('Assistant did not stop before Proctor practice')

    practice_error = None
    receipt = None
    failure_code = 'practice-command'
    try:
        managed_stage('proctor-practice')
        completed = subprocess.run(['argos', 'proctor', 'practice', '--json'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=2100, check=False)
        if len(completed.stdout) > 1024 * 1024 or len(completed.stderr) > 1024 * 1024:
            failure_code = 'practice-output-oversized'
            raise ValueError('Bundled-model Proctor practice command failed')
        if completed.returncode != 0:
            proctor_failure_diagnostics(home)
            failure_code = 'practice-command-nonzero'
            stderr = completed.stderr.lower()
            for marker, code in ((b'stop the existing ollama service', 'backend-still-running'),
                                 (b'stop the existing openclaw gateway', 'gateway-still-running'),
                                 (b'argos local model selection is unavailable', 'model-selection'),
                                 (b'pinned openclaw executable is unavailable', 'openclaw-unavailable'),
                                 (b'system openssl is required', 'openssl-unavailable')):
                if marker in stderr:
                    failure_code = code
                    break
            raise ValueError('Bundled-model Proctor practice command failed')
        failure_code = 'practice-json'
        practice = json.loads(completed.stdout)
        failure_code = 'practice-receipt'
        transcript_id = practice.get('transcript_id')
        result_summary = practice.get('result')
        outcome = result_summary.get('state') if isinstance(result_summary, dict) else None
        if outcome != 'COMPLETED':
            proctor_failure_diagnostics(home)
        terminal_states = {'COMPLETED', 'ABANDONED', 'TIMED_OUT', 'INVALIDATED'}
        expected_status = ('completed' if outcome == 'COMPLETED' and
                           result_summary.get('unanswered') == 0 else 'incomplete')
        if (practice.get('status') != expected_status or practice.get('practice_only') is not True or
                practice.get('calibration_status') != 'uncalibrated' or
                outcome not in terminal_states or
                not isinstance(transcript_id, str) or not re.fullmatch(r'[a-f0-9]{32}', transcript_id)):
            raise ValueError('Bundled-model Proctor practice did not return a terminal host receipt')
        managed_stage('proctor-result-' + outcome.lower())
        failure_code = 'transcript-store'
        proctor_root = home / '.local/state/argos-live/proctor'
        database_path = proctor_root / 'state.sqlite3'
        with closing(sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True, timeout=5)) as database:
            row = database.execute('SELECT envelope_json FROM transcripts WHERE session_id=?',
                                   ('sess_' + transcript_id,)).fetchone()
        if not row:
            raise ValueError('Proctor did not persist its signed transcript')
        failure_code = 'transcript-signature'
        signer = Ed25519Signer(proctor_root / 'transcript-ed25519.pem')
        envelope = json.loads(row[0])
        if not verify_envelope(envelope, signer.public_key_der):
            raise ValueError('Proctor transcript signature did not verify')
        managed_stage('proctor-signature-verified')
        failure_code = 'model-identity'
        payload = json.loads(envelope['payload_json'])
        subject = payload.get('subject', {})
        _target, verified_model, identity = startup.source(home, include_model_identity=True)
        if (verified_model != model_tag or subject.get('model_tag') != model_tag or
                subject.get('model_identity') != identity or
                subject.get('model_digest') != identity.get('sha256')):
            raise ValueError('Signed Proctor transcript does not bind the verified model source')
        managed_stage('proctor-model-identity-verified')
        failure_code = 'transcript-score'
        score = result_summary
        if (payload.get('outcome') != outcome or type(payload.get('total_items')) is not int or
                not 0 <= payload['total_items'] <= 4 or
                (outcome == 'COMPLETED' and payload['total_items'] != 4) or
                type(payload.get('accepted_correct')) is not int or
                not 0 <= payload['accepted_correct'] <= payload['total_items'] or
                score.get('correct') != payload['accepted_correct'] or
                score.get('total') != payload['total_items']):
            raise ValueError('Proctor transcript and practice receipt disagree')
        managed_stage('proctor-transcript-verified')
        receipt = {'proctor_practice_recorded': True,
            'proctor_practice_completed': expected_status == 'completed', 'proctor_practice_outcome': outcome,
            'proctor_transcript_saved': True,
            'proctor_signature_verified': True, 'proctor_model_identity_bound': True,
            'proctor_calibration_status': 'uncalibrated', 'proctor_campaign_started': False,
            'proctor_backend_weights_loaded_attested': False, 'proctor_transcript_id': transcript_id,
            'proctor_model_tag': model_tag,
            'proctor_answered': len(payload['accepted_answers']),
            'proctor_modules_submitted': (len(payload['modules']) == 2 and
                                         all(module['state'] == 'SUBMITTED' for module in payload['modules'])),
            'proctor_score': {'correct': payload['accepted_correct'], 'total': payload['total_items']}}
    except Exception:
        practice_error = failure_code
        managed_stage('proctor-practice-failed-' + failure_code)

    restart_error = None
    try:
        dashboard_post('/api/startup/start')
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            state = dashboard_json('/api/startup')
            if (state.get('phase') == 'ready' and state.get('model_reply_verified') is True and
                    state.get('model') == model_tag):
                managed_stage('proctor-assistant-resumed')
                break
            if state.get('phase') == 'failed':
                raise ValueError('Assistant restart failed')
            time.sleep(2)
        else:
            raise ValueError('Assistant restart did not reach readiness')
    except Exception:
        restart_error = True
    if restart_error:
        raise ValueError('Assistant did not resume after Proctor practice')
    if practice_error:
        raise ValueError('Real-model Proctor practice failed verification after assistant recovery')
    receipt['proctor_assistant_resumed'] = True
    return receipt


def managed_check_body(started, desktop_seconds, native_lab):
    from argoslive.desktop import session_url
    from argoslive.ollama import NoRedirect
    from argoslive import starter
    from argoslive.web.status import gateway
    home = Path.home()
    descriptor = home / '.local/state/argos-live/desktop-session.json'
    deadline = time.monotonic() + 1200
    managed_stage('managed-startup')
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
            # This harness launches only QEMU's standard VGA adapter and never
            # passes through a compute GPU. Ollama may label a software Vulkan
            # runner "split" even though all inference is on guest CPU cores.
            metrics = ready_cpu_metrics(report, vm_has_no_compute_gpu_passthrough=True)
            globals()['ARGOS_C3_LAST_STAGE'] = 'managed-chat-check'
            chat_target = assistant_chat_target(opener, origin, token, home)
            chat_available = (chat_target.scheme == 'http' and chat_target.hostname == '127.0.0.1'
                              and chat_target.path == '/chat' and chat_target.fragment.startswith('token='))
            if (report['auto_open_chat'] is False and chat_available and firefox_model_lab_visible()):
                stable_since = stable_since or time.monotonic()
                # Mission Control remains open after warm-up. The URL check only
                # confirms chat can be opened; it is not a browser reply test.
                if time.monotonic() - stable_since >= 120:
                    break
            else:
                stable_since = None
        time.sleep(2)
    else:
        raise ValueError('Automatic browser/gateway startup exceeded the guest deadline')
    state = json.loads((home / '.config/argos-live/state.json').read_text())
    is_guest = globals().get('ARGOS_QEMU_GUEST_MODE', False)
    if state.get('mode') != ('guest' if is_guest else 'try') or state.get('model_source') != 'bundled':
        raise ValueError('Automatic setup did not use immutable try-mode starter')
    starter.read_only()
    if any(path.name != '.argos-storage-id' for path in Path(state['storage']).iterdir()):
        raise ValueError('Automatic setup copied model files')
    # Exercise the exact command installed in the Applications menu. The live
    # desktop is already owned and ready, so this follows its authenticated
    # reconnect path and opens the dedicated Lab view in shipped Firefox.
    managed_stage('model-lab-launch')
    lab_env = dict(os.environ, DISPLAY=':0', XAUTHORITY=str(home / '.Xauthority'))
    subprocess.run(['argos', 'desktop', '--model-lab'], check=True, timeout=20,
                   env=lab_env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    managed_stage('model-lab-command-returned')
    lab_deadline = time.monotonic() + 60
    while not firefox_model_lab_visible():
        focus_firefox_dashboard()
        if firefox_model_lab_visible():
            break
        if time.monotonic() >= lab_deadline:
            print('ARGOS_C3_BROWSER ' + json.dumps({'dashboard_window_found':
                  firefox_dashboard_window() is not None, 'active_dashboard': False}), flush=True)
            raise ValueError('Model Lab command did not open its shipped Firefox view')
        time.sleep(.5)
    time.sleep(5)
    if not firefox_model_lab_visible():
        raise ValueError('Model Lab view did not remain open after assistant readiness')
    managed_stage('model-lab-visible')
    time.sleep(5)
    managed_stage('managed-browser')
    # Drive the shipped Firefox binary in a disposable isolated profile. The
    # native Marionette session waits for the actual enabled DOM control, then
    # sends a trusted WebDriver click; it does not call the start API directly.
    managed_stage('model-lab-button-click')
    native_lab.start(lab_env, origin + '/?' + urlencode({'token': token, 'view': 'lab'})
                     + '#lab-start', timeout=30)
    native_lab.click_baseline()
    managed_stage('model-lab-button-activated')

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
        print('ARGOS_C3_DIAG ' + json.dumps({key: (lab_value or {}).get(key) for key in
              ('available', 'active', 'phase', 'failure', 'recovery', 'model', 'error')}, default=str)[:600], flush=True)
        for path in ('/api/startup', '/api/models/control', '/api/models/selection'):
            try:
                value = dashboard_json(path)
                print('ARGOS_C3_DIAG ' + path + ' ' + json.dumps({key: value.get(key) for key in
                      ('phase', 'active', 'model', 'failure', 'model_reply_verified', 'job_id')}, default=str)[:500], flush=True)
            except Exception as error:
                print('ARGOS_C3_DIAG ' + path + ' ' + type(error).__name__, flush=True)
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
    managed_stage('model-lab-results-saved')

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
    managed_stage('model-lab-assistant-resumed')
    proctor_receipt = {}
    if globals().get('ARGOS_QEMU_PROCTOR_SMOKE', False):
        if is_guest:
            raise ValueError('Real-model Proctor smoke is unavailable in RAM-only guest mode')
        proctor_receipt = real_proctor_practice(home, opener, origin, token, dashboard_json, state['model'])
    if is_guest:
        from argoslive import session_mode, storage_view
        from argoslive.web.status import mounts_and_blocks, persistence
        mounts, blocks = mounts_and_blocks()
        if not session_mode.guest() or persistence(mounts, blocks)['active']:
            raise ValueError('Guest mode incorrectly loaded persistence')
        for _, _, path in storage_view.categories(home, state):
            if path is None:
                raise ValueError('Guest data location missing')
            session_mode.require_ram(path, mounts)
    print('ARGOS_C3_RESULT ' + json.dumps({'schema': 'argos-qemu-managed/1',
        'guest_ram_policy_verified': is_guest,
        'guest_reboot_reset_verified': False,
        'desktop_started': True, 'network_routes': False, 'dashboard_authenticated': True,
        'model_lab_launcher_available': True,
        'model_lab_launch_command_succeeded': True, 'model_lab_ui_visible': True,
        'model_lab_button_clicked': True, 'model_lab_baseline_completed': True,
        'model_lab_speed_result_saved': True, 'model_lab_ability_result_saved': True,
        'model_lab_assistant_resumed': True, 'model_lab_run_ids': run_ids,
        'model_lab_interaction': 'shipped Firefox binary; isolated Marionette test profile',
        'original_launcher_tab_interaction_verified': False,
        'setup_mode': 'managed', 'automatic_first_boot': True, 'bundled_read_only_source': True,
        'model_reply_verified': True, 'startup_metrics': metrics,
        'mission_control_visible': True, 'chat_destination_available': True,
        'desktop_wait_seconds': desktop_seconds,
        'managed_elapsed_seconds': report['elapsed_seconds'],
        'ready_seconds': time.monotonic() - started, 'physical_acceptance': False,
        'browser_chat_reply_verified': False, 'requires_screenshot_review': True,
        **proctor_receipt}), flush=True)
    # The host captures the actual shipped Firefox; no substitute test browser.
    time.sleep(30)
