"""Desktop-owned startup progress and controls; no imported policy or credentials."""
import copy
from pathlib import Path
import threading
import time
import traceback

from . import auto_setup, catalog, model_verify, starter, storage
from .bench_speed import measurement
from .owned_gateway import owned as gateway_owned, private_log
from .owned_ollama import owned as backend_owned
from .web.status import chat_url, gateway_ready, read_json

PHASES = {'idle': 'Start your local assistant.', 'setup': 'Preparing your workspace…',
    'verify-starter': 'Checking the bundled model…', 'select-storage': 'Choosing space for future models…',
    'write-configuration': 'Saving your local workspace…', 'verify-model': 'Verifying selected model files…',
    'configured': 'Your workspace is configured.',
    'model-service': 'Starting local inference…', 'first-reply': 'Warming up the local model…',
    'gateway': 'Starting your assistant…', 'ready': 'Your local assistant is ready.',
    'stopping': 'Stopping your assistant…', 'stopped': 'Your assistant is stopped.',
    'failed': 'Startup needs attention. Check the private startup diagnostics, then retry.'}


def source(home):
    state = read_json(storage.safe_local(home / '.config/argos-live/state.json'))
    selected = storage.validate_configured(state)
    config = read_json(storage.safe_local(home / '.openclaw/openclaw.json'))
    model = state.get('model')
    provider = config.get('models', {}).get('providers', {}).get('ollama', {})
    primary = config.get('agents', {}).get('defaults', {}).get('model', {}).get('primary')
    tools = config.get('tools', {})
    if (not isinstance(provider, dict) or provider.get('baseUrl') != 'http://127.0.0.1:11434' or
            provider.get('api') != 'ollama' or primary != 'ollama/' + str(model) or
            tools.get('profile') != 'minimal' or not isinstance(tools.get('deny'), list) or
            not {'gateway', 'group:runtime', 'group:fs', 'group:web', 'browser'} <= set(tools['deny']) or
            tools.get('elevated', {}).get('enabled') is not False or
            config.get('commands', {}).get('bash') is not False or
            config.get('commands', {}).get('restart') is not False or config.get('channels')):
        raise ValueError('Automatic startup requires the reviewed local conversation profile')
    entry = next((item for item in catalog.load()['models'] if item['tag'] == model), None)
    if entry is None:
        raise ValueError('Selected model is not resolved to the reviewed public catalog')
    kind = state.get('model_source', 'managed')
    if kind == 'bundled':
        if model != starter.TAG:
            raise ValueError('Unsupported bundled model')
        starter.read_only(starter.ROOT)
        target = starter.ROOT
    elif kind == 'managed':
        model_verify.verify(selected, entry)
        target = selected
    else:
        raise ValueError('Unrecognized inference source')
    return target, model


class Controller:
    def __init__(self, home=None, *, configure=auto_setup.configure, resolve_source=source,
                 backend=backend_owned, gateway=gateway_owned, ready=gateway_ready,
                 conversation=chat_url, clock=time.monotonic, auto_open_chat=True):
        self.home = storage.safe_local(Path.home() if home is None else Path(home))
        self.configure, self.resolve_source = configure, resolve_source
        self.backend, self.gateway, self.ready, self.conversation = backend, gateway, ready, conversation
        self.clock = clock
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.phase = 'idle'
        self.started = None
        self.metrics = None
        self.model = None
        self.auto_open_chat = auto_open_chat
        self.chat_claimed = False
        self.origin = None

    def transition(self, phase):
        if phase not in PHASES:
            raise ValueError('Unknown startup phase')
        with self.lock:
            if self.stop_event.is_set() and phase not in ('stopped', 'failed'):
                return
            self.phase = phase

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            return {'schema': 'argos-startup/1', 'managed': True, 'phase': self.phase, 'message': PHASES[self.phase],
                'active': active, 'can_start': not active,
                'can_stop': active and not self.stop_event.is_set(),
                'elapsed_seconds': max(0, self.clock() - self.started) if self.started is not None else None,
                'model': self.model, 'model_reply_verified': self.metrics is not None,
                'metrics': copy.deepcopy(self.metrics), 'gateway_ready': self.phase == 'ready',
                'auto_open_chat': self.phase == 'ready' and self.auto_open_chat and not self.chat_claimed}

    def start(self):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                return self.snapshot()
            self.stop_event.clear()
            self.phase, self.started = 'setup', self.clock()
            self.model, self.metrics, self.origin = None, None, None
            self.chat_claimed = False
            self.worker = threading.Thread(target=self.run, daemon=True, name='argos-startup')
            self.worker.start()
            return self.snapshot()

    def stop(self):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                self.stop_event.set()
                self.phase = 'stopping'
            return self.snapshot()

    def claim_chat(self):
        with self.lock:
            if self.phase != 'ready' or self.chat_claimed or self.stop_event.is_set():
                raise ValueError('Automatic conversation handoff is unavailable')
            url = self.conversation(self.home / '.openclaw/openclaw.json',
                ready=lambda origin: origin == self.origin and self.ready(origin))
            self.chat_claimed = True
            return url

    def interrupted(self):
        if self.stop_event.is_set():
            raise ValueError('Startup stopped')

    def run(self):
        try:
            self.configure(self.home, progress=lambda event: self.transition(event['phase']))
            self.interrupted()
            self.transition('verify-model')
            target, model = self.resolve_source(self.home)
            self.interrupted()
            with self.lock:
                self.model = model
            root = storage.safe_local(self.home / '.local/state/argos-live')
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            self.transition('model-service')
            with self.backend(target, port=11434, context_tokens=32768, lease_store=root,
                              cancel=self.stop_event.is_set) as client:
                self.interrupted()
                self.transition('first-reply')
                client.timeout = 120
                reply = client.generate(model, 'Say hello in one short sentence.',
                    options={'num_ctx': 32768, 'num_predict': 16, 'temperature': 0, 'seed': 1},
                    think=False, keep_alive='5m', cancel=self.stop_event.is_set)
                if (not reply.get('text', '').strip() or
                        type(reply.get('final', {}).get('eval_count')) is not int or reply['final']['eval_count'] <= 0):
                    raise ValueError('Selected model did not produce a measured reply')
                value = measurement(reply, client.ps().get('models', []), model)
                with self.lock:
                    self.metrics = value
                self.interrupted()
                self.transition('gateway')
                with self.gateway(self.home, cancel=self.stop_event.is_set) as origin:
                    self.interrupted()
                    with self.lock:
                        self.origin = origin
                    self.transition('ready')
                    while not self.stop_event.wait(2):
                        if not self.ready(origin):
                            raise ValueError('Owned gateway stopped responding')
                # Native group/backend cleanup remains inside ownership contexts.
                client.unload(model)
            self.transition('stopped')
        except Exception:
            self.transition('stopped' if self.stop_event.is_set() else 'failed')
            if not self.stop_event.is_set():
                try:
                    root = storage.safe_local(self.home / '.local/state/argos-live')
                    root.mkdir(parents=True, mode=0o700, exist_ok=True)
                    with private_log(root / 'startup.log') as log:
                        log.write(traceback.format_exc().encode()[-65536:])
                except (OSError, ValueError):
                    pass

    def close(self):
        self.stop()
        if self.worker is not None:
            self.worker.join(timeout=5)
