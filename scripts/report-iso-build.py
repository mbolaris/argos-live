#!/usr/bin/env python3
"""Verify public CI outputs before recording an ISO candidate checksum."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def scan_log(path):
    if path.stat().st_size > 512 * 1024**2:
        raise ValueError('Build log exceeds review bound')
    patterns = [rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----',
                rb'gh[pousr]_[A-Za-z0-9]{20,}', rb'github_pat_[A-Za-z0-9_]{20,}',
                rb'\bsk-[A-Za-z0-9_-]{20,}']
    tail = b''
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            combined = tail + chunk
            if any(re.search(pattern, combined) for pattern in patterns):
                raise ValueError('Credential-shaped material detected; build log must not be uploaded')
            tail = combined[-4096:]


def report(root, commit):
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Expected exact Git commit')
    iso = root / 'argos-live-amd64.iso'
    for name in ('argos-live-amd64.iso', 'SHA256SUMS', 'packages.txt', 'build.log'):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or linked build artifact: ' + name)
    with iso.open('rb') as stream:
        stream.seek(0x8001)
        if stream.read(5) != b'CD001':
            raise ValueError('Output lacks an ISO9660 descriptor')
    if (root / 'SHA256SUMS').stat().st_size > 256:
        raise ValueError('Invalid checksum record')
    checksum = (root / 'SHA256SUMS').read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{64}  argos-live-amd64\.iso', checksum):
        raise ValueError('Unexpected checksum filename or format')
    digest = hashlib.sha256()
    with iso.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(chunk)
    if digest.hexdigest() != checksum.split()[0]:
        raise ValueError('ISO checksum differs from the build output')
    packages = root / 'packages.txt'
    if not 1 <= packages.stat().st_size <= 16 * 1024**2:
        raise ValueError('Invalid package manifest size')
    manifest = packages.read_text()
    for package in ('linux-image-amd64', 'xfce4', 'lightdm', 'python3'):
        if not re.search(r'^' + re.escape(package) + r'\s', manifest, re.M):
            raise ValueError('Required image package is missing: ' + package)
    scan_log(root / 'build.log')
    pins = {}
    for line in (ROOT / 'versions.env').read_text().splitlines():
        key, separator, value = line.partition('=')
        if separator and re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            pins[key] = value
    return {'schema': 'argos-iso-build/1', 'commit': commit, 'pins': pins,
            'iso_sha256': digest.hexdigest(), 'iso_bytes': iso.stat().st_size,
            'packages_sha256': hashlib.sha256(packages.read_bytes()).hexdigest(),
            'runtime_lock_sha256': hashlib.sha256((ROOT / 'live/config/includes.chroot/usr/local/share/argos-live/package-lock.json').read_bytes()).hexdigest(),
            'credential_pattern_scan_passed': True, 'boot_acceptance': False,
            'physical_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--commit')
    parser.add_argument('--log-only', action='store_true')
    args = parser.parse_args()
    if args.log_only:
        scan_log(args.artifacts / 'build.log')
    elif args.commit:
        print(json.dumps(report(args.artifacts, args.commit), indent=2))
    else:
        parser.error('--commit is required unless --log-only is used')


if __name__ == '__main__':
    main()
