"""Questionless fresh Live configuration; never replace an owner configuration."""
import json
import os
from pathlib import Path
import secrets

from . import starter, storage, session_mode
from .pull_jobs import read_json

PLUGIN_ROOT = '/usr/local/share/argos-live/plugins/argos-improve'
# Seeded once into a fresh workspace; existing owner files are never replaced.
WORKSPACE_FILES = (('AGENTS.md', 'SELF-IMPROVEMENT-AGENTS.md'), ('SOUL.md', 'SELF-IMPROVEMENT-SOUL.md'),
                   ('IDENTITY.md', 'SELF-IMPROVEMENT-IDENTITY.md'),
                   ('tools/argos-control.py', 'SELF-IMPROVEMENT-CONTROL.py'))
# While IMPROVEMENT-LOG.md has a '## Next' step and no '## Done', keep the campaign moving.
HEARTBEAT_PROMPT = ('Self-improvement heartbeat. Run `tail -n 30 IMPROVEMENT-LOG.md` in your workspace. If it has a '
                    '"## Next" step and no "## Done" section, your campaign is active: take the last Next step now, '
                    'following AGENTS.md, then append one short entry to the log. If there is no active campaign, '
                    'reply exactly HEARTBEAT_OK.')


def workspace_file(name):
    return (Path(__file__).resolve().parent / 'data' / name).read_bytes()


def conversation_config(model, workspace, *, plugin_root=PLUGIN_ROOT):
    return {
        'gateway': {'mode': 'local', 'bind': 'loopback', 'auth': {'mode': 'token', 'token': secrets.token_hex(32)}},
        'agents': {'defaults': {'model': {'primary': 'ollama/' + model}, 'workspace': str(workspace),
                                'skipBootstrap': True,
                                'heartbeat': {'every': '3m', 'session': 'main', 'target': 'none',
                                              'timeoutSeconds': 1800, 'prompt': HEARTBEAT_PROMPT}}},
        'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434', 'apiKey': 'ollama-local', 'api': 'ollama',
            'models': [{'id': model, 'name': model, 'input': ['text'], 'reasoning': False,
                        'contextWindow': 32768, 'maxTokens': 4096,
                        'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}},
        'tools': {'profile': 'minimal',
                  'alsoAllow': ['group:fs', 'group:runtime', 'web_fetch', 'argos_evaluate', 'argos_compare'],
                  'deny': ['gateway', 'browser'],
                  'exec': {'host': 'gateway', 'security': 'full', 'ask': 'off'},
                  'elevated': {'enabled': False},
                  # Local Ollama runs otherwise hide tool schemas behind tool search, and
                  # models then call argos_evaluate by name and get an empty turn.
                  'toolSearch': False},
        'plugins': {'enabled': True, 'load': {'paths': [str(plugin_root)]},
                    'entries': {'argos-improve': {'enabled': True}}},
        'commands': {'bash': False, 'restart': False}}


def persistence():
    from .web.status import mounts_and_blocks, persistence as observed
    mounts, blocks = mounts_and_blocks()
    return observed(mounts, blocks)


def publish_new(path, value, journal):
    """Publish a private complete file without replacing a racing owner file."""
    path = storage.safe_local(path)
    raw = value if isinstance(value, bytes) else (json.dumps(value, indent=2) + '\n').encode()
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
             'model': starter.TAG, 'model_source': 'bundled', 'permissions': 'local-tools-and-benchmarks',
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
        for path in (models, state_path.parent, config_path.parent / 'workspace', config_path.parent / 'workspace/tools'):
            mkdir(path)
        # Marker is metadata, not a private credential; use exclusive creation
        # on DATA filesystems that may not support hard links.
        marker = storage.safe_local(models / '.argos-storage-id')
        raw = (state['storage_id'] + '\n').encode()
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        journal.append((marker, os.fstat(descriptor).st_ino, raw))
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        workspace = config_path.parent / 'workspace'
        for target, source in WORKSPACE_FILES:
            publish_new(workspace / target, workspace_file(source), journal)
        publish_new(config_path, conversation_config(starter.TAG, workspace), journal)
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
