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
from .pull_jobs import worker_lock

PIN = '0.35.1'


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
def owned(target, *, executable=None, timeout=60, lease_store=None, port=0, context_tokens=2048, cancel=None):
    if sys.platform != 'linux':
        raise ValueError('Owned Ollama onboarding requires Linux')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Owned Ollama requires an integer loopback port')
    if type(context_tokens) is not int or not 256 <= context_tokens <= 1048576:
        raise ValueError('Owned Ollama context is outside the supported bounds')
    target = safe_local(target)
    executable = executable or shutil.which('ollama')
    if not executable:
        raise ValueError('Pinned Ollama executable is unavailable')
    executable = str(safe_local(executable))
    with socket.socket() as reservation:
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reservation.bind(('127.0.0.1', port))
        port = reservation.getsockname()[1]
    env = dict(os.environ)
    # Do not pass custom upstream/auth/proxy/GPU overrides into public pulls.
    for key in list(env):
        if key.startswith('OLLAMA_') or key.lower().endswith('_proxy'):
            env.pop(key)
    env.update(OLLAMA_HOST=f'127.0.0.1:{port}', OLLAMA_MODELS=str(target),
               OLLAMA_NO_CLOUD='1', OLLAMA_NOPRUNE='1', OLLAMA_CONTEXT_LENGTH=str(context_tokens),
               OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    store = (safe_local(lease_store) if lease_store is not None else
             target.parent.parent if target.parent.name == '.argos-pulls' else target)
    lease = safe_local(store / '.argos-daemon-lease')
    lease.mkdir(mode=0o700, exist_ok=True)
    # Supervisor emits only the child PID, never backend logs or credentials.
    process = subprocess.Popen([sys.executable, '-m', 'argoslive.owned_ollama',
                                '--supervise', executable, str(lease)], env=env,
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
            if cancel and cancel():
                raise ValueError('Owned Ollama startup stopped')
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


def supervise(executable, lease, *, arguments=None, log=None):
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
    # Supervisor owns this lease, so worker death cannot release daemon exclusion
    # while the old process group is still shutting down.
    with worker_lock(Path(lease)):
        try:
            if stopping or os.getppid() != parent:
                return
            output = subprocess.DEVNULL if log is None else log
            child = subprocess.Popen([executable, *(arguments if arguments is not None else ['serve'])],
                                     stdout=output, stderr=output, start_new_session=True)
            print(child.pid, flush=True)
            while not stopping and child.poll() is None:
                time.sleep(0.1)
        finally:
            if child:
                stop_group(child)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--supervise':
        raise SystemExit(2)
    supervise(sys.argv[2], sys.argv[3])
