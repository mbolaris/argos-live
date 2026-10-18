#!/usr/bin/env python3
"""Exercise the pinned SDK admission hook with synthetic responses, no model.

This proves the local embedded entry gate only. It does not establish desktop
owner identity, heartbeat authorization, backend exclusion, or worker drainage.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.auto_setup import conversation_config
from argoslive.owned_gateway import environment


PLUGIN = '''import fs from 'node:fs';
export default function register(api) {
  const config = api.pluginConfig;
  api.on('before_agent_run', (event, ctx) => {
    fs.appendFileSync(config.capture, JSON.stringify({
      phase:'before', runId:ctx.runId ?? null, agentId:ctx.agentId ?? null,
      sessionId:ctx.sessionId ?? null, sessionKey:ctx.sessionKey ?? null,
      trigger:ctx.trigger ?? null, senderIsOwner:event.senderIsOwner ?? null
    })+'\\n');
    if (config.mode === 'error') throw new Error('fixture admission unavailable');
    if (config.mode === 'invalid') return {unexpected:true};
    return {outcome:config.mode === 'allow' ? 'allow' : 'block',
            reason:'fixture admission denied'};
  });
  api.on('agent_end', (_event, ctx) => {
    fs.appendFileSync(config.capture, JSON.stringify({phase:'end',runId:ctx.runId ?? null})+'\\n');
  });
}
'''


def run(cli, report):
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Admission fixture requires an unprivileged disposable hosted runner')
    requests, failures = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.respond({'/api/version': {'version': '0.40.5'}, '/api/tags': {'models': []}}.get(self.path))

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 2 * 1024**2:
                failures.append('invalid-request-length')
                return self.respond(None)
            value = json.loads(self.rfile.read(length))
            if self.path == '/api/show':
                self.respond({'parameters': 'num_ctx 32768', 'capabilities': ['completion'],
                              'model_info': {'general.architecture': 'llama', 'llama.context_length': 32768}})
            elif self.path == '/api/chat':
                # Save only counts, never messages, headers or prompts.
                requests.append(value.get('model'))
                self.respond({'model': value['model'], 'message': {'role': 'assistant', 'content': 'READY'},
                              'done': True, 'done_reason': 'stop', 'eval_count': 1}, value.get('stream', True))
            else:
                failures.append('unexpected-endpoint')
                self.respond(None)

        def respond(self, value, stream=False):
            raw = (json.dumps(value) + '\n').encode()
            self.send_response(200 if value is not None else 404)
            self.send_header('Content-Type', 'application/x-ndjson' if stream else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    # Never reuse or interrupt a listener. This script cannot run on Toronado.
    server = ThreadingHTTPServer(('127.0.0.1', 11434), Handler, bind_and_activate=False)
    server.allow_reuse_address = False
    server.server_bind()
    server.server_activate()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    receipt = {'schema': 'argos-admission-hook-protocol/1', 'passed': False,
               'scope': 'synthetic local embedded SDK entry; no model-quality result', 'cases': []}
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='argos-admission-probe-', dir=os.environ['RUNNER_TEMP']) as temporary:
            root = Path(temporary)
            plugin = root / 'probe'
            plugin.mkdir(mode=0o700)
            (plugin / 'index.js').write_text(PLUGIN)
            (plugin / 'package.json').write_text(json.dumps({'name': 'argos-admission-probe', 'version': '1.0.0',
                'type': 'module', 'openclaw': {'extensions': ['./index.js']}}))
            (plugin / 'openclaw.plugin.json').write_text(json.dumps({'id': 'argos-admission-probe',
                'configSchema': {'type': 'object', 'additionalProperties': False,
                    'required': ['capture', 'mode'], 'properties': {
                        'capture': {'type': 'string'}, 'mode': {'type': 'string'}}}}))
            # The ungranted case is an explicit negative control: the SDK ignores
            # this non-bundled hook. Never treat that configuration as protected.
            for mode, granted in [('block', False), ('block', True), ('error', True),
                                  ('invalid', True), ('allow', True)]:
                home = root / (mode + ('-granted' if granted else '-ungranted'))
                workspace = home / '.openclaw/workspace'
                workspace.mkdir(parents=True, mode=0o700)
                (workspace / 'AGENTS.md').write_text('Reply READY.')
                capture = home / 'hook.jsonl'
                config = conversation_config('fixture:latest', workspace, plugin_root=plugin)
                config['agents']['defaults']['heartbeat']['every'] = '0m'
                config['tools'] = {'profile': 'minimal', 'deny': ['*'], 'toolSearch': False}
                config['skills'] = {'allowBundled': [], 'load': {'watch': False}}
                config['plugins'] = {'enabled': True, 'allow': ['argos-admission-probe'],
                    'load': {'paths': [str(plugin)]}, 'entries': {'argos-admission-probe': {
                        'enabled': True, 'hooks': {'allowConversationAccess': granted},
                        'config': {'capture': str(capture), 'mode': mode}}}}
                config_path = workspace.parent / 'openclaw.json'
                config_path.write_text(json.dumps(config))
                config_path.chmod(0o600)
                session = str(uuid.uuid4())
                session_key = 'agent:main:admission-probe-' + session
                before = len(requests)
                result = subprocess.run([str(cli), 'agent', '--local', '--agent', 'main',
                    '--session-id', session, '--session-key', session_key, '--message', 'Say READY.',
                    '--timeout', '45', '--json'], env=environment(home, config_path), cwd=workspace,
                    capture_output=True, text=True, timeout=75)
                events = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
                gates = [event for event in events if event['phase'] == 'before']
                count = len(requests) - before
                case = {'mode': mode, 'conversation_access': granted, 'exit_code': result.returncode,
                        'model_requests': count, 'events': events}
                receipt['cases'].append(case)
                report.write_text(json.dumps(receipt, indent=2) + '\n')
                expected_requests = 1 if mode == 'allow' or not granted else 0
                if count != expected_requests or failures or len(gates) != int(granted):
                    # Inputs are exclusively synthetic; retain bounded CLI output
                    # to diagnose registration/schema failures in this fixture.
                    report.with_suffix('.diagnostic.txt').write_text((result.stdout + result.stderr)[-12000:])
                    raise ValueError('Pinned SDK admission contract failed: ' + json.dumps(case))
                if granted and (not gates[0]['runId'] or gates[0]['agentId'] != 'main' or
                                gates[0]['sessionId'] != session or gates[0]['sessionKey'] != session_key):
                    raise ValueError('Pinned SDK admission context identity differs')
                if expected_requests and (result.returncode or 'READY' not in result.stdout):
                    raise ValueError('Synthetic allow control did not complete')
        receipt['passed'] = True
        return receipt
    finally:
        report.write_text(json.dumps(receipt, indent=2) + '\n')
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    value = run(args.openclaw.resolve(strict=True), args.report)
    print(json.dumps({'passed': value['passed'], 'scope': value['scope'], 'cases': len(value['cases'])}))
