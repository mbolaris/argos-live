#!/usr/bin/env python3
"""Matched CPU prompt-load diagnostic; never a release gate or quality score."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
native = runpy.run_path(str(ROOT / 'scripts/smoke-native-chat.py'))
starter, storage = native['starter'], native['storage']


def run(cli, ollama, seed, output):
    scratch = storage.safe_local(Path(os.environ.get('RUNNER_TEMP', '/missing')).absolute())
    seed = storage.safe_local(seed.absolute())
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0 or
            scratch not in seed.parents or output.exists()):
        raise ValueError('Diagnostic requires a fresh unprivileged hosted fixture')
    starter.verify(seed)
    for path in seed.rglob('*'):
        storage.safe_local(path).chmod(0o555 if path.is_dir() else 0o444)
    seed.chmod(0o555)
    identity = starter.read_only(seed)
    guide = (ROOT / 'runtime/argoslive/data/SELF-IMPROVEMENT-AGENTS.md').read_bytes()
    report = {'schema': 'argos-native-prompt-control/1', 'release_acceptance': False,
              'quality_score': False, 'deadline_seconds': 180, 'num_predict': 32,
              'design': 'full guide / empty guide / full guide; fresh HOME and daemon per case; same runner',
              'limitations': 'filesystem cache and elapsed runner load are uncontrolled; diagnostic only',
              'cases': []}
    output.parent.mkdir(parents=True, exist_ok=True)
    for label, instructions in (('full-before', guide), ('empty-guide', b''), ('full-after', guide)):
        with tempfile.TemporaryDirectory(prefix='argos-prompt-control-', dir=scratch) as temp:
            home = Path(temp)
            state = home / '.openclaw'
            workspace = state / 'workspace'
            workspace.mkdir(parents=True, mode=0o700)
            (workspace / 'AGENTS.md').write_bytes(instructions)
            config = native['conversation_config'](starter.TAG, workspace,
                plugin_root=ROOT / 'openclaw-plugin/argos-improve')
            config['models']['providers']['ollama']['models'][0].update(
                maxTokens=32, params={'num_predict': 32})
            config['gateway']['auth']['token'] = 'fictional-public-prompt-load-fixture'
            path = state / 'openclaw.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            env = native['child_environment'](home)
            env.update(NODE_OPTIONS='--import=' + (ROOT / 'scripts/native-chat-request-probe.mjs').as_uri(),
                ARGOS_NATIVE_REQUEST_REPORT=str(home / 'native-request-metrics.json'),
                ARGOS_NATIVE_OPENCLAW_ENTRY=str(cli.resolve()))
            row = {'label': label, 'guide_bytes': len(instructions), 'completed': False}
            started = time.monotonic()
            try:
                version = native['command'](cli, ['--version'], env, timeout=30).decode()
                pin = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines()
                           if '=' in line and not line.startswith('#'))['OPENCLAW_VERSION']
                if pin not in native['re'].findall(r'\d{4}\.\d+\.\d+', version):
                    raise ValueError('Diagnostic host differs from pin')
                native['command'](cli, ['config', 'validate', '--json'], env, timeout=60)
                # Each case owns a new server group and shadow model store.
                # Its shutdown unloads the model; no owner service is adopted.
                with native['owned'](seed, executable=ollama, port=11434, context_tokens=32768,
                                     lease_store=home) as client:
                    raw = native['command'](cli, ['agent', '--local', '--agent', 'main', '--message',
                        'Say hello in one short sentence. Do not use any tools.', '--thinking', 'off',
                        '--timeout', '180', '--json'], env, timeout=240)
                    result = native['summary'](raw)
                    native['verify_request_budget'](native['request_metrics'](env))
                    placement = native['placement'](client.ps().get('models', []), starter.TAG)
                    if placement['mode'] != 'CPU':
                        raise ValueError('CPU placement not established')
                    row.update(completed=True, reply_bytes=result['reply_bytes'],
                               diagnostics=native['failure_diagnostics'](env, raw))
                    client.unload(starter.TAG)
            except Exception as error:
                # command() already emits a fixed-label safe failure object.
                # Never export an arbitrary exception string or CLI output.
                prefix = 'Native OpenClaw command failed: '
                text = str(error)
                row['error_type'] = type(error).__name__
                row['diagnostics'] = (json.loads(text[len(prefix):]) if text.startswith(prefix)
                                      else native['failure_diagnostics'](env))
            row['elapsed_seconds'] = round(time.monotonic() - started, 2)
            row['wire_request'] = native['request_metrics'](env)
            if (workspace / 'AGENTS.md').read_bytes() != instructions:
                raise ValueError('Diagnostic guide changed')
            if starter.read_only(seed) != identity:
                raise ValueError('Diagnostic seed changed')
            report['cases'].append(row)
            output.write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'label': label, 'completed': row['completed'],
                              'elapsed_seconds': row['elapsed_seconds']}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('openclaw', 'ollama', 'seed', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    run(args.openclaw.absolute(), args.ollama.absolute(), args.seed, args.output)
