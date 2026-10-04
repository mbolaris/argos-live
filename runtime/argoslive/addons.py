"""Inert capability inventory; no plugin loading, grants or provider installation."""
import argparse
import json
from pathlib import Path
import re
import shutil

DEFAULT = Path(__file__).resolve().parent / 'data/addons.json'
PLAN = [
    ('local-chat', 'ollama', ['ollama'], ['Verified local model and loopback provider configuration']),
    ('local-vision', 'ollama', ['ollama'], ['Verified vision model, supplied test image and capacity test']),
    ('memory', 'memory-core', [], ['Encrypted per-agent state; selected local embeddings and reboot-recall test']),
    ('browser', 'browser', [], ['Supported Chrome/Chromium runtime, isolated profile and browser tool permission']),
    ('documents', 'document-extract', [], ['Installed clawpdf dependencies; controlled sample extraction']),
    ('voice-output', 'tts-local-cli', [], ['Reviewed Linux speech CLI, voice assets and audio output']),
    ('voice-input', None, [], ['Compatible local transcription adapter/engine/assets not selected']),
    ('image-generation', None, [], ['Compatible local image adapter/engine/assets not selected']),
    ('reviewed-skills', None, [], ['Owner-reviewed definitions, observed Linux dependencies and tool policy']),
    ('optional-channel', 'telegram', [], ['Owner-selected channel credentials, network and activation']),
]


def validate(data):
    if (not isinstance(data, dict) or data.get('schema') != 'argos-addons/1'
            or not isinstance(data.get('host_version'), str)
            or not re.fullmatch(r'sha512-[A-Za-z0-9+/]{86}==', data.get('host_integrity', ''))
            or not isinstance(data.get('plugins'), list)):
        raise ValueError('Invalid addon catalog')
    seen = set()
    for item in data['plugins']:
        if (not isinstance(item, dict) or item.get('id') in seen
                or not re.fullmatch(r'[a-z0-9-]+', item.get('id', ''))
                or item.get('version') != data['host_version']
                or item.get('compatible_host') != data['host_version']
                or item.get('host_integrity') != data['host_integrity']
                or item.get('distribution') != 'host-bundled'
                or not isinstance(item.get('license'), str)
                or not isinstance(item.get('npm_dependencies'), dict)
                or not isinstance(item.get('declared_contracts'), dict)
                or any(not re.fullmatch(r'[a-f0-9]{64}', item.get(k, '')) for k in ('manifest_sha256', 'package_sha256'))
                or item.get('invocation_verified') is not False):
            raise ValueError('Invalid bundled provenance; invocation must remain unverified')
        seen.add(item['id'])
    if not {'ollama', 'memory-core', 'browser', 'document-extract', 'tts-local-cli', 'telegram'} <= seen:
        raise ValueError('Missing required capability candidates')
    for item in data.get('shipped_skill_documents', []):
        if (not isinstance(item.get('path'), str) or item['path'].startswith('/')
                or '..' in item['path'].split('/') or not item['path'].endswith('/SKILL.md')
                or not re.fullmatch(r'[a-f0-9]{64}', item.get('sha256', ''))):
            raise ValueError('Invalid inert skill descriptor')
    if data.get('external_addons') != []:
        raise ValueError('External candidates require independent reviewed pins')
    return data


def load(path=DEFAULT):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))


def observation(inspect, *, runtime=False):
    """Whitelist harmless receipt fields. Snapshot status is not runtime loading."""
    plugin = inspect.get('plugin', {})
    if not isinstance(plugin, dict) or not isinstance(plugin.get('id'), str):
        raise ValueError('Unexpected plugin inspect shape')
    return {'id': plugin['id'], 'version': plugin.get('version'),
            'discovered': True, 'reported_status': plugin.get('status'),
            'runtime_loaded': plugin.get('status') == 'loaded' if runtime else None,
            'inspection_runtime': runtime, 'invocation_verified': False,
            'effective_agent_tool_grants': None, 'gateway_exercised': False}


def inventory(data, *, observations=(), which=shutil.which):
    data = validate(data)
    observed = {item['id']: item for item in observations}
    candidates = {item['id']: item for item in data['plugins']}
    for ident, receipt in observed.items():
        if ident not in candidates or receipt.get('version') != data['host_version']:
            raise ValueError('Observed plugin is outside the pinned catalog')
    rows = []
    for ident, plugin, binaries, requirements in PLAN:
        missing = [name for name in binaries if which(name) is None]
        row = {'capability': ident, 'plugin': plugin, 'bundled_available': plugin in candidates if plugin else None,
               'installed_on_target': True if plugin in observed else None,
               'runtime_loaded': observed.get(plugin, {}).get('runtime_loaded'),
               'missing_binaries': missing, 'requirements_pending': requirements,
               'effective_agent_tool_grants': None, 'invocation_verified': False, 'ready': False,
               'state': 'dependency-missing' if missing else 'acceptance-pending' if plugin else 'selection-pending'}
        rows.append(row)
    return {'schema': 'argos-capabilities/1', 'host_version': data['host_version'],
            'capabilities': rows, 'dependency_license_review': 'pending',
            'note': 'No activation, installation, credential or policy changes.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only addon candidates and conservative capability readiness.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    result = inventory(load())
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for item in result['capabilities']:
            print(f"{item['capability']}: {item['state']}; ready=false")
            for reason in item['requirements_pending']:
                print('  ' + reason)
    return 0
