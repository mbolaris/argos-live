#!/usr/bin/env python3
"""Run the optional Proctor tools through the real pinned SDK with synthetic replies."""
import argparse
from http.server import BaseHTTPRequestHandler
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'scripts'))
from argoslive import controller_bridge, workload
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


def run(cli, report):
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.geteuid() == 0):
        raise ValueError('Proctor integration fixture requires an unprivileged disposable hosted runner')
    progress = {'tools': 0, 'errors': []}

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
            if self.path == '/api/show':
                self.respond({'parameters': 'num_ctx 32768', 'capabilities': ['completion', 'tools'],
                              'model_info': {'general.architecture': 'llama', 'llama.context_length': 32768}})
                return
            if self.path != '/api/chat':
                progress['errors'].append('unexpected-endpoint')
                return self.respond(None)
            calls = progress['tools']
            if request.get('tools') and calls < len(TOOLS):
                tool, args = TOOLS[calls], ARGS[calls]
                progress['tools'] += 1
                message = {'role': 'assistant', 'content': '', 'tool_calls': [{
                    'id': f'proctor-call-{calls}', 'type': 'function',
                    'function': {'name': tool, 'arguments': args}}]}
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
        'scope': 'real pinned OpenClaw SDK and host tools; synthetic answers; four-item regression fixture only',
        'production_gateway_dispatch': False, 'protected_service_identity': False,
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
            cartridge_path = home / '.local/share/argos-live/proctor/cartridges/regression.db'
            cartridge_path.parent.mkdir(parents=True, mode=0o700)
            compile_cartridge(source, cartridge_path)
            state = open_state(home / '.local/share/argos-live/proctor/state.db')
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
                receipt.update(tool_calls=progress['tools'],
                    proctor_workload_released=True, transcript_id=transcript_id,
                    transcript_sha256=transcript_hash, signature_verified=True,
                    synthetic_score=payload['accepted_correct'], synthetic_total=payload['total_items'],
                    answer_key_exposure='not present in agent tool receipts', held_out_claim=False)
            reservation = json.loads((home / '.local/state/argos-live/workload/reservation.json').read_text())
            if reservation.get('state') != 'released' or reservation.get('result_id') != transcript_id:
                raise ValueError('Proctor reservation did not bind the saved signed transcript')
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
