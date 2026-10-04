#!/usr/bin/env python3
"""Real pinned OpenClaw schema/native recovery smoke in disposable private state.

No gateway, inference, network provider or owner profile is started. This checks
the upstream runtime surfaces needed by P4; it does not implement pack apply.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def smoke(cli, expected_version):
    with tempfile.TemporaryDirectory(prefix='argos-pack-schema-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        state = root / 'source'
        state.mkdir(mode=0o700)
        entries = {}
        expected_personas = []
        for ident in ('guide', 'discussion', 'experimental'):
            workspace = state / ('workspace-' + ident)
            workspace.mkdir(mode=0o700)
            persona = 'Original fictional fixture identity: ' + ident + '\n'
            (workspace / 'SOUL.md').write_text(persona, encoding='utf-8')
            expected_personas.append(persona.encode())
            entries[ident] = {'identity': {'name': ident.title()}, 'workspace': str(workspace),
                             'agentDir': str(state / 'agents' / ident / 'agent'),
                             'model': 'ollama/qwen3:0.6b'}
        entries['guide']['default'] = True
        config = {'gateway': {'mode': 'local', 'bind': 'loopback',
                              'auth': {'mode': 'token', 'token': 'fictional-ci-token-not-owner-data'}},
                  'agents': {'defaults': {'workspace': entries['guide']['workspace']}, 'entries': entries},
                  'tools': {'profile': 'minimal',
                            'deny': ['group:runtime', 'group:fs', 'group:web', 'browser'],
                            'elevated': {'enabled': False}}}
        config_path = state / 'openclaw.json'
        original_config = (json.dumps(config, indent=2) + '\n').encode()
        config_path.write_bytes(original_config)
        config_path.chmod(0o600)
        env = dict(os.environ, OPENCLAW_STATE_DIR=str(state),
                   OPENCLAW_CONFIG_PATH=str(config_path), NO_COLOR='1')
        def run(*args):
            result = subprocess.run([cli, *args], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                # This process sees fictional fixtures only; redact even their token.
                detail = (result.stdout + result.stderr)[-6000:].replace(
                    'fictional-ci-token-not-owner-data', '[fixture token]')
                raise RuntimeError('Pinned OpenClaw smoke failed: ' +
                                   ' '.join(args[:2]) + '\n' + detail)
            return result.stdout
        version = run('--version')
        if expected_version not in re.findall(r'\d{4}\.\d+\.\d+', version):
            raise RuntimeError('Installed OpenClaw differs from required version')
        run('config', 'validate')
        run('agents', 'list', '--json')
        backup = root / 'verified-native-backup.tar.gz'
        run('backup', 'create', '--output', str(backup), '--verify')
        run('backup', 'verify', str(backup))
        backup_digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        # Mutate only disposable fixtures to establish the recovery source is distinct.
        (state / 'workspace-guide/SOUL.md').write_text('Changed fixture\n', encoding='utf-8')
        config['agents']['entries']['guide']['identity']['name'] = 'Changed fixture'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        run('config', 'validate')
        restored = root / 'fresh-restored-stage'
        run('backup', 'restore', str(backup), '--target', str(restored))
        configs = list(restored.rglob('openclaw.json'))
        if not any(path.read_bytes() == original_config for path in configs):
            raise RuntimeError('Restored config bytes differ from snapshot')
        personas = [path.read_bytes() for path in restored.rglob('SOUL.md')]
        if sorted(personas) != sorted(expected_personas):
            raise RuntimeError('Restored personas differ from snapshot')
        # A rejected config must be observable before any proposed activation.
        config['tools']['profile'] = 'invalid-fixture-profile'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        invalid = subprocess.run([cli, 'config', 'validate'], cwd=root, env=env,
                                 capture_output=True, text=True, timeout=120)
        if invalid.returncode == 0:
            raise RuntimeError('Invalid fixture unexpectedly passed validation')
        return {'schema': 'argos-pack-runtime-smoke/1', 'openclaw_version': expected_version,
                'valid_three_agent_config': True, 'invalid_config_rejected': True,
                'native_backup_verified': True, 'backup_sha256': backup_digest,
                'fresh_restore_config_personas_byte_match': True,
                'pack_apply_implemented': False, 'physical_acceptance': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    report = smoke(str(Path(args.openclaw).resolve(strict=True)), args.version)
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
