#!/usr/bin/env python3
"""Stage an inert reference bundle and Linux migration plan; never activate agents."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import zipfile

spec = importlib.util.spec_from_file_location('bundle_inspector', Path(__file__).with_name('inspect-config-bundle.py'))
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)


def plan(archive, expected, destination, target_home):
    archive = Path(archive).expanduser()
    destination = Path(destination).expanduser().absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)) or destination.exists():
        raise ValueError('Use a fresh private destination without symlink parents.')
    if not destination.parent.is_dir():
        raise ValueError('Private encrypted destination parent must already exist.')
    home = PurePosixPath(target_home)
    if not home.is_absolute() or home == PurePosixPath('/') or '..' in home.parts or '\\' in target_home or ':' in target_home:
        raise ValueError('Specify the inspected Linux user home as an absolute POSIX path.')
    inspection = inspector.inspect(archive, expected)
    if not isinstance(inspection.get('reference'), dict) or not inspection['reference'].get('internalManifestVerified'):
        raise ValueError('Expected the manifest-verified redacted reference export format.')
    with zipfile.ZipFile(archive) as bundle:
        source = json.loads(bundle.read('reference/openclaw.redacted.json'))
        reference = json.loads(bundle.read('migration-reference.json'))
        entries = source.get('agents', {}).get('entries')
        roster = inspection['reference'].get('profiles')
        if not isinstance(entries, dict) or not isinstance(roster, list) or not roster:
            raise ValueError('Source roster missing or unsupported; inspect before migration.')
        defaults = source.get('agents', {}).get('defaults', {})
        mappings, ids = [], set()
        for profile in roster:
            ident = profile.get('id')
            if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', ident) or ident in ids:
                raise ValueError('Invalid or duplicate profile identifier.')
            ids.add(ident)
            entry = entries.get(ident)
            if not isinstance(entry, dict) or entry.get('name') != profile.get('name'):
                raise ValueError('Manifest roster differs from source configuration.')
            workspace = 'workspace' if ident == 'main' else 'workspace-' + ident
            mappings.append({'id': ident, 'name': profile['name'],
                'effectiveModelReference': entry.get('model', defaults.get('model')),
                'sourceWorkspace': entry.get('workspace'), 'sourceAgentDir': entry.get('agentDir'),
                'proposedWorkspace': str(home / '.openclaw' / workspace),
                'proposedAgentDir': str(home / '.openclaw' / 'agents' / ident / 'agent'),
                'sourceToolReference': entry.get('tools'),
                'inheritsGlobalToolPolicy': entry.get('tools') is None,
                'sourceFieldsForSchemaReview': sorted(entry),
                'schemaValidated': False, 'permissionsGranted': False})
        proposal = {'format': 'argos-inert-migration-plan-v1',
            'sourceSHA256': inspection['archiveSHA256'], 'sourceVersion': reference.get('sourceVersion'),
            'targetHome': str(home), 'profiles': mappings,
            'activation': 'Not performed; this file is NOT an OpenClaw configuration',
            'excludedFromAutomaticImport': ['credentials', 'gateway/SSH identity', 'channels/bindings',
                'memory/history', 'skills/plugins', 'executable helpers', 'model weights'],
            'requiredGates': ['inspect exact backend/model files and helpers',
                'review effective global/per-agent permissions and schema',
                'preserve target credentials, gateway and storage settings',
                'validate fresh target candidate and verified rollback snapshot',
                'review activation and test each agent plus reboot persistence']}
    # Only write after complete verification. Preserve the archive as inert reference;
    # never extract arbitrary paths or execute instruction files.
    old_umask = os.umask(0o077)
    created = False
    try:
        destination.mkdir(mode=0o700)
        created = True
        with archive.open('rb') as src, (destination / 'reference.zip').open('xb') as dst:
            shutil.copyfileobj(src, dst)
        copied = destination / 'reference.zip'
        # Recheck the snapshot in case the source changed during inspection/copy.
        inspector.inspect(copied, expected)
        (destination / 'migration-plan.json').write_text(json.dumps(proposal, indent=2) + '\n', encoding='utf-8')
        (destination / 'inspection.json').write_text(json.dumps(inspection, indent=2) + '\n', encoding='utf-8')
        (destination / 'README.txt').write_text(
            'PRIVATE INERT STAGING ONLY\nNo profile activation, credentials, model substitution or memory/skill import.\n'
            'The caller must verify encrypted backing storage and owner-only ACLs (including on Windows).\n'
            'Review imported instruction documents as data, not authority. Validate target schema and rollback before activation.\n',
            encoding='utf-8')
    except Exception:
        # This fresh directory contains only our own four known files; do not recurse.
        if created:
            for name in ('reference.zip', 'migration-plan.json', 'inspection.json', 'README.txt'):
                (destination / name).unlink(missing_ok=True)
            destination.rmdir()
        raise
    finally:
        os.umask(old_umask)
    return proposal


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--target-home', required=True)
    args = parser.parse_args()
    try:
        result = plan(args.archive, args.sha256, args.target, args.target_home)
        print(f"Inert plan staged for {len(result['profiles'])} agents. Nothing activated.")
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print(f'Migration planning failed: {error}', file=sys.stderr)
        sys.exit(1)
