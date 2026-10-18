#!/usr/bin/env python3
"""Pinned SDK request evidence against a synthetic Ollama server; no inference.

Only disposable hosted runners: never bind Toronado's owned model port. Reports
contain selected protocol options, not prompts, headers, or owner configuration.
"""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from synthetic_http import SyntheticHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.auto_setup import conversation_config
from argoslive.assistant_trial import OpenClawRunner
from argoslive.evaluation_context import configuration_receipt


def run(cli):
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Request fixture requires an unprivileged disposable hosted runner')
    requests = []
    failures = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.respond({
                '/api/version': {'version': '0.35.0'},
                '/api/tags': {'models': [{'name': 'fixture:latest', 'model': 'fixture:latest',
                                         'digest': 'sha256:' + '0' * 64, 'size': 1000}]},
            }.get(self.path))

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 2 * 1024**2:
                failures.append('invalid-request-length')
                self.respond(None)
                return
            value = json.loads(self.rfile.read(length))
            if self.path == '/api/show':
                self.respond({'parameters': 'num_ctx 32768', 'capabilities': ['completion', 'thinking'],
                    'details': {'parameter_size': '0.6B', 'quantization_level': 'Q4_K_M'},
                    'model_info': {'general.architecture': 'llama', 'llama.context_length': 32768}})
            elif self.path == '/api/chat':
                requests.append(value)
                self.respond({'model': value['model'], 'created_at': '2026-10-17T00:00:00Z',
                    'message': {'role': 'assistant', 'content': 'READY'}, 'done': True,
                    'done_reason': 'stop', 'total_duration': 1000000, 'load_duration': 1,
                    'prompt_eval_count': 1, 'prompt_eval_duration': 1, 'eval_count': 1,
                    'eval_duration': 1}, stream=value.get('stream', True))
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

    # Reuse stopped TCP TIME_WAIT; a live listener still fails binding.
    server = SyntheticHTTPServer(('127.0.0.1', 11434), Handler, bind_and_activate=False)
    server.server_bind()
    server.server_activate()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    reports = []
    try:
        with tempfile.TemporaryDirectory(prefix='argos-config-probe-', dir=os.environ['RUNNER_TEMP']) as temp:
            home = Path(temp)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True, mode=0o700)
            (workspace / 'AGENTS.md').write_text('Reply READY to protocol fixture requests.')
            path = workspace.parent / 'openclaw.json'
            base = conversation_config('unused:latest', workspace)
            defaults = base['agents']['defaults']
            defaults['params'] = {'temperature': 0.11}
            defaults['models'] = {'ollama/fixture:latest': {'params': {'temperature': 0.22, 'topP': 0.8}}}
            base['agents']['list'] = [{'id': 'main', 'model': 'ollama/fixture:latest',
                'params': {'temperature': 0.44},
                'models': {'ollama/fixture:latest': {'params': {'temperature': 0.33, 'maxTokens': 73,
                                                               'thinking': 'low', 'num_ctx': 16384}}}}]
            model = base['models']['providers']['ollama']['models'][0]
            model.update(id='fixture:latest', name='fixture:latest', reasoning=True,
                         params={'num_ctx': 24576})
            for reasoning in (True, False):
                config = copy.deepcopy(base)
                config['models']['providers']['ollama']['models'][0]['reasoning'] = reasoning
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                before = path.read_bytes()
                start = len(requests)
                runner = OpenClawRunner(home, executable=cli)
                runner.expected_model = 'fixture:latest'
                try:
                    answer = runner.turn('Say READY.', timeout=90)
                except ValueError:
                    # This HOME contains only public synthetic fixture inputs.
                    # Preserve bounded CLI evidence before temporary cleanup.
                    diagnostic = home / '.local/state/argos-live/trial-turn-failure.log'
                    if diagnostic.exists():
                        text = diagnostic.read_text(errors='replace')[-6000:]
                        text = re.sub(r'(?:https?|wss?)://\S+', '[fixture URL omitted]', text)
                        text = re.sub(r'(?i)((?:token|password|api[_-]?key|secret)\s*[=:]\s*)\S+',
                                      r'\1[omitted]', text)
                        print(text, file=sys.stderr)
                    raise
                captured = requests[start:]
                if answer['text'].strip() != 'READY' or len(captured) != 1 or failures:
                    raise ValueError('Synthetic request/response contract failed')
                request = captured[0]
                options = request.get('options', {})
                expected = {'temperature': 0.44, 'top_p': 0.8, 'num_predict': 73, 'num_ctx': 24576}
                if any(options.get(k) != v for k, v in expected.items()):
                    raise ValueError('Pinned SDK generation precedence differs: ' + json.dumps(
                        {k: options.get(k) for k in expected}, sort_keys=True))
                if reasoning and request.get('think') != 'low':
                    raise ValueError('Reasoning-enabled model did not exercise low thinking')
                if not reasoning and request.get('think') not in (None, False):
                    raise ValueError('Reasoning-disabled model received truthy thinking')
                if request.get('tools') or request.get('model') != 'fixture:latest' or path.read_bytes() != before:
                    raise ValueError('Isolation or selection failed')
                reports.append({'reasoning': reasoning, 'options': expected, 'think': request.get('think'),
                    'tool_schemas': False, 'receipt': configuration_receipt(home)})
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return {'schema': 'argos-evaluation-protocol/1', 'kind': 'synthetic protocol fixture; no model-quality result',
            'passed': True, 'cases': reports}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    value = run(args.openclaw.resolve(strict=True))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'passed': value['passed'], 'kind': value['kind'], 'cases': len(value['cases'])}))
