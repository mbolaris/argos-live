#!/usr/bin/env python3
"""Real pinned SDK controller/hooks/tools, synthetic model; disposable CI only."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from synthetic_http import SyntheticHTTPServer
import json
import hashlib
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import controller_bridge, workload
from argoslive.auto_setup import conversation_config
from argoslive.results import Store


def run(cli, report):
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Controller fixture requires an unprivileged disposable hosted runner')
    counts = {'controller_requests': 0, 'evaluation_requests': 0, 'unsafe_exec_denied': False}
    failures = []
    marker = None

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
                self.respond({'parameters': 'num_ctx 32768', 'capabilities': ['completion', 'tools'],
                              'model_info': {'general.architecture': 'llama', 'llama.context_length': 32768}})
            elif self.path == '/api/chat':
                message = {'role': 'assistant', 'content': 'synthetic answer'}
                if value.get('tools'):
                    # A synthetic test plan, not a product planner or evidence
                    # of an actual model making autonomous experiment choices.
                    index = counts['controller_requests']
                    counts['controller_requests'] += 1
                    history = json.dumps(value.get('messages', []))
                    if 'This controller scope permits only admitted Argos host tools' in history:
                        counts['unsafe_exec_denied'] = True
                    if index == 0:
                        tool, args = 'exec', {'command': 'printf unexpected > ' + shlex.quote(str(marker))}
                    elif index == 1:
                        tool, args = 'argos_evaluate', {'suite': 'quick'}
                    elif index == 2:
                        found = re.search(r'Run ID: ([a-f0-9]{32})', history)
                        if not found:
                            failures.append('controller-missing-saved-run-id')
                        tool, args = 'argos_log', {'text': '--literal fixture note; saved run ' +
                                                (found[1] if found else 'missing')}
                    else:
                        tool, args = None, None
                        message['content'] = 'READY'
                    if tool:
                        message.update(content='', tool_calls=[{'id': f'fixture-call-{index}',
                            'type': 'function', 'function': {'name': tool, 'arguments': args}}])
                else:
                    counts['evaluation_requests'] += 1
                self.respond({'model': value['model'], 'message': message, 'done': True,
                              'done_reason': 'stop', 'eval_count': 1}, value.get('stream', True))
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

    server = SyntheticHTTPServer(('127.0.0.1', 11434), Handler, bind_and_activate=False)
    server.server_bind()
    server.server_activate()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipt = {'schema': 'argos-native-controller-bridge/1', 'passed': False,
               'scope': 'real pinned SDK hooks and host workers; synthetic responses; no model-quality result',
               'production_gateway_dispatch': False, 'protected_service_identity': False,
               'backend_drainage_proven': False}
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='argos-controller-probe-', dir=os.environ['RUNNER_TEMP']) as temporary:
            home = Path(temporary)
            marker = home / 'forbidden-exec-marker'
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True, mode=0o700)
            (workspace / 'AGENTS.md').write_text('Use the requested tools and reply READY.')
            config = conversation_config('fixture:latest', workspace,
                                         plugin_root=ROOT / 'openclaw-plugin/argos-improve')
            config['agents']['defaults']['heartbeat']['every'] = '0m'
            config['skills'] = {'allowBundled': [], 'load': {'watch': False},
                                'workshop': {'autonomous': {'mode': 'off'}}}
            config['plugins']['allow'] = ['argos-improve']
            config['plugins']['slots'] = {'memory': 'none'}
            config['plugins']['entries']['argos-improve'].update(
                hooks={'allowConversationAccess': True}, config={'hostAdmission': True})
            path = workspace.parent / 'openclaw.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            before = path.read_bytes()
            key = 'agent:main:host-' + str(uuid.uuid4())
            with controller_bridge.owned(home, session_key=key, worker_timeout=300) as (bridge, _env):
                bridge.launch(cli, 'Exercise the synthetic fixture tools, then reply READY.', timeout=300)
                try:
                    response, stderr = bridge.finish(timeout=330)
                except BaseException:
                    diagnostic = getattr(bridge, 'last_stdout', '') + getattr(bridge, 'last_stderr', '')
                    diagnostic += '\nChild outcome:\n' + getattr(bridge, 'last_child_stdout', '')[-8000:]
                    diagnostic += '\nChild diagnostic:\n' + getattr(bridge, 'last_child_stderr', '')[-6000:]
                    for secret in (bridge.secret, (bridge.active or {}).get('token', '')):
                        if secret:
                            diagnostic = diagnostic.replace(secret, '[omitted]')
                    report.with_suffix('.diagnostic.txt').write_text(diagnostic[-14000:])
                    raise
                if bridge.secret in json.dumps(response) + stderr:
                    raise ValueError('Controller transport credential leaked')
                if 'READY' not in json.dumps(response) or marker.exists() or failures or not counts['unsafe_exec_denied']:
                    raise ValueError('Native controller/tool admission contract failed: ' + json.dumps(counts))
                if counts['controller_requests'] != 4 or counts['evaluation_requests'] != 20:
                    raise ValueError('Unexpected controller/evaluation request counts: ' + json.dumps(counts))
                # SDK end and child completion cannot release the host's scope.
                try:
                    with workload.reserve(home, 'proctor'):
                        raise AssertionError('Proctor entered before controller context exit')
                except workload.Busy:
                    pass
                outcomes = [item for item in bridge.outcomes if item['kind'] == 'evaluation']
                if len(outcomes) != 1:
                    raise ValueError('Missing host-verified saved outcome')
                saved = Store(home / '.local/share/argos-live/results').load(outcomes[0]['result_id'])
                if saved['state'] != 'completed' or path.read_bytes() != before:
                    raise ValueError('Evaluation/configuration contract failed')
                worker = json.loads((home / '.local/state/argos-live/workload/controller-worker.json').read_bytes())
                result_artifact = report.with_name('controller-bridge-result.json')
                worker_artifact = report.with_name('controller-bridge-worker.json')
                result_artifact.write_text(json.dumps(saved, indent=2) + '\n')
                worker_artifact.write_text(json.dumps(worker, indent=2) + '\n')
                receipt.update(counts, controller_worker_exit=bridge.worker.returncode,
                    controller_process_group_drained=worker['process_group_drained'],
                    sdk_end_observed=worker['sdk_end_observed'], saved_run_id=saved['id'],
                    saved_coverage=saved['coverage'], host_tools=worker['tools'],
                    result_sha256=hashlib.sha256(result_artifact.read_bytes()).hexdigest(),
                    worker_receipt_sha256=hashlib.sha256(worker_artifact.read_bytes()).hexdigest(),
                    no_exec_side_effect=True, configuration_unchanged=True)
            with workload.reserve(home, 'proctor') as slot:
                slot.complete()
            receipt.update(passed=True, proctor_admitted_after_host_release=True)
            return receipt
    finally:
        report.write_text(json.dumps(receipt, indent=2) + '\n')
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    value = run(args.openclaw.absolute(), args.report)
    print(json.dumps({'passed': value['passed'], 'scope': value['scope']}))
