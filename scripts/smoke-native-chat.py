#!/usr/bin/env python3
"""Hosted disposable native OpenClaw/Ollama chat acceptance, never owner state."""
import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import sqlite3
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


def failure_diagnostics(env, stdout=b'', stderr=b''):
    """Export only fixed-label counters from this disposable smoke fixture.

    Never export event text, tool arguments, session IDs, configuration or raw
    subprocess output. A failed diagnostic must not hide the original failure.
    """
    report = {'stdout_bytes': len(stdout), 'stderr_bytes': len(stderr),
              'transcript_scan': 'absent'}
    report['wire_request'] = request_metrics(env)
    # The pinned host can return a structured failure with useful numeric usage
    # and prompt-size metadata. Never copy arbitrary keys or free text from it.
    try:
        value = json.loads(stdout) if len(stdout) <= 1024**2 else {}
        body = value.get('result', value)
        meta = body.get('meta', {})
        agent = meta.get('agentMeta', {})
        numeric = {}
        def number(label, value):
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**12:
                numeric[label] = value
        number('duration_ms', meta.get('durationMs'))
        number('prompt_tokens', agent.get('promptTokens'))
        for section in ('usage', 'lastCallUsage'):
            usage = agent.get(section, {})
            if isinstance(usage, dict):
                for key in ('input', 'output', 'cacheRead', 'cacheWrite', 'total'):
                    number(section + '_' + key, usage.get(key))
        prompt = meta.get('systemPromptReport', {})
        for section in ('systemPrompt', 'tools', 'skills'):
            row = prompt.get(section, {})
            if isinstance(row, dict):
                for key in ('chars', 'schemaChars', 'promptChars'):
                    number(section + '_' + key, row.get(key))
        if type(meta.get('aborted')) is bool:
            report['aborted'] = meta['aborted']
        report['numeric_metadata'] = numeric
    except (ValueError, TypeError, AttributeError, OverflowError):
        report['numeric_metadata'] = {}
    try:
        state = Path(env['OPENCLAW_STATE_DIR'])
        database = state / 'agents/main/agent/openclaw-agent.sqlite'
        if database.is_file() and not database.is_symlink():
            roles = dict.fromkeys(('assistant', 'user', 'toolResult', 'other'), 0)
            calls = dict.fromkeys(('exec', 'write', 'edit', 'argos_evaluate', 'other'), 0)
            with closing(sqlite3.connect(database.absolute().as_uri() + '?mode=ro',
                                        uri=True, timeout=1)) as connection:
                # Bound both the number and size of inspected events. Oversized
                # rows are counted, but never decoded or included in the report.
                rows = connection.execute('SELECT CASE WHEN length(event_json) <= 1048576 '
                    'THEN event_json ELSE NULL END FROM transcript_events '
                    'ORDER BY created_at DESC LIMIT 64').fetchall()
            skipped = 0
            for (raw,) in rows:
                try:
                    message = json.loads(raw).get('message', {})
                    role = message.get('role')
                    roles[role if role in roles else 'other'] += 1
                    content = message.get('content', [])
                    for block in content if isinstance(content, list) else []:
                        if isinstance(block, dict) and block.get('type') == 'toolCall':
                            name = block.get('name')
                            calls[name if name in calls else 'other'] += 1
                except (TypeError, ValueError, AttributeError):
                    skipped += 1
            report.update(transcript_scan='read', scanned_events=len(rows),
                          skipped_events=skipped, roles=roles, tool_calls=calls)
    except (OSError, sqlite3.Error, KeyError, ValueError):
        report['transcript_scan'] = 'unavailable'
    return report


def request_metrics(env):
    try:
        log_path = env.get('ARGOS_NATIVE_REQUEST_LOG')
        path = Path(log_path or env['ARGOS_NATIVE_REQUEST_REPORT'])
        if path.is_symlink() or path.stat().st_size > 65536:
            return {}
        if log_path:
            events = [json.loads(line) for line in path.read_text().splitlines() if line]
            requests, probes, summaries, per_process = [], {}, {}, {}
            truncated = False
            for event in events:
                if not isinstance(event, dict):
                    return {}
                kind, pid = event.get('kind'), event.get('pid')
                if kind == 'probe' and type(pid) is int and pid > 0:
                    probes[pid] = event
                elif kind == 'request' and type(pid) is int and pid > 0:
                    per_process[pid] = per_process.get(pid, 0) + 1
                    if len(requests) < 64:
                        requests.append(event)
                    else:
                        truncated = True
                elif kind == 'summary' and type(pid) is int and pid > 0:
                    summaries[pid] = event
                elif kind == 'truncated' and type(pid) is int and pid > 0:
                    truncated = True
                else:
                    return {}
            probe_pids = set(probes)
            summary_pids = set(summaries)
            request_pids = set(per_process)
            summary_mismatch_count = 0
            # Each injected Node process reports its own count on exit. Missing
            # summaries, failed writes, and truncated streams fail closed.
            if (not probes or probe_pids != summary_pids or
                    not request_pids.issubset(probe_pids)):
                truncated = True
            for pid, probe in probes.items():
                summary = summaries.get(pid, {})
                observed = per_process.get(pid, 0)
                if (summary.get('request_count') != observed or
                        summary.get('requests_logged') != observed or
                        summary.get('log_failed') is not False or
                        probe.get('probe_loaded') is not True):
                    summary_mismatch_count += 1
                    truncated = True
            value = {'request_count': sum(per_process.values()), 'requests': requests,
                     'requests_truncated': truncated,
                     'probe_process_count': len(probe_pids),
                     'summary_process_count': len(summary_pids),
                     'request_process_count': len(request_pids),
                     'missing_summary_count': len(probe_pids - summary_pids),
                     'orphan_summary_count': len(summary_pids - probe_pids),
                     'request_without_probe_count': len(request_pids - probe_pids),
                     'summary_mismatch_count': summary_mismatch_count,
                     'probe_loaded': any(row.get('probe_loaded') is True for row in probes.values()),
                     'runtime_fetch_hooked': any(row.get('runtime_fetch_hooked') is True
                                                 for row in probes.values())}
        else:
            value = json.loads(path.read_text())
        if not isinstance(value, dict):
            return {}
        allowed = ('request_count', 'probe_process_count', 'summary_process_count',
                   'request_process_count', 'missing_summary_count', 'orphan_summary_count',
                   'request_without_probe_count', 'summary_mismatch_count',
                   'request_bytes', 'num_predict', 'num_ctx',
                   'message_chars', 'tool_schema_chars', 'temperature', 'tool_result_messages')
        result = {key: value[key] for key in allowed if type(value.get(key)) in (int, float)
                  and math.isfinite(value[key]) and -2 <= value[key] <= 10**12}
        result.update({key: value[key] for key in ('body_inspected', 'num_predict_present',
                      'num_ctx_present', 'think', 'probe_loaded', 'runtime_fetch_hooked',
                      'requests_truncated')
                      if type(value.get(key)) is bool})
        records = value.get('requests')
        if isinstance(records, list) and len(records) <= 64:
            numeric = ('request_bytes', 'num_predict', 'num_ctx', 'message_chars',
                       'tool_schema_chars', 'temperature', 'tool_result_messages')
            booleans = ('body_inspected', 'num_predict_present', 'num_ctx_present', 'think')
            result['requests'] = [{**{key: row[key] for key in numeric
                                      if type(row.get(key)) in (int, float)
                                      and math.isfinite(row[key]) and -2 <= row[key] <= 10**12},
                                  **{key: row[key] for key in booleans
                                     if type(row.get(key)) is bool}}
                                 for row in records if isinstance(row, dict)]
        return result
    except (KeyError, OSError, ValueError, OverflowError):
        return {}


def verify_request_budget(metrics):
    requests = metrics.get('requests')
    count = metrics.get('request_count')
    valid = (isinstance(requests, list) and bool(requests) and type(count) is int and
             count == len(requests) and metrics.get('requests_truncated') is False and
             all(row.get('body_inspected') is True and row.get('num_predict') == 32
                 for row in requests))
    if not valid:
        # `metrics` is produced by request_metrics(), which exports only bounded
        # numeric and boolean fields. This detail makes a real cap miss
        # distinguishable from a capture-path failure without exposing prompts.
        raise ValueError('Native smoke generation limit was not established on every wire request: ' +
                         json.dumps(metrics, sort_keys=True))


def command(cli, arguments, env, *, timeout=180):
    started = time.monotonic()
    process = subprocess.Popen([str(cli), *arguments], env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError('Native OpenClaw outer deadline exceeded: ' + json.dumps({
                'elapsed_seconds': round(time.monotonic() - started, 1),
                **failure_diagnostics(env, error.output or b'', error.stderr or b'')})) from None
        if process.returncode:
            # Output can contain config; never place it in public action logs.
            text = (stdout + stderr)[-65536:].decode(errors='replace').lower()
            indicators = {name: any(term in text for term in terms) for name, terms in {
                'session_lock': ('session file locked', 'lock timeout', 'already locked'),
                'embedded_gateway_conflict': ('a gateway is running for this state directory',),
                'agent_selection': ('unknown agent', 'agent not found', 'requires --agent'),
                'invalid_config': ('invalid config', 'config validation'),
                'model_missing': ('model not found', 'model does not exist'),
                'context_capacity': ('context window', 'context length', 'out of memory'),
                'connection': ('econnrefused', 'fetch failed', 'connection refused', 'socket hang up'),
                'auth': ('unauthorized', 'missing api key', 'authentication'),
                'permission': ('permission denied', 'eacces'),
                'port_conflict': ('eaddrinuse', 'address already in use'),
                'model_load': ('unable to load model', 'failed to load model'),
                'timeout': ('timed out', 'timeout'),
            }.items()}
            raise ValueError('Native OpenClaw command failed: ' + json.dumps({
                'exit_code': process.returncode,
                'elapsed_seconds': round(time.monotonic() - started, 1), **indicators,
                **failure_diagnostics(env, stdout, stderr)}))
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
        # Exercise the shipped workspace instructions, as fresh auto-setup does,
        # rather than OpenClaw's generic first-run AGENTS template.
        instructions = (ROOT / 'runtime/argoslive/data/SELF-IMPROVEMENT-AGENTS.md').read_bytes()
        (workspace / 'AGENTS.md').write_bytes(instructions)
        config = conversation_config(starter.TAG, workspace,
                                     plugin_root=ROOT / 'openclaw-plugin/argos-improve')
        # A bounded CI response, not a change to the shipped assistant budget.
        config['models']['providers']['ollama']['models'][0]['maxTokens'] = 32
        # maxTokens is catalog metadata in the pinned native provider. The
        # actual Ollama request budget must be an explicit native model option.
        config['models']['providers']['ollama']['models'][0]['params'] = {'num_predict': 32}
        config['gateway']['auth']['token'] = 'fictional-public-native-chat-fixture'
        path = state / 'openclaw.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        env = child_environment(home)
        # The observer is injected only into this hosted disposable fixture;
        # it forwards the original fetch unchanged and records no request text.
        env['NODE_OPTIONS'] = '--import=' + (ROOT / 'scripts/native-chat-request-probe.mjs').as_uri()
        env['ARGOS_NATIVE_REQUEST_LOG'] = str(home / 'native-request-metrics.jsonl')
        env['ARGOS_NATIVE_OPENCLAW_ENTRY'] = str(cli.resolve())
        version = command(cli, ['--version'], env, timeout=30).decode()
        if pins['OPENCLAW_VERSION'] not in re.findall(r'\d{4}\.\d+\.\d+', version):
            raise ValueError('Native host differs from the accepted pin')
        command(cli, ['config', 'validate', '--json'], env, timeout=60)
        started = time.monotonic()
        with owned(seed, executable=ollama.absolute(), port=11434, context_tokens=32768,
                   lease_store=home) as client:
            # Leave headroom for slower CPU runners to read the full agent prompt.
            request_log = Path(env['ARGOS_NATIVE_REQUEST_LOG'])
            request_log.write_text('', encoding='utf-8')
            request_log.chmod(0o600)
            result = summary(command(cli, ['agent', '--local', '--agent', 'main', '--message',
                'Say hello in one short sentence. Do not use any tools.', '--thinking', 'off',
                '--timeout', '240', '--json'], env, timeout=300))
            verify_request_budget(request_metrics(env))
            observed = placement(client.ps().get('models', []), starter.TAG)
            if observed['mode'] != 'CPU':
                raise ValueError('Native chat CPU placement was not established: ' + json.dumps(observed))
            client.unload(starter.TAG)
        if starter.verify(seed) != identity:
            raise ValueError('Native chat changed the image starter identity')
        if (workspace / 'AGENTS.md').read_bytes() != instructions:
            raise ValueError('Native chat changed the installed improvement guide')
        return {'schema': 'argos-native-chat-smoke/1', **result, 'wire_request': request_metrics(env),
                'host_version': pins['OPENCLAW_VERSION'],
                'backend_version': PIN, 'backend': 'CPU', 'elapsed_seconds': time.monotonic() - started,
                'seed_unchanged': True, 'guide_unchanged': True, 'weights_copied': False, 'generation_budget': 32,
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
