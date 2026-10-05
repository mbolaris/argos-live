"""Reviewed local model selection with private crash recovery and startup rollback."""
import copy
import json
import os
import secrets
import time

from . import catalog, model_verify, starter, storage
from .lab import Controller as Workload
from .pull_jobs import read_json, write_json


def paths(home):
    return (storage.safe_local(home / '.config/argos-live/state.json'),
            storage.safe_local(home / '.openclaw/openclaw.json'),
            storage.safe_local(home / '.config/argos-live/model-selection.json'))


def replace_raw(path, raw):
    path = storage.safe_local(path)
    temporary = path.parent / ('.selection-' + secrets.token_hex(16))
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def finish_journal(path):
    path.unlink()
    if os.name != 'nt':
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def restore(home):
    """A pending switch is rolled back on next desktop launch, never replayed."""
    state, config, journal = paths(home)
    if not journal.exists():
        return False
    value = read_json(journal)
    if value.get('schema') != 'argos-model-selection/1':
        raise ValueError('Selection recovery requires review')
    for path, key in ((state, 'state'), (config, 'config')):
        current = read_json(path)
        if path.read_bytes() not in (value['raw'][key].encode(), value['candidate'][key].encode()):
            raise ValueError('Owner edits prevent automatic selection rollback')
    for path, key in ((config, 'config'), (state, 'state')):
        replace_raw(path, value['raw'][key].encode())
    finish_journal(journal)
    return True


class Controller(Workload):
    budget_seconds = 1500

    def __init__(self, startup, *, verify=model_verify.verify, **options):
        super().__init__(startup, **options)
        self.verify = verify
        self.tag = None
        self.previous = None
        self.recovery_blocked = False

    def start(self, *, tag):
        if not isinstance(tag, str) or not any(e['tag'] == tag for e in catalog.load()['models']):
            raise ValueError('Choose an exact reviewed model')
        with self.startup.lock, self.lock:
            if self.closed or self.startup.lab_active:
                raise ValueError('Another desktop workload is active')
            self.tag = tag
            self.recovery_blocked = False
            return super().start()

    def wait_stopped(self):
        deadline = time.monotonic() + 180
        while self.startup.snapshot()['active']:
            if time.monotonic() >= deadline:
                raise ValueError('Assistant resources were not released')
            time.sleep(.1)

    def wait_ready(self):
        deadline = time.monotonic() + 900
        while True:
            value = self.startup.snapshot()
            if value['phase'] == 'ready' and value['model_reply_verified']:
                return
            if self.cancel_event.is_set() or value['phase'] in ('failed', 'stopped') or time.monotonic() >= deadline:
                raise ValueError('Selected assistant did not become ready')
            time.sleep(.1)

    def execute(self):
        # Validates the existing conversation policy before any configuration edit.
        self.startup.resolve_source(self.startup.home)
        state_path, config_path, journal = paths(self.startup.home)
        if journal.exists():
            raise ValueError('An unfinished selection requires recovery')
        before = {'state': read_json(state_path), 'config': read_json(config_path)}
        raw = {'state': state_path.read_bytes().decode('utf-8'), 'config': config_path.read_bytes().decode('utf-8')}
        if before['config'].get('agents', {}).get('list'):
            raise ValueError('Multi-agent profiles require separate model review')
        self.previous = before['state']['model']
        self.model = self.tag
        entry = next(e for e in catalog.load()['models'] if e['tag'] == self.tag)
        if 'text' not in entry['capabilities'] or entry['context_tokens'] < 32768:
            raise ValueError('Model does not support this conversation profile')
        self.report('verifying')
        if self.tag == starter.TAG:
            starter.read_only(starter.ROOT)
            kind = 'bundled'
        else:
            target = storage.validate_configured(before['state'])
            self.verify(target, entry, cancel=self.cancel_event)
            kind = 'managed'
        if self.cancel_event.is_set():
            return 'cancelled'
        after = copy.deepcopy(before)
        after['state'].update(model=self.tag, model_source=kind)
        after['config']['agents']['defaults']['model']['primary'] = 'ollama/' + self.tag
        provider = after['config']['models']['providers']['ollama']
        template = copy.deepcopy(provider['models'][0])
        template.update(id=self.tag, name=self.tag, input=['text'], reasoning=False)
        existing = next((index for index, item in enumerate(provider['models']) if item.get('id') == self.tag), None)
        if existing is None:
            provider['models'].append(template)
        else:
            provider['models'][existing] = template
        # Complete owner-only journal reaches durable storage before either file.
        candidate = {key: raw[key] if value == before[key] else json.dumps(value, sort_keys=True, indent=2) + '\n'
                     for key, value in after.items()}
        write_json(journal, {'schema': 'argos-model-selection/1', 'before': before, 'after': after,
                            'raw': raw, 'candidate': candidate})
        try:
            if state_path.read_bytes() != raw['state'].encode() or config_path.read_bytes() != raw['config'].encode():
                raise ValueError('Configuration changed during review')
            replace_raw(config_path, candidate['config'].encode())
            replace_raw(state_path, candidate['state'].encode())
            self.report('starting')
            with self.startup.lock:
                self.startup.start(_reserved=True)
                self.startup.chat_claimed = True
            self.wait_ready()
            # Do not commit across concurrent external edits.
            if read_json(state_path) != after['state'] or read_json(config_path) != after['config']:
                raise ValueError('Configuration changed during startup')
            finish_journal(journal)
            self.resume = False
            return 'completed'
        except Exception:
            self.report('restoring')
            try:
                self.startup.stop()
                self.wait_stopped()
                restore(self.startup.home)
            except Exception:
                self.resume = False
                self.recovery_blocked = True
                raise
            return 'cancelled' if self.cancel_event.is_set() else 'rolled-back'

    def failure_outcome(self):
        return 'recovery-blocked' if self.recovery_blocked else super().failure_outcome()
