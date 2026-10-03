#!/usr/bin/env python3
"""Verify and stage a private upstream backup, without activating its config."""
import argparse, hashlib, os
from pathlib import Path
import subprocess
import sys


def stage(archive, expected, destination):
    archive = Path(archive).expanduser()
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('A regular private backup file is required.')
    archive = archive.resolve(strict=True)
    destination = Path(destination).expanduser().absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('Staging paths must not contain symlinks.')
    if destination.exists():
        raise ValueError('Use a fresh staging directory; active profiles are never overwritten.')
    parent = destination.parent.resolve(strict=True)
    if parent.is_symlink() or destination.name in ('', '.', '..'):
        raise ValueError('Invalid staging destination.')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected.lower():
        raise ValueError('Transferred backup checksum differs; no restore attempted.')
    subprocess.run(['openclaw', 'backup', 'verify', str(archive)], check=True)
    subprocess.run(['openclaw', 'backup', 'restore', str(archive), '--target', str(destination)], check=True)
    print('Private backup staged. Active gateway, configuration, sessions and storage are unchanged.')
    print('Next: inspect paths/providers/permissions, validate a Linux candidate, then activate with rollback.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        stage(args.archive, args.sha256, args.target)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Profile staging failed: {error}', file=sys.stderr)
        sys.exit(1)
