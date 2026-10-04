#!/usr/bin/env python3
"""Build inert addon metadata from the SHA512-pinned published host archive."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.pull_jobs import write_json

SELECTED = ('ollama', 'memory-core', 'browser', 'document-extract', 'tts-local-cli', 'telegram')


def build(path, pins):
    digest = hashlib.sha512()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            digest.update(chunk)
    if 'sha512-' + base64.b64encode(digest.digest()).decode() != pins['OPENCLAW_INTEGRITY']:
        raise ValueError('Published host integrity mismatch')
    with tarfile.open(path) as archive:
        members = {}
        for item in archive.getmembers():
            if item.name in members:
                raise ValueError('Duplicate archive entry')
            members[item.name] = item
        def raw(name):
            item = members[name]
            if not item.isfile() or item.size > 1024**2:
                raise ValueError('Expected bounded regular metadata')
            return archive.extractfile(item).read()
        root = json.loads(raw('package/package.json'))
        if root['version'] != pins['OPENCLAW_VERSION']:
            raise ValueError('Host version mismatch')
        plugins = []
        for ident in SELECTED:
            prefix = 'package/dist/extensions/' + ident + '/'
            manifest_raw = raw(prefix + 'openclaw.plugin.json')
            manifest = json.loads(manifest_raw)
            package_raw = raw(prefix + 'package.json')
            package = json.loads(package_raw)
            if manifest['id'] != ident or package['version'] != pins['OPENCLAW_VERSION']:
                raise ValueError('Bundled identity/version mismatch')
            plugins.append({'id': ident, 'package': package['name'], 'version': package['version'],
                            'distribution': 'host-bundled', 'compatible_host': pins['OPENCLAW_VERSION'],
                            'host_integrity': pins['OPENCLAW_INTEGRITY'],
                            'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
                            'package_sha256': hashlib.sha256(package_raw).hexdigest(),
                            'license': package.get('license', root['license']),
                            'license_scope': 'plugin-package' if package.get('license') else 'host-package',
                            'npm_dependencies': package.get('dependencies', {}),
                            'declared_contracts': manifest.get('contracts', {}),
                            'declared_providers': manifest.get('providers', []),
                            'enabled_by_upstream_default': manifest.get('enabledByDefault'),
                            'package_presence_verified': True, 'invocation_verified': False})
        skills = [{'path': name.removeprefix('package/'), 'sha256': hashlib.sha256(raw(name)).hexdigest()}
                  for name in sorted(members) if name.endswith('/SKILL.md')]
    return {'schema': 'argos-addons/1', 'host_version': pins['OPENCLAW_VERSION'],
            'host_integrity': pins['OPENCLAW_INTEGRITY'], 'plugins': plugins,
            'shipped_skill_documents': skills,
            'external_addons': [], 'external_selection_pending': ['local-transcription', 'local-image-generation'],
            'note': 'Metadata only. Contracts/default enablement are not effective agent tool grants or readiness.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/argoslive/data/addons.json')
    args = parser.parse_args()
    pins = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines()
                if '=' in line and not line.startswith('#'))
    write_json(args.output.absolute(), build(args.archive, pins))
    args.output.chmod(0o644)  # Public build metadata must be readable by desktop users.


if __name__ == '__main__':
    main()
