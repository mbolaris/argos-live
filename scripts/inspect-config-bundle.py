#!/usr/bin/env python3
"""Inspect an untrusted configuration ZIP without extracting or running its contents."""
import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

MAX_MEMBERS = 2000
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
EXECUTABLE_SUFFIXES = {'.exe', '.dll', '.com', '.bat', '.cmd', '.ps1', '.sh', '.py', '.js', '.mjs', '.cjs', '.so'}


def inspect(archive, expected):
    archive = Path(archive)
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('Expected a regular configuration ZIP.')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
        raise ValueError('Expected SHA256 must contain 64 hex digits.')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected.lower():
        raise ValueError('Transfer SHA256 differs; no inspection attempted.')
    members, seen, total, reference = [], set(), 0, None
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > MAX_MEMBERS:
            raise ValueError('Too many archive members.')
        for entry in entries:
            # orig_filename preserves NUL/backslash input that ZipInfo may normalize.
            name = entry.orig_filename
            parts = PurePosixPath(name).parts
            if (not name or '\\' in name or ':' in name or name.startswith('/')
                    or any(p in ('.', '..') for p in name.split('/') if p)
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)
                    or any(p.endswith((' ', '.')) for p in parts)):
                raise ValueError('Unsafe archive member path.')
            key = name.rstrip('/').casefold()
            if key in seen:
                raise ValueError('Duplicate or case-colliding archive member.')
            seen.add(key)
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('Links or special files are not configuration data.')
            if entry.flag_bits & 1:
                raise ValueError('Encrypted ZIP members require a separate reviewed workflow.')
            if entry.is_dir():
                continue
            if Path(name).suffix.casefold() in EXECUTABLE_SUFFIXES or mode & 0o111:
                raise ValueError('Executable helper in configuration-only export.')
            total += entry.file_size
            if entry.file_size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('Archive expansion exceeds configuration limits.')
            if entry.file_size > max(1024 * 1024, entry.compress_size * 200):
                raise ValueError('Suspicious archive expansion ratio.')
            # Full bounded read verifies CRC; content is never interpreted as instructions.
            with bundle.open(entry) as content:
                h, count = hashlib.sha256(), 0
                for chunk in iter(lambda: content.read(65536), b''):
                    count += len(chunk)
                    if count > MAX_FILE or count > entry.file_size:
                        raise ValueError('Unexpected member expansion.')
                    h.update(chunk)
                if count != entry.file_size:
                    raise ValueError('Member length differs.')
            members.append({'path': name, 'bytes': count, 'sha256': h.hexdigest()})
        names = {item['path']: item for item in members}
        if 'manifest.json' in names and 'migration-reference.json' in names:
            manifest = json.loads(bundle.read('manifest.json'))
            migration = json.loads(bundle.read('migration-reference.json'))
            declared = manifest.get('files')
            if not isinstance(declared, list):
                raise ValueError('Reference manifest file inventory missing.')
            covered = set()
            for item in declared:
                if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                    raise ValueError('Invalid reference manifest entry.')
                name = item['path']
                actual = names.get(name)
                if name in covered or not actual or item.get('bytes') != actual['bytes'] or item.get('sha256') != actual['sha256']:
                    raise ValueError('Internal reference manifest differs from ZIP contents.')
                covered.add(name)
            if covered != set(names) - {'manifest.json'}:
                raise ValueError('Unlisted reference ZIP files.')
            reference = {'sourceVersion': migration.get('sourceVersion'),
                         'sourceSchema': migration.get('sourceSchema'),
                         'profiles': manifest.get('profiles'),
                         'internalManifestVerified': True}
    # Filenames and hashes can themselves be private; callers protect this report.
    return {'archiveSHA256': digest.hexdigest(), 'kind': 'configuration-only ZIP',
            'fileCount': len(members), 'expandedBytes': total, 'members': members,
            'credentialExclusion': 'Not independently established; content review required',
            'activation': 'Not performed', 'recoveryBackup': False, 'reference': reference}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.archive, args.sha256), indent=2))
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError) as error:
        print(f'Configuration inspection failed: {error}', file=sys.stderr)
        sys.exit(1)
