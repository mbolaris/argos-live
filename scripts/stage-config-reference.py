#!/usr/bin/env python3
"""Validate and extract a redacted reference ZIP; never activate configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile


def private_windows_directory(path):
    sid = subprocess.check_output([
        'powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'
    ], text=True).strip()
    if not re.fullmatch(r'S-1-[0-9-]+', sid):
        raise ValueError('Cannot identify Windows owner for private staging')
    subprocess.run([
        'icacls.exe', str(path), '/inheritance:r', '/grant:r',
        f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F',
        '/remove:g', '*S-1-5-32-544', '*S-1-3-4'
    ], check=True, stdout=subprocess.DEVNULL)


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '\\' in name or ':' in name
            or any(ord(c) < 32 for c in name)
            or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('Unsafe archive path')
    for part in path.parts:
        if part.endswith((' ', '.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part):
            raise ValueError('Unsafe platform-specific archive path')
    return path


def stage(archive, expected, destination):
    archive = Path(archive).absolute()
    destination = Path(destination).absolute()
    if not re.fullmatch('[a-fA-F0-9]{64}', expected):
        raise ValueError('A complete SHA256 checksum is required')
    for path in (archive, *archive.parents, destination, *destination.parents):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Linked input or staging paths are not allowed')
    if not archive.is_file() or archive.stat().st_size > 128 * 1024**2:
        raise ValueError('Expected a bounded regular reference ZIP')
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Select a new directory under an existing private parent')
    # Verify and snapshot the same bytes that will be extracted.
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected.lower():
        raise ValueError('Transfer checksum mismatch')
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > 1000 or sum(i.file_size for i in infos) > 128 * 1024**2:
            raise ValueError('Archive exceeds reference export limits')
        names = [i.filename for i in infos]
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError('Duplicate archive entries')
        for item in infos:
            safe_name(item.filename)
            mode = item.external_attr >> 16
            if item.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError('Reference entries must be regular files')
            if (PurePosixPath(item.filename).suffix.lower() in {
                    '.exe', '.dll', '.com', '.bat', '.cmd', '.ps1', '.sh',
                    '.py', '.js', '.mjs', '.cjs', '.so'} or mode & 0o111):
                raise ValueError('Executable helpers are excluded from reference staging')
            if item.file_size > 2 * 1024**2 or item.flag_bits & 1:
                raise ValueError('Unsupported reference entry')
        if z.testzip() is not None:
            raise ValueError('Archive CRC mismatch')
        manifest = json.loads(z.read('manifest.json'))
        records = manifest['files']
        if len({r['path'] for r in records}) != len(records):
            raise ValueError('Duplicate manifest records')
        if set(names) != {'manifest.json', *(r['path'] for r in records)}:
            raise ValueError('Manifest does not cover the archive exactly')
        for record in records:
            content = z.read(record['path'])
            if len(content) != record['bytes'] or hashlib.sha256(content).hexdigest() != record['sha256']:
                raise ValueError('Reference manifest hash mismatch')
        if 'migration-reference.json' not in names or 'reference/openclaw.redacted.json' not in names:
            raise ValueError('Not a redacted configuration reference export')
        temporary = Path(tempfile.mkdtemp(prefix='.argos-reference-', dir=destination.parent))
        try:
            if os.name == 'nt':
                private_windows_directory(temporary)
            for item in infos:
                target = temporary.joinpath(*safe_name(item.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o777 if os.name == 'nt' else 0o700)
                with target.open('xb') as stream:
                    stream.write(z.read(item.filename))
                if os.name != 'nt':
                    target.chmod(0o600)
            # Publish only into a freshly created destination; never overwrite it.
            destination.mkdir(mode=0o777 if os.name == 'nt' else 0o700)
            if os.name == 'nt':
                private_windows_directory(destination)
            for child in temporary.iterdir():
                shutil.move(str(child), str(destination / child.name))
        finally:
            shutil.rmtree(temporary)
    return len(infos)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        count = stage(args.archive, args.sha256, args.target)
        print(f'{count} reference files verified and staged. No configuration or capability was activated.')
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Reference staging failed: {error}\n')
