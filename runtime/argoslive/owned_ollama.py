"""Linux-only private Ollama process, supervised for parent-death cleanup."""
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import time

from .ollama import Client, NotRunning
from .storage import safe_local

PIN = '0.35.0'


def stop_group(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
    # Runners may outlive an already-exited daemon leader.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def owns_port(pid, port):
    """Do not accept a same-version daemon that won a port allocation race."""
    try:
        inodes = {os.readlink(p) for p in Path(f'/proc/{pid}/fd').iterdir()}
        for row in Path(f'/proc/{pid}/net/tcp').read_text().splitlines()[1:]:
            columns = row.split()
            if (columns[1] == f'0100007F:{port:04X}' and columns[3] == '0A'
                    and f'socket:[{columns[9]}]' in inodes):
                return True
    except (OSError, IndexError):
        pass
    return False


@contextmanager
def owned(target, *, executable=None, timeout=60):
    if sys.platform != 'linux':
        raise ValueError('Owned Ollama onboarding requires Linux')
    target = safe_local(target)
    executable = executable or shutil.which('ollama')
    if not executable:
        raise ValueError('Pinned Ollama executable is unavailable')
    executable = str(safe_local(executable))
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = dict(os.environ)
    # Do not pass custom upstream/auth/proxy/GPU overrides into public pulls.
    for key in list(env):
        if key.startswith('OLLAMA_') or key.lower().endswith('_proxy'):
            env.pop(key)
    env.update(OLLAMA_HOST=f'127.0.0.1:{port}', OLLAMA_MODELS=str(target),
               OLLAMA_NO_CLOUD='1', OLLAMA_NOPRUNE='1', OLLAMA_CONTEXT_LENGTH='2048',
               OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    # Supervisor emits only the child PID, never backend logs or credentials.
    process = subprocess.Popen([sys.executable, '-m', 'argoslive.owned_ollama',
                                '--supervise', executable], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, start_new_session=True)
    try:
        # Supervisor startup has no network/model work before this single line.
        import select
        if not select.select([process.stdout], [], [], 5)[0]:
            raise ValueError('Ollama supervisor did not start')
        pid = int(process.stdout.readline().strip())
        client = Client(f'http://127.0.0.1:{port}', timeout=30)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError('Owned Ollama failed to start')
            if owns_port(pid, port):
                try:
                    version = client.version()
                except NotRunning:
                    time.sleep(0.1)
                    continue
                if version != PIN:
                    raise ValueError('Ollama version differs from the pinned runtime')
                yield client
                return
            time.sleep(0.1)
        raise ValueError('Owned Ollama startup timed out')
    finally:
        process.terminate()
        # Supervisor kills the entire daemon/runner group before exiting.
        process.wait(timeout=25)
        process.stdout.close()


def supervise(executable):
    import ctypes
    parent = os.getppid()
    child = None
    stopping = False
    def terminate(*args):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    # Linux PR_SET_PDEATHSIG. Install handler before arming it, check race afterward.
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise ValueError('Cannot establish parent-death supervision')
    try:
        if stopping or os.getppid() != parent:
            return
        child = subprocess.Popen([executable, 'serve'], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        print(child.pid, flush=True)
        while not stopping and child.poll() is None:
            time.sleep(0.1)
    finally:
        if child:
            stop_group(child)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--supervise':
        raise SystemExit(2)
    supervise(sys.argv[2])
