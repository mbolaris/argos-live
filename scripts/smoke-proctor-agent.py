#!/usr/bin/env python3
"""Run the optional Proctor tools through the real pinned SDK with synthetic replies."""
import argparse
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'scripts'))
from argoslive import controller_bridge, workload
from argoslive import auto_setup, proctor_service
from argoslive.auto_setup import conversation_config
from argoslive.proctor import AgentSession, Caller, Cartridge, Proctor, compile_cartridge, open_state
from argoslive.proctor.engine import digest
from argoslive.proctor.signing import Ed25519Signer, generate_key, verify_envelope
from synthetic_http import SyntheticHTTPServer


TOOLS = ['argos_proctor_start', 'argos_proctor_status', 'argos_proctor_item', 'argos_proctor_answer',
         'argos_proctor_item', 'argos_proctor_answer', 'argos_proctor_submit',
         'argos_proctor_continue', 'argos_proctor_item', 'argos_proctor_answer',
         'argos_proctor_item', 'argos_proctor_answer', 'argos_proctor_submit',
         'argos_proctor_feedback']
ARGS = [{}, {}, {'item_id': 'q1'}, {'item_id': 'q1', 'answer': 'B'}, {'item_id': 'q2'},
        {'item_id': 'q2', 'answer': '4'}, {'module_id': 'm1'}, {}, {'item_id': 'q3'},
        {'item_id': 'q3', 'answer': 'A'}, {'item_id': 'q4'},
        {'item_id': 'q4', 'answer': '-1.25'}, {'module_id': 'm2'}, {}]
if len(TOOLS) != len(ARGS):
    raise RuntimeError('Synthetic Proctor tool plan is inconsistent')
CAMPAIGN_TOOLS = ['argos_inspect', 'argos_audit_instructions']
CAMPAIGN_ARGS = [{}, {}]


def run(cli, report):
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Proctor integration fixture requires an unprivileged disposable hosted runner')
    progress = {'tools': 0, 'errors': [], 'phase': 'proctor', 'model_tool_names': [],
                'provider_idless_calls': 0, 'start_result_on_wire_verified': False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            values = {'/api/version': {'version': '0.40.5'}, '/api/tags': {'models': []}}
            self.respond(values.get(self.path))

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 2 * 1024**2:
                progress['errors'].append('invalid-request-length')
                return self.respond(None)
            request = json.loads(self.rfile.read(length))
            if isinstance(request.get('tools'), list):
                names = {tool.get('function', {}).get('name') for tool in request['tools']
                         if isinstance(tool, dict) and isinstance(tool.get('function'), dict) and
                         isinstance(tool['function'].get('name'), str)}
                progress['model_tool_names'] = sorted(set(progress['model_tool_names']) | names)
            if self.path == '/api/show':
                self.respond({'parameters': 'num_ctx 32768', 'capabilities': ['completion', 'tools'],
                              'model_info': {'general.architecture': 'llama', 'llama.context_length': 32768}})
                return
            if self.path != '/api/chat':
                progress['errors'].append('unexpected-endpoint')
                return self.respond(None)
            calls = progress['tools']
            if progress['phase'] == 'proctor' and calls == 1:
                # Do not let a scripted model conceal missing tool-result history.
                # Require the actual start response on the follow-up wire request.
                results = [row for row in request.get('messages', [])
                           if isinstance(row, dict) and row.get('role') == 'tool']
                try:
                    started = json.loads(results[-1]['content'])
                    step = started['next_step']
                    if (started['state'] != 'ACTIVE' or step['tool'] != 'argos_proctor_item' or
                            step['arguments']['item_id'] not in started['item_ids']):
                        raise ValueError('Missing start navigation')
                except (IndexError, KeyError, TypeError, ValueError):
                    progress['errors'].append('start-result-not-forwarded')
                    return self.respond(None)
                progress['start_result_on_wire_verified'] = True
            campaign_end = len(TOOLS) + (len(CAMPAIGN_TOOLS) if progress['phase'] == 'campaign' else 0)
            if request.get('tools') and calls < campaign_end:
                if calls < len(TOOLS):
                    tool, args = TOOLS[calls], ARGS[calls]
                else:
                    tool, args = CAMPAIGN_TOOLS[calls - len(TOOLS)], CAMPAIGN_ARGS[calls - len(TOOLS)]
                progress['tools'] += 1
                # Ollama's documented native tool response need not contain an ID:
                # https://docs.ollama.com/capabilities/tool-calling
                call = {'type': 'function',
                        'function': {'index': 0, 'name': tool, 'arguments': args}}
                if calls % 2:
                    call['id'] = f'proctor-call-{calls}'
                else:
                    progress['provider_idless_calls'] += 1
                message = {'role': 'assistant', 'content': '', 'tool_calls': [call]}
            else:
                message = {'role': 'assistant', 'content': 'PROCTOR_COMPLETE'}
            self.respond({'model': request['model'], 'message': message, 'done': True,
                          'done_reason': 'stop', 'eval_count': 1}, request.get('stream', True))

        def respond(self, value, stream=False):
            raw = (json.dumps(value) + '\n').encode()
            self.send_response(200 if value is not None else 404)
            self.send_header('Content-Type', 'application/x-ndjson' if stream else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = SyntheticHTTPServer(('127.0.0.1', 11434), Handler, bind_and_activate=False)
    server.server_bind()
    server.server_activate()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipt = {'schema': 'argos-native-proctor-agent/1', 'passed': False,
        'scope': 'real pinned OpenClaw SDK, host tools, and managed private gateway/service; synthetic model and answers; four-item pilot only',
        'managed_gateway_service_path': False, 'production_gateway_dispatch': False,
        'protected_service_identity': False,
        'model_identity_attested': False, 'calibrated_ability_claim': False}
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='argos-proctor-agent-', dir=os.environ['RUNNER_TEMP']) as temporary:
            home = Path(temporary)
            workspace = home / '.openclaw/workspace'
            workspace.mkdir(parents=True, mode=0o700)
            (workspace / 'AGENTS.md').write_text('Use only the host-selected Proctor exam tools. Finish the exam.')
            config = conversation_config('fixture:latest', workspace,
                                         plugin_root=ROOT / 'openclaw-plugin/argos-improve')
            config['agents']['defaults']['heartbeat']['every'] = '0m'
            config['skills'] = {'allowBundled': [], 'load': {'watch': False},
                                'workshop': {'autonomous': {'mode': 'off'}}}
            config['plugins']['allow'] = ['argos-improve']
            config['plugins']['slots'] = {'memory': 'none'}
            config['plugins']['entries']['argos-improve'].update(
                hooks={'allowConversationAccess': True}, config={'hostAdmission': True})
            config['tools']['alsoAllow'].extend(TOOLS)
            config_path = workspace.parent / 'openclaw.json'
            config_path.write_text(json.dumps(config))
            config_path.chmod(0o600)

            source = json.loads((ROOT / 'tests/fixtures/proctor/fixed.json').read_text())
            source['forms'][0]['modules'][0]['duration_ms'] = 60_000
            source['forms'][0]['modules'][1]['duration_ms'] = 60_000
            source['forms'][0]['modules'][1]['break_ms'] = 500
            proctor_root = home / '.local/share/argos-live/proctor'
            proctor_root.mkdir(parents=True, mode=0o700)
            proctor_root.chmod(0o700)
            cartridge_path = proctor_root / 'cartridges/regression.db'
            cartridge_path.parent.mkdir(parents=True, mode=0o700)
            cartridge_path.parent.chmod(0o700)
            compile_cartridge(source, cartridge_path)
            state = open_state(proctor_root / 'state.db')
            host_token, token_secret = uuid.uuid4().hex, os.urandom(32)
            signing_key = home / '.local/share/argos-live/proctor/signing.key'
            generate_key(signing_key)
            signer = Ed25519Signer(signing_key)
            engine = Proctor(Cartridge(cartridge_path), state,
                callers={'host': Caller(digest(host_token))}, token_secret=token_secret,
                boot_id='synthetic-boot', signer=signer)
            engine.recover()
            profile = AgentSession(engine, caller_id='host', caller_token=host_token,
                form_id='fixed-a', tier='held_out',
                subject={'lineage_id': 'synthetic-lineage', 'memory_id': 'synthetic-memory',
                    'subject_type': 'deployed_agent_profile', 'model_tag': 'fixture:latest',
                    'model_digest': 'a' * 64, 'configuration': {'prompt_sha256': 'b' * 64}},
                policy={'enforcement_level': 'declared', 'assistance_policy': 'closed_book'})
            key = 'agent:main:proctor-' + str(uuid.uuid4())
            with controller_bridge.owned(home, session_key=key, worker_timeout=300,
                                         exam_session=profile) as (bridge, _env):
                bridge.launch(cli, 'Take the preselected Proctor exam, then reply PROCTOR_COMPLETE.', timeout=600)
                response, stderr = bridge.finish(timeout=630)
                if 'PROCTOR_COMPLETE' not in json.dumps(response):
                    raise ValueError('Pinned OpenClaw did not finish the Proctor tool session')
                if progress['tools'] != len(TOOLS) or progress['errors']:
                    raise ValueError('Unexpected Proctor tool dispatch: ' + json.dumps(progress))
                if any(item['kind'] in {'evaluation', 'log', 'edit', 'resolve'} for item in bridge.outcomes):
                    raise ValueError('Campaign tools were available during the Proctor session')
                if any(item['kind'] == 'proctor_feedback' for item in bridge.outcomes):
                    raise ValueError('Held-out exam feedback was returned to the examinee')
                signed = profile.host_transcript()
                if not verify_envelope(signed, signer.public_key_der):
                    raise ValueError('Host-issued Proctor transcript signature did not verify')
                payload = json.loads(signed['payload_json'])
                if payload['outcome'] != 'COMPLETED' or payload['accepted_correct'] != 4:
                    raise ValueError('Synthetic Proctor transcript does not match the scripted answers')
                transcript_hash = hashlib.sha256(signed['payload_json'].encode()).hexdigest()
                transcript_id = profile.session_id.removeprefix('sess_')
                if any(key in json.dumps(bridge.outcomes) for key in ('accepted_correct', 'payload_json', 'correct')):
                    raise ValueError('Agent-facing Proctor receipts exposed scoring or the signed transcript')
                if not progress['provider_idless_calls']:
                    raise ValueError('Fixture did not exercise provider calls without IDs')
                receipt.update(tool_calls=progress['tools'],
                    start_result_on_wire_verified=progress['start_result_on_wire_verified'],
                    provider_idless_tool_calls=progress['provider_idless_calls'],
                    proctor_workload_released=True, transcript_id=transcript_id,
                    transcript_sha256=transcript_hash, signature_verified=True,
                    synthetic_score=payload['accepted_correct'], synthetic_total=payload['total_items'],
                    answer_key_exposure='not present in agent tool receipts', held_out_claim=False)
            reservation = json.loads((home / '.local/state/argos-live/workload/reservation.json').read_text())
            if reservation.get('state') != 'released' or reservation.get('result_id') != transcript_id:
                raise ValueError('Proctor reservation did not bind the saved signed transcript')

            # Exercise the owner-facing service entry point and its isolated,
            # tool-restricted gateway profile with the same synthetic model.
            progress.update(tools=0, errors=[], phase='practice')
            progress['model_tool_names'] = []
            service_home = home / 'service-home'
            service_home.mkdir(mode=0o700)
            model_storage = service_home / 'Models'
            model_storage.mkdir(mode=0o700)
            storage_id = uuid.uuid4().hex
            (model_storage / '.argos-storage-id').write_text(storage_id + '\n')
            model_manifest = model_storage / 'manifests/registry.ollama.ai/library/fixture/latest'
            model_manifest.parent.mkdir(parents=True)
            synthetic_manifest = b'synthetic fixture model manifest\n'
            model_manifest.write_bytes(synthetic_manifest)
            model_blob = b'synthetic fixture model bytes'
            model_identity = {
                'schema': 'argos-verified-model/1', 'tag': 'fixture:latest',
                'catalog_manifest_digest': 'sha256:' + hashlib.sha256(synthetic_manifest).hexdigest(),
                'local_manifest_sha256': hashlib.sha256(synthetic_manifest).hexdigest(),
                'artifacts': [{'digest': 'sha256:' + hashlib.sha256(model_blob).hexdigest(),
                               'size': len(model_blob),
                               'media_type': 'application/vnd.ollama.image.model'}],
                'verified_bytes': len(model_blob),
                'verification': 'catalog manifest and every declared model blob SHA-256 verified',
            }
            model_identity['sha256'] = hashlib.sha256(json.dumps(
                model_identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

            def synthetic_source(_home, *, include_model_identity=False):
                return ((model_storage, 'fixture:latest', model_identity) if include_model_identity
                        else (model_storage, 'fixture:latest'))
            setup_state = service_home / '.config/argos-live/state.json'
            setup_state.parent.mkdir(parents=True, mode=0o700)
            setup_state.write_text(json.dumps({'storage': str(model_storage), 'storage_id': storage_id,
                                               'model': 'fixture:latest'}))
            owner_workspace = service_home / '.openclaw/workspace'
            owner_workspace.mkdir(parents=True, mode=0o700)
            (owner_workspace / 'AGENTS.md').write_text('Use managed Argos host tools; preserve saved evidence.')
            owner_config_path = service_home / '.openclaw/openclaw.json'
            owner_config = conversation_config('fixture:latest', owner_workspace,
                                                plugin_root=ROOT / 'openclaw-plugin/argos-improve')
            owner_config_path.write_text(json.dumps(owner_config))
            owner_config_path.chmod(0o600)
            from unittest.mock import patch
            real_finish = controller_bridge.Bridge.finish

            def report_finish_failure(bridge, *, timeout=1900):
                try:
                    return real_finish(bridge, timeout=timeout)
                except BaseException:
                    raw = getattr(bridge, 'last_stdout', '')
                    stderr = getattr(bridge, 'last_stderr', '')
                    def redact(value):
                        value = re.sub(r'(?i)(token\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', value)
                        value = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*', r'\1[redacted]', value)
                        value = re.sub(r'(?<![A-Za-z0-9])[A-Fa-f0-9]{32,}(?![A-Za-z0-9])', '[redacted-id]', value)
                        value = re.sub(r'/home/runner/[^\s:]+', '[runner-path]', value)
                        return value[:3000]
                    try:
                        decoded = json.loads(raw)
                        body = decoded.get('result', decoded) if isinstance(decoded, dict) else {}
                        meta = body.get('meta', {}) if isinstance(body, dict) else {}
                        payloads = body.get('payloads', []) if isinstance(body, dict) else []
                    except (TypeError, ValueError):
                        decoded, meta, payloads = {}, {}, []
                    diagnostic = {
                        'schema': 'argos-proctor-smoke-failure/1',
                        'worker_returncode': bridge.worker.returncode if bridge.worker else None,
                        'stdout_bytes': len(raw.encode()),
                        'stderr_bytes': len(getattr(bridge, 'last_stderr', '').encode()),
                        'stdout_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                        'stderr_sha256': hashlib.sha256(stderr.encode()).hexdigest(),
                        'stdout_excerpt': redact(raw),
                        'stderr_excerpt': redact(stderr),
                        'response_status': decoded.get('status') if isinstance(decoded, dict) else None,
                        'response_error_present': bool(meta.get('error')) if isinstance(meta, dict) else False,
                        'payload_count': len(payloads) if isinstance(payloads, list) else None,
                        'synthetic_model_tool_calls': progress['tools'],
                        'synthetic_model_errors': list(progress['errors']),
                        'synthetic_model_tool_names': list(progress['model_tool_names']),
                        'controller_admission': {
                            'active': bool(bridge.active),
                            'ended': bool(bridge.active and bridge.active.get('ended')),
                            'uncertain': bridge.uncertain,
                            'diagnostics': bridge.active.get('diagnostics') if bridge.active else None,
                            'host_tool_requests': bridge.active.get('host_tool_requests', 0) if bridge.active else 0,
                            'host_tool_failures': bridge.active.get('host_tool_failures', []) if bridge.active else [],
                            'host_calls_accepted': len(bridge.active.get('calls', [])) if bridge.active else 0,
                            'tool_outcome_kinds': [item.get('kind') for item in bridge.outcomes],
                        },
                        'tool_outcomes': list(bridge.outcomes),
                        'sdk_end_observed': bool(bridge.active and bridge.active.get('ended')),
                    }
                    report.with_name('proctor-agent-failure.json').write_text(
                        json.dumps(diagnostic, indent=2) + '\n')
                    raise

            with patch.object(auto_setup, 'PLUGIN_ROOT', str(ROOT / 'openclaw-plugin/argos-improve')), \
                    patch.object(proctor_service.startup, 'source',
                                 side_effect=synthetic_source), \
                    patch.object(proctor_service, 'refuse_live_backend'), \
                    patch.object(proctor_service.owned_ollama, 'owned',
                                 side_effect=lambda *args, **kwargs: nullcontext(None)), \
                    patch.object(controller_bridge.Bridge, 'finish', report_finish_failure):
                service_result = proctor_service.run_practice(
                    service_home, None, 'pilot-a', executable=cli)
            if (service_result['status'] != 'completed' or service_result['result']['correct'] != 4 or
                    progress['tools'] != len(TOOLS) or progress['errors']):
                raise ValueError('Owner-facing Proctor service did not complete the synthetic practice exam')
            if (not set(proctor_service.PROCTOR_TOOL_NAMES).issubset(progress['model_tool_names']) or
                    set(proctor_service.CAMPAIGN_TOOL_NAMES) & set(progress['model_tool_names'])):
                raise ValueError('Managed practice profile exposed the wrong Argos tool set')
            service_reservation = json.loads((service_home / '.local/state/argos-live/workload/reservation.json').read_text())
            if (service_reservation.get('state') != 'released' or
                    service_reservation.get('result_id') != service_result['transcript_id']):
                raise ValueError('Owner-facing service did not bind and release the signed transcript')
            transcript_db = service_home / '.local/state/argos-live/proctor/state.sqlite3'
            import sqlite3
            with sqlite3.connect(transcript_db) as conn:
                row = conn.execute('SELECT envelope_json FROM transcripts WHERE session_id=?',
                                   ('sess_' + service_result['transcript_id'],)).fetchone()
            if not row:
                raise ValueError('Owner-facing Proctor service did not save its signed transcript')
            service_signer = Ed25519Signer(
                service_home / '.local/state/argos-live/proctor/transcript-ed25519.pem')
            saved_envelope = json.loads(row[0])
            if not verify_envelope(saved_envelope, service_signer.public_key_der):
                raise ValueError('Owner-facing Proctor service transcript signature did not verify')
            saved_subject = json.loads(saved_envelope['payload_json'])['subject']
            model_identity_binding_verified = (
                saved_subject.get('model_identity') == model_identity and
                saved_subject.get('model_digest') == model_identity['sha256'])
            if not model_identity_binding_verified:
                raise ValueError('Signed Proctor transcript did not bind the host model identity receipt')
            # Exercise the chained owner command: practice must finalize and
            # release before a separate campaign profile receives host tools.
            progress.update(tools=0, errors=[], phase='campaign', model_tool_names=[])
            with patch.object(auto_setup, 'PLUGIN_ROOT', str(ROOT / 'openclaw-plugin/argos-improve')), \
                    patch.object(proctor_service.startup, 'source',
                              side_effect=synthetic_source), \
                    patch.object(proctor_service, 'refuse_live_backend'), \
                    patch.object(proctor_service.owned_ollama, 'owned',
                                 side_effect=lambda *args, **kwargs: nullcontext(None)):
                improvement_result = proctor_service.run_improvement(
                    service_home, None, 'pilot-a', executable=cli)
            expected_campaign_calls = len(TOOLS) + len(CAMPAIGN_TOOLS)
            if (improvement_result['status'] != 'completed' or
                    improvement_result['practice_is_improvement_evidence'] is not False or
                    progress['tools'] != expected_campaign_calls or progress['errors']):
                raise ValueError('Owner-facing chained improvement flow did not complete its scoped campaign')
            if not improvement_result['practice']['transcript_id']:
                raise ValueError('Chained improvement flow lacks its saved practice transcript ID')
            campaign_reservation = json.loads((service_home / '.local/state/argos-live/workload/reservation.json').read_text())
            if campaign_reservation.get('state') != 'released':
                raise ValueError('Improvement campaign reservation was not released after its worker drained')
            if any(item['kind'] in {'evaluation', 'edit', 'resolve'}
                   for item in improvement_result['campaign']['tool_outcomes']):
                raise ValueError('Synthetic no-experiment campaign unexpectedly changed or evaluated anything')
            receipt.update(managed_gateway_service_path=True,
                service_practice_score=service_result['result']['correct'],
                service_practice_total=service_result['result']['total'],
                service_transcript_id=service_result['transcript_id'],
                service_signature_verified=True, verified_model_identity_binding=True,
                actual_model_weights_verified=False, improvement_campaign_completed=True,
                campaign_tool_calls=progress['tools'], campaign_saved_evaluations=0,
                production_gateway_dispatch=False)
            receipt['passed'] = True
            state.close()
    finally:
        report.write_text(json.dumps(receipt, indent=2) + '\n')
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    if not receipt['passed']:
        raise ValueError('Native Proctor SDK acceptance did not pass')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openclaw', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    value = run(args.openclaw.absolute(), args.report)
    print(json.dumps({'passed': value['passed'], 'scope': value['scope']}))
