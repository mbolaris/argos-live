#!/usr/bin/env python3
"""Check public pinned package metadata and CLI inventory in disposable state.

Runtime inspection registers plugins; it does not prove a gateway tool invocation.
No owner profile, model download, gateway or channel activation is involved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import addons


def verify_package(package, catalog):
    catalog = addons.validate(catalog)
    root = json.loads((package / 'package.json').read_text())
    if root['version'] != catalog['host_version']:
        raise ValueError('Installed host version differs from catalog')
    for plugin in catalog['plugins']:
        for filename, field in [('openclaw.plugin.json', 'manifest_sha256'), ('package.json', 'package_sha256')]:
            path = package / 'dist/extensions' / plugin['id'] / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != plugin[field]:
                raise ValueError('Installed bundled metadata differs: ' + plugin['id'])
    for skill in catalog['shipped_skill_documents']:
        if hashlib.sha256((package / skill['path']).read_bytes()).hexdigest() != skill['sha256']:
            raise ValueError('Installed skill document differs from published package')
    return True


def smoke(cli, package):
    catalog = addons.load()
    verify_package(package, catalog)
    with tempfile.TemporaryDirectory(prefix='argos-addon-inventory-') as directory:
        home = Path(directory)
        home.chmod(0o700)
        state = home / 'state'
        state.mkdir(mode=0o700)
        config = state / 'openclaw.json'
        config.write_text(json.dumps({'gateway': {'mode': 'local'}, 'tools': {'profile': 'minimal'}}))
        config.chmod(0o600)
        env = {key: value for key, value in os.environ.items() if not key.startswith('OPENCLAW_')}
        env.update(HOME=str(home), USERPROFILE=str(home), OPENCLAW_STATE_DIR=str(state),
                   OPENCLAW_CONFIG_PATH=str(config), XDG_CONFIG_HOME=str(home / 'config'),
                   XDG_CACHE_HOME=str(home / 'cache'), NO_COLOR='1')
        def run(*args):
            result = subprocess.run([str(cli), *args], cwd=home, env=env,
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError('Disposable inventory failed: ' + ' '.join(args) + '\n' +
                                   (result.stdout + result.stderr)[-4000:])
            return json.loads(result.stdout)
        snapshots, registrations = [], []
        for plugin in catalog['plugins']:
            ident = plugin['id']
            snapshots.append(addons.observation(run('plugins', 'inspect', ident, '--json')))
            registrations.append(addons.observation(run('plugins', 'inspect', ident, '--runtime', '--json'), runtime=True))
        # List skill eligibility without executing or installing any skill.
        skills = run('skills', 'list', '--json')
        if not isinstance(skills, (dict, list)):
            raise ValueError('Unexpected installed skill inventory shape')
        return {'schema': 'argos-addon-runtime-smoke/1', 'host_version': catalog['host_version'],
                'installed_package_metadata_verified': True,
                'shipped_skill_documents_verified': len(catalog['shipped_skill_documents']),
                'skill_inventory_cli_passed': True, 'snapshot_inventory': snapshots,
                'runtime_registration_inventory': registrations,
                'capabilities': addons.inventory(catalog, observations=registrations),
                'gateway_invocations_verified': False, 'physical_acceptance': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', required=True, type=Path)
    parser.add_argument('--package-root', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    report = smoke(args.openclaw.resolve(strict=True), args.package_root.resolve(strict=True))
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
