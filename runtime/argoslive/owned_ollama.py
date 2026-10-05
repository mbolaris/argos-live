"""Linux-only private Ollama process, supervised for parent-death cleanup."""
from contextlib import contextmanager
import os
import math
import select
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
from .private_files import private_log

PIN = '0.35.1'


def supervisor_pid(process, *, deadline, cancel=None):
    """Read only a bounded PID line, with cancellation and one startup budget.

    Avoid blocking readline after a partial pipe write. A cold Live interpreter
    can take longer than five seconds before executing the supervisor module.
    """
    pending = b''
    while True:
        if cancel and cancel():
            raise ValueError('Supervisor startup stopped')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Supervisor startup timed out; inspect private supervisor log')
        if not select.select([process.stdout], [], [], min(.1, remaining))[0]:
            if process.poll() is not None:
                raise ValueError('Supervisor exited before publishing ownership')
            continue
        chunk = os.read(process.stdout.fileno(), 33 - len(pending))
        if not chunk:
            raise ValueError('Supervisor closed its ownership pipe')
        pending += chunk
        if len(pending) > 32:
            raise ValueError('Supervisor ownership record exceeds the bound')
        if b'\n' in pending:
            pid, extra = pending.split(b'\n', 1)
            if extra or not pid.isdigit() or not 0 < int(pid) <= 2147483647:
                raise ValueError('Invalid supervisor ownership record')
            return int(pid)


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
        inodes = set()
        for descriptor in Path(f'/proc/{pid}/fd').iterdir():
            try:
                inodes.add(os.readlink(descriptor))
            except (FileNotFoundError, ProcessLookupError):
                # HTTP request threads can close another descriptor during
                # enumeration. The listening socket must still match below.
                continue
        for row in Path(f'/proc/{pid}/net/tcp').read_text().splitlines()[1:]:
            columns = row.split()
            if (columns[1] == f'0100007F:{port:04X}' and columns[3] == '0A'
                    and f'socket:[{columns[9]}]' in inodes):
                return True
    except (OSError, IndexError):
        pass
    return False


@contextmanager
def owned(target, *, executable=None, timeout=180, lease_store=None, port=0, context_tokens=2048, cancel=None):
    if sys.platform != 'linux':
        raise ValueError('Owned Ollama onboarding requires Linux')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise ValueError('Owned Ollama startup timeout is outside supported bounds')
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
    log_path = safe_local(lease / 'ollama.log')
    # Validate privacy before launching; the supervisor owns the writing handle.
    with private_log(log_path):
        pass
    # Supervisor emits only the child PID, never backend logs or credentials.
    deadline = time.monotonic() + timeout
    with private_log(lease / 'supervisor.log') as supervisor_log:
        process = subprocess.Popen([sys.executable, '-m', 'argoslive.owned_ollama',
                                    '--supervise', executable, str(lease), str(log_path)], env=env,
                                   stdout=subprocess.PIPE, stderr=supervisor_log,
                                   text=True, start_new_session=True)
    try:
        pid = supervisor_pid(process, deadline=deadline, cancel=cancel)
        client = Client(f'http://127.0.0.1:{port}', timeout=30)
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
    if len(sys.argv) not in (4, 5) or sys.argv[1] != '--supervise':
        raise SystemExit(2)
    if len(sys.argv) == 5:
        with private_log(Path(sys.argv[4])) as log:
            supervise(sys.argv[2], sys.argv[3], log=log)
    else:
        supervise(sys.argv[2], sys.argv[3])
