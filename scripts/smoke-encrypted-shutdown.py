#!/usr/bin/env python3
"""Three cold shutdowns of an exact ISO on a disposable encrypted virtual USB.

Root execution is allowed only in a disposable GitHub-hosted runner. No physical
device is an input. Never repair or replay the test filesystem before checking it.
"""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import selectors
import stat
import subprocess
import tempfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_boot', ROOT / 'scripts/smoke-qemu-iso.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


def command(args, **options):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          env={**os.environ, 'LC_ALL': 'C'}, timeout=options.pop('timeout', 180), **options).stdout


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def filesystem_header(text):
    fields = dict(re.findall(r'^([^:\n]+):\s*([^\n]*)$', text, re.M))
    if fields.get('Filesystem state', '').strip() != 'clean':
        raise ValueError('Stopped persistence filesystem is not clean; no repair attempted')
    if 'needs_recovery' in fields.get('Filesystem features', '').split():
        raise ValueError('Stopped persistence filesystem needs journal replay; no repair attempted')
    return {name: fields.get(name, '').strip() for name in
            ('Filesystem UUID', 'Filesystem state', 'Filesystem features')}


def checked_files(receipt, cycle):
    if receipt.get('cycle') != cycle or receipt.get('scope') != 'synthetic persistence sentinels':
        raise ValueError('Unexpected guest receipt')
    files = receipt.get('files')
    if not isinstance(files, dict) or len(files) != cycle * 2:
        raise ValueError('Missing persistence record/snapshot sentinels')
    decoded = {}
    for name, value in files.items():
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or
                not name.startswith('home/argos/.local/state/argos-live/shutdown-test/')):
            raise ValueError('Guest reported an unexpected backup path')
        raw = base64.b64decode(value['base64'], validate=True)
        if len(raw) > 4096 or hashlib.sha256(raw).hexdigest() != value['sha256']:
            raise ValueError('Guest backup hash differs')
        decoded[name] = raw
    upper = PurePosixPath(receipt.get('upper_relative', ''))
    if upper.as_posix() != 'rw':
        raise ValueError('Unexpected persistence upper-directory layout')
    return decoded


def guest_payload(nonce, cycle):
    source = f'''
import base64,hashlib,json,os,subprocess,time
from pathlib import Path
assert 'argos.shutdown_test={nonce}' in Path('/proc/cmdline').read_text().split()
assert Path.home()==Path('/home/argos')
assert not subprocess.check_output(['ip','route'],text=True).strip()
deadline=time.monotonic()+90
while subprocess.run(['systemctl','is-active','--quiet','argos-shutdown-root.service']).returncode:
 if time.monotonic()>deadline:raise RuntimeError('Shutdown-root service did not become active')
 time.sleep(1)
subprocess.run(['sudo','-n','test','-x','/run/initramfs/shutdown'],check=True)
assert subprocess.check_output(['findmnt','-n','-o','FSTYPE','-M','/run/initramfs'],text=True).strip()=='tmpfs'
root=Path.home()/'.local/state/argos-live/shutdown-test'
root.mkdir(parents=True,exist_ok=True)
assert len(list(root.glob('*.json')))==({cycle}-1)*2
for kind in ['record','snapshot']:
 p=root/('{cycle}-'+kind+'.json')
 with p.open('xb') as f:
  f.write(json.dumps({{'scope':'synthetic persistence sentinels','cycle':{cycle},'kind':kind,'nonce':'{nonce}'}}).encode())
  f.flush();os.fsync(f.fileno())
fd=os.open(root,os.O_RDONLY);os.fsync(fd);os.close(fd)
files={{}}
for p in sorted(root.glob('*.json')):
 b=p.read_bytes();files[p.relative_to('/').as_posix()]={{'base64':base64.b64encode(b).decode(),'sha256':hashlib.sha256(b).hexdigest()}}
print('ARGOS_SHUTDOWN_READY '+json.dumps({{'scope':'synthetic persistence sentinels','cycle':{cycle},'upper_relative':'rw','files':files}}),flush=True)
'''
    wrapped = ('try:\n' + ''.join(' ' + line + '\n' for line in source.splitlines()) +
               "except Exception as e:\n print('ARGOS_SHUTDOWN_FAIL '+type(e).__name__,flush=True)\n")
    encoded = base64.b64encode(zlib.compress(wrapped.encode())).decode()
    line = f"python3 -c \"import base64,zlib;exec(zlib.decompress(base64.b64decode('{encoded}')))\"\n"
    if len(line) > 3500:
        raise ValueError('Guest payload exceeds the serial terminal line budget')
    return line


def write_json(path, value):
    with path.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def cold_cycle(work, output, append, key, cycle, previous):
    nonce = secrets.token_hex(16)
    args = ['qemu-system-x86_64', '-accel', 'tcg', '-cpu', 'max', '-smp', '2', '-m', '4096',
            '-display', 'none', '-nic', 'none', '-no-reboot', '-monitor', 'none', '-serial', 'stdio',
            '-kernel', str(work / 'kernel'), '-initrd', str(work / 'initrd'),
            '-append', append + ' systemd.unit=multi-user.target argos.shutdown_test=' + nonce,
            '-drive', f'file={work / "TEST-DO-NOT-WRITE.raw"},format=raw,if=none,id=media',
            '-device', 'qemu-xhci', '-device', 'usb-storage,drive=media,removable=on']
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    serial = bytearray()
    unlocked = logged_in = password = payload = powering_off = False
    receipt = None
    deadline = time.monotonic() + 900
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                for event, _ in selector.select(.5):
                    chunk = event.fileobj.read1(65536)
                    serial.extend(chunk)
                if len(serial) > 16 * 1024**2:
                    raise ValueError('Guest serial output exceeded its bound')
                text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', serial.decode(errors='replace')).replace('\r', '')
                tail = text[-32768:]
                def send(value):
                    process.stdin.write(value.encode()); process.stdin.flush()
                if not unlocked and re.search(r'Please unlock disk|Enter passphrase for|Please enter passphrase', tail, re.I):
                    send(key + '\n'); unlocked = True
                elif unlocked and not logged_in and re.search(r'login:\s*$', tail):
                    send('argos\n'); logged_in = True
                elif logged_in and not password and re.search(r'Password:\s*$', tail):
                    send('live\n'); password = True
                elif logged_in and not payload and re.search(r'argos@[^\n]+\$\s*$', tail):
                    send(guest_payload(nonce, cycle)); payload = True
                if re.search(r'\nARGOS_SHUTDOWN_FAIL \w+\n', text):
                    raise ValueError('Guest rejected shutdown preparation; see serial evidence')
                ready = re.search(r'\nARGOS_SHUTDOWN_READY (\{[^\n]+\})\n', text)
                if ready and not powering_off:
                    receipt = json.loads(ready[1])
                    decoded = checked_files(receipt, cycle)
                    if any(decoded.get(name) != raw for name, raw in previous.items()):
                        raise ValueError('Earlier record/snapshot changed across a cold boot')
                    # This backup is durable outside the guest BEFORE poweroff.
                    write_json(output / f'cycle-{cycle}-backup.json', receipt)
                    send('sudo -n /sbin/poweroff\n'); powering_off = True
                if process.poll() is not None:
                    serial.extend(process.stdout.read())
                    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', serial.decode(errors='replace')).replace('\r', '')
                    if process.returncode != 0 or not powering_off:
                        raise ValueError('QEMU exited without successful requested poweroff')
                    marker = text.rfind('ARGOS_EXITRD_ENTERED:')
                    if marker < 0:
                        raise ValueError('Shutdown never entered the RAM environment')
                    final = text[marker:]
                    if ('All filesystems, swaps, loop devices, MD devices and DM devices detached.' not in final or
                            'Unable to finalize remaining' in final):
                        raise ValueError('RAM shutdown did not confirm complete storage detachment')
                    return receipt
            raise ValueError('Encrypted guest shutdown timed out; forced cleanup is not a passing shutdown')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=10)
        # Only sanitized serial, never the key/raw disk, enters public evidence.
        (output / f'cycle-{cycle}-console.log').write_bytes(bytes(serial).replace(key.encode(), b'[TEST KEY REDACTED]'))
        process.stdin.close(); process.stdout.close()


@contextmanager
def stopped_mapping(disk, key_file):
    loop = command(['losetup', '--read-only', '--find', '--show', '--partscan', str(disk)]).strip()
    name = 'argos-shutdown-check-' + secrets.token_hex(8)
    opened = False
    try:
        if command(['losetup', '-n', '-O', 'BACK-FILE', loop]).strip() != str(disk):
            raise ValueError('Read-only loop does not belong to this virtual disk')
        if command(['blockdev', '--getro', loop]).strip() != '1':
            raise ValueError('Virtual-disk loop is not read-only')
        command(['cryptsetup', 'open', '--readonly', '--key-file', str(key_file), loop + 'p4', name])
        opened = True
        mapping = '/dev/mapper/' + name
        if command(['blockdev', '--getro', mapping]).strip() != '1':
            raise ValueError('Decrypted test mapping is not read-only')
        yield mapping
    finally:
        if opened:
            command(['cryptsetup', 'close', name])
        command(['losetup', '-d', loop])


def offline_check(work, output, key_file, receipt, cycle):
    files = checked_files(receipt, cycle)
    with stopped_mapping(work / 'TEST-DO-NOT-WRITE.raw', key_file) as mapping:
        header = command(['dumpe2fs', '-h', mapping])
        (output / f'cycle-{cycle}-superblock.txt').write_text(header)
        clean = filesystem_header(header)
        checked = subprocess.run(['e2fsck', '-f', '-n', mapping], capture_output=True, text=True,
                                 env={**os.environ, 'LC_ALL': 'C'}, timeout=300)
        (output / f'cycle-{cycle}-fsck.txt').write_text(checked.stdout + checked.stderr)
        if checked.returncode != 0:
            raise ValueError('Read-only filesystem check found errors; no repair attempted')
        mount = work / 'inspection'
        mount.mkdir(exist_ok=True)
        command(['mount', '-o', 'ro,noload,nodev,nosuid,noexec', mapping, str(mount)])
        try:
            for name, original in files.items():
                path = mount / 'rw' / name
                cursor = mount
                for part in path.relative_to(mount).parts:
                    cursor = cursor / part
                    if cursor.is_symlink():
                        raise ValueError('Linked persistence sentinel was refused')
                if path.read_bytes() != original:
                    raise ValueError('Persisted record/snapshot differs from the pre-poweroff backup')
        finally:
            command(['umount', str(mount)])
    return {'cycle': cycle, 'superblock': clean, 'read_only_fsck_exit': checked.returncode,
            'backup_files_verified': len(files), 'journal_replay_or_repair': False}


def run(iso, output):
    if (os.name != 'posix' or os.geteuid() != 0 or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise ValueError('This test requires an explicitly approved disposable GitHub-hosted root runner')
    if iso.is_symlink() or not stat.S_ISREG(iso.stat().st_mode):
        raise ValueError('Expected a regular ISO file, never a device')
    checksum = (iso.parent / 'SHA256SUMS').read_text().strip()
    actual = digest(iso)
    if checksum != actual + '  argos-live-amd64.iso':
        raise ValueError('ISO checksum differs from the build artifact')
    build = json.loads((iso.parent / 'build-report.json').read_text())
    commit = command(['git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT), 'rev-parse', 'HEAD']).strip()
    if build.get('commit') != commit or build.get('iso_sha256') != actual:
        raise ValueError('The test checkout must match the exact ISO build commit')
    if output.exists():
        raise ValueError('Choose a new evidence directory')
    # Evidence is sanitized and publishable. Keys/disks live in a separate
    # private directory, never below the artifact upload directory.
    output.mkdir(mode=0o755, parents=True)
    result = {'schema': 'argos-encrypted-shutdown/1', 'commit': commit, 'iso_sha256': actual,
              'passed': False, 'cycles': [], 'firmware_boot_verified': False,
              'scope': 'exact-ISO direct-kernel encrypted virtual USB; synthetic records; not physical-card acceptance'}
    try:
        with tempfile.TemporaryDirectory(prefix='argos-shutdown-private-') as temporary:
            work = Path(temporary)
            key = secrets.token_hex(32)
            key_file = work / 'test-only.key'
            key_file.write_text(key); key_file.chmod(0o600)
            command(['bash', str(ROOT / 'scripts/make-vm-image.sh'), str(iso),
                     str(work / 'TEST-DO-NOT-WRITE.raw'), '24G', str(key_file)], timeout=600)
            def extract(source, target):
                command(['xorriso', '-osirrox', 'on', '-indev', str(iso), '-extract', source, str(target)])
            extract('/boot/grub/grub.cfg', work / 'grub.cfg')
            kernel, initrd, append = boot.desktop_entry((work / 'grub.cfg').read_text())
            extract(kernel, work / 'kernel'); extract(initrd, work / 'initrd')
            previous = {}
            for cycle in range(1, 4):
                print(f'Encrypted shutdown cycle {cycle}/3 started.', flush=True)
                receipt = cold_cycle(work, output, append, key, cycle, previous)
                result['cycles'].append(offline_check(work, output, key_file, receipt, cycle))
                previous = checked_files(receipt, cycle)
                write_json(output / 'result.json', result)
                print(f'Cycle {cycle}: clean before replay; saved records verified.', flush=True)
            result['passed'] = True
    except BaseException as error:
        result['failure'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        write_json(output / 'result.json', result)
        for path in output.iterdir():
            if path.is_file():
                path.chmod(0o644)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.iso.absolute(), args.output.absolute())
