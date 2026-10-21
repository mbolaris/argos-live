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


def run(cli, ollama, seed, report):
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
        with patch.object(proctor_service.startup, 'source', side_effect=source), \
                patch.object(auto_setup, 'PLUGIN_ROOT', str(ROOT / 'openclaw-plugin/argos-improve')), \
                patch.object(proctor_service.owned_gateway, 'environment', side_effect=observed_environment), \
                patch.dict(os.environ, {'PATH': str(ollama.resolve().parent) + os.pathsep + os.environ['PATH']}):
            result = proctor_service.run_practice(home, executable=str(cli.absolute()))
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
            'image_acceptance': False}
        turn = json.loads((home / '.local/state/argos-live/workload/controller-turn.json').read_text())
        receipt['tool_kinds'] = [row['kind'] for row in turn.get('tools', [])
                                if isinstance(row, dict) and row.get('kind') in
                                {'proctor_' + name for name in
                                 ('start', 'status', 'item', 'answer', 'submit', 'host_submit', 'continue', 'feedback', 'finalize')}]
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
                payload['total_items'] != 4 or len(payload['accepted_answers']) != 4 or
                not verified or not receipt['model_identity_bound']):
            raise ValueError('Real-model Proctor did not complete all four practice items; see receipt')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('openclaw', 'ollama', 'seed', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.openclaw, args.ollama, args.seed, args.report)
