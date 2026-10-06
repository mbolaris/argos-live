"""Questionless fresh Live configuration; never replace an owner configuration."""
import json
import os
from pathlib import Path
import secrets

from . import starter, storage, session_mode
from .pull_jobs import read_json


def conversation_config(model, workspace):
    return {
        'gateway': {'mode': 'local', 'bind': 'loopback', 'auth': {'mode': 'token', 'token': secrets.token_hex(32)}},
        'agents': {'defaults': {'model': {'primary': 'ollama/' + model}, 'workspace': str(workspace)}},
        'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434', 'apiKey': 'ollama-local', 'api': 'ollama',
            'models': [{'id': model, 'name': model, 'input': ['text'], 'reasoning': False,
                        'contextWindow': 32768, 'maxTokens': 4096,
                        'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}},
        'tools': {'profile': 'minimal', 'deny': ['gateway', 'group:runtime', 'group:fs', 'group:web', 'browser'],
                  'elevated': {'enabled': False}},
        'commands': {'bash': False, 'restart': False}}


def persistence():
    from .web.status import mounts_and_blocks, persistence as observed
    mounts, blocks = mounts_and_blocks()
    return observed(mounts, blocks)


def publish_new(path, value, journal):
    """Publish a private complete file without replacing a racing owner file."""
    path = storage.safe_local(path)
    raw = (json.dumps(value, indent=2) + '\n').encode()
    temp = path.parent / ('.setup-' + secrets.token_hex(16))
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
        journal.append((path, path.stat().st_ino, raw))
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temp.unlink(missing_ok=True)


def configure(home=None, *, planner=storage.plan, verify_seed=starter.read_only,
              probe_persistence=persistence, progress=None):
    """No prompts, mounts, downloads or daemon startup; retained state is reused."""
    home = storage.safe_local(Path.home() if home is None else Path(home))
    is_guest = session_mode.guest()
    if is_guest:
        session_mode.require_ram(home)
    state_path = storage.safe_local(home / '.config/argos-live/state.json')
    config_path = storage.safe_local(home / '.openclaw/openclaw.json')
    def report(phase):
        if progress:
            progress({'phase': phase})
    if state_path.exists():
        state = read_json(state_path)
        storage.validate_configured(state)
        read_json(config_path)
        return {'status': 'existing', **{key: state.get(key) for key in
                ('mode', 'model', 'model_source', 'storage', 'permissions')}}
    if config_path.exists() or (config_path.parent.exists() and any(config_path.parent.iterdir())):
        raise ValueError('Existing OpenClaw state needs review; automatic setup will not replace it')
    report('verify-starter')
    identity = verify_seed()
    if identity.get('tag') != starter.TAG:
        raise ValueError('Unexpected bundled starter identity')
    report('select-storage')
    # Seed weights stay in the image. Reserve only workspace capacity here;
    # each managed pull checks its own real model budget before downloading.
    selected = planner(1)
    models = storage.safe_local(Path(selected['path']))
    if is_guest:
        session_mode.require_ram(models)
    if models.exists() and (not models.is_dir() or any(models.iterdir())):
        raise ValueError('Proposed model directory already contains data; automatic setup will not adopt it')
    observed = probe_persistence()
    if type(observed.get('active')) is not bool:
        raise ValueError('Persistence status unavailable; no automatic configuration written')
    if is_guest and observed['active']:
        raise ValueError('Guest mode cannot use live persistence; reboot using the guest entry')
    state = {'storage': str(models), 'storage_id': secrets.token_hex(24),
             'model': starter.TAG, 'model_source': 'bundled', 'permissions': 'conversation-only',
             'mode': 'guest' if is_guest else ('persistent' if observed['active'] else 'try'),
             'storage_temporary': selected['kind'] == 'ram', 'storage_encrypted': selected.get('encrypted'),
             'persistence_encrypted': observed.get('encrypted'), 'starter': identity}
    if selected.get('volume_uuid'):
        state['storage_uuid'] = selected['volume_uuid']
    journal, directories = [], []
    def mkdir(path):
        storage.safe_local(path)
        if path.exists():
            if not path.is_dir():
                raise ValueError('Setup directory is not a directory')
            return
        mkdir(path.parent)
        path.mkdir(mode=0o700)
        directories.append(path)
    try:
        report('write-configuration')
        for path in (models, state_path.parent, config_path.parent / 'workspace'):
            mkdir(path)
        # Marker is metadata, not a private credential; use exclusive creation
        # on DATA filesystems that may not support hard links.
        marker = storage.safe_local(models / '.argos-storage-id')
        raw = (state['storage_id'] + '\n').encode()
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        journal.append((marker, os.fstat(descriptor).st_ino, raw))
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        publish_new(config_path, conversation_config(starter.TAG, config_path.parent / 'workspace'), journal)
        publish_new(state_path, state, journal)
    except BaseException:
        # Remove only files this transaction published, still matching its bytes
        # and inode. Changed owner files and nonempty directories are preserved.
        for path, inode, raw in reversed(journal):
            try:
                storage.safe_local(path)
                if path.stat().st_ino == inode and path.read_bytes() == raw:
                    path.unlink()
            except (OSError, ValueError):
                pass
        for path in reversed(directories):
            try:
                path.rmdir()
            except OSError:
                pass
        raise
    report('configured')
    return {'status': 'created', **state}
