"""Private verified pack staging and file-level preview, without activation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid

from . import packs
from .pack_export import bounded, private_directory, unlinked


def model_resolution(preference, catalog=None, installed=None):
    """Match exact caller-supplied identities; this does not prove inference readiness."""
    if preference is None:
        return {'status': 'unresolved', 'reason': 'No model preference supplied', 'ready': False}
    name = preference['name'].removeprefix('ollama/')
    for status, inventory in (('installed', installed), ('in catalog', catalog)):
        entry = (inventory or {}).get(name)
        if (isinstance(entry, dict) and entry.get('verified') is True
                and isinstance(entry.get('manifest_sha256'), str)
                and re.fullmatch(r'[a-f0-9]{64}', entry['manifest_sha256'])
                and (not preference.get('quantization')
                     or preference['quantization'] == entry.get('quantization'))):
            return {'status': status, 'model': name, 'manifest_sha256': entry['manifest_sha256'],
                    'ready': False, 'evidence': 'Caller-supplied model inventory; capability test required'}
    return {'status': 'unresolved', 'model': name,
            'reason': 'No exact verified Ollama identity/quantization match', 'ready': False}


def active_roster(home):
    home = unlinked(home)
    config = home / 'openclaw.json'
    if not config.exists():
        return {}
    data = json.loads(bounded(config).decode('utf-8-sig'))
    agents = data.get('agents', {})
    if isinstance(agents.get('list'), list):
        entries = agents['list']
    elif isinstance(agents.get('entries'), dict):
        entries = []
        for key, entry in agents['entries'].items():
            if not isinstance(entry, dict):
                raise ValueError('Invalid active roster')
            entries.append(dict(entry, id=key))
    elif agents.get('defaults', {}).get('workspace'):
        entries = [{'id': 'main', 'workspace': agents['defaults']['workspace']}]
    else:
        return {}
    roster = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid active roster')
        packs.identifier(entry.get('id'))
        key = entry['id'].casefold()
        if key in roster:
            raise ValueError('Ambiguous active roster IDs')
        if entry['id'] == 'main' and not entry.get('workspace'):
            entry = dict(entry, workspace=agents.get('defaults', {}).get('workspace'))
        roster[key] = entry
    return roster


def preview(manifest, roster, *, catalog=None, installed=None):
    changes = []
    files = {item['path']: item for item in manifest['files']}
    for agent in manifest['agents']:
        active = roster.get(agent['id'].casefold())
        conflicts = []
        if active and active['id'] != agent['id']:
            conflicts.append('Existing agent ID differs only by case')
        active_name = (active.get('name') or active.get('identity', {}).get('name')) if active else None
        if active_name and active_name != agent['name']:
            conflicts.append('Existing ID belongs to a differently named agent')
        workspace = active.get('workspace') if active else None
        if active and (not isinstance(workspace, str) or not Path(workspace).is_absolute()):
            conflicts.append('Existing workspace unavailable or not an absolute local path')
            workspace = None
        diffs = []
        for name in agent['persona_files'] + agent['skill_files']:
            parts = name.split('/')
            relative = Path(parts[3]) if parts[2] == 'persona' else Path('skills', *parts[3:])
            state = 'added' if not active else 'unavailable'
            current_sha256 = None
            if workspace:
                try:
                    path = unlinked(Path(workspace) / relative)
                    if not Path(workspace).is_dir():
                        raise ValueError('Workspace unavailable')
                    state = 'changed' if path.exists() else 'added'
                    if path.exists():
                        current = bounded(path)
                        current_sha256 = hashlib.sha256(current).hexdigest()
                        if hashlib.sha256(current).hexdigest() == files[name]['sha256']:
                            state = 'unchanged'
                except (OSError, ValueError):
                    state = 'unavailable'
                    conflicts.append('Existing document cannot be safely compared')
            diffs.append({'path': name, 'status': state, 'current_sha256': current_sha256})
        changes.append({'id': agent['id'], 'name': agent['name'],
                        'action': 'update' if active else 'add', 'conflicts': sorted(set(conflicts)),
                        'files': diffs, 'model': model_resolution(agent.get('model_preference'), catalog, installed),
                        'skills_needing_review': agent['skill_files']})
    return {'schema': 'argos-pack-preview/1', 'agents': changes, 'activation': False,
            'permissions': 'Not imported', 'memory_history': 'Not imported',
            'existing_files_absent_from_pack': 'Retained; this preview does not propose deletions'}


def stage(archive, staging_root, active_home, expected=None, *, stage_id=None,
          catalog=None, installed=None):
    archive, staging_root = unlinked(archive), unlinked(staging_root)
    if not staging_root.is_dir():
        raise ValueError('Use an existing private staging root on encrypted storage')
    inspection = packs.inspect(archive, expected)
    # Copy a bounded snapshot matching exactly the already-inspected bytes.
    with archive.open('rb') as stream:
        raw = stream.read(packs.MAX_ARCHIVE + 1)
    if hashlib.sha256(raw).hexdigest() != inspection['archive_sha256']:
        raise ValueError('Pack changed after inspection; nothing staged')
    roster = active_roster(active_home)
    protected = [unlinked(active_home)]
    protected += [unlinked(entry['workspace']) for entry in roster.values()
                  if isinstance(entry.get('workspace'), str) and Path(entry['workspace']).is_absolute()]
    if any(staging_root.is_relative_to(path) for path in protected):
        raise ValueError('Staging must be outside active home and workspaces')
    report = preview(inspection['manifest'], roster, catalog=catalog, installed=installed)
    stage_id = stage_id or ('pack-' + uuid.uuid4().hex)
    packs.identifier(stage_id)
    target = staging_root / stage_id
    if target.exists():
        raise ValueError('Stage already exists; previous reviews are never overwritten')
    private_directory(target)
    candidate = target / '.reference-review.zip'
    with candidate.open('xb') as stream:
        stream.write(raw)
    candidate.chmod(0o600)
    packs.inspect(candidate, inspection['archive_sha256'])
    candidate.rename(target / 'reference.zip')
    report.update(stage_id=stage_id, archive_sha256=inspection['archive_sha256'])
    config = unlinked(active_home) / 'openclaw.json'
    report['active_config_sha256'] = hashlib.sha256(bounded(config)).hexdigest() if config.exists() else None
    for name, data in (('manifest.json', inspection['manifest']), ('preview.json', report)):
        path = target / name
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        path.chmod(0o600)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--sha256')
    parser.add_argument('--staging-root', required=True,
                        help='Existing owner-private directory on verified encrypted storage')
    parser.add_argument('--active-home', default=str(Path.home() / '.openclaw'))
    args = parser.parse_args(argv)
    print(json.dumps(stage(args.archive, args.staging_root, args.active_home, args.sha256), indent=2))
