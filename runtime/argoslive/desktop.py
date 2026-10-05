"""Single-instance desktop dashboard with questionless local assistant startup."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .owned_gateway import private_log
from .owned_ollama import owns_port
from .pull_jobs import worker_lock
from .storage import safe_local
from .startup import Controller
from .lab import Controller as LabController
from .results import Store
from .web.server import DashboardServer
from .web.status import read_json
from .ollama import NoRedirect


def process_identity(pid):
    raw = Path(f'/proc/{pid}/stat').read_text()
    return raw[raw.rfind(')') + 2:].split()[19]


def session_url(value):
    if not isinstance(value, dict) or value.get('schema') != 'argos-desktop-session/1':
        raise ValueError('Desktop session metadata needs review')
    url = urlsplit(value.get('url', ''))
    tokens = parse_qs(url.query, max_num_fields=2)
    token = tokens.get('token', [])
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or
            url.path != '/' or url.fragment or not url.port or list(tokens) != ['token'] or len(token) != 1 or
            not re.fullmatch(r'[A-Za-z0-9_-]{40,64}', token[0])):
        raise ValueError('Desktop session endpoint is invalid')
    return f'http://127.0.0.1:{url.port}', token[0]


def open_browser(url):
    browser = next((shutil.which(name) for name in ('firefox-esr', 'firefox', 'xdg-open') if shutil.which(name)), None)
    if not browser:
        raise ValueError('A desktop browser is unavailable')
    subprocess.Popen([browser, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reconnect(home, *, browser=open_browser):
    path = safe_local(home / '.local/state/argos-live/desktop-session.json')
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise ValueError('Desktop session metadata must be owner-only')
    value = read_json(path)
    origin, token = session_url(value)
    pid = value.get('pid')
    if (type(pid) is not int or pid <= 0 or
            Path(f'/proc/{pid}').stat().st_uid != os.getuid() or
            process_identity(pid) != value.get('process_start') or not owns_port(pid, urlsplit(origin).port)):
        raise ValueError('Desktop session is unavailable; no service is adopted')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(origin + '/api/startup', headers={'X-Argos-Token': token}), timeout=3) as response:
        raw = response.read(65537)
    if len(raw) > 65536 or json.loads(raw).get('schema') != 'argos-startup/1':
        raise ValueError('Desktop session did not establish its identity')
    browser(value['url'])


def serve(home, root, *, port=0, browser=open_browser, no_browser=False, controller=None, stop=None):
    controller = controller or Controller(home)
    stop = stop or threading.Event()
    path = safe_local(root / 'desktop-session.json')
    if path.exists():
        # A stale generated descriptor can be replaced, but never an owner file.
        session_url(read_json(path))
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError('Existing desktop session metadata needs review')
    lab = LabController(controller, store=Store(home / '.local/share/argos-live/results'))
    with DashboardServer(port=port, startup=controller, lab=lab) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        raw = (json.dumps({'schema': 'argos-desktop-session/1', 'pid': os.getpid(),
            'process_start': process_identity(os.getpid()), 'url': server.url}) + '\n').encode()
        temporary = safe_local(root / '.desktop-session-new')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            inode = path.stat().st_ino
            worker.start()
            if not no_browser:
                browser(server.url)
            controller.start()
            stop.wait()
        finally:
            temporary.unlink(missing_ok=True)
            lab.close()
            controller.close()
            if worker.is_alive():
                server.shutdown()
                worker.join(timeout=5)
            if path.exists() and path.stat().st_ino == locals().get('inode') and path.read_bytes() == raw:
                path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0, help='Loopback dashboard port; default chooses a free port')
    parser.add_argument('--no-browser', action='store_true', help='Run managed services without opening a browser')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        raise ValueError('The managed desktop launcher requires Linux')
    home = safe_local(Path.home())
    root = safe_local(home / '.local/state/argos-live')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lease = safe_local(root / '.desktop-lease')
    lease.mkdir(mode=0o700, exist_ok=True)
    for path in (root, lease):
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise ValueError('Desktop runtime directories must be owner-only')
    lock = worker_lock(lease)
    try:
        lock.__enter__()
    except ValueError:
        reconnect(home, browser=(lambda url: None) if args.no_browser else open_browser)
        return 0
    stop = threading.Event()
    prior = {sig: signal.signal(sig, lambda *args: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        serve(home, root, port=args.port, no_browser=args.no_browser, stop=stop)
    except Exception:
        # Native private logs explain failures; never print a tokenized URL.
        import traceback
        with private_log(root / 'startup.log') as log:
            log.write(traceback.format_exc().encode()[-65536:])
        raise ValueError('Desktop startup failed; inspect private startup.log') from None
    finally:
        for sig, handler in prior.items():
            signal.signal(sig, handler)
        lock.__exit__(None, None, None)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
