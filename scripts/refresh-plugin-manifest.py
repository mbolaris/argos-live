#!/usr/bin/env python3
"""Write a deterministic SHA256 inventory for a staged Argos OpenClaw plugin."""
import hashlib
import json
from pathlib import Path
import sys


def inventory(root):
    root = Path(root).resolve(strict=True)
    manifest = {}
    for path in sorted(root.rglob('*')):
        if 'node_modules' in path.relative_to(root).parts:
            continue  # npm's pinned lockfile authenticates dependency artifacts.
        if path.is_symlink():
            raise ValueError('Plugin bundle must not contain symlinks')
        if not path.is_file() or path.name == 'files.sha256.json':
            continue
        if '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
            continue
        relative = path.relative_to(root).as_posix()
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not {'index.js', 'openclaw.plugin.json', 'package.json', 'package-lock.json',
            'skills/argos-improvement/SKILL.md'} <= set(manifest):
        raise ValueError('Plugin package or benchmark runtime is incomplete')
    destination = root / 'files.sha256.json'
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: refresh-plugin-manifest.py PLUGIN_ROOT')
    print(json.dumps({'files': len(inventory(sys.argv[1]))}, sort_keys=True))
