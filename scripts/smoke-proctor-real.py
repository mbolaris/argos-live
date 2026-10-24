#!/usr/bin/env python3
"""Disposable hosted real-model service test; no synthetic answers or model switch."""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, proctor_service, starter
from argoslive.proctor.signing import Ed25519Signer, verify_envelope


def safe_controller_diagnostics(turn):
    """Export bounded worker outcomes, error classes and counters, never text."""
    if not isinstance(turn, dict):
        return {}
    result = {}
    count = turn.get('host_tool_requests')
    if type(count) is int and 0 <= count <= 10000:
        result['host_tool_requests'] = count
    allowed = {'proctor_start', 'proctor_status', 'proctor_item', 'proctor_answer',
               'proctor_continue', 'proctor_submit', 'proctor_feedback', 'proctor_tool_call'}
    error_codes = {'UNAUTHORIZED_CALLER', 'UNAUTHORIZED_SESSION', 'CARTRIDGE_UNAVAILABLE',
        'IDEMPOTENCY_CONFLICT', 'MODULE_NOT_STARTABLE', 'MODULE_NOT_ACTIVE',
        'INVALID_SUBMISSION_ARGUMENTS', 'ITEM_NOT_IN_MODULE', 'MODULE_NOT_RELEASED',
        'INVALID_ANSWER_FORMAT', 'STALE_REVISION', 'AID_NOT_ALLOWED', 'UNKNOWN_AID',
        'AID_COMPLETION_CONFLICT', 'AID_NO_LONGER_ACTIVE', 'MODULE_DEADLINE_EXPIRED',
        'TRANSCRIPT_NOT_ISSUED'}
    failures = turn.get('host_tool_failures')
    if isinstance(failures, list):
        safe_failures = []
        for row in failures[:32]:
            if (not isinstance(row, dict) or row.get('kind') not in allowed or
                    not isinstance(row.get('error_class'), str) or len(row['error_class']) > 64):
                continue
            failure = {'kind': row['kind'], 'error_class': row['error_class']}
            if row.get('kind') == 'proctor_answer' and row.get('error_code') in error_codes:
                failure['error_code'] = row['error_code']
            safe_failures.append(failure)
        result['host_tool_failures'] = safe_failures
    outcomes = turn.get('tools')
    if isinstance(outcomes, list):
        result['tool_outcomes'] = [
            {'kind': row['kind'], 'status': row['status']}
            for row in outcomes[:64]
            if (isinstance(row, dict) and row.get('kind') in allowed | {'proctor_host_submit', 'proctor_finalize'} and
                isinstance(row.get('status'), str) and len(row['status']) <= 64)]
    worker_turns = turn.get('worker_turns')
    if isinstance(worker_turns, list):
        safe_turns = []
        for row in worker_turns[:32]:
            if (not isinstance(row, dict) or row.get('outcome') not in
                    {'completed', 'incomplete-turn', 'blocked-turn'} or
                    type(row.get('turn')) is not int or not 1 <= row['turn'] <= 10000 or
                    type(row.get('returncode')) is not int or not -255 <= row['returncode'] <= 255 or
                    any(type(row.get(key)) is not int or not 0 <= row[key] <= 2 * 1024**2
                        for key in ('stdout_bytes', 'stderr_bytes')) or
                    any(type(row.get(key)) is not bool for key in
                        ('process_group_drained', 'session_bound')) or
                    type(row.get('host_tool_requests')) is not int or
                    not 0 <= row['host_tool_requests'] <= 10000 or
                    type(row.get('host_tool_failures')) is not int or
                    not 0 <= row['host_tool_failures'] <= 32 or
                    row.get('response_status') not in {'ok', 'error'}):
                continue
            safe = {key: row[key] for key in ('turn', 'outcome', 'returncode', 'stdout_bytes',
                    'stderr_bytes', 'process_group_drained', 'session_bound',
                    'host_tool_requests', 'host_tool_failures', 'response_status')}
            if row.get('sdk_error_kind') in {'incomplete_turn', 'hook_block'}:
                safe['sdk_error_kind'] = row['sdk_error_kind']
            safe_turns.append(safe)
        result['worker_turns'] = safe_turns
    diagnostics = turn.get('admission_diagnostics')
    safe_counts = ('tool_hooks', 'bound_calls', 'executions')
    safe_rejections = ('unknown_tool', 'missing_admission', 'invalid_call_id', 'stale_binding')
    if (isinstance(diagnostics, dict) and isinstance(diagnostics.get('rejected'), dict) and
            all(type(diagnostics.get(name)) is int and 0 <= diagnostics[name] <= 10000 for name in safe_counts) and
            all(type(diagnostics['rejected'].get(name)) is int and
                0 <= diagnostics['rejected'][name] <= 10000 for name in safe_rejections)):
        result['admission'] = {
            **{name: diagnostics[name] for name in safe_counts},
            'rejected': {name: diagnostics['rejected'][name] for name in safe_rejections}}
    return result


def safe_finish_failure(path):
    """Copy only fixed-schema controller failure facts; never export text output."""
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != 'argos-controller-failure/1':
        return {'schema_valid': False}
    failure = value.get('failure')
    if not isinstance(failure, dict):
        return {'schema_valid': False}
    result = {'schema_valid': True}
    for key in ('code', 'exception_class'):
        item = failure.get(key)
        if isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', item):
            result[key] = item
    for key in ('returncode', 'stdout_bytes', 'stderr_bytes', 'live_group_members'):
        item = failure.get(key)
        if type(item) is int and -255 <= item <= 2 * 1024**2:
            result[key] = item
    for key in ('status_ok', 'payloads_list', 'session_bound'):
        item = failure.get(key)
        if type(item) is bool:
            result[key] = item
    response = failure.get('worker_response')
    if isinstance(response, dict):
        safe_response = {}
        for key in ('json_valid', 'size_limited', 'object', 'result_object', 'error_present',
                    'session_bound'):
            item = response.get(key)
            if type(item) is bool:
                safe_response[key] = item
        for key in ('status', 'error_code', 'error_name', 'error_type', 'error_kind'):
            item = response.get(key)
            if isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', item):
                safe_response[key] = item
        for key in ('payload_count',):
            item = response.get(key)
            if type(item) is int and 0 <= item <= 10000:
                safe_response[key] = item
        result['worker_response'] = safe_response
    return result


def run(cli, ollama, seed, report, *, deterministic_profile=False):
    scratch = Path(os.environ.get('RUNNER_TEMP', '/missing')).resolve()
    seed = seed.resolve(strict=True)
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            scratch not in seed.parents or os.geteuid() == 0):
        raise ValueError('Real Proctor smoke requires an unprivileged disposable hosted fixture')
    identity = starter.read_only(seed, include_model_identity=True)['model_identity']
    with tempfile.TemporaryDirectory(prefix='argos-proctor-real-', dir=scratch) as temporary:
        home = Path(temporary)
        workspace = home / '.openclaw/workspace'
        workspace.mkdir(mode=0o700, parents=True)
        config = auto_setup.conversation_config(starter.TAG, workspace,
            plugin_root=ROOT / 'openclaw-plugin/argos-improve')
        if deterministic_profile:
            config['models']['providers']['ollama']['models'][0]['params'] = {'temperature': 0}
        config_path = home / '.openclaw/openclaw.json'
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)
        state = home / '.config/argos-live/state.json'
        state.parent.mkdir(mode=0o700, parents=True)
        state.write_text(json.dumps({'model': starter.TAG}))
        # Substitute only fixture storage discovery. Identity is verified from
        # the same immutable seed; service, model, answers and signing are real.
        def source(_home, *, include_model_identity=False):
            return ((seed, starter.TAG, identity) if include_model_identity else (seed, starter.TAG))
        original_environment = proctor_service.owned_gateway.environment
        def observed_environment(home, config_path):
            env = original_environment(home, config_path)
            env.update(NODE_OPTIONS='--import=' + (ROOT / 'scripts/native-chat-request-probe.mjs').as_uri(),
                ARGOS_NATIVE_REQUEST_REPORT=str(home / 'proctor-wire.json'),
                ARGOS_NATIVE_OPENCLAW_ENTRY=str(cli.resolve()))
            return env
        try:
            with patch.object(proctor_service.startup, 'source', side_effect=source), \
                patch.object(auto_setup, 'PLUGIN_ROOT', str(ROOT / 'openclaw-plugin/argos-improve')), \
                patch.object(proctor_service.owned_gateway, 'environment', side_effect=observed_environment), \
                patch.dict(os.environ, {'PATH': str(ollama.resolve().parent) + os.pathsep + os.environ['PATH']}):
                result = proctor_service.run_practice(home, executable=str(cli.absolute()))
        except BaseException as error:
            state_root = home / '.local/state/argos-live/workload'
            turn_path = state_root / 'controller-turn.json'
            turn = json.loads(turn_path.read_text(encoding='utf-8')) if turn_path.is_file() else {}
            failure = {'schema': 'argos-real-proctor-service-failure/1',
                       'failure_class': type(error).__name__,
                       'controller_failure': safe_finish_failure(state_root / 'controller-failure.json'),
                       'controller_diagnostics': safe_controller_diagnostics(turn),
                       'practice_only': True, 'image_acceptance': False}
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(failure, indent=2) + '\n')
            raise
        root = home / '.local/state/argos-live/proctor'
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(root / 'state.sqlite3')) as db:
            row = db.execute('SELECT envelope_json FROM transcripts WHERE session_id=?',
                             ('sess_' + result['transcript_id'],)).fetchone()
        envelope = json.loads(row[0])
        signer = Ed25519Signer(root / 'transcript-ed25519.pem')
        verified = verify_envelope(envelope, signer.public_key_der)
        payload = json.loads(envelope['payload_json'])
        receipt = {'schema': 'argos-real-proctor-service/1',
            'transcript_id': result['transcript_id'], 'outcome': payload['outcome'],
            'signature_verified': verified,
            'model_identity_bound': payload['subject']['model_identity'] == identity,
            'transcript_sha256': hashlib.sha256(envelope['payload_json'].encode()).hexdigest(),
            'model_tag': starter.TAG, 'total': payload['total_items'],
            'answered': len(payload['accepted_answers']), 'correct': payload['accepted_correct'],
            'practice_only': True, 'calibration_status': 'uncalibrated',
            'host_turns': result['host_turns'],
            'requested_temperature': config['models']['providers']['ollama']['models'][0].get('params', {}).get('temperature'),
            'image_acceptance': False}
        turn = json.loads((home / '.local/state/argos-live/workload/controller-turn.json').read_text())
        receipt['tool_kinds'] = [row['kind'] for row in turn.get('tools', [])
                                if isinstance(row, dict) and row.get('kind') in
                                {'proctor_' + name for name in
                                 ('start', 'status', 'item', 'answer', 'submit', 'host_submit', 'continue', 'feedback', 'finalize', 'tool_call')}]
        receipt['controller_diagnostics'] = safe_controller_diagnostics(turn)
        tool_call_answer = next((row for row in payload['accepted_answers']
                                 if row.get('item_id') == 'q5'), None)
        expected_tool_call = {'name': 'argos_evaluate_wait',
                              'arguments': {'job_id': '0123456789abcdef0123456789abcdef'}}
        wire = home / 'proctor-wire.json'
        receipt['wire_request'] = json.loads(wire.read_text()) if wire.is_file() else {}
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(receipt, indent=2) + '\n')
        # Only this public-pilot scratch fixture exports model reply text. There
        # is no owner workspace or owner prompt. Strip exact ephemeral gateway
        # tokens and identifier-shaped values; never export raw SDK output.
        tokens = [config['gateway']['auth']['token']]
        for path in (root / 'profiles').rglob('openclaw.json'):
            tokens.append(json.loads(path.read_text())['gateway']['auth']['token'])
        replies = []
        for row in result.get('agent_summary', [])[:64]:
            text = row.get('text') if isinstance(row, dict) else None
            if not isinstance(text, str): continue
            for token in tokens: text = text.replace(token, '[fixture-token]')
            replies.append(re.sub(r'(?i)[a-f0-9]{32,}', '[identifier]', text)[:4096])
        report.with_name('proctor-real-replies.json').write_text(json.dumps(replies, indent=2) + '\n')
        # This fixture uses only the public pilot and disposable synthetic
        # configuration. Preserve the signed record and public verification key,
        # never the private key, so the saved ID remains independently auditable.
        report.with_name('proctor-real-transcript.json').write_text(json.dumps({
            'envelope': envelope,
            'public_key_der_base64': base64.b64encode(signer.public_key_der).decode()}, indent=2) + '\n')
        if (result['status'] != 'completed' or payload['outcome'] != 'COMPLETED' or
                payload['total_items'] != 5 or len(payload['accepted_answers']) != 5 or
                tool_call_answer is None or json.loads(tool_call_answer['answer']) != expected_tool_call or
                not any(row.get('kind') == 'proctor_tool_call' and row.get('status') == 'simulated'
                        for row in turn.get('tools', []) if isinstance(row, dict)) or
                not all(module['state'] == 'SUBMITTED' for module in payload['modules']) or
                not verified or not receipt['model_identity_bound']):
            raise ValueError('Real-model Proctor did not complete and verify all five practice items; see receipt')
        worker_turns = receipt['controller_diagnostics'].get('worker_turns', [])
        if (len(worker_turns) != result['host_turns'] or
                any(not row['process_group_drained'] or not row['session_bound'] for row in worker_turns)):
            raise ValueError('Real-model Proctor receipt did not verify every drained, session-bound worker turn')
        if (receipt['requested_temperature'] is not None and
                receipt['wire_request'].get('temperature') != receipt['requested_temperature']):
            raise ValueError('Deterministic fixture request temperature was not observed on the wire')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('openclaw', 'ollama', 'seed', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--deterministic-profile', action='store_true')
    args = parser.parse_args()
    run(args.openclaw, args.ollama, args.seed, args.report, deterministic_profile=args.deterministic_profile)
