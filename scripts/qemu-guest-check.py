#!/usr/bin/env python3
"""Executed only inside a fresh offline CI guest, never on an owner installation."""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
from urllib.error import HTTPError

sys.path.insert(0, '/usr/local/lib/argos-live')


def main():
    started = time.monotonic()
    if os.environ.get('USER') != 'argos' or Path.home() != Path('/home/argos'):
        raise ValueError('Unexpected test guest user')
    setup_mode = globals().get('ARGOS_QEMU_SETUP_MODE', 'interactive')
    if setup_mode != 'managed' and Path('/home/argos/.config/argos-live/state.json').exists():
        raise ValueError('Test requires an unconfigured disposable guest')
    def stage(name):
        globals()['ARGOS_C3_LAST_STAGE'] = name
        print('ARGOS_C3_STAGE ' + name, flush=True)
    stage('desktop')
    deadline = time.monotonic() + 180
    while subprocess.run(['pgrep', '-u', 'argos', '-x', 'xfce4-session'], stdout=subprocess.DEVNULL).returncode:
        if time.monotonic() >= deadline:
            raise ValueError('Desktop session did not start')
        time.sleep(2)
    session_pid = int(subprocess.check_output(
        ['pgrep', '-u', 'argos', '-x', 'xfce4-session'], text=True).splitlines()[0])
    session_env = dict(os.environ)
    for item in Path(f'/proc/{session_pid}/environ').read_bytes().split(b'\0'):
        if b'=' in item:
            key, value = item.split(b'=', 1)
            session_env[key.decode()] = value.decode(errors='replace')
    print('ARGOS_C3_SESSION_ENV ' + json.dumps({
        key: (session_env.get(key) if key in ('DISPLAY', 'XDG_CURRENT_DESKTOP',
                                              'XDG_SESSION_TYPE') else
              bool(session_env.get(key)))
        for key in ('DISPLAY', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE',
                    'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR')
    }, sort_keys=True), flush=True)

    def user_process_names():
        result = subprocess.run(['ps', '-u', 'argos', '-o', 'pid=,comm='],
                                capture_output=True, text=True, timeout=10)
        return ' | '.join(line.strip() for line in result.stdout.splitlines())

    def session_command(command):
        result = subprocess.run(command, env=session_env, capture_output=True, text=True,
                                timeout=10)
        if result.returncode:
            details = (result.stderr or result.stdout).strip()
            raise ValueError(f"{' '.join(command)} failed ({result.returncode}): {details}")
        return result

    # The next image ships a twelve-hour screensaver delay, while leaving idle
    # activation and the preferences UI available to the owner.
    saver_autostart = Path('/etc/xdg/autostart/xfce4-screensaver.desktop')
    if not saver_autostart.is_file():
        raise ValueError('XFCE screensaver autostart entry is unavailable')
    autostart_lines = saver_autostart.read_text(errors='replace').splitlines()
    if ('X-XFCE-Autostart-Phase=Application' not in autostart_lines or
            'X-XFCE-Autostart-Notify=true' not in autostart_lines):
        raise ValueError('XFCE screensaver must use the application autostart phase and notify readiness')
    if ('Exec=/usr/local/sbin/argos-start-screensaver' not in autostart_lines or
            'TryExec=/usr/local/sbin/argos-start-screensaver' not in autostart_lines or
            not Path('/usr/local/sbin/argos-start-screensaver').is_file()):
        raise ValueError('XFCE screensaver autostart must use the installed D-Bus readiness supervisor')
    saver_delay = session_command(['xfconf-query', '-c', 'xfce4-screensaver', '-p',
                                   '/saver/idle-activation/delay'])
    saver_enabled = session_command(['xfconf-query', '-c', 'xfce4-screensaver', '-p',
                                     '/saver/idle-activation/enabled'])
    saver_service_enabled = session_command(['xfconf-query', '-c', 'xfce4-screensaver', '-p',
                                             '/saver/enabled'])
    lock_enabled = session_command(['xfconf-query', '-c', 'xfce4-screensaver', '-p',
                                    '/lock/enabled'])
    lock_on_saver = session_command(['xfconf-query', '-c', 'xfce4-screensaver', '-p',
                                     '/lock/saver-activation/enabled'])
    saver_ui = Path('/usr/bin/xfce4-screensaver-preferences')
    if (saver_delay.stdout.strip() != '720' or saver_enabled.stdout.strip().lower() != 'true' or
            saver_service_enabled.stdout.strip().lower() != 'true' or
            lock_enabled.stdout.strip().lower() != 'false' or
            lock_on_saver.stdout.strip().lower() != 'false'):
        raise ValueError('Fresh desktop did not load the twelve-hour screensaver default')
    if not saver_ui.is_file():
        raise ValueError('Screensaver preferences are unavailable for manual control')
    # XFCE's early autostart can race the first session-bus initialization on
    # the clean image. The supervisor retries with a deliberate settle interval.
    saver_deadline = time.monotonic() + 90
    saver_ready = False
    last_saver_error = 'screensaver process has not started'
    while time.monotonic() < saver_deadline:
        process = subprocess.run(['pgrep', '-u', 'argos', '-f',
                                  r'(^|/)xfce4-screensaver($| )'],
                                 stdout=subprocess.DEVNULL)
        if process.returncode == 0:
            activate = subprocess.run(['xfce4-screensaver-command', '--activate'], env=session_env,
                                       capture_output=True, text=True, timeout=10)
            if activate.returncode == 0:
                saver_ready = True
                break
            last_saver_error = (activate.stderr or activate.stdout).strip()
        else:
            last_saver_error = 'screensaver process has not started'
        time.sleep(1)
    if not saver_ready:
        saver_pids = subprocess.run(
            ['pgrep', '-u', 'argos', '-f', r'(^|/)xfce4-screensaver($| )'],
            capture_output=True, text=True, timeout=10)
        saver_processes = []
        saver_env = []
        for pid in saver_pids.stdout.split():
            status = Path(f'/proc/{pid}/status')
            if status.is_file():
                fields = [line for line in status.read_text(errors='replace').splitlines()
                          if line.startswith(('Name:', 'State:', 'PPid:'))]
                saver_processes.append(f'{pid}: {", ".join(fields)}')
            environment = Path(f'/proc/{pid}/environ')
            if environment.is_file():
                values = dict(item.split(b'=', 1) for item in environment.read_bytes().split(b'\0')
                              if b'=' in item)
                saver_env.append({key: (values.get(key.encode(), b'').decode(errors='replace')
                                        if key in ('DISPLAY', 'XDG_SESSION_TYPE') else
                                        bool(values.get(key.encode())))
                                  for key in ('DISPLAY', 'XDG_SESSION_TYPE',
                                              'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR')})
        dbus_owner = subprocess.run(
            ['gdbus', 'call', '--session', '--dest', 'org.freedesktop.DBus',
             '--object-path', '/org/freedesktop/DBus', '--method',
             'org.freedesktop.DBus.NameHasOwner', 'org.xfce.ScreenSaver'],
            env=session_env, capture_output=True, text=True, timeout=10)
        debug_probe = 'not-run'
        debug_output = ''
        for pid in saver_pids.stdout.split():
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
        time.sleep(1)
        try:
            probe = subprocess.Popen(['xfce4-screensaver', '--debug'], env=session_env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, errors='replace')
            time.sleep(4)
            debug_owner = subprocess.run(
                ['gdbus', 'call', '--session', '--dest', 'org.freedesktop.DBus',
                 '--object-path', '/org/freedesktop/DBus', '--method',
                 'org.freedesktop.DBus.NameHasOwner', 'org.xfce.ScreenSaver'],
                env=session_env, capture_output=True, text=True, timeout=10)
            debug_probe = debug_owner.stdout.strip() or 'owner-query-failed'
            try:
                output, _ = probe.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                probe.terminate()
                output, _ = probe.communicate(timeout=5)
            debug_output = '\n'.join(
                line for line in output.splitlines()
                if any(term in line.lower() for term in ('screensaver', 'xfconf',
                                                          'error', 'warning')))[-4000:]
        except (OSError, subprocess.TimeoutExpired) as error:
            debug_probe = type(error).__name__
        user_journal = subprocess.run(
            ['journalctl', '--user', '-b', '--no-pager', '-n', '100',
             '--grep=xfce4-screensaver|screensaver'],
            env=session_env, capture_output=True, text=True, timeout=10)
        saver_runtime_log = Path(session_env.get('XDG_RUNTIME_DIR', '/run/user/1000')) / 'argos-screensaver.log'
        saver_runtime_tail = '\n'.join(saver_runtime_log.read_text(errors='replace').splitlines()[-60:]) \
            if saver_runtime_log.is_file() else ''
        session_errors = Path.home() / '.xsession-errors'
        session_error_tail = ''
        if session_errors.is_file():
            saver_lines = [line for line in session_errors.read_text(errors='replace').splitlines()
                           if 'screensaver' in line.lower()]
            session_error_tail = '\n'.join(saver_lines[-30:])
        raise ValueError('XFCE screensaver did not become ready within 30 seconds: '
                         f'{last_saver_error}; user processes: {user_process_names()}; '
                         f'screensaver process status: {saver_processes}; '
                         f'screensaver environment: {saver_env}; '
                         f'D-Bus owner: {dbus_owner.stdout.strip() or dbus_owner.stderr.strip()}; '
                         f'debug restart D-Bus owner: {debug_probe}; '
                         f'debug restart output: {debug_output}; '
                         f'supervisor startup output: {saver_runtime_tail}; '
                         f'user journal: {user_journal.stdout.strip() or user_journal.stderr.strip()}; '
                         f'session log: {session_error_tail}')
    session_command(['xfce4-screensaver-command', '--deactivate'])
    refresh = subprocess.run(['systemctl', 'is-active', '--quiet', 'argos-refresh-runtime.service'],
                             timeout=10)
    if refresh.returncode:
        raise ValueError('Argos persistence refresh did not run before the desktop')
    help_result = subprocess.run(['argos', '--help'], check=True, capture_output=True,
                                  text=True, timeout=20)
    if not re.search(r'\bdesktop\b', help_result.stdout):
        raise ValueError('The installed Argos CLI is missing the managed desktop command')
    lab_help = subprocess.run(['argos', 'desktop', '--help'], check=True, capture_output=True,
                              text=True, timeout=20)
    lab_menu = Path('/usr/share/applications/argos-model-lab.desktop').read_text()
    if '--model-lab' not in lab_help.stdout or not re.search(
            r'^Exec=argos desktop --model-lab\s*$', lab_menu, re.M):
        raise ValueError('The installed Model Lab menu does not open its dedicated dashboard view')
    desktop_seconds = time.monotonic() - started
    # Long TCG inference is unattended. Test-only anti-idle settings prevent
    # DPMS from replacing the captured VGA surface with QEMU's placeholder.
    for command in (['xset', 's', 'off'], ['xset', '-dpms'], ['xset', 's', 'noblank']):
        subprocess.run(command, env=session_env, check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if subprocess.check_output(['ip', 'route'], text=True).strip():
        raise ValueError('Test guest unexpectedly has a network route')
    if setup_mode == 'managed':
        managed_check(started, desktop_seconds)
        return
    # Installed executable has no .py suffix; use an explicit source loader.
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader('argos_guest', SourceFileLoader('argos_guest', '/usr/local/bin/argos'))
    argos = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(argos)
    stage('temporary-setup')
    if setup_mode == 'auto':
        argos.main(['setup', '--auto'])
    elif setup_mode == 'interactive':
        answers = iter(['TEMPORARY', 'yes', '', 'yes', ''])
        argos.setup(ask=lambda prompt: next(answers))
    else:
        raise ValueError('Unknown disposable setup mode')
    state = argos.load()
    if setup_mode == 'auto':
        from argoslive import starter
        if state.get('mode') != 'try' or state.get('model_source') != 'bundled':
            raise ValueError('Automatic setup did not select the bundled try session')
        starter.read_only()
        if any(path.name != '.argos-storage-id' for path in Path(state['storage']).iterdir()):
            raise ValueError('Automatic setup copied weights to writable storage')
    stage('ollama')
    # The acceptance VM has no compute GPU. Avoid Ollama's Vulkan probe under
    # TCG and retain backend diagnostics for the fixed public smoke prompt.
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    os.environ['OLLAMA_VULKAN'] = '0'
    os.environ['OLLAMA_DEBUG'] = '1'
    from argoslive.startup import source
    from argoslive.owned_ollama import owned as owned_ollama
    target, model = source(Path.home())
    backend = owned_ollama(target, port=11434, context_tokens=32768)
    client = backend.__enter__()
    client.timeout = 600
    dashboard = None
    browser = None
    try:
        stage('dashboard')
        dashboard = subprocess.Popen(['argos', 'dashboard', '--port', '8765'], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        line = dashboard.stdout.readline()
        match = re.search(r'(http://127\.0\.0\.1:8765)/\?token=([A-Za-z0-9_-]+)', line)
        if not match:
            raise ValueError('Dashboard did not start')
        base, token = match.groups()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(base + '/api/status', headers={'X-Argos-Token': token})
        with opener.open(request, timeout=60) as response:
            status = json.load(response)
        if not status['ollama']['reachable']:
            raise ValueError('Dashboard did not report the model service')
        dashboard_seconds = time.monotonic() - started
        stage('firefox')
        # Test-only profile and loopback driver; fail before slow TCG inference.
        browser = ready_firefox(session_env, base + '/?token=' + token)
        stage('cpu-inference')
        from argoslive import bench_speed
        # Only this disposable VM process uses eight tokens: TCG is instruction
        # emulation, not a representative machine performance measurement.
        # The result records the changed limit, so normal 128-token runs cannot
        # be compared to it. The installed runtime and ISO stay unchanged.
        bench_speed.LIMIT = 8
        try:
            result = bench_speed.run(client, model, sizes=['short'])
        except Exception as error:
            # Keep server details private: classify only a small, fixed set of
            # likely causes after retrying with a fixed, one-token diagnostic.
            diagnosis = 'diagnostic-request-failed'
            payload = json.dumps({'model': model, 'prompt': 'Reply OK.',
                                  'stream': False,
                                  'options': {'num_ctx': 512, 'num_predict': 1,
                                              'temperature': 0}}).encode()
            request = urllib.request.Request('http://127.0.0.1:11434/api/generate',
                                             data=payload,
                                             headers={'Content-Type': 'application/json'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(request, timeout=120):
                    diagnosis = 'diagnostic-request-passed'
            except HTTPError as response_error:
                try:
                    detail = json.loads(response_error.read(65536)).get('error', '').lower()
                except (ValueError, UnicodeError, AttributeError):
                    detail = ''
                finally:
                    response_error.close()
                if any(term in detail for term in ('out of memory', 'not enough memory',
                                                    'failed to allocate', 'could not allocate')):
                    diagnosis = 'insufficient-memory'
                elif any(term in detail for term in ('unsupported architecture',
                                                      'unsupported model', 'unknown model')):
                    diagnosis = 'unsupported-model'
                elif any(term in detail for term in ('no such file', 'cannot open',
                                                      'failed to open')):
                    diagnosis = 'missing-model-file'
                elif any(term in detail for term in ('context length', 'num_ctx')):
                    diagnosis = 'context-setting'
                elif any(term in detail for term in ('runner', 'backend', 'llama-server')):
                    diagnosis = 'runner-startup'
                else:
                    # Preserve enough controlled diagnostic context to distinguish
                    # a backend failure without exposing paths or opaque IDs in CI.
                    safe_detail = re.sub(r'(?<!\w)(?:/[^\s,;)]*|[A-Za-z]:\\[^\s,;)]*)',
                                         '<path>', detail)
                    safe_detail = re.sub(r'\b[0-9a-f]{32,}\b', '<id>', safe_detail)
                    safe_detail = re.sub(r'\s+', ' ', safe_detail).strip().lower()
                    safe_detail = re.sub(r'[^a-z0-9 .,:;_()<>-]', '?', safe_detail)[:160]
                    diagnosis = f'http-{response_error.code}-detail-{safe_detail or "empty"}'
            except (OSError, TimeoutError, ValueError):
                diagnosis = 'diagnostic-request-unreachable'
            raise ValueError(f'Starter speed benchmark failed ({type(error).__name__}); '
                             f'fixed CPU inference diagnostic: {diagnosis}') from error
        if result['prompts'][0]['skipped'] or len(result['prompts'][0]['runs']) != 3:
            raise ValueError('Starter speed benchmark did not complete')
        if any(item['backend']['mode'] != 'CPU' for item in result['prompts'][0]['runs']):
            raise ValueError('Test did not establish CPU inference')
        from argoslive.results import Store
        store = Store()
        store.save(result)
        if store.load(result['id']) != result:
            raise ValueError('Guest benchmark result did not round-trip')
        print('ARGOS_C3_RESULT ' + json.dumps({'schema': 'argos-qemu-smoke/1',
              'desktop_started': True, 'network_routes': False, 'dashboard_authenticated': True,
              'model_lab_launcher_available': True,
              'desktop_wait_seconds': desktop_seconds, 'dashboard_seconds': dashboard_seconds,
              'benchmark_seconds': result['elapsed_seconds'],
              'generation_limit': result['settings']['generation_limit'],
              'generation_tokens_per_second': result['prompts'][0]['summary']['generation_tokens_per_second'],
              'backend': 'CPU', 'result_round_trip': True, 'automatic_first_boot': False,
              'setup_mode': setup_mode, 'bundled_read_only_source': setup_mode == 'auto',
              'native_firefox_dashboard': True,
              'physical_acceptance': False}), flush=True)
        # Keep services/page alive until the host captures its screenshot.
        time.sleep(30)
    finally:
        if browser:
            browser.terminate()
            browser.wait(timeout=10)
        if dashboard:
            dashboard.terminate()
            dashboard.wait(timeout=10)
        backend.__exit__(*sys.exc_info())


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        stage = globals().get('ARGOS_C3_LAST_STAGE', 'unknown')
        print('ARGOS_C3_ERROR ' + ' '.join(str(error).split()), flush=True)
        print('ARGOS_C3_FAIL ' + type(error).__name__ + ' ' + stage, flush=True)
        raise SystemExit(1)
