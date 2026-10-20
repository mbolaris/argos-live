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
import signal
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import controller_bridge, instruction_changes, workload
from argoslive.auto_setup import conversation_config
from argoslive.results import Store


def run(cli, report):
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Controller fixture requires an unprivileged disposable hosted runner')
    counts = {'controller_requests': 0, 'evaluation_requests': 0, 'unsafe_exec_denied': False}
    failures = []
    marker = None
    abort_mode = {'enabled': False}
    evaluation_started = threading.Event()
    release_evaluation = threading.Event()

    def tool_values(messages):
        """Read structured tool replies from the SDK's actual provider history."""
        found = []
        def visit(value):
            if isinstance(value, dict):
                if value.get('status') in {'inspected', 'changed', 'restored'}:
                    found.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except (ValueError, TypeError):
                    return
                if not isinstance(decoded, str):
                    visit(decoded)
        for item in messages:
            if item.get('role') == 'tool':
                visit(item.get('content'))
        return found

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
                        tool, args = 'argos_inspect', {}
                    elif index == 2:
                        tool, args = 'argos_evaluate', {'suite': 'quick'}
                    elif index == 3:
                        inspected = [item for item in tool_values(value.get('messages', []))
                                     if item['status'] == 'inspected']
                        found = re.search(r'Run ID: ([a-f0-9]{32})', history)
                        if not inspected or not found:
                            raise ValueError('Missing native inspection/baseline receipt')
                        tool, args = 'argos_edit_instructions', {
                            'baseline_id': found[1], 'expected_sha256': inspected[-1]['sha256'],
                            'find': 'Use the requested tools', 'replace': 'Use the requested tools carefully',
                            'hypothesis': 'Synthetic transport fixture; no measured improvement claimed.'}
                    elif index == 4:
                        changed = [item for item in tool_values(value.get('messages', []))
                                   if item['status'] == 'changed']
                        if not changed:
                            raise ValueError('Missing native edit receipt')
                        tool, args = 'argos_resolve_instructions', {
                            'change_id': changed[-1]['change_id'],
                            'expected_sha256': changed[-1]['after_sha256'], 'action': 'restore'}
                    elif index == 5:
                        tool, args = 'argos_audit_instructions', {}
                    elif index == 6:
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
                    if abort_mode['enabled']:
                        evaluation_started.set()
                        if not release_evaluation.wait(90):
                            failures.append('aborted-evaluation-gate-timeout')
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
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                # A real SDK abort can close its inference request while
                # the host-owned evaluator is still draining and saving.
                pass

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
            instructions = workspace / 'AGENTS.md'
            instructions.write_text('Use the requested tools and reply READY.')
            original_instructions = instructions.read_bytes()
            config = conversation_config('fixture:latest', workspace,
                                         plugin_root=ROOT / 'openclaw-plugin/argos-improve')
            config['agents']['defaults']['heartbeat']['every'] = '0m'
            config['skills'] = {'allowBundled': [], 'load': {'watch': False},
                                'workshop': {'autonomous': {'mode': 'off'}}}
            config['plugins']['allow'] = ['argos-improve']
            config['plugins']['slots'] = {'memory': 'none'}
            config['plugins']['entries']['argos-improve'].update(
                hooks={'allowConversationAccess': True}, config={'hostAdmission': True})
            config['tools']['alsoAllow'].extend([
                'argos_inspect', 'argos_audit_instructions', 'argos_edit_instructions', 'argos_resolve_instructions'])
            path = workspace.parent / 'openclaw.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            before = path.read_bytes()
            key = 'agent:main:host-' + str(uuid.uuid4())
            with controller_bridge.owned(home, session_key=key, worker_timeout=300) as (bridge, _env):
                bridge.launch(cli, 'Exercise the synthetic fixture tools, then reply READY.', timeout=600)
                try:
                    response, stderr = bridge.finish(timeout=630)
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
                if counts['controller_requests'] != 8 or counts['evaluation_requests'] != 20:
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
                audited = instruction_changes.audit(home)
                if (instructions.read_bytes() != original_instructions or not audited['passed'] or
                        audited['qualified_experiments'] != 0 or len(audited['changes']) != 1 or
                        audited['changes'][0]['action'] != 'restore'):
                    raise ValueError('Native instruction snapshot/restore audit failed')
                if (audited['changes'][0]['baseline']['run_ids'] != [saved['id']] or
                        audited['changes'][0]['candidate']['run_ids']):
                    raise ValueError('Instruction audit omitted its host-verified baseline evidence')
                worker = json.loads((home / '.local/state/argos-live/workload/controller-worker.json').read_bytes())
                result_artifact = report.with_name('controller-bridge-result.json')
                worker_artifact = report.with_name('controller-bridge-worker.json')
                instruction_artifact = report.with_name('controller-bridge-instructions.json')
                result_artifact.write_text(json.dumps(saved, indent=2) + '\n')
                worker_artifact.write_text(json.dumps(worker, indent=2) + '\n')
                instruction_artifact.write_text(json.dumps(audited, indent=2) + '\n')
                receipt.update(counts, controller_worker_exit=bridge.worker.returncode,
                    controller_process_group_drained=worker['process_group_drained'],
                    sdk_end_observed=worker['sdk_end_observed'], saved_run_id=saved['id'],
                    saved_coverage=saved['coverage'], host_tools=worker['tools'],
                    result_sha256=hashlib.sha256(result_artifact.read_bytes()).hexdigest(),
                    worker_receipt_sha256=hashlib.sha256(worker_artifact.read_bytes()).hexdigest(),
                    instruction_audit_sha256=hashlib.sha256(instruction_artifact.read_bytes()).hexdigest(),
                    instruction_journal_verified=True, instructions_restored=True,
                    qualified_experiments=0, independent_gain_verified=False,
                    no_exec_side_effect=True, configuration_unchanged=True)
            with workload.reserve(home, 'proctor') as slot:
                slot.complete()
            receipt.update(proctor_admitted_after_host_release=True)

            # Exercise a real pinned SDK SIGTERM abort while its admitted evaluation
            # is blocked in the synthetic inference backend. The agent process
            # must exit, but its host-owned delegated evaluator must keep the
            # reservation, save a complete run without a polling client, and
            # leave the interrupted controller quarantined.
            abort_home = home / 'aborted-controller'
            abort_workspace = abort_home / '.openclaw/workspace'
            abort_workspace.mkdir(parents=True, mode=0o700)
            (abort_workspace / 'AGENTS.md').write_text('Run an ability check, then reply READY.')
            abort_config = conversation_config('fixture:latest', abort_workspace,
                plugin_root=ROOT / 'openclaw-plugin/argos-improve')
            abort_config['agents']['defaults']['heartbeat']['every'] = '0m'
            abort_config['skills'] = {'allowBundled': [], 'load': {'watch': False},
                                      'workshop': {'autonomous': {'mode': 'off'}}}
            abort_config['plugins']['allow'] = ['argos-improve']
            abort_config['plugins']['slots'] = {'memory': 'none'}
            abort_config['plugins']['entries']['argos-improve'].update(
                hooks={'allowConversationAccess': True}, config={'hostAdmission': True})
            abort_config['tools']['alsoAllow'].extend([
                'argos_inspect', 'argos_audit_instructions', 'argos_edit_instructions', 'argos_resolve_instructions'])
            (abort_workspace.parent / 'openclaw.json').write_text(json.dumps(abort_config))
            (abort_workspace.parent / 'openclaw.json').chmod(0o600)
            counts.update(controller_requests=0, evaluation_requests=0, unsafe_exec_denied=False)
            abort_mode['enabled'] = True
            release_evaluation.clear()
            releaser = None
            teardown_errors = []
            try:
                try:
                    with controller_bridge.owned(abort_home, session_key='agent:main:abort-' + str(uuid.uuid4()),
                                                 worker_timeout=300) as (aborted, _abort_env):
                        aborted.launch(cli, 'Run the quick ability check, then reply READY.', timeout=600)
                        if not evaluation_started.wait(45):
                            raise ValueError('Pinned SDK did not dispatch the gated evaluation')
                        if aborted.worker.poll() is not None:
                            raise ValueError('Pinned SDK ended before the explicit abort signal')
                        # OpenClaw's local agent CLI handles SIGTERM as a run
                        # interruption. Keep the tool backend gated so no normal
                        # successful tool result can reach the agent first.
                        aborted.worker.send_signal(signal.SIGTERM)
                        try:
                            abort_stdout, abort_stderr = aborted.worker.communicate(timeout=20)
                        except subprocess.TimeoutExpired as error:
                            raise ValueError('Pinned SDK did not exit after SIGTERM') from error
                        receipt.update(sdk_sigterm_sent=True, sdk_abort_worker_exit=aborted.worker.returncode,
                                       sdk_abort_output_sha256=hashlib.sha256(
                                           (abort_stdout + '\n' + abort_stderr).encode()).hexdigest())
                        if not aborted.pending or aborted.pending.poll() is not None:
                            raise ValueError('SDK abort cancelled or lost the host-owned evaluation')
                        requests_at_abort = counts['controller_requests']
                        try:
                            with workload.reserve(abort_home, 'evaluation'):
                                raise ValueError('Competing evaluation entered while SDK-aborted job was active')
                        except workload.Busy:
                            pass

                        def release_after_teardown_starts():
                            try:
                                deadline = time.monotonic() + 15
                                while not aborted.closed and time.monotonic() < deadline:
                                    time.sleep(.01)
                                if not aborted.closed:
                                    raise ValueError('Host teardown did not begin after SDK abort')
                                if not aborted.pending or aborted.pending.poll() is not None:
                                    raise ValueError('Host killed evaluation before its saved publication')
                                try:
                                    with workload.reserve(abort_home, 'evaluation'):
                                        raise ValueError('Admission released before aborted evaluation was saved')
                                except workload.Busy:
                                    pass
                                release_evaluation.set()
                            except BaseException as error:
                                teardown_errors.append(error)
                                release_evaluation.set()

                        releaser = threading.Thread(target=release_after_teardown_starts, daemon=True)
                        releaser.start()
                        raise RuntimeError('synthetic SDK agent turn aborted after evaluation dispatch')
                except RuntimeError as error:
                    if str(error) != 'synthetic SDK agent turn aborted after evaluation dispatch':
                        raise
            finally:
                release_evaluation.set()
                if releaser:
                    releaser.join(timeout=20)
                    if releaser.is_alive():
                        raise ValueError('SDK abort drainage fixture did not finish')
            if teardown_errors:
                raise teardown_errors[0]
            abort_store = Store(abort_home / '.local/share/argos-live/results')
            abort_listing = abort_store.list()
            if abort_listing['rejected'] or len(abort_listing['runs']) != 1:
                raise ValueError('SDK-aborted evaluation did not publish exactly one saved run')
            abort_run = abort_store.load(abort_listing['runs'][0]['id'])
            reservation = json.loads((abort_home / '.local/state/argos-live/workload/reservation.json').read_text())
            abort_result_artifact = report.with_name('controller-bridge-abort-result.json')
            abort_result_artifact.write_text(json.dumps(abort_run, indent=2) + '\n')
            evaluation_outcomes = [item for item in aborted.outcomes if item.get('kind') == 'evaluation']
            abort_checks = {
                'run_completed': abort_run['state'] == 'completed',
                'all_tasks_saved': abort_run['coverage']['completed'] == 20,
                'pending_worker_cleared': aborted.pending is None,
                'one_host_evaluation_outcome': len(evaluation_outcomes) == 1,
                'outcome_matches_saved_run': bool(evaluation_outcomes) and
                    evaluation_outcomes[0].get('result_id') == abort_run['id'],
                'reservation_quarantined': reservation.get('state') == 'quarantined',
                'controller_inference_stopped': counts['controller_requests'] == requests_at_abort,
                'no_fixture_errors': not failures,
            }
            receipt['sdk_abort_checks'] = abort_checks
            receipt['sdk_abort_reservation_state'] = reservation.get('state')
            receipt['sdk_abort_outcomes'] = aborted.outcomes
            receipt['sdk_abort_failures'] = failures
            if not all(abort_checks.values()):
                raise ValueError('SDK abort acceptance checks failed: ' + json.dumps(abort_checks))
            receipt.update(sdk_sigterm_aborted_controller=True,
                sdk_sigterm_worker_exit=aborted.worker.returncode,
                sdk_abort_evaluation_saved=True, sdk_abort_saved_run_id=abort_run['id'],
                sdk_abort_saved_coverage=abort_run['coverage'], sdk_abort_second_evaluation_refused=True,
                sdk_abort_controller_inference_stayed_stopped=True,
                sdk_abort_reservation_quarantined=True, sdk_abort_controller_requests=counts['controller_requests'])
            receipt['sdk_abort_result_sha256'] = hashlib.sha256(abort_result_artifact.read_bytes()).hexdigest()
            receipt['passed'] = True
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
