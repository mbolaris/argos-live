#!/usr/bin/env python3
"""Hosted disposable native OpenClaw/Ollama chat acceptance, never owner state."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.auto_setup import conversation_config
from argoslive.bench_speed import placement
from argoslive.owned_ollama import owned, PIN, stop_group
from argoslive import starter, storage


def summary(raw):
    if len(raw) > 1024**2:
        raise ValueError('Native chat result exceeds the bound')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('ok') is False or value.get('status') in ('error', 'timeout'):
        raise ValueError('Native chat command reported a failure')
    body = value.get('result', value)
    if not isinstance(body, dict):
        raise ValueError('Native chat result has an invalid shape')
    meta = body.get('meta', {})
    if not isinstance(meta, dict):
        raise ValueError('Native chat metadata has an invalid shape')
    agent = meta.get('agentMeta', {})
    if (not isinstance(agent, dict) or meta.get('error') or
            agent.get('provider') != 'ollama' or agent.get('model') != starter.TAG):
        raise ValueError('Native chat provider/model identity was not established')
    rows = body.get('payloads')
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Native chat reply payload is missing')
    texts = [row.get('text', '') for row in rows]
    if any(not isinstance(text, str) for text in texts) or not ''.join(texts).strip():
        raise ValueError('Native chat produced no text reply')
    return {'provider': agent['provider'], 'model': agent['model'],
            'reply_bytes': len(''.join(texts).encode()), 'reply_verified': True,
            'effective_tool_denial_verified': False}


def child_environment(home):
    # Do not inherit owner/provider credentials, proxy or state overrides.
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ') if key in os.environ}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / '.config'),
               XDG_DATA_HOME=str(home / '.local/share'), XDG_CACHE_HOME=str(home / '.cache'),
               OPENCLAW_STATE_DIR=str(home / '.openclaw'),
               OPENCLAW_CONFIG_PATH=str(home / '.openclaw/openclaw.json'), NO_COLOR='1')
    return env


def command(cli, arguments, env, *, timeout=180):
    process = subprocess.Popen([str(cli), *arguments], env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode:
            # Output can contain config; never place it in public action logs.
            raise ValueError('Native OpenClaw command failed')
        return stdout
    finally:
        stop_group(process)
        process.stdout.close()
        process.stderr.close()


def run(cli, ollama, seed):
    scratch = storage.safe_local(Path(os.environ.get('RUNNER_TEMP', '/missing')).absolute())
    seed = storage.safe_local(seed.absolute())
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            scratch not in seed.parents or os.geteuid() == 0):
        raise ValueError('Native chat smoke requires an unprivileged hosted scratch fixture')
    starter.verify(seed)
    for path in seed.rglob('*'):
        storage.safe_local(path).chmod(0o555 if path.is_dir() else 0o444)
    seed.chmod(0o555)
    identity = starter.read_only(seed)
    pins = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines()
                if '=' in line and not line.startswith('#'))
    with tempfile.TemporaryDirectory(prefix='argos-native-chat-', dir=scratch) as temp:
        home = Path(temp)
        state = home / '.openclaw'
        state.mkdir(mode=0o700)
        workspace = state / 'workspace'
        workspace.mkdir(mode=0o700)
        config = conversation_config(starter.TAG, workspace)
        # A bounded CI response, not a change to the shipped assistant budget.
        config['models']['providers']['ollama']['models'][0]['maxTokens'] = 32
        config['gateway']['auth']['token'] = 'fictional-public-native-chat-fixture'
        path = state / 'openclaw.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        env = child_environment(home)
        version = command(cli, ['--version'], env, timeout=30).decode()
        if pins['OPENCLAW_VERSION'] not in re.findall(r'\d{4}\.\d+\.\d+', version):
            raise ValueError('Native host differs from the accepted pin')
        command(cli, ['config', 'validate', '--json'], env, timeout=60)
        started = time.monotonic()
        with owned(seed, executable=ollama.absolute(), port=11434, context_tokens=32768,
                   lease_store=home) as client:
            result = summary(command(cli, ['agent', '--local', '--agent', 'main', '--message',
                'Say hello in one short sentence. Do not use any tools.', '--thinking', 'off',
                '--timeout', '120', '--json'], env, timeout=180))
            observed = placement(client.ps().get('models', []), starter.TAG)
            if observed['mode'] != 'CPU':
                raise ValueError('Native chat CPU placement was not established: ' + json.dumps(observed))
            client.unload(starter.TAG)
        if starter.verify(seed) != identity:
            raise ValueError('Native chat changed the image starter identity')
        return {'schema': 'argos-native-chat-smoke/1', **result, 'host_version': pins['OPENCLAW_VERSION'],
                'backend_version': PIN, 'backend': 'CPU', 'elapsed_seconds': time.monotonic() - started,
                'seed_unchanged': True, 'weights_copied': False, 'generation_budget': 32,
                'gateway_ui_verified': False, 'physical_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', required=True, type=Path)
    parser.add_argument('--ollama', required=True, type=Path)
    parser.add_argument('--seed', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.openclaw.absolute(), args.ollama.absolute(), args.seed), indent=2))


if __name__ == '__main__':
    main()
