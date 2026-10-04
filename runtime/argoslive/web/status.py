"""Read-only dashboard probes. Unknown measurements stay unknown; no write tests."""
import json
from http.client import HTTPException
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

from argoslive import hw, storage
from argoslive.bench_speed import placement
from argoslive.ollama import Client, NoRedirect, OllamaError


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Configuration too large')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Configuration must be an object')
    return result


def gateway(config):
    value = config.get('gateway', {})
    port = value.get('port', 18789)
    if (value.get('bind', 'loopback') != 'loopback' or value.get('mode', 'local') != 'local'
            or type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('Only a local loopback gateway is supported')
    return f'http://127.0.0.1:{port}'


def gateway_ready(origin):
    # Never use environment proxies or follow a redirect away from loopback.
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(origin + '/readyz', timeout=2) as response:
            raw = response.read(16385)
        return len(raw) <= 16384 and json.loads(raw).get('ready') is True
    except (OSError, HTTPException, ValueError, TypeError, AttributeError):
        return False


def chat_url(config_path, *, ready=gateway_ready):
    config = read_json(config_path)
    origin = gateway(config)
    auth = config.get('gateway', {}).get('auth', {})
    token = auth.get('token')
    if auth.get('mode', 'token') != 'token' or not isinstance(token, str) or not token:
        raise ValueError('Token-based chat is not configured')
    if not ready(origin):
        raise ValueError('Assistant is not ready')
    return origin + '/chat#token=' + quote(token, safe='')


def mounts_and_blocks(run=hw.command, proc=Path('/proc')):
    text = hw.read(proc / 'self/mountinfo')
    if text is None:
        raise ValueError('Mount information unavailable')
    mounts = storage.mount_table(text)
    raw = run(['lsblk', '--json', '--paths', '--output', 'NAME,TYPE,FSTYPE,UUID,TRAN,MAJ:MIN'])
    return mounts, storage.block_table(raw) if raw else {}


def encryption(mount, blocks):
    block = storage.block_for(mount, blocks) if mount else None
    states = set(block['encrypted_paths']) if block else set()
    return next(iter(states)) if len(states) == 1 else None


def persistence(mounts, blocks):
    for mount in mounts:
        if (mount['target'].startswith(('/run/live/persistence/', '/lib/live/mount/persistence/'))
                and (Path(mount['target']) / 'persistence.conf').is_file()):
            return {'active': True, 'encrypted': encryption(mount, blocks), 'mode': 'persistent'}
    return {'active': False, 'encrypted': None, 'mode': 'temporary'}


def snapshot(home=None, *, run=hw.command, hardware=hw.snapshot, client=None,
             ready=gateway_ready, proc=Path('/proc')):
    started = time.monotonic()
    home = Path.home() if home is None else Path(home)
    config_path = home / '.openclaw/openclaw.json'
    result = {'schema': 'argos-dashboard/1', 'dashboard': 'running', 'mode': 'read-only-status',
              'assistant': 'not-configured', 'chat_available': False,
              'ollama': {'reachable': False, 'version': None, 'loaded_models': None, 'ownership_verified': False},
              'network': {'default_route': None, 'internet_verified': False},
              'persistence': {'active': None, 'encrypted': None, 'mode': 'unknown'},
              'model_storage': {'state': 'not-configured', 'path': None, 'encrypted': None,
                                'free_bytes': None, 'model': None}}
    try:
        mounts, blocks = mounts_and_blocks(run, proc)
        result['persistence'] = persistence(mounts, blocks)
    except (OSError, ValueError, TypeError, KeyError):
        mounts, blocks = [], {}
    try:
        configured = read_json(home / '.config/argos-live/state.json')
        path = storage.validate_configured(configured, mounts=mounts, blocks=blocks)
        result['model_storage'].update(state='available', path=str(path),
            encrypted=encryption(storage.covering(path, mounts), blocks),
            model=configured.get('model') if isinstance(configured.get('model'), str) else None)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError):
        result['model_storage']['state'] = 'needs-attention'
    model_path = result['model_storage']['path']
    result['hardware'] = hardware([model_path] if model_path else [])
    directories = result['hardware'].get('model_directories', [])
    if directories:
        result['model_storage']['free_bytes'] = directories[0].get('free_bytes')
    try:
        raw = run(['ip', '-j', 'route', 'show', 'default'])
        routes = json.loads(raw) if raw is not None else None
        if isinstance(routes, list):
            result['network']['default_route'] = bool(routes)
    except (ValueError, TypeError):
        pass
    client = client or Client(timeout=2)
    try:
        version = client.version()
        result['ollama'].update(reachable=True, version=version if isinstance(version, str) else None)
        models = client.ps().get('models', [])
        if isinstance(models, list):
            result['ollama']['loaded_models'] = []
            for model in models:
                name = model.get('name') or model.get('model')
                if isinstance(name, str):
                    result['ollama']['loaded_models'].append({'name': name, 'backend': placement(models, name)})
    except (OllamaError, OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    try:
        config = read_json(config_path)
        origin = gateway(config)
        result['assistant'] = 'ready' if ready(origin) else 'not-ready'
        auth = config.get('gateway', {}).get('auth', {})
        result['chat_available'] = (result['assistant'] == 'ready' and auth.get('mode', 'token') == 'token'
                                    and isinstance(auth.get('token'), str) and bool(auth['token']))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result['assistant'] = 'configuration-needs-attention'
    result['probe_seconds'] = round(time.monotonic() - started, 3)
    return result
