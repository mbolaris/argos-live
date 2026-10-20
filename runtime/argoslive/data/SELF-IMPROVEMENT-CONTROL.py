#!/usr/bin/env python3
"""Self-upgrade controls for the Argos agent, using the dashboard's own supported endpoints.

  argos-control.py status            startup, model download and storage state (JSON)
  argos-control.py upgrades          reviewed tool-capable models: exact tag, size, fit on this GPU, installed;
                                     "next" names the model to try. Use its tag exactly.
  argos-control.py download TAG      verified download of a reviewed catalog model; follows it to the end.
                                     It restarts the assistant (ending your turn) unless TAG is already installed.
  argos-control.py restart           stop and start the assistant (Ollama + OpenClaw gateway)

`restart` ends your current turn, so run it DETACHED:
  systemd-run --user --collect --unit=argos-self-restart --on-active=15s \
      /usr/bin/python3 ~/.openclaw/workspace/tools/argos-control.py restart
Its outcome is written to ~/.local/state/argos-live/self-restart-last.json.
The dashboard session token is read locally and never printed.
"""
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

home = Path.home()
state_dir = home / '.local/state/argos-live'
opener = build_opener(ProxyHandler({}))


def dashboard():
    url = urlsplit(json.loads((state_dir / 'desktop-session.json').read_text())['url'])
    if url.hostname != '127.0.0.1' or url.scheme != 'http':
        raise SystemExit('Unexpected dashboard address')
    token, origin = parse_qs(url.query)['token'][0], f'http://127.0.0.1:{url.port}'

    def call(path, body=None, post=False):
        data = json.dumps(body).encode() if body is not None else (b'' if post else None)
        headers = {'X-Argos-Token': token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(origin + path, data=data, headers=headers, method='POST' if data is not None else 'GET')
        try:
            with opener.open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            return {'http_status': error.code, 'error': json.loads(error.read() or b'{}').get('error')}
    return call


def status(call):
    start, models, storage = call('/api/startup'), call('/api/models/control'), call('/api/storage')
    progress = models.get('progress') or {}
    reservation_path = state_dir / 'workload/reservation.json'
    workload = json.loads(reservation_path.read_text()) if reservation_path.exists() else {'state': 'released'}
    return {'workload': {k: workload.get(k) for k in ('state', 'kind', 'id')},
            'evaluation_running': workload.get('kind') == 'evaluation' and workload.get('state') == 'active',
            'recovery_required': workload.get('state') == 'quarantined',
            'assistant': {k: start.get(k) for k in ('phase', 'model', 'model_reply_verified', 'failure')},
            'download': {'phase': models.get('phase'), 'active': models.get('active'), 'model': models.get('model'),
                         'bytes_done': progress.get('bytes_done'), 'bytes_total': progress.get('bytes_total'),
                         'reply_test': models.get('reply_test')},
            'storage_confirmed': storage.get('confirmed')}


def installed_models():
    try:
        with opener.open('http://127.0.0.1:11434/api/tags', timeout=10) as response:
            return {model['name'] for model in json.load(response).get('models', [])}
    except (OSError, ValueError):
        return set()


def upgrades():
    sys.path.insert(0, '/usr/local/lib/argos-live')
    from argoslive import catalog, first_model, hw
    vram = max((gpu.get('vram_total_bytes') or 0 for gpu in hw.snapshot().get('gpus', [])), default=0)
    config = json.loads((home / '.openclaw/openclaw.json').read_text())
    current = config['agents']['defaults']['model']['primary'].split('/', 1)[-1]
    installed, rows = installed_models(), []
    for entry in catalog.load()['models']:
        if 'tools' not in entry.get('capabilities', []) or '/' in entry['tag'] or not entry.get('kv_cache'):
            continue
        need = first_model.footprint(entry)
        rows.append({'tag': entry['tag'], 'family': entry.get('family'), 'billion_params': round(entry.get('parameter_count', 0) / 1e9, 1),
                     'needs_gb': round(need / 2**30, 1), 'fits': need <= vram, 'installed': entry['tag'] in installed,
                     'current': entry['tag'] == current})
    rows.sort(key=lambda row: -row['billion_params'])
    size = {row['tag']: row['billion_params'] for row in rows}
    better = [row for row in rows if row['fits'] and row['family'] in first_model.GENERAL_FAMILIES
              and row['billion_params'] > size.get(current, 0)]
    if better:
        nxt = 'Try ' + better[0]['tag'] + ': ' + ('printf "yes\n" | argos select-model --model ' if better[0]['installed']
                                                 else 'python3 tools/argos-control.py download ') + better[0]['tag']
    else:
        nxt = 'No larger general model fits; tune configuration and instructions instead (MoE such as qwen3:30b only if it fits and you want to test it).'
    return {'gpu_vram_gb': round(vram / 2**30, 1), 'current': current, 'next': nxt,
            'fitting_models': ['{tag} {billion_params}B needs {needs_gb}GB{i}{c}'.format(
                **row, i=' installed' if row['installed'] else '', c=' CURRENT' if row['current'] else '')
                for row in rows if row['fits']][:4]}


def download(call, tag):
    if tag in installed_models():
        # A download restarts the assistant to load-test the model; never repeat one.
        return {'tag': tag, 'already_installed': True, 'started': False,
                'next': 'Switch now: printf "yes\\n" | argos select-model --model ' + tag}
    started = call('/api/models/download', {'tag': tag})
    if started.get('http_status'):
        return {'tag': tag, 'started': False, **started,
                'hint': 'Check the exact catalog tag, free space, and that no other download or Lab run is active.'}
    while True:
        time.sleep(10)
        snapshot = call('/api/models/control')
        if not snapshot.get('active'):
            return {'tag': tag, 'final_phase': snapshot.get('phase'), 'reply_test': snapshot.get('reply_test'),
                    'next': 'If final_phase is completed: printf "yes\\n" | argos select-model --model ' + tag}


def restart(call):
    def record(**facts):
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        (state_dir / 'self-restart-last.json').write_text(
            json.dumps({'observed': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **facts}, indent=1) + '\n')
    record(phase='stopping')
    call('/api/startup/stop', post=True)
    deadline = time.time() + 300
    while time.time() < deadline and call('/api/startup').get('active'):
        time.sleep(2)
    record(phase='starting')
    call('/api/startup/start', post=True)
    deadline, state = time.time() + 1200, {}
    while time.time() < deadline:
        time.sleep(3)
        state = call('/api/startup')
        if state.get('phase') in ('ready', 'failed'):
            break
    record(phase=state.get('phase'), model=state.get('model'), failure=state.get('failure'),
           model_reply_verified=state.get('model_reply_verified'))
    return {'restart_phase': state.get('phase')}


if __name__ == '__main__':
    command = sys.argv[1:2] or ['status']
    if command == ['upgrades']:
        print(json.dumps(upgrades(), indent=1))
        raise SystemExit
    call = dashboard()
    if command == ['status']:
        print(json.dumps(status(call), indent=1))
    elif command == ['download'] and len(sys.argv) == 3:
        print(json.dumps(download(call, sys.argv[2]), indent=1))
    elif command == ['restart']:
        print(json.dumps(restart(call)))
    else:
        raise SystemExit(__doc__)
