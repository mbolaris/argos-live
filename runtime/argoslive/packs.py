"""Inspect argos-pack/1 personality archives as inert data; never extract."""
import hashlib
from datetime import datetime
import io
import json
from pathlib import Path
import re
import stat
import zipfile

MAX_ARCHIVE = 32 * 1024**2
MAX_TOTAL = 16 * 1024**2
MAX_FILE = 1024**2
MAX_MEMBERS = 128
PERSONAS = {'AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md'}
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)),
            *(f'lpt{i}' for i in range(1, 10))}


def safe_path(name):
    if not isinstance(name, str) or len(name) > 240:
        raise ValueError('Invalid pack path')
    parts = name.split('/')
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', part)
           or part.endswith('.') or part.split('.')[0].casefold() in RESERVED
           for part in parts):
        raise ValueError('Unsafe pack path')
    return name


def object_keys(value, required, optional=()):
    if (not isinstance(value, dict) or not set(required) <= set(value)
            or set(value) - set(required) - set(optional)):
        raise ValueError('Invalid or forbidden manifest fields')


def text(value, maximum=256):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise ValueError('Invalid manifest text')


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('Invalid identifier')


def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid UTF-8/JSON document') from exc


def validate_manifest(manifest):
    object_keys(manifest, {'schema', 'id', 'version', 'created', 'agents', 'files'})
    if manifest['schema'] != 'argos-pack/1':
        raise ValueError('Unsupported pack schema')
    identifier(manifest['id'])
    text(manifest['version'], 64)
    if not isinstance(manifest['created'], str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', manifest['created']):
        raise ValueError('Expected UTC created timestamp')
    datetime.strptime(manifest['created'], '%Y-%m-%dT%H:%M:%SZ')
    agents = manifest['agents']
    if not isinstance(agents, list) or not 1 <= len(agents) <= 16:
        raise ValueError('Expected 1–16 agents')
    ids, assigned = set(), set()
    for agent in agents:
        object_keys(agent, {'id', 'name', 'persona_files', 'skill_files'}, {'model_preference', 'notes'})
        identifier(agent['id'])
        key = agent['id'].casefold()
        if key in ids:
            raise ValueError('Duplicate agent ID')
        ids.add(key)
        text(agent['name'])
        if 'notes' in agent:
            text(agent['notes'], 2048)
        preference = agent.get('model_preference')
        if preference is not None:
            object_keys(preference, {'name'}, {'quantization'})
            text(preference['name'])
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*', preference['name'])
                    or ':/' in preference['name'] or '..' in preference['name']):
                raise ValueError('Model preference must be a model reference, not a URL/path')
            if 'quantization' in preference:
                identifier(preference['quantization'])
        for group in ('persona_files', 'skill_files'):
            paths = agent[group]
            if not isinstance(paths, list) or (group == 'persona_files' and not paths):
                raise ValueError('Invalid document selection')
            for name in paths:
                safe_path(name)
                parts = name.split('/')
                prefix = ['agents', agent['id'], 'persona' if group == 'persona_files' else 'skills']
                if parts[:3] != prefix:
                    raise ValueError('Document belongs to a different agent or category')
                if group == 'persona_files':
                    if len(parts) != 4 or parts[3] not in PERSONAS:
                        raise ValueError('Persona document not allowlisted')
                else:
                    if len(parts) != 5 or parts[4] not in ('SKILL.md', 'definition.json', 'README.txt'):
                        raise ValueError('Skill definition not allowlisted')
                    identifier(parts[3])
                if name.casefold() in assigned:
                    raise ValueError('Duplicate document assignment')
                assigned.add(name.casefold())
    files = manifest['files']
    if not isinstance(files, list) or not 1 <= len(files) < MAX_MEMBERS:
        raise ValueError('Invalid file manifest')
    declared = set()
    expanded = 0
    for item in files:
        object_keys(item, {'path', 'bytes', 'sha256'})
        safe_path(item['path'])
        if (type(item['bytes']) is not int or not 0 <= item['bytes'] <= MAX_FILE
                or not isinstance(item['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
            raise ValueError('Invalid file integrity metadata')
        key = item['path'].casefold()
        if key in declared:
            raise ValueError('Duplicate declared file')
        declared.add(key)
        expanded += item['bytes']
    if expanded > MAX_TOTAL:
        raise ValueError('Manifest expansion limit exceeded')
    if declared != assigned:
        raise ValueError('File manifest and document assignments differ')
    return manifest


def inspect(archive, expected_sha256=None):
    path = Path(archive)
    if path.is_symlink() or not path.is_file() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('Expected a regular private pack file')
    with path.open('rb') as stream:
        raw = stream.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('Pack exceeds archive limit')
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256)
                or digest != expected_sha256.lower()):
            raise ValueError('Transfer SHA256 differs or is invalid')
    payload = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            entries = bundle.infolist()
            if not 1 <= len(entries) <= MAX_MEMBERS:
                raise ValueError('Too many pack members')
            seen, total = set(), 0
            for entry in entries:
                name = safe_path(entry.orig_filename)
                mode = entry.external_attr >> 16
                if (entry.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or mode & 0o111 or entry.flag_bits & 1):
                    raise ValueError('Directories, links, encrypted members or executable files are forbidden')
                if name.casefold() in seen:
                    raise ValueError('Duplicate or case-colliding pack member')
                seen.add(name.casefold())
                total += entry.file_size
                if (entry.file_size > MAX_FILE or total > MAX_TOTAL
                        or entry.file_size > max(65536, entry.compress_size * 200)):
                    raise ValueError('Pack expansion limit exceeded')
                with bundle.open(entry) as stream:
                    data = stream.read(MAX_FILE + 1)
                if len(data) != entry.file_size:
                    raise ValueError('Member length differs')
                data.decode('utf-8')
                payload[name] = data  # Bounded reads check ZIP CRCs, never extraction.
    except (zipfile.BadZipFile, UnicodeError, RuntimeError, NotImplementedError) as exc:
        raise ValueError('Invalid personality ZIP') from exc
    if 'manifest.json' not in payload:
        raise ValueError('Pack manifest missing')
    manifest = validate_manifest(decode(payload['manifest.json']))
    if set(payload) != {'manifest.json', *(item['path'] for item in manifest['files'])}:
        raise ValueError('Manifest does not cover exact ZIP contents')
    for item in manifest['files']:
        data = payload[item['path']]
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Payload integrity differs')
        if item['path'].endswith('/definition.json'):
            definition = decode(data)
            object_keys(definition, {'name', 'description', 'instructions'}, {'dependencies'})
            identifier(definition['name'])
            text(definition['description'], 2048)
            if not isinstance(definition['instructions'], str):
                raise ValueError('Invalid skill instructions')
            dependencies = definition.get('dependencies', [])
            if not isinstance(dependencies, list):
                raise ValueError('Invalid skill dependencies')
            for dependency in dependencies:
                identifier(dependency)
    return {'schema': 'argos-pack-inspection/1', 'archive_sha256': digest,
            'file_count': len(payload), 'expanded_bytes': total, 'manifest': manifest,
            'activation': False, 'extracted': False,
            'content_review': 'Required: free-form text can contain private or operational content'}
