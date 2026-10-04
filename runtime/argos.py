#!/usr/bin/env python3
"""Local setup and fail-closed model storage. No secrets in the image."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error


def runtime_package_path(script=__file__, installed='/usr/local/lib/argos-live'):
    """Use the checkout package when present, otherwise the image install path."""
    checkout = Path(script).resolve().parent
    if (checkout / 'argoslive/__init__.py').is_file():
        return checkout
    return Path(installed)


sys.path.insert(0, str(runtime_package_path()))
import argoslive

STATE = Path.home() / '.config/argos-live/state.json'
OC = Path.home() / '.openclaw'
SEED = Path('/usr/local/share/argos-live/seed-model')

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, indent=2) + '\n')
    temp.chmod(0o600)
    temp.replace(path)

def probe_storage(path, minimum=0):
    p = Path(path).resolve(strict=True)
    if not p.is_dir():
        raise ValueError('Select an existing directory.')
    free = shutil.disk_usage(p).free
    if free < minimum:
        raise ValueError(f'Insufficient free space: {free / 2**30:.2f} GiB; need {minimum / 2**30:.2f} GiB.')
    marker = p / ('.argos-write-check-' + secrets.token_hex(8))
    with marker.open('x') as f:
        f.write('write check')
    marker.unlink()
    return p, free

def persistence_present():
    # Full-root Debian live persistence contains /persistence.conf on its backing fs.
    return any(any(root.glob('*/persistence.conf')) for root in (Path('/run/live/persistence'), Path('/lib/live/mount/persistence')))

def setup(ask=input):
    if STATE.exists():
        raise ValueError('Setup already exists. Back up state before reconfiguring.')
    if not persistence_present():
        print('WARNING: no live persistence detected. Settings will be lost at reboot.')
        if ask('Continue for a temporary test? Type TEMPORARY: ') != 'TEMPORARY':
            return
    print('Argos uses a local model. GitHub and cloud accounts are optional.')
    print('Default permissions: conversation and session status; shell, file tools, browser, and updates denied.')
    if ask('Accept these permissions? [yes/no]: ').strip().lower() != 'yes':
        raise ValueError('Permission setup cancelled. Broader permissions require deliberate configuration and review.')
    print('Model files on external storage are not encrypted by Argos. Use an encrypted volume if needed.')
    default = Path.home() / 'Models'
    answer = ask(f'Existing model storage directory, or Enter for {default}: ').strip()
    if not answer:
        default.mkdir(mode=0o700, exist_ok=True)
        answer = str(default)
    p, free = probe_storage(answer)
    print(f'Selected: {p}; free: {free / 2**30:.2f} GiB. No download has started.')
    if ask('Use this location? [yes/no]: ').strip().lower() != 'yes':
        return
    models = p / 'argos-models'
    models.mkdir(exist_ok=True, mode=0o700)
    seed = SEED
    if seed.is_dir() and not (models / 'manifests').exists():
        probe_storage(models, 1024**3)
        print('Copying the bundled Qwen3 0.6B model (about 0.5 GiB) into selected storage.')
        for name in ('blobs', 'manifests'):
            shutil.copytree(seed / name, models / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.partial'))
        if (seed / 'LICENSE-Qwen3.txt').is_file():
            shutil.copyfile(seed / 'LICENSE-Qwen3.txt', models / 'LICENSE-Qwen3.txt')
        verify_blobs(models)
    identity_path = models / '.argos-storage-id'
    identity = secrets.token_hex(24)
    if identity_path.exists():
        identity = identity_path.read_text().strip()
    else:
        identity_path.write_text(identity + '\n')
        identity_path.chmod(0o600)
    model = ask('Local Ollama model tag [qwen3:0.6b]: ').strip() or 'qwen3:0.6b'
    if not re.fullmatch(r'[A-Za-z0-9_.:/-]+', model) or 'cloud' in model.split(':')[-1]:
        raise ValueError('Invalid local model tag.')
    config = {
        'gateway': {'mode': 'local', 'bind': 'loopback', 'auth': {'mode': 'token', 'token': secrets.token_hex(32)}},
        'agents': {'defaults': {'model': {'primary': 'ollama/' + model}, 'workspace': str(OC / 'workspace')}},
        'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434', 'apiKey': 'ollama-local', 'api': 'ollama',
             'models': [{'id': model, 'name': model, 'input': ['text'], 'reasoning': False,
                         'contextWindow': 32768, 'maxTokens': 4096,
                         'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}},
        'tools': {'profile': 'minimal', 'deny': ['gateway', 'group:runtime', 'group:fs', 'group:web', 'browser'], 'elevated': {'enabled': False}},
        'commands': {'bash': False, 'restart': False}
    }
    save(OC / 'openclaw.json', config)
    (OC / 'workspace').mkdir(exist_ok=True, mode=0o700)
    save(STATE, {'storage': str(models), 'storage_id': identity, 'model': model, 'permissions': 'conversation-only'})
    print('Setup saved. Bundled Qwen3 0.6B supports offline conversation after setup. Other models need a download.')
    print('Optional providers: openclaw onboard. Keep the configured limited tool policy; enter keys only in its local prompt.')

def load():
    if not STATE.exists():
        raise ValueError('Run argos setup first.')
    state = json.loads(STATE.read_text())
    from argoslive.storage import validate_configured
    p = validate_configured(state)
    probe_storage(p)
    return state

def request(endpoint, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request('http://127.0.0.1:11434' + endpoint, data=data,
                                 headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=600)

def server(state):
    env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS=state['storage'], OLLAMA_NO_CLOUD='1', OLLAMA_CONTEXT_LENGTH='32768')
    # Own the process and storage explicitly; never reuse an unrelated host daemon.
    try:
        with request('/api/version'):
            raise ValueError('Port 11434 is already in use. Stop that daemon before starting Argos.')
    except (OSError, urllib.error.URLError):
        pass
    process = subprocess.Popen(['ollama', 'serve'], env=env, stdout=subprocess.DEVNULL)
    for _ in range(60):
        if process.poll() is not None:
            raise ValueError('Ollama exited during startup. Check terminal diagnostics.')
        try:
            with request('/api/version'):
                return process
        except OSError:
            time.sleep(1)
    process.terminate()
    process.wait()
    raise ValueError('Ollama startup timed out.')

def verify_blobs(storage):
    manifests = list((Path(storage) / 'manifests').rglob('*'))
    digests = set()
    for m in manifests:
        if not m.is_file():
            continue
        obj = json.loads(m.read_text())
        digests.update(x['digest'] for x in [obj['config']] + obj['layers'])
    if not digests:
        raise ValueError('No model manifests found.')
    for digest in digests:
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('Unsupported manifest digest.')
        blob = Path(storage) / 'blobs' / digest.replace(':', '-')
        h = hashlib.sha256()
        with blob.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                h.update(chunk)
        if h.hexdigest() != digest.split(':')[1]:
            raise ValueError(f'Artifact verification failed: {blob.name}')
    return len(digests)

def download_budget(model, storage):
    # Read public registry metadata before requesting any model weights.
    name, separator, tag = model.partition(':')
    tag = tag if separator else 'latest'
    if '/' not in name:
        name = 'library/' + name
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name) or not re.fullmatch(r'[A-Za-z0-9_.-]+', tag):
        raise ValueError('Only public local Ollama registry models are supported by this download workflow.')
    with urllib.request.urlopen(f'https://registry.ollama.ai/v2/{name}/manifests/{tag}', timeout=30) as r:
        manifest = json.load(r)
    missing = 0
    for part in [manifest['config']] + manifest['layers']:
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', part['digest']):
            raise ValueError('Unsupported model artifact digest.')
        file = Path(storage) / 'blobs' / part['digest'].replace(':', '-')
        if not file.is_file() or file.stat().st_size != part['size']:
            missing += part['size']
    return missing, max(1024**3, int(missing * 1.1) + 256 * 1024**2)

def select_model(model):
    state = load()
    if not model or not re.fullmatch(r'[A-Za-z0-9_.:/-]+', model) or 'cloud' in model.split(':')[-1]:
        raise ValueError('Specify a local model with --model, for example qwen3:8b.')
    print(f"Select {model}; model storage remains {state['storage']}. No weights downloaded yet.")
    if input('Select this model? [yes/no]: ').strip().lower() != 'yes':
        return
    config_path = OC / 'openclaw.json'
    config = json.loads(config_path.read_text())
    config['agents']['defaults']['model']['primary'] = 'ollama/' + model
    entry = config['models']['providers']['ollama']['models'][0]
    entry['id'] = model
    entry['name'] = model
    save(config_path, config)
    state['model'] = model
    save(STATE, state)
    print('Run argos download to review the exact registry download size.')

def command_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='Print the diagnostic result as JSON.')
    common.add_argument('--model-dir', action='append', default=argparse.SUPPRESS,
                        help='Read-only capacity probe for an existing directory (repeatable).')
    common.add_argument('--model', default=argparse.SUPPRESS)
    common.add_argument('--required-gib', type=float, default=argparse.SUPPRESS,
                        help='Download space budget; increase for larger models after checking their advertised size.')
    parser = argparse.ArgumentParser(prog='argos', description='Argos Live setup, local models, portable personalities and dashboard.', parents=[common])
    commands = parser.add_subparsers(dest='command', required=True)
    legacy = {'setup': 'Set up the local assistant', 'start': 'Start the assistant',
              'download': 'Download the selected model (legacy)', 'verify': 'Verify model artifacts',
              'diagnostics': 'Collect local diagnostics', 'select-model': 'Select a model',
              'hw': 'Read hardware measurements', 'storage': 'Preview model storage', 'catalog': 'List reviewed models'}
    for name, help_text in legacy.items():
        commands.add_parser(name, help=help_text, parents=[common])
    delegates = {'dashboard': ('argoslive.web.server', 'Open the local dashboard server'),
                 'addons': ('argoslive.addons', 'Inspect addon capability candidates'),
                 'pull': ('argoslive.model_onboarding', 'Manage verified model download jobs')}
    for name, (module, help_text) in delegates.items():
        commands.add_parser(name, help=help_text, add_help=False).set_defaults(delegate=module)
    bench = commands.add_parser('bench', help='Run local model benchmarks')
    benchmarks = bench.add_subparsers(dest='operation', required=True)
    benchmarks.add_parser('speed', help='Measure Ollama speed', add_help=False).set_defaults(delegate='argoslive.bench_speed')
    benchmarks.add_parser('ability', help='Measure original ability probes', add_help=False).set_defaults(delegate='argoslive.bench_ability')
    pack = commands.add_parser('pack', help='Export, review, apply or roll back personality packs')
    packs = pack.add_subparsers(dest='operation', required=True)
    for operation in ('export', 'import', 'apply', 'rollback'):
        module = 'pack_' + operation if operation in ('export', 'import') else 'pack_apply'
        packs.add_parser(operation, help=operation.title() + ' a personality pack', add_help=False).set_defaults(delegate='argoslive.' + module)
    return parser


def main(argv=None):
    parser = command_parser()
    args, remaining = parser.parse_known_args(argv)
    if hasattr(args, 'delegate'):
        from importlib import import_module
        if args.delegate == 'argoslive.pack_apply':
            remaining = [args.operation, *remaining]
        return import_module(args.delegate).main(remaining)
    if remaining:
        parser.error('unrecognized arguments: ' + ' '.join(remaining))
    for name, default in {'json': False, 'model_dir': [], 'model': None, 'required_gib': 4}.items():
        if not hasattr(args, name):
            setattr(args, name, default)
    if args.command == 'catalog':
        from argoslive.catalog import load as load_catalog
        data = load_catalog()
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            for model in data['models']:
                print(f"{model['tag']}: {model['total_download_bytes'] / 2**30:.2f} GiB; {model['quantization']}; {model['license']}")
            print('Catalog metadata only; models and capabilities require local verification.')
        return
    if args.command == 'storage':
        from argoslive.storage import plan
        if not math.isfinite(args.required_gib) or args.required_gib <= 0:
            raise ValueError('Space budget must be positive.')
        configured = json.loads(STATE.read_text()) if STATE.exists() else None
        result = plan(int(args.required_gib * 2**30), configured)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            encryption = {True: 'encrypted', False: 'unencrypted', None: 'unknown'}[result['encrypted']]
            print(f"Model storage: {result['path']}; encryption: {encryption}; free: {result['free_bytes'] / 2**30:.2f} GiB")
            print(result['reason'])
            print('Selection preview only; no storage created or changed.')
        return
    if args.command == 'hw':
        from argoslive.hw import snapshot
        result = snapshot(args.model_dir)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            cpu, ram = result['cpu'], result['ram']
            print(f"CPU: {cpu['model'] or 'unknown'}; cores {cpu['cores']}; threads {cpu['threads']}")
            print(f"RAM bytes: total {ram['total_bytes']}; available {ram['available_bytes']}")
            print(f"GPUs: {json.dumps(result['gpus'])}")
            print(f"Model directories: {json.dumps(result['model_directories'])}")
            print(f"Kernel: {result['kernel']}; Secure Boot: {result['secure_boot']}")
        return
    if args.command == 'setup':
        return setup()
    if args.command == 'diagnostics':
        for cmd in [('lsblk', '-o', 'NAME,MODEL,SERIAL,TRAN,SIZE,FSTYPE,UUID,MOUNTPOINTS'), ('df', '-h'), ('nvidia-smi',), ('ollama', '--version'), ('openclaw', '--version')]:
            try:
                run(*cmd)
            except (OSError, subprocess.CalledProcessError) as e:
                print(str(e))
        return
    state = load()
    if args.command == 'select-model':
        return select_model(args.model)
    if args.command == 'verify':
        print(f"Verified {verify_blobs(state['storage'])} content-addressed artifacts.")
        return
    if args.command == 'download':
        if args.required_gib <= 0:
            raise ValueError('Space budget must be positive.')
        missing, required = download_budget(state['model'], state['storage'])
        required = max(required, int(args.required_gib * 2**30))
        p, free = probe_storage(state['storage'], required)
        print(f"Download {state['model']} into {p}; missing artifacts {missing / 2**30:.2f} GiB; required space {required / 2**30:.2f} GiB; {free / 2**30:.2f} GiB free.")
        print('This needs internet. Repeat the command after interruption to resume Ollama partial blobs.')
        if input('Download now? [yes/no]: ').strip().lower() != 'yes':
            return
    daemon = server(state)
    try:
        if args.command == 'download':
            run('ollama', 'pull', state['model'])
            print(f"Verified {verify_blobs(state['storage'])} artifacts.")
        else:
            with request('/api/tags') as response:
                names = [x['name'] for x in json.load(response)['models']]
            if state['model'] not in names:
                raise ValueError('Model weights are unavailable. Run argos download while online.')
            print('Conversation-only permissions. Local model; internet is not required.')
            run('openclaw', 'gateway', 'run')
    finally:
        daemon.terminate()
        daemon.wait(timeout=30)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Argos: {error}', file=sys.stderr)
        sys.exit(1)
