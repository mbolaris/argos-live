"""Deliberate private personality export. Source files/configuration stay untouched."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import zipfile

from . import packs

WINDOWS_HOST = os.name == 'nt'
SECRET_KEYS = {'apikey', 'token', 'accesstoken', 'refreshtoken', 'password',
               'passphrase', 'clientsecret', 'privatekey', 'authorization', 'credentials',
               'secrets', 'headers', 'env', 'environment', 'cookie', 'auth'}
SECRET_PATTERNS = [re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
                   re.compile(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----', re.S)]


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def unlinked(path):
    path = Path(path).absolute()
    if any(linked(parent) for parent in (path, *path.parents)):
        raise ValueError('Linked source or output path rejected')
    return path


def bounded(path):
    path = unlinked(path)
    if not path.is_file():
        raise ValueError('Expected a regular source document')
    with path.open('rb') as stream:
        data = stream.read(packs.MAX_FILE + 1)
    if len(data) > packs.MAX_FILE:
        raise ValueError('Source document exceeds pack limit')
    return data


def private_directory(path):
    path.mkdir(mode=0o700)
    if os.name == 'nt':
        sid = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                      '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'], text=True).strip()
        if not re.fullmatch(r'S-1-[0-9-]+', sid):
            raise ValueError('Cannot establish private output owner')
        subprocess.run(['icacls.exe', str(path), '/inheritance:r', '/grant:r',
                        f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
                       check=True, stdout=subprocess.DEVNULL)


def export(source, destination, agent_ids, skills=(), workspace_overrides=None):
    source, destination = unlinked(source), unlinked(destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Choose a fresh output directory with an existing private parent')
    config = json.loads(bounded(source / 'openclaw.json').decode('utf-8-sig'))
    agents = config.get('agents', {})
    if isinstance(agents.get('entries'), dict):
        roster = agents['entries']
    elif isinstance(agents.get('list'), list):
        roster = {}
        for entry in agents['list']:
            if not isinstance(entry, dict) or entry.get('id') in roster:
                raise ValueError('Invalid source agent roster')
            roster[entry.get('id')] = entry
    else:
        raise ValueError('Unsupported source roster; inspect before exporting')
    if not agent_ids or len(set(agent_ids)) != len(agent_ids):
        raise ValueError('Select unique source agent IDs')
    chosen = dict(workspace_overrides or {})
    if set(chosen) - set(agent_ids):
        raise ValueError('Workspace mapping references an unselected agent')
    selected_skills = {}
    for selection in skills:
        agent, sep, skill = selection.partition(':')
        if not sep or agent not in agent_ids:
            raise ValueError('Skill selection must be selected-agent:skill-id')
        packs.identifier(skill)
        if skill in selected_skills.setdefault(agent, []):
            raise ValueError('Duplicate skill selection')
        selected_skills[agent].append(skill)
    secrets = set()
    def gather(value, sensitive=False):
        if isinstance(value, dict):
            for key, child in value.items():
                norm = re.sub(r'[^a-z0-9]', '', key.lower())
                gather(child, sensitive or norm in SECRET_KEYS or norm.endswith('apikey'))
        elif isinstance(value, list):
            for child in value:
                gather(child, sensitive)
        elif sensitive and isinstance(value, str) and len(value) >= 8:
            secrets.add(value)
    gather(config)
    credential_root = source / 'credentials'
    if credential_root.is_dir() and not linked(credential_root):
        for credential in credential_root.glob('*.json'):
            gather(json.loads(bounded(credential).decode('utf-8-sig')), True)
    if (source / 'secrets.json').is_file():
        gather(json.loads(bounded(source / 'secrets.json').decode('utf-8-sig')), True)
    payload, exported, redacted = {}, [], []
    def add(path, target):
        value = bounded(path).decode('utf-8-sig')
        original = value
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '<REDACTED>')
        for pattern in SECRET_PATTERNS:
            value = pattern.sub('<REDACTED>', value)
        if value != original:
            redacted.append(target)
        payload[target] = value.encode('utf-8')
    for agent_id in agent_ids:
        packs.identifier(agent_id)
        entry = roster.get(agent_id)
        if not isinstance(entry, dict):
            raise ValueError('Selected source agent not found')
        workspace = chosen.get(agent_id) or entry.get('workspace')
        if workspace is None and agent_id == 'main':
            workspace = agents.get('defaults', {}).get('workspace')
        if not isinstance(workspace, str) or not workspace:
            raise ValueError('Explicit workspace required for selected agent')
        if not WINDOWS_HOST and PureWindowsPath(workspace).drive:
            raise ValueError('Windows workspace needs an explicit local --workspace mapping')
        workspace = Path(workspace).expanduser()
        if not workspace.is_absolute():
            raise ValueError('Source workspace must be absolute or explicitly mapped')
        workspace = unlinked(workspace)
        if not workspace.is_dir():
            raise ValueError('Selected workspace unavailable')
        if destination.is_relative_to(source) or destination.is_relative_to(workspace):
            raise ValueError('Private output must be outside source and workspaces')
        exported_agent = {'id': agent_id, 'name': entry.get('name') or agent_id,
                          'persona_files': [], 'skill_files': []}
        for filename in sorted(packs.PERSONAS):
            path = workspace / filename
            if path.exists():
                target = f'agents/{agent_id}/persona/{filename}'
                add(path, target)
                exported_agent['persona_files'].append(target)
        for skill in selected_skills.get(agent_id, []):
            root = unlinked(workspace / 'skills' / skill)
            if not (root / 'SKILL.md').is_file() and not (root / 'definition.json').is_file():
                raise ValueError('Selected skill definition missing')
            for filename in ('SKILL.md', 'definition.json', 'README.txt'):
                if (root / filename).exists():
                    target = f'agents/{agent_id}/skills/{skill}/{filename}'
                    add(root / filename, target)
                    exported_agent['skill_files'].append(target)
        model = entry.get('model', agents.get('defaults', {}).get('model'))
        model = model.get('primary') if isinstance(model, dict) else model
        if isinstance(model, str) and model:
            # A preference is not an installed provider binding or a replacement model.
            exported_agent['model_preference'] = {'name': model.removeprefix('ollama/')}
        exported.append(exported_agent)
    manifest = {'schema': 'argos-pack/1', 'id': 'personal-export', 'version': '1',
                'created': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'agents': exported, 'files': [
                    {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    for name, data in payload.items()]}
    packs.validate_manifest(manifest)
    private_directory(destination)  # Enforce output privacy before any private bytes are written.
    bundle_path = destination / '.personality-pack-review.zip'
    with zipfile.ZipFile(bundle_path, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
        for name, data in payload.items():
            bundle.writestr(name, data)
    bundle_path.chmod(0o600)
    report = packs.inspect(bundle_path)
    bundle_path.rename(destination / 'personality-pack.zip')
    (destination / 'SHA256SUMS').write_text(report['archive_sha256'] + '  personality-pack.zip\n', encoding='utf-8')
    (destination / 'SHA256SUMS').chmod(0o600)
    return {'archive_sha256': report['archive_sha256'], 'agents': agent_ids,
            'files': len(payload), 'redacted_files': redacted,
            'excluded': ['credentials and runtime config', 'memory/history', 'tool permissions and providers',
                         'executables/media/model weights', 'unselected skills and non-allowlisted files'],
            'activation': False, 'content_review': 'Required; arbitrary prose is not certified secret-free'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='OpenClaw home containing openclaw.json')
    parser.add_argument('--output', required=True, help='Fresh private output directory on encrypted storage')
    parser.add_argument('--agent', action='append', required=True, help='Explicit selected source ID (repeatable)')
    parser.add_argument('--skill', action='append', default=[], help='Selected agent:skill-id (repeatable)')
    parser.add_argument('--workspace', action='append', default=[], help='Explicit agent=local-path mapping')
    args = parser.parse_args(argv)
    overrides = {}
    for mapping in args.workspace:
        agent, sep, path = mapping.partition('=')
        if not sep or agent in overrides:
            raise ValueError('Expected unique agent=path workspace mapping')
        overrides[agent] = path
    print(json.dumps(export(args.source, args.output, args.agent, args.skill, overrides), indent=2))
