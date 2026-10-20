#!/usr/bin/env python3
"""Offline guest acceptance of an existing checksum-verified ISO."""
import argparse
from collections import Counter
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
GUEST_PAYLOAD_CHUNK_SIZE = 240


def desktop_entry(text, *, guest=False):
    name = 'Argos guest - resets on reboot, no passphrase' if guest else 'Argos desktop'
    match = re.search(r'menuentry "' + re.escape(name) + r'"\s*\{([^}]+)\}', text)
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
    if guest and (not {'nopersistence', 'argos.guest=1'}.issubset(args[1:]) or
                  any(arg == 'persistence' or arg.startswith('persistence-') for arg in args[1:])):
        raise ValueError('Guest boot must skip persistence and unlocking')
    # Direct-kernel test adds a serial console only in the VM launch, not the ISO.
    return args[0], initrd[1], ' '.join([*args[1:], 'console=ttyS0,115200'])


def screenshot(qmp, path):
    qmp_commands(qmp, [{'execute': 'screendump', 'arguments': {'filename': str(path.absolute())}}])


def qmp_commands(qmp, commands):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(15)
        connection.connect(str(qmp))
        stream = connection.makefile('rwb')
        json.loads(stream.readline())
        for command in [{'execute': 'qmp_capabilities'}, *commands]:
            stream.write(json.dumps(command).encode() + b'\n')
            stream.flush()
            while True:
                reply = json.loads(stream.readline())
                if 'error' in reply:
                    raise ValueError('QEMU command failed')
                if 'return' in reply:
                    break


def crop_ppm_top(raw, rows):
    """Remove browser chrome rows before any dashboard frame is saved."""
    header = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', raw)
    if not header:
        raise ValueError('Unexpected QEMU screenshot format')
    width, height = int(header[1]), int(header[2])
    pixels = raw[header.end():]
    if (width < 800 or height < 600 or rows < 0 or height - rows < 600 or
            len(pixels) != width * height * 3):
        raise ValueError('Cannot safely crop the QEMU browser frame')
    return f'P6\n{width} {height - rows}\n255\n'.encode() + pixels[width * rows * 3:]


def screenshot_dashboard_content(qmp, path):
    """Capture privately, strip Firefox's token-bearing toolbar, then publish pixels."""
    private_path = qmp.parent / ('capture-' + secrets.token_hex(8) + '.ppm')
    try:
        screenshot(qmp, private_path)
        path.write_bytes(crop_ppm_top(private_path.read_bytes(), 160))
    finally:
        private_path.unlink(missing_ok=True)


def capture_graphical_dashboard(qmp, path, *, timeout=60):
    """Wait for the newly opened browser to paint before accepting pixels."""
    deadline = time.monotonic() + timeout
    while True:
        screenshot_dashboard_content(qmp, path)
        try:
            graphical_frame(path)
            return
        except ValueError as error:
            if 'blank or placeholder' not in str(error):
                raise
            if time.monotonic() >= deadline:
                raise ValueError('QEMU browser frame remained blank after paint wait') from error
            time.sleep(.5)


def lab_progress_phase(line):
    """Return only a recognized test phase; never surface guest text in host logs."""
    try:
        value = json.loads(line)
    except (TypeError, ValueError):
        return None
    phase = value.get('phase') if isinstance(value, dict) else None
    return phase if phase == 'ability' else None


def guest_result(serial, *, setup_mode='interactive', guest=False, proctor_smoke=False):
    # Serial reads split anywhere, including after a nested JSON object's closing
    # brace. Only a complete newline-terminated record can establish acceptance.
    match = re.search(r'ARGOS_C3_RESULT (\{[^\r\n]+\})\r?\n', serial)
    if not match:
        return None
    result = json.loads(match[1])
    if guest and result.get('guest_ram_policy_verified') is not True:
        raise ValueError('Guest did not establish RAM-only workspace')
    if setup_mode == 'managed':
        if not isinstance(result, dict) or result.get('schema') != 'argos-qemu-managed/1':
            raise ValueError('Unexpected managed guest record')
        for field in ('desktop_started', 'dashboard_authenticated', 'automatic_first_boot',
                      'bundled_read_only_source', 'model_reply_verified',
                      'mission_control_visible', 'chat_destination_available', 'requires_screenshot_review',
                      'model_lab_launcher_available', 'model_lab_launch_command_succeeded',
                      'model_lab_ui_visible', 'model_lab_button_clicked',
                      'model_lab_baseline_completed', 'model_lab_speed_result_saved',
                      'model_lab_ability_result_saved', 'model_lab_assistant_resumed'):
            if result.get(field) is not True:
                raise ValueError('Managed guest did not establish startup acceptance')
        for field in ('network_routes', 'physical_acceptance', 'browser_chat_reply_verified'):
            if result.get(field) is not False:
                raise ValueError('Unexpected managed guest scope')
        if proctor_smoke:
            for field in ('proctor_practice_completed', 'proctor_transcript_saved',
                          'proctor_signature_verified', 'proctor_model_identity_bound',
                          'proctor_assistant_resumed'):
                if result.get(field) is not True:
                    raise ValueError('Managed guest did not establish Proctor acceptance')
            if (result.get('proctor_calibration_status') != 'uncalibrated' or
                    result.get('proctor_campaign_started') is not False or
                    result.get('proctor_backend_weights_loaded_attested') is not False):
                raise ValueError('Unexpected Proctor acceptance scope')
            if (not isinstance(result.get('proctor_transcript_id'), str) or
                    not re.fullmatch(r'[a-f0-9]{32}', result['proctor_transcript_id']) or
                    not isinstance(result.get('proctor_model_tag'), str) or not result['proctor_model_tag'] or
                    not isinstance(result.get('proctor_score'), dict) or
                    type(result['proctor_score'].get('correct')) is not int or
                    type(result['proctor_score'].get('total')) is not int or
                    result['proctor_score']['total'] != 4 or
                    not 0 <= result['proctor_score']['correct'] <= 4):
                raise ValueError('Managed guest Proctor receipt is incomplete')
        if result.get('setup_mode') != 'managed' or result.get('startup_metrics', {}).get('backend', {}).get('mode') != 'CPU':
            raise ValueError('Managed guest did not establish CPU startup')
        return result
    if not isinstance(result, dict) or result.get('schema') != 'argos-qemu-smoke/1':
        raise ValueError('Unexpected guest acceptance record')
    for field in ('desktop_started', 'dashboard_authenticated', 'result_round_trip', 'native_firefox_dashboard',
                  'model_lab_launcher_available'):
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
    colors = [pixels[offset:offset + 3] for offset in range(0, len(pixels) - 2, stride)]
    if len(set(colors)) < 9 or Counter(colors).most_common(1)[0][1] / len(colors) > .90:
        raise ValueError('QEMU captured a blank or placeholder frame; review screenshot')


def guest_commands(source):
    packed = zlib.compress(source)
    encoded = base64.b64encode(packed).decode()
    path = '/tmp/argos-ci-check-' + secrets.token_hex(8)
    commands = []
    # Keep serial terminal lines small: longer canonical lines have lost bytes
    # on some VM hosts even when the following completion marker was received.
    for offset in range(0, len(encoded), GUEST_PAYLOAD_CHUNK_SIZE):
        index = len(commands)
        prefix = 'stty -echo; umask 077; ' if index == 0 else ''
        redirect = '>' if index == 0 else '>>'
        commands.append(f"{prefix}printf %s '{encoded[offset:offset + GUEST_PAYLOAD_CHUNK_SIZE]}' {redirect} {path}; "
                        f"printf '\\nARGOS_C3_PAYLOAD_{index}\\n'\n")
    code = (f'import pathlib,base64,zlib,hashlib;p=pathlib.Path("{path}");'
            'b=base64.b64decode(p.read_bytes());'
            f'assert hashlib.sha256(b).hexdigest()=="{hashlib.sha256(packed).hexdigest()}";'
            'p.unlink();exec(zlib.decompress(b))')
    commands.append('python3 -c ' + shlex.quote(code) + '; stty echo\n')
    if any(len(command) >= 2000 for command in commands):
        raise ValueError('Guest command exceeds the serial line bound')
    return commands


def acceptance_payload(setup_mode, guest_mode, proctor_smoke):
    preamble = (f'ARGOS_QEMU_SETUP_MODE = {setup_mode!r}\n'
                f'ARGOS_QEMU_GUEST_MODE = {guest_mode!r}\n'
                f'ARGOS_QEMU_PROCTOR_SMOKE = {proctor_smoke!r}\n').encode()
    return (preamble + (ROOT / 'scripts/qemu-firefox-check.py').read_bytes() + b'\n' +
            (ROOT / 'scripts/qemu-managed-check.py').read_bytes() + b'\n' +
            (ROOT / 'scripts/qemu-guest-check.py').read_bytes())


def run(image, output, *, timeout=3600, setup_mode='interactive', guest_mode=False,
        proctor_smoke=False, accel='tcg'):
    if accel not in ('tcg', 'kvm'):
        raise ValueError('Unknown VM acceleration')
    if guest_mode and setup_mode != 'managed':
        raise ValueError('Guest acceptance requires managed startup')
    if proctor_smoke and (setup_mode != 'managed' or guest_mode or accel != 'kvm'):
        raise ValueError('Proctor smoke requires managed setup, persistent mode, and explicit KVM')
    if proctor_smoke and timeout == 3600:
        timeout = 5400
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
    source = acceptance_payload(setup_mode, guest_mode, proctor_smoke)
    guest = guest_commands(source)
    with tempfile.TemporaryDirectory(prefix='argos-qemu-') as temp:
        work = Path(temp)
        def extract(source, destination):
            subprocess.run(['xorriso', '-osirrox', 'on', '-indev', str(image), '-extract', source,
                            str(destination)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        extract('/boot/grub/grub.cfg', work / 'grub.cfg')
        kernel, initrd, append = desktop_entry((work / 'grub.cfg').read_text(), guest=guest_mode)
        extract(kernel, work / 'kernel')
        extract(initrd, work / 'initrd')
        qmp = work / 'qmp.sock'
        process = subprocess.Popen(['qemu-system-x86_64', '-accel', accel, '-cpu', 'host' if accel == 'kvm' else 'max', '-smp', '2',
                    '-m', '8192' if setup_mode == 'managed' else '4096', '-display', f'vnc=unix:{work / "vnc.sock"}', '-vga', 'std',
                    '-nic', 'none', '-no-reboot', '-device', 'qemu-xhci', '-device', 'usb-tablet',
                    '-kernel', str(work / 'kernel'), '-initrd', str(work / 'initrd'), '-append', append,
                    '-cdrom', str(image), '-serial', 'stdio', '-monitor', 'none',
                    '-qmp', f'unix:{qmp},server=on,wait=off'], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        started = time.monotonic()
        print(f'Starting offline {accel} guest; acceptance timeout is {int(timeout / 60)} minutes.', flush=True)
        reported_stages = set()
        reported_lab_phases = set()
        browser_paint_acknowledged = False
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
                            if stage == 'model-lab-button-activated':
                                time.sleep(2)
                                capture_graphical_dashboard(qmp, output / 'lab-click.ppm')
                    for line in re.findall(r'ARGOS_C3_LAB (\{[^\r\n]+\})\r?\n', tail):
                        phase = lab_progress_phase(line)
                        if phase and phase not in reported_lab_phases:
                            reported_lab_phases.add(phase)
                            print(f'Guest Model Lab phase: {phase}', flush=True)
                            if not (output / 'lab-progress.ppm').exists():
                                capture_graphical_dashboard(qmp, output / 'lab-progress.ppm')
                    if (setup_mode == 'managed' and 'managed-browser' in reported_stages and
                            not browser_paint_acknowledged):
                        # Capture the shipped dashboard, but let the guest's
                        # native Firefox WebDriver session perform the trusted
                        # button interaction after it verifies DOM readiness.
                        capture_graphical_dashboard(qmp, output / 'desktop.ppm')
                        browser_paint_acknowledged = True
                    elif ({'cpu-inference', 'managed-browser'} & reported_stages and
                          not (output / 'desktop.ppm').exists()):
                        # Capture startup, not the idle desktop after a
                        # several-minute CPU emulation workload.
                        capture_graphical_dashboard(qmp, output / 'desktop.ppm')
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
                    if (setup_mode == 'managed' and 'model-lab-command-returned' in reported_stages and
                            not (output / 'lab-startup.ppm').exists()):
                        # Preserve the visible state immediately after the menu command,
                        # including failures before the button interaction stage.
                        screenshot_dashboard_content(qmp, output / 'lab-startup.ppm')
                    if re.search(r'ARGOS_C3_FAIL [A-Za-z]+(?: [a-z-]+)?\r?\n', tail):
                        raise ValueError('Guest acceptance failed; see console artifact')
                    result = guest_result(tail, setup_mode=setup_mode, guest=guest_mode,
                                          proctor_smoke=proctor_smoke)
                    if result is not None:
                        result.update(iso_sha256=digest.hexdigest(), vm_elapsed_seconds=time.monotonic() - started,
                                      vm_memory_mib=8192 if setup_mode == 'managed' else 4096,
                                      vm_acceleration=accel,
                                      boot_method='direct kernel/initrd from original desktop entry; serial appended',
                                      firmware_boot_verified=False)
                        if not (output / 'desktop.ppm').exists():
                            raise ValueError('Native dashboard startup screenshot missing')
                        graphical_frame(output / 'desktop.ppm')
                        result['screenshot_stage'] = ('shipped Firefox after automatic gateway handoff; toolbar cropped before artifact'
                            if setup_mode == 'managed' else 'native Firefox dashboard before CPU benchmark')
                        if (output / 'lab-progress.ppm').exists():
                            result['lab_progress_screenshot_stage'] = (
                                'shipped Firefox during a real Model Lab ability phase; toolbar cropped before artifact')
                        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
                        print(json.dumps(result, indent=2))
                        return result
                raise ValueError('QEMU acceptance timed out; see console artifact')
        finally:
            if setup_mode != 'managed' and qmp.exists() and not (output / 'desktop.ppm').exists():
                try:
                    screenshot_dashboard_content(qmp, output / 'desktop.ppm')
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
    parser.add_argument('--guest', action='store_true', help='Test the RAM-only guest boot entry with managed startup')
    parser.add_argument('--proctor-smoke', action='store_true',
                        help='Run and verify a real bundled-model Proctor practice session; requires managed KVM')
    parser.add_argument('--accel', choices=('tcg', 'kvm'), default='tcg', help='Explicit acceleration; never silently fall back')
    args = parser.parse_args()
    run(args.iso.absolute(), args.output.absolute(), setup_mode=args.setup_mode, guest_mode=args.guest,
        proctor_smoke=args.proctor_smoke, accel=args.accel)
