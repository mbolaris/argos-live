"""Disposable offline guest Firefox check using its built-in Marionette server."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time


class FirefoxDriver:
    def __init__(self, connection):
        self.connection = connection
        self.sequence = 0
        hello = self.read()
        if not isinstance(hello, dict) or hello.get('marionetteProtocol') != 3:
            raise ValueError('Unsupported Firefox test protocol')

    def read(self):
        prefix = bytearray()
        while True:
            value = self.connection.recv(1)
            if not value:
                raise ValueError('Firefox test connection closed')
            if value == b':':
                break
            if not value.isdigit() or len(prefix) >= 8:
                raise ValueError('Invalid Firefox test frame')
            prefix.extend(value)
        if not prefix or not 0 < int(prefix) <= 1024**2:
            raise ValueError('Firefox test frame exceeds limit')
        remaining, raw = int(prefix), bytearray()
        while remaining:
            value = self.connection.recv(remaining)
            if not value:
                raise ValueError('Firefox test frame interrupted')
            raw.extend(value)
            remaining -= len(value)
        return json.loads(raw)

    def command(self, name, parameters=None):
        self.sequence += 1
        raw = json.dumps([0, self.sequence, name, parameters or {}]).encode()
        self.connection.sendall(str(len(raw)).encode() + b':' + raw)
        response = self.read()
        if (not isinstance(response, list) or len(response) != 4 or
                response[:2] != [1, self.sequence] or response[2] is not None):
            # Never include remote error text, which may contain the session URL.
            raise ValueError('Firefox test command failed')
        return response[3]


def ready_firefox(env, url, timeout=240):
    def stage(name):
        print('ARGOS_C3_STAGE firefox-' + name, flush=True)
    profile = Path(tempfile.mkdtemp(prefix='argos-ci-firefox-'))
    (profile / 'user.js').write_text('\n'.join([
        'user_pref("browser.shell.checkDefaultBrowser", false);',
        'user_pref("browser.aboutwelcome.enabled", false);',
        'user_pref("browser.startup.homepage_override.mstone", "ignore");',
        'user_pref("gfx.webrender.software", true);']), encoding='utf-8')
    browser = subprocess.Popen(['firefox', '--no-remote', '--marionette', '--kiosk',
                                '--profile', str(profile), 'about:blank'], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    stage('starting')
    connection = None
    try:
        while time.monotonic() < deadline:
            if browser.poll() is not None:
                raise ValueError('Test Firefox exited during startup')
            try:
                connection = socket.create_connection(('127.0.0.1', 2828), timeout=1)
                break
            except OSError:
                time.sleep(2)
        if connection is None:
            raise ValueError('Test Firefox did not start')
        with connection:
            stage('connected')
            connection.settimeout(max(1, deadline - time.monotonic()))
            driver = FirefoxDriver(connection)
            driver.command('WebDriver:NewSession', {'acceptInsecureCerts': False})
            stage('session')
            driver.command('WebDriver:Navigate', {'url': url})
            stage('navigated')
            probe = '''return {hardware: document.querySelectorAll('#hardware .card').length,
                capabilities: document.querySelectorAll('#capabilities .card').length,
                catalog: document.querySelectorAll('#model-catalog .card').length,
                refreshed: document.getElementById('refresh')?.disabled === false};'''
            last = None
            while time.monotonic() < deadline:
                connection.settimeout(max(1, deadline - time.monotonic()))
                reply = driver.command('WebDriver:ExecuteScript',
                    {'script': probe, 'args': [], 'newSandbox': True, 'sandbox': 'default',
                     'line': 1, 'filename': 'public-argos-ci-probe.js'})
                value = reply.get('value')
                if value != last:
                    print('ARGOS_C3_FIREFOX ' + json.dumps(value), flush=True)
                    last = value
                if (isinstance(value, dict) and value.get('hardware') == 8 and
                        value.get('capabilities') == 10 and value.get('catalog', 0) >= 8 and
                        value.get('refreshed') is True):
                    # Test-only URL redaction, after the app captured its token.
                    # The original product does not strip its query parameter.
                    driver.command('WebDriver:ExecuteScript', {'script':
                        "history.replaceState(null, '', location.pathname); return true;",
                        'args': [], 'newSandbox': True, 'sandbox': 'default', 'line': 1,
                        'filename': 'public-argos-ci-redact.js'})
                    stage('ready')
                    time.sleep(5)  # Allow the validated DOM to paint before QMP capture.
                    return browser
                time.sleep(2)
        raise ValueError('Firefox dashboard content did not become ready')
    except BaseException:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill(); browser.wait(timeout=10)
        raise
