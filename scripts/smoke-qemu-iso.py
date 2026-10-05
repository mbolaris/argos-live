#!/usr/bin/env python3
"""Offline TCG guest acceptance of an existing checksum-verified ISO."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import selectors
import shlex
import socket
import subprocess
import tempfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]


def desktop_entry(text):
    match = re.search(r'menuentry "Argos desktop"\s*\{([^}]+)\}', text)
    if not match:
        raise ValueError('Reviewed desktop menu entry is missing')
    kernel = re.search(r'^\s*linux (.+)$', match[1], re.M)
    initrd = re.search(r'^\s*initrd (\S+)\s*$', match[1], re.M)
    if not kernel or not initrd:
        raise ValueError('Desktop kernel or initrd is missing')
    args = shlex.split(kernel[1])
    for path in (args[0], initrd[1]):
        if not path.startswith('/live/') or '..' in PurePosixPath(path).parts:
            raise ValueError('Unexpected image boot path')
    if 'boot=live' not in args[1:] or 'console=tty0' not in args[1:]:
        raise ValueError('Desktop entry lacks reviewed boot arguments')
    # Direct-kernel test adds a serial console only in the VM launch, not the ISO.
    return args[0], initrd[1], ' '.join([*args[1:], 'console=ttyS0,115200'])


def screenshot(qmp, path):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(15)
        connection.connect(str(qmp))
        stream = connection.makefile('rwb')
        json.loads(stream.readline())
        for command in ({'execute': 'qmp_capabilities'},
                        {'execute': 'screendump', 'arguments': {'filename': str(path.absolute())}}):
            stream.write(json.dumps(command).encode() + b'\n')
            stream.flush()
            while True:
                reply = json.loads(stream.readline())
                if 'error' in reply:
                    raise ValueError('QEMU screenshot failed')
                if 'return' in reply:
                    break


def guest_result(serial, *, setup_mode='interactive'):
    # Serial reads split anywhere, including after a nested JSON object's closing
    # brace. Only a complete newline-terminated record can establish acceptance.
    match = re.search(r'ARGOS_C3_RESULT (\{[^\r\n]+\})\r?\n', serial)
    if not match:
        return None
    result = json.loads(match[1])
    if setup_mode == 'managed':
        if not isinstance(result, dict) or result.get('schema') != 'argos-qemu-managed/1':
            raise ValueError('Unexpected managed guest record')
        for field in ('desktop_started', 'dashboard_authenticated', 'automatic_first_boot',
                      'bundled_read_only_source', 'model_reply_verified', 'handoff_claimed',
                      'firefox_gateway_connection', 'firefox_control_page_visible', 'requires_screenshot_review'):
            if result.get(field) is not True:
                raise ValueError('Managed guest did not establish startup acceptance')
        for field in ('network_routes', 'physical_acceptance', 'browser_chat_reply_verified'):
            if result.get(field) is not False:
                raise ValueError('Unexpected managed guest scope')
        if result.get('setup_mode') != 'managed' or result.get('startup_metrics', {}).get('backend', {}).get('mode') != 'CPU':
            raise ValueError('Managed guest did not establish CPU startup')
        return result
    if not isinstance(result, dict) or result.get('schema') != 'argos-qemu-smoke/1':
        raise ValueError('Unexpected guest acceptance record')
    for field in ('desktop_started', 'dashboard_authenticated', 'result_round_trip', 'native_firefox_dashboard'):
        if result.get(field) is not True:
            raise ValueError('Guest did not establish required acceptance')
    for field in ('network_routes', 'automatic_first_boot', 'physical_acceptance'):
        if result.get(field) is not False:
            raise ValueError('Unexpected guest acceptance scope')
    if result.get('backend') != 'CPU' or result.get('generation_limit') != 8:
        raise ValueError('Unexpected guest inference settings')
    if result.get('setup_mode') != setup_mode or result.get('bundled_read_only_source') is not (setup_mode == 'auto'):
        raise ValueError('Guest did not establish requested setup and model source')
    return result


def graphical_frame(path):
    raw = path.read_bytes()
    header = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', raw)
    if not header:
        raise ValueError('Unexpected QEMU screenshot format')
    width, height = int(header[1]), int(header[2])
    pixels = raw[header.end():]
    if width < 800 or height < 600 or len(pixels) != width * height * 3:
        raise ValueError('QEMU did not capture the configured graphical desktop')
    stride = max(3, len(pixels) // 6000 // 3 * 3)
    colors = {pixels[offset:offset + 3] for offset in range(0, len(pixels) - 2, stride)}
    if len(colors) < 9:
        raise ValueError('QEMU captured a blank or placeholder frame; review screenshot')


def guest_commands(source):
    packed = zlib.compress(source)
    encoded = base64.b64encode(packed).decode()
    path = '/tmp/argos-ci-check-' + secrets.token_hex(8)
    commands = []
    for offset in range(0, len(encoded), 1500):
        index = len(commands)
        prefix = 'stty -echo; umask 077; ' if index == 0 else ''
        redirect = '>' if index == 0 else '>>'
        commands.append(f"{prefix}printf %s '{encoded[offset:offset + 1500]}' {redirect} {path}; "
                        f"printf '\\nARGOS_C3_PAYLOAD_{index}\\n'\n")
    code = (f'import pathlib,base64,zlib,hashlib;p=pathlib.Path("{path}");'
            'b=base64.b64decode(p.read_bytes());'
            f'assert hashlib.sha256(b).hexdigest()=="{hashlib.sha256(packed).hexdigest()}";'
            'p.unlink();exec(zlib.decompress(b))')
    commands.append('python3 -c ' + shlex.quote(code) + '; stty echo\n')
    if any(len(command) >= 2000 for command in commands):
        raise ValueError('Guest command exceeds the serial line bound')
    return commands


def run(image, output, *, timeout=1800, setup_mode='interactive'):
    if setup_mode not in ('interactive', 'auto', 'managed'):
        raise ValueError('Unknown disposable setup mode')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a fresh VM output directory')
    output.mkdir(parents=True, exist_ok=True)
    record = (image.parent / 'SHA256SUMS').read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{64}  argos-live-amd64\.iso', record):
        raise ValueError('Unexpected candidate checksum record')
    digest = hashlib.sha256()
    with image.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(chunk)
    if digest.hexdigest() != record.split()[0]:
        raise ValueError('Candidate ISO checksum differs')
    source = (f'ARGOS_QEMU_SETUP_MODE = {setup_mode!r}\n'.encode() +
              (ROOT / 'scripts/qemu-firefox-check.py').read_bytes() + b'\n' +
              (ROOT / 'scripts/qemu-managed-check.py').read_bytes() + b'\n' +
              (ROOT / 'scripts/qemu-guest-check.py').read_bytes())
    guest = guest_commands(source)
    with tempfile.TemporaryDirectory(prefix='argos-qemu-') as temp:
        work = Path(temp)
        def extract(source, destination):
            subprocess.run(['xorriso', '-osirrox', 'on', '-indev', str(image), '-extract', source,
                            str(destination)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        extract('/boot/grub/grub.cfg', work / 'grub.cfg')
        kernel, initrd, append = desktop_entry((work / 'grub.cfg').read_text())
        extract(kernel, work / 'kernel')
        extract(initrd, work / 'initrd')
        qmp = work / 'qmp.sock'
        process = subprocess.Popen(['qemu-system-x86_64', '-accel', 'tcg', '-cpu', 'max', '-smp', '2',
                    '-m', '8192' if setup_mode == 'managed' else '4096', '-display', f'vnc=unix:{work / "vnc.sock"}', '-vga', 'std',
                    '-nic', 'none', '-no-reboot',
                    '-kernel', str(work / 'kernel'), '-initrd', str(work / 'initrd'), '-append', append,
                    '-cdrom', str(image), '-serial', 'stdio', '-monitor', 'none',
                    '-qmp', f'unix:{qmp},server=on,wait=off'], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        started = time.monotonic()
        print('Starting offline CPU-emulated guest; acceptance timeout is 30 minutes.', flush=True)
        reported_stages = set()
        next_heartbeat = started + 60
        tail = ''
        login_sent = password_sent = payload_sent = False
        payload_next = None
        try:
            with (output / 'console.log').open('wb') as log, selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while time.monotonic() - started < timeout:
                    if process.poll() is not None:
                        raise ValueError('QEMU exited before acceptance')
                    for key, _ in selector.select(0.5):
                        chunk = key.fileobj.read1(4096)
                        if not chunk:
                            continue
                        log.write(chunk)
                        log.flush()
                        tail = (tail + chunk.decode('utf-8', errors='replace'))[-65536:]
                    for stage in re.findall(r'ARGOS_C3_STAGE ([a-z-]+)\r?\n', tail):
                        if stage not in reported_stages:
                            reported_stages.add(stage)
                            print(f'Guest stage: {stage}', flush=True)
                    if {'cpu-inference', 'managed-browser'} & reported_stages and not (output / 'desktop.ppm').exists():
                        # Native DOM readiness plus paint delay precede this
                        # stage. Capture startup, not the idle desktop after a
                        # several-minute CPU emulation workload.
                        screenshot(qmp, output / 'desktop.ppm')
                        graphical_frame(output / 'desktop.ppm')
                    if time.monotonic() >= next_heartbeat:
                        print(f'Guest running: {int(time.monotonic() - started)} seconds; '
                              f'payload started: {payload_sent}', flush=True)
                        next_heartbeat = time.monotonic() + 60
                    if not login_sent and re.search(r'login:\s*$', tail):
                        process.stdin.write(b'argos\n'); process.stdin.flush()
                        login_sent = True
                        tail = ''
                    elif login_sent and not password_sent and re.search(r'Password:\s*$', tail):
                        process.stdin.write(b'live\n'); process.stdin.flush()
                        password_sent = True
                        tail = ''
                    elif payload_next is None and re.search(r'argos@[^\r\n]+\$\s*$', tail):
                        process.stdin.write(guest[0].encode()); process.stdin.flush()
                        payload_next = 1
                        tail = ''
                    if (payload_next is not None and not payload_sent and
                            re.search(fr'(?:^|\n)ARGOS_C3_PAYLOAD_{payload_next - 1}\r?\n', tail)):
                        process.stdin.write(guest[payload_next].encode()); process.stdin.flush()
                        payload_next += 1
                        payload_sent = payload_next == len(guest)
                        tail = ''
                    if re.search(r'ARGOS_C3_FAIL [A-Za-z]+\r?\n', tail):
                        raise ValueError('Guest acceptance failed; see console artifact')
                    result = guest_result(tail, setup_mode=setup_mode)
                    if result is not None:
                        result.update(iso_sha256=digest.hexdigest(), vm_elapsed_seconds=time.monotonic() - started,
                                      vm_memory_mib=8192 if setup_mode == 'managed' else 4096,
                                      boot_method='direct kernel/initrd from original desktop entry; serial appended',
                                      firmware_boot_verified=False)
                        if not (output / 'desktop.ppm').exists():
                            raise ValueError('Native dashboard startup screenshot missing')
                        graphical_frame(output / 'desktop.ppm')
                        result['screenshot_stage'] = ('shipped Firefox after automatic gateway handoff; test-only fullscreen'
                            if setup_mode == 'managed' else 'native Firefox dashboard before CPU benchmark')
                        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
                        print(json.dumps(result, indent=2))
                        return result
                raise ValueError('QEMU acceptance timed out; see console artifact')
        finally:
            if setup_mode != 'managed' and qmp.exists() and not (output / 'desktop.ppm').exists():
                try:
                    screenshot(qmp, output / 'desktop.ppm')
                except (OSError, ValueError):
                    pass  # Preserve the original failure and console evidence.
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--setup-mode', choices=('interactive', 'auto', 'managed'), default='interactive')
    args = parser.parse_args()
    run(args.iso.absolute(), args.output.absolute(), setup_mode=args.setup_mode)
