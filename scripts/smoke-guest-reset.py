#!/usr/bin/env python3
"""Verify guest-state reset across a requested reboot of an exact ISO.

Only a disposable GitHub-hosted VM is supported. The input is a regular ISO,
not a physical device. This tests synthetic user state, not downloaded models.
"""
import argparse
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import stat
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_boot', ROOT / 'scripts/smoke-qemu-iso.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
BOOT_ID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')


def probe_user_state(home, phase, nonce, boot_id, mounts):
    """Check RAM backing before touching fixed synthetic paths in the guest."""
    import hashlib
    import re
    from argoslive import session_mode
    if phase not in ('seed', 'verify') or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise ValueError('Invalid reset probe')
    directories = [home / path for path in ('.openclaw', '.openclaw/workspace',
        '.openclaw/agents', '.local/share/argos-live/results', '.config/argos-live')]
    # Validate every destination before the first write. No connected disk may
    # receive a sentinel merely because a later category fails its RAM check.
    for directory in directories:
        session_mode.require_ram(directory, mounts)
    markers = [directory / ('.argos-guest-reset-' + nonce) for directory in directories]
    if any(marker.exists() or marker.is_symlink() for marker in markers):
        raise ValueError('Guest reset sentinel unexpectedly exists')
    if phase == 'seed':
        for marker in markers:
            marker.parent.mkdir(parents=True, exist_ok=True)
            with marker.open('xb') as stream:
                stream.write(nonce.encode())
                stream.flush()
            if marker.read_bytes() != nonce.encode():
                raise ValueError('Guest reset sentinel did not round-trip')
    return {'schema': 'argos-guest-reset-phase/1', 'phase': phase,
            'boot_id': boot_id, 'markers_checked': len(markers),
            'ram_backing_verified': True, 'seeded': phase == 'seed',
            'all_markers_absent': phase == 'verify',
            'marker_sha256': hashlib.sha256(nonce.encode()).hexdigest()}


def guest_payload(phase, nonce):
    return ("import json,sys\nfrom pathlib import Path\n"
            "sys.path.insert(0,'/usr/local/lib/argos-live')\n" +
            inspect.getsource(probe_user_state) + '\n' +
            "try:\n"
            " from argoslive import session_mode,storage\n"
            " from argoslive.web.status import mounts_and_blocks,persistence\n"
            " assert Path.home()==Path('/home/argos')\n"
            " assert session_mode.guest()\n"
            " assert 'nopersistence' in Path('/proc/cmdline').read_text().split()\n"
            " mounts,blocks=mounts_and_blocks()\n"
            " assert not persistence(mounts,blocks)['active']\n"
            f" result=probe_user_state(Path.home(),{phase!r},{nonce!r},"
            "Path('/proc/sys/kernel/random/boot_id').read_text().strip(),mounts)\n"
            " print('ARGOS_RESET_READY '+json.dumps(result),flush=True)\n"
            "except Exception as error:\n"
            " print('ARGOS_RESET_FAIL '+type(error).__name__,flush=True)\n").encode()


def checked_phase(value, phase, nonce):
    if (not isinstance(value, dict) or value.get('schema') != 'argos-guest-reset-phase/1'
            or value.get('phase') != phase
            or not isinstance(value.get('boot_id'), str)
            or not BOOT_ID.fullmatch(value['boot_id'])
            or type(value.get('markers_checked')) is not int or value['markers_checked'] != 5
            or value.get('ram_backing_verified') is not True
            or value.get('seeded') is not (phase == 'seed')
            or value.get('all_markers_absent') is not (phase == 'verify')
            or value.get('marker_sha256') != hashlib.sha256(nonce.encode()).hexdigest()):
        raise ValueError('Guest reset phase receipt is incomplete')
    return value


def verify_reset(first, second, nonce):
    checked_phase(first, 'seed', nonce)
    checked_phase(second, 'verify', nonce)
    if first['boot_id'] == second['boot_id']:
        raise ValueError('Guest reset requires a distinct kernel boot')
    return True


def checked_exit(returncode, requested, phase, text):
    if returncode != 0 or not requested:
        raise ValueError('VM exited without successful requested shutdown')
    if phase == 'seed' and not re.search(r'reboot: Restarting system', text):
        raise ValueError('Guest did not reach the requested kernel reboot')


def cycle(work, output, iso, append, accel, phase, nonce):
    # -no-reboot makes the first requested guest reboot exit QEMU naturally.
    # A fresh process then boots the same read-only ISO, with no writable disks.
    process = subprocess.Popen(['qemu-system-x86_64', '-accel', accel,
        '-cpu', 'host' if accel == 'kvm' else 'max', '-smp', '2', '-m', '4096',
        '-display', 'none', '-nic', 'none', '-no-reboot', '-monitor', 'none',
        '-serial', 'stdio', '-kernel', str(work / 'kernel'), '-initrd', str(work / 'initrd'),
        '-append', append + ' systemd.unit=multi-user.target', '-cdrom', str(iso)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    commands = boot.guest_commands(guest_payload(phase, nonce))
    serial = bytearray()
    logged_in = password_sent = requested = False
    payload_next = None
    receipt = None
    deadline = time.monotonic() + 900
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                for event, _ in selector.select(.5):
                    serial.extend(event.fileobj.read1(65536))
                if len(serial) > 16 * 1024**2:
                    raise ValueError('Guest reset serial output exceeded its bound')
                text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', serial.decode(errors='replace')).replace('\r', '')
                tail = text[-32768:]
                def send(value):
                    process.stdin.write(value.encode())
                    process.stdin.flush()
                if not logged_in and re.search(r'login:\s*$', tail):
                    send('argos\n')
                    logged_in = True
                elif logged_in and not password_sent and re.search(r'Password:\s*$', tail):
                    send('live\n')
                    password_sent = True
                elif payload_next is None and re.search(r'argos@[^\n]+\$\s*$', tail):
                    send(commands[0])
                    payload_next = 1
                if (payload_next is not None and payload_next < len(commands) and
                        re.search(fr'(?:^|\n)ARGOS_C3_PAYLOAD_{payload_next - 1}\n', tail)):
                    send(commands[payload_next])
                    payload_next += 1
                if re.search(r'\nARGOS_RESET_FAIL \w+\n', text):
                    raise ValueError('Guest rejected reset probe; see serial artifact')
                ready = re.search(r'\nARGOS_RESET_READY (\{[^\n]+\})\n', text)
                if ready and not requested:
                    receipt = checked_phase(json.loads(ready[1]), phase, nonce)
                    # Preserve synthetic marker receipt before leaving this boot.
                    (output / (phase + '-receipt.json')).write_text(json.dumps(receipt, indent=2) + '\n')
                    send('sudo -n /sbin/' + ('reboot' if phase == 'seed' else 'poweroff') + '\n')
                    requested = True
                if process.poll() is not None:
                    serial.extend(process.stdout.read())
                    checked_exit(process.returncode, requested, phase, serial.decode(errors='replace'))
                    return receipt
            raise ValueError('Guest reset timed out; forced cleanup does not pass')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        (output / (phase + '-console.log')).write_bytes(serial)
        process.stdin.close()
        process.stdout.close()


def run(iso, output, accel='kvm'):
    if (os.name != 'posix' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise ValueError('Use only an explicitly approved disposable GitHub-hosted VM')
    if accel not in ('kvm', 'tcg'):
        raise ValueError('Unknown VM acceleration')
    if not stat.S_ISREG(iso.stat().st_mode):
        raise ValueError('Input must be a regular ISO file')
    expected = (iso.parent / 'SHA256SUMS').read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{64}  argos-live-amd64\.iso', expected):
        raise ValueError('Unexpected ISO checksum record')
    with iso.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != expected.split()[0]:
        raise ValueError('ISO checksum differs')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a fresh output directory')
    output.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix='argos-guest-reset-') as temp:
        work = Path(temp)
        def extract(source, destination):
            subprocess.run(['xorriso', '-osirrox', 'on', '-indev', str(iso),
                '-extract', source, str(destination)], check=True, capture_output=True, timeout=180)
        extract('/boot/grub/grub.cfg', work / 'grub.cfg')
        kernel, initrd, append = boot.desktop_entry((work / 'grub.cfg').read_text(), guest=True)
        extract(kernel, work / 'kernel')
        extract(initrd, work / 'initrd')
        first = cycle(work, output, iso, append, accel, 'seed', nonce)
        second = cycle(work, output, iso, append, accel, 'verify', nonce)
    verify_reset(first, second, nonce)
    result = {'schema': 'argos-guest-reset/1', 'iso_sha256': digest, 'passed': True,
        'guest_reboot_reset_verified': True, 'markers_verified': 5,
        'kernel_boot_ids': [first['boot_id'], second['boot_id']],
        'scope': 'synthetic profile/workspace/conversation/result/settings markers; offline direct-kernel guest',
        'firmware_boot_verified': False, 'physical_acceptance': False,
        'downloaded_model_reset_verified': False, 'vm_acceleration': accel}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--accel', choices=('kvm', 'tcg'), default='kvm')
    args = parser.parse_args()
    run(args.iso.absolute(), args.output.absolute(), args.accel)
