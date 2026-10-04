#!/usr/bin/env python3
"""Executed only inside a fresh offline CI guest, never on an owner installation."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, '/usr/local/lib/argos-live')


def main():
    started = time.monotonic()
    if os.environ.get('USER') != 'argos' or Path.home() != Path('/home/argos'):
        raise ValueError('Unexpected test guest user')
    if Path('/home/argos/.config/argos-live/state.json').exists():
        raise ValueError('Test requires an unconfigured disposable guest')
    def stage(name):
        print('ARGOS_C3_STAGE ' + name, flush=True)
    stage('desktop')
    deadline = time.monotonic() + 180
    while subprocess.run(['pgrep', '-u', 'argos', '-x', 'xfce4-session'], stdout=subprocess.DEVNULL).returncode:
        if time.monotonic() >= deadline:
            raise ValueError('Desktop session did not start')
        time.sleep(2)
    desktop_seconds = time.monotonic() - started
    if subprocess.check_output(['ip', 'route'], text=True).strip():
        raise ValueError('Test guest unexpectedly has a network route')
    # Installed executable has no .py suffix; use an explicit source loader.
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader('argos_guest', SourceFileLoader('argos_guest', '/usr/local/bin/argos'))
    argos = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(argos)
    stage('temporary-setup')
    answers = iter(['TEMPORARY', 'yes', '', 'yes', ''])
    argos.setup(ask=lambda prompt: next(answers))
    state = argos.load()
    stage('ollama')
    daemon = argos.server(state)
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
        stage('cpu-inference')
        from argoslive import bench_speed
        from argoslive.ollama import Client
        # Only this disposable VM process uses eight tokens: TCG is instruction
        # emulation, not a representative machine performance measurement.
        # The result records the changed limit, so normal 128-token runs cannot
        # be compared to it. The installed runtime and ISO stay unchanged.
        bench_speed.LIMIT = 8
        result = bench_speed.run(Client(timeout=600), 'qwen3:0.6b', sizes=['short'])
        if result['prompts'][0]['skipped'] or len(result['prompts'][0]['runs']) != 3:
            raise ValueError('Starter speed benchmark did not complete')
        if any(item['backend']['mode'] != 'CPU' for item in result['prompts'][0]['runs']):
            raise ValueError('Test did not establish CPU inference')
        from argoslive.results import Store
        store = Store()
        store.save(result)
        if store.load(result['id']) != result:
            raise ValueError('Guest benchmark result did not round-trip')
        env = dict(os.environ, DISPLAY=':0', XAUTHORITY='/home/argos/.Xauthority')
        stage('firefox')
        # Helper is prepended by the host. Its test-only profile, kiosk and
        # loopback debugger do not change ordinary distro browser startup.
        browser = ready_firefox(env, base + '/?token=' + token)
        print('ARGOS_C3_RESULT ' + json.dumps({'schema': 'argos-qemu-smoke/1',
              'desktop_started': True, 'network_routes': False, 'dashboard_authenticated': True,
              'desktop_wait_seconds': desktop_seconds, 'dashboard_seconds': dashboard_seconds,
              'benchmark_seconds': result['elapsed_seconds'],
              'generation_limit': result['settings']['generation_limit'],
              'generation_tokens_per_second': result['prompts'][0]['summary']['generation_tokens_per_second'],
              'backend': 'CPU', 'result_round_trip': True, 'automatic_first_boot': False,
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
        daemon.terminate()
        daemon.wait(timeout=30)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('ARGOS_C3_FAIL ' + type(error).__name__, flush=True)
        raise SystemExit(1)
