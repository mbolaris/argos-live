#!/usr/bin/env python3
"""XFCE welcome and local assistant launcher. No network needed for setup."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote
from urllib.request import urlopen


def runtime():
    path = Path(__file__).with_name('argos.py')
    if not path.exists():
        path = Path('/usr/local/bin/argos')
    loader = importlib.machinery.SourceFileLoader('argos_runtime', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def gateway_url(config):
    gateway = config.get('gateway', {})
    if gateway.get('bind', 'loopback') != 'loopback':
        raise ValueError('The welcome window requires a local-only assistant.')
    port = int(gateway.get('port', 18789))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid assistant port.')
    return f'http://127.0.0.1:{port}'


def ready(base):
    try:
        with urlopen(base + '/readyz', timeout=2) as response:
            return json.load(response).get('ready') is True
    except (OSError, ValueError):
        return False


def network_status():
    try:
        result = subprocess.run(['ip', '-j', 'route', 'show', 'default'],
                                capture_output=True, text=True, timeout=3, check=True)
        routes = json.loads(result.stdout)
        return 'Connected to a network' if routes else 'Offline — local chat still works'
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'Network status unavailable — local chat still works'


def persistence_status():
    """Only claim encryption when the mounted persistence device is dm-crypt."""
    from argoslive import session_mode
    if session_mode.guest():
        return 'Guest mode — workspace resets on reboot'
    try:
        result = subprocess.run(['findmnt', '-rn', '-o', 'TARGET,SOURCE'],
                                capture_output=True, text=True, timeout=3, check=True)
        for line in result.stdout.splitlines():
            target, source = line.split(maxsplit=1)
            if not target.startswith(('/run/live/persistence/', '/lib/live/mount/persistence/')):
                continue
            if not (Path(target) / 'persistence.conf').is_file():
                continue
            device = Path(source).resolve().name
            uuid = Path('/sys/class/block') / device / 'dm/uuid'
            if uuid.is_file() and uuid.read_text().startswith('CRYPT-'):
                return 'Encrypted persistence active'
            return 'Persistence active — encryption not confirmed'
        return 'Temporary session — changes may be lost at reboot'
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'Persistence status unavailable'


def model_available(state):
    name, separator, tag = state['model'].partition(':')
    tag = tag if separator else 'latest'
    parts = name.split('/')
    if len(parts) == 1:
        parts = ['registry.ollama.ai', 'library', *parts]
    elif len(parts) == 2:
        parts = ['registry.ollama.ai', *parts]
    manifest = Path(state['storage']) / 'manifests'
    manifest = manifest.joinpath(*parts, tag)
    try:
        data = json.loads(manifest.read_text())
        for item in [data['config']] + data['layers']:
            digest = item['digest']
            import re
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                return False
            blob = Path(state['storage']) / 'blobs' / digest.replace(':', '-')
            if not blob.is_file() or ('size' in item and blob.stat().st_size != item['size']):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


class Welcome:
    def __init__(self, root):
        self.root = root
        self.argos = runtime()
        self.events = queue.Queue()
        self.busy = False
        self.process = None
        self.owns_process = False
        self.root.title('Welcome to Argos Live')
        self.root.geometry(f'760x600+{max(0, (root.winfo_screenwidth()-760)//2)}+{max(30, (root.winfo_screenheight()-600)//2)}')
        self.root.minsize(720, 570)
        self.root.configure(bg='#f4f7fb')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#f4f7fb')
        style.configure('TLabel', background='#f4f7fb', foreground='#172d46', font=('Sans', 11))
        style.configure('TButton', font=('Sans', 11), padding=10)
        style.configure('Title.TLabel', font=('Sans', 25, 'bold'))
        style.configure('Status.TLabel', font=('Sans', 11, 'bold'))
        frame = ttk.Frame(root, padding=28)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Welcome to Argos Live', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Your local AI workspace', font=('Sans', 14)).pack(anchor='w', pady=(3, 20))
        ttk.Label(frame, text='Chat on this computer with the bundled model. No cloud account required.',
                  wraplength=680).pack(anchor='w', pady=(0, 18))
        self.status = {}
        for name in ('Local model', 'Live persistence', 'Network'):
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=6)
            ttk.Label(row, text=name, width=18, style='Status.TLabel').pack(side='left')
            value = tk.StringVar(value='Checking…')
            self.status[name] = value
            ttk.Label(row, textvariable=value, wraplength=475).pack(side='left')
        self.setup_frame = ttk.Frame(frame)
        self.setup_frame.pack(fill='x', pady=(18, 0))
        self.storage = tk.StringVar(value=str(Path.home() / 'Models'))
        self.accept = tk.BooleanVar(value=False)
        if not self.argos.STATE.exists():
            ttk.Label(self.setup_frame, text='Model storage').pack(anchor='w')
            row = ttk.Frame(self.setup_frame)
            row.pack(fill='x', pady=5)
            ttk.Entry(row, textvariable=self.storage).pack(side='left', fill='x', expand=True)
            ttk.Button(row, text='Choose folder…', command=self.choose).pack(side='right', padx=(8, 0))
            ttk.Label(self.setup_frame, text='Uses the bundled model; no download. External folders need their own encryption.',
                      wraplength=680).pack(anchor='w')
            ttk.Checkbutton(self.setup_frame, text='Allow conversation only. File access, shell and browser tools stay disabled.',
                            variable=self.accept).pack(anchor='w', pady=(12, 0))
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.pack(fill='x', pady=(20, 8))
        self.message = tk.StringVar(value='Ready when you are.')
        ttk.Label(frame, textvariable=self.message, wraplength=680).pack(anchor='w')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(16, 0))
        self.start_button = ttk.Button(buttons, text='Start Assistant', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='Stop Assistant', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=10)
        ttk.Button(buttons, text='View diagnostics', command=self.diagnostics).pack(side='right')
        self.log_path = Path.home() / '.local/state/argos-live/startup.log'
        self.root.after(100, self.drain)
        self.refresh()

    def choose(self):
        chosen = filedialog.askdirectory(parent=self.root, title='Choose model storage')
        if chosen:
            self.storage.set(chosen)

    def post(self, kind, value):
        self.events.put((kind, value))

    def refresh(self):
        def check():
            values = {'Network': network_status(), 'Live persistence': persistence_status()}
            try:
                if self.argos.STATE.exists():
                    state = self.argos.load()
                    values['Local model'] = (state['model'] + ' — ready on disk') if model_available(state) else 'Model files missing'
                else:
                    seed = Path('/usr/local/share/argos-live/seed-model/manifests')
                    values['Local model'] = 'Bundled Qwen3 — setup needed' if seed.is_dir() else 'Bundled model missing'
            except (OSError, ValueError, KeyError) as error:
                values['Local model'] = 'Storage needs attention'
                self.post('message', str(error))
            self.post('status', values)
        threading.Thread(target=check, daemon=True).start()
        self.root.after(10000, self.refresh)

    def start(self):
        if self.busy:
            return
        setup_needed = not self.argos.STATE.exists()
        if setup_needed and not self.accept.get():
            messagebox.showinfo('Conversation permissions', 'Select the conversation-only permission checkbox to continue.', parent=self.root)
            return
        temporary = False
        if setup_needed and not self.argos.persistence_present():
            temporary = messagebox.askyesno('Temporary session', 'No persistent storage was detected. Setup and conversations may be lost at reboot. Continue temporarily?', parent=self.root)
            if not temporary:
                return
        storage = self.storage.get().strip()
        if setup_needed and not storage:
            messagebox.showerror('Model storage', 'Choose a folder for the bundled model.', parent=self.root)
            return
        self.busy = True
        self.start_button.configure(state='disabled')
        self.progress.start(12)
        threading.Thread(target=self.start_worker, args=(setup_needed, storage, temporary), daemon=True).start()

    def start_worker(self, setup_needed, storage, temporary):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if setup_needed:
                self.post('message', 'Setting up your workspace and verifying the bundled model…')
                def ask(prompt):
                    if prompt.startswith('Continue for a temporary'):
                        return 'TEMPORARY' if temporary else ''
                    if prompt.startswith(('Accept these permissions', 'Use this location')):
                        return 'yes'
                    if prompt.startswith('Existing model storage'):
                        return '' if storage == str(Path.home() / 'Models') else storage
                    if prompt.startswith('Local Ollama model'):
                        self.post('message', 'Bundled model verified. Saving your workspace…')
                        return 'qwen3:0.6b'
                    raise ValueError('Unexpected setup question; setup stopped.')
                # Setup output goes to private diagnostics, not a terminal window.
                import contextlib
                with self.log_path.open('a') as log, contextlib.redirect_stdout(log):
                    self.log_path.chmod(0o600)
                    self.argos.setup(ask=ask)
                if not self.argos.STATE.exists():
                    raise ValueError('Setup was not saved.')
            state = self.argos.load()
            if not model_available(state):
                raise ValueError('Selected model files are missing. Choose an installed model before starting.')
            config = json.loads((self.argos.OC / 'openclaw.json').read_text())
            base = gateway_url(config)
            token = config.get('gateway', {}).get('auth', {}).get('token')
            if not token:
                raise ValueError('Assistant authentication is not configured.')
            if not ready(base):
                self.post('message', 'Starting the local model and assistant…')
                executable = str(Path('/usr/local/bin/argos'))
                with self.log_path.open('a') as log:
                    self.log_path.chmod(0o600)
                    self.process = subprocess.Popen([executable, 'start'], stdout=log, stderr=log, start_new_session=True)
                self.owns_process = True
                deadline = time.monotonic() + 150
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise ValueError('Assistant startup stopped. View diagnostics for details.')
                    if ready(base):
                        break
                    time.sleep(1)
                else:
                    self.stop_owned()
                    raise ValueError('Assistant startup timed out. View diagnostics, then retry.')
            self.post('message', 'Assistant ready. Opening your conversation…')
            # Fragment stays out of HTTP request logs; never print this URL.
            url = base + '/chat#token=' + quote(token, safe='')
            browser = next((shutil.which(name) for name in ('firefox-esr', 'firefox', 'xdg-open') if shutil.which(name)), None)
            if not browser:
                raise ValueError('No browser is installed. Install Firefox to open the conversation.')
            subprocess.Popen([browser, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.post('done', 'Your assistant is ready. The conversation is open in your browser.')
        except Exception as error:
            self.post('error', str(error))

    def stop_owned(self):
        if self.owns_process and self.process:
            import signal
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                self.owns_process = False
                return
            time.sleep(3)
            # Kill remaining children even if the supervisor exited first.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
        self.owns_process = False

    def stop(self):
        if self.busy:
            return
        self.busy = True
        self.start_button.configure(state='disabled')
        def worker():
            try:
                self.stop_owned()
                self.post('stopped', 'Assistant stopped. Your saved conversations remain available.')
            except Exception:
                self.post('error', 'Could not stop the assistant. View diagnostics for details.')
        threading.Thread(target=worker, daemon=True).start()

    def diagnostics(self):
        window = tk.Toplevel(self.root)
        window.title('Argos startup diagnostics')
        window.geometry('800x430')
        text = tk.Text(window, wrap='word', font=('Monospace', 10))
        text.pack(fill='both', expand=True, padx=12, pady=12)
        try:
            content = self.log_path.read_bytes()[-40000:].decode(errors='replace')
            # Avoid displaying the known auth token if a dependency logs it.
            if (self.argos.OC / 'openclaw.json').exists():
                config = json.loads((self.argos.OC / 'openclaw.json').read_text())
                token = config.get('gateway', {}).get('auth', {}).get('token')
                if token:
                    content = content.replace(token, '[redacted]')
        except (OSError, ValueError):
            content = 'No startup log yet. Start Assistant to collect diagnostics.'
        text.insert('1.0', content)
        text.configure(state='disabled')

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'status':
                    for key, text in value.items():
                        self.status[key].set(text)
                elif kind in ('done', 'error', 'stopped'):
                    self.busy = False
                    self.progress.stop()
                    self.start_button.configure(state='normal', text='Open Conversation' if kind == 'done' else 'Start Assistant')
                    self.stop_button.configure(state='normal' if self.owns_process else 'disabled')
                    self.message.set(value)
                    if self.argos.STATE.exists():
                        self.setup_frame.pack_forget()
                else:
                    self.message.set(value)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def close(self):
        if self.busy:
            messagebox.showinfo('Setup in progress', 'Please wait for setup or startup to finish.', parent=self.root)
            return
        # Closing this window leaves a running assistant available in the browser.
        self.root.destroy()


def main():
    import fcntl
    lock_dir = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / ('argos-welcome-' + str(os.getuid()))
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    with (lock_dir / 'window.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        root = tk.Tk()
        Welcome(root)
        root.mainloop()


if __name__ == '__main__':
    main()
