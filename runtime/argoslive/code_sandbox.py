"""Fail-closed Linux amd64 Python sandbox for small original code probes."""
import math
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import struct
import subprocess
import sys
import time

OUTPUT_LIMIT = 8192
SOURCE_LIMIT = 65536


def kill(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class Unavailable(ValueError):
    pass


def seccomp():
    """Native x86-64 cBPF: deny process creation, networking and namespace changes.

    Unknown architectures and x32 syscall numbers are rejected. The filter is
    inherited across exec; no network socket or child process can be created.
    """
    def instruction(code, jt=0, jf=0, value=0):
        return struct.pack('=HBBI', code, jt, jf, value)
    deny = 0x00050000 | 1  # SECCOMP_RET_ERRNO | EPERM
    program = [instruction(0x20, value=4), instruction(0x15, jt=1, value=0xc000003e),
               instruction(0x06, value=0x80000000), instruction(0x20, value=0),
               instruction(0x35, jf=1, value=0x40000000), instruction(0x06, value=deny)]
    # Linux x86-64 syscall numbers; supported architecture is checked by caller and filter.
    for number in (41, 42, 53, 56, 57, 58, 101, 155, 161, 165, 166, 248, 249, 250,
                   272, 298, 304, 308, 310, 311, 321, 323, 425, 426, 427,
                   428, 429, 430, 431, 432, 433, 435, 438):
        program += [instruction(0x15, jf=1, value=number), instruction(0x06, value=deny)]
    program.append(instruction(0x06, value=0x7fff0000))
    return b''.join(program)


def command(code_fd, filter_fd):
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise Unavailable('Code sandbox requires Linux amd64')
    bwrap = shutil.which('bwrap')
    python = Path('/usr/bin/python3')
    if not bwrap or not python.is_file():
        raise Unavailable('Code sandbox requires bubblewrap and the system Python')
    args = [bwrap, '--unshare-all', '--unshare-user', '--unshare-cgroup',
            '--die-with-parent', '--new-session', '--cap-drop', 'ALL', '--clearenv',
            '--setenv', 'PATH', '/usr/bin', '--setenv', 'HOME', '/work',
            '--ro-bind', str(python.resolve()), '/usr/bin/python3',
            '--ro-bind', '/usr/lib', '/usr/lib']
    for directory in ('/lib', '/lib64'):
        if Path(directory).is_dir():
            args += ['--ro-bind', directory, directory]
    # No home, /etc, /run, /proc, devices, host sockets or writable host mount.
    args += ['--size', str(16 * 1024**2), '--tmpfs', '/work', '--chdir', '/work',
             '--file', str(code_fd), '/work/main.py', '--remount-ro', '/',
             '--seccomp', str(filter_fd), '--', '/usr/bin/python3', '-I', '-S', '-B', '/work/main.py']
    return [sys.executable, '-I', str(Path(__file__).with_name('sandbox_limits.py')), *args]


def run(source, *, timeout=3.0, cancel=None):
    if not isinstance(source, str):
        raise ValueError('Code source must be text')
    raw = source.encode('utf-8')
    if not 1 <= len(raw) <= SOURCE_LIMIT:
        raise ValueError('Code source exceeds the sandbox bound')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0.1 <= timeout <= 10:
        raise ValueError('Sandbox timeout must be 0.1–10 seconds')
    # Validate the platform before using Linux-only descriptor and signal APIs.
    command(0, 0)
    started = time.monotonic()
    descriptors = []
    process = None
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    state = None
    try:
        for name, data in [('argos-code', raw), ('argos-filter', seccomp())]:
            fd = os.memfd_create(name, os.MFD_CLOEXEC)
            descriptors.append(fd)
            os.write(fd, data)
            os.lseek(fd, 0, os.SEEK_SET)
        process = subprocess.Popen(command(*descriptors), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   pass_fds=descriptors, start_new_session=True,
                                   env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            while selector.get_map():
                if cancel is not None and cancel.is_set():
                    state = 'cancelled'
                    break
                if time.monotonic() - started >= timeout:
                    state = 'timeout'
                    break
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = output[key.data]
                    remaining = OUTPUT_LIMIT - len(target)
                    target.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        state = 'output_limit'
                        break
                if state:
                    break
        if state:
            kill(process)
        try:
            process.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            state = 'timeout'
            kill(process)
            process.wait(timeout=2)
        state = state or ('completed' if process.returncode == 0 else 'error')
        return {'state': state, 'returncode': process.returncode,
                'stdout': bytes(output['stdout']).decode('utf-8', errors='replace'),
                'stderr': bytes(output['stderr']).decode('utf-8', errors='replace'),
                'elapsed_seconds': time.monotonic() - started}
    finally:
        for fd in descriptors:
            os.close(fd)
        if process:
            if process.poll() is None:
                kill(process)
                process.wait(timeout=2)
            process.stdout.close()
            process.stderr.close()


def available():
    try:
        result = run('print("argos-sandbox-probe")')
        return result['state'] == 'completed' and result['stdout'] == 'argos-sandbox-probe\n'
    except (Unavailable, OSError):
        return False
