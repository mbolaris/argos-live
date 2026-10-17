import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.proctor.signing import Ed25519Signer, generate_key, verify_envelope
from argoslive.proctor import Caller, Cartridge, Proctor, compile_cartridge, open_state
from argoslive.proctor.engine import digest

OPENSSL = os.environ.get('ARGOS_TEST_OPENSSL', 'openssl')


@unittest.skipUnless(shutil.which(OPENSSL), 'System OpenSSL required for real Ed25519 checks')
class SigningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = self.root / 'installation.key'
        generate_key(self.key, executable=OPENSSL)
        self.signer = Ed25519Signer(self.key, executable=OPENSSL)

    def envelope(self):
        # Sign exact persisted bytes, including Unicode; no reserialization convention needed.
        payload = json.dumps({'subject': 'fixture', 'value': 'π', 'temperature': 0.1}, ensure_ascii=False)
        return {'envelope_version': 'argos.proctor.envelope.v1', 'payload_json': payload,
                'signature': self.signer.sign(payload.encode('utf-8'))}

    def test_real_sign_and_verify_reject_tampering_and_other_installation(self):
        envelope = self.envelope()
        self.assertTrue(verify_envelope(envelope, self.signer.public_key_der, executable=OPENSSL))
        changed = copy.deepcopy(envelope)
        changed['payload_json'] += ' '
        self.assertFalse(verify_envelope(changed, self.signer.public_key_der, executable=OPENSSL))
        other_key = self.root / 'other.key'
        generate_key(other_key, executable=OPENSSL)
        other = Ed25519Signer(other_key, executable=OPENSSL)
        self.assertFalse(verify_envelope(envelope, other.public_key_der, executable=OPENSSL))
        changed = copy.deepcopy(envelope)
        changed['signature']['algorithm'] = 'HMAC-SHA256'
        self.assertFalse(verify_envelope(changed, self.signer.public_key_der, executable=OPENSSL))

    def test_key_provisioning_refuses_overwrite_and_public_permissions(self):
        with self.assertRaises(FileExistsError):
            generate_key(self.key, executable=OPENSSL)
        if os.name != 'nt':
            self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
            self.key.chmod(0o644)
            with self.assertRaises(ValueError):
                Ed25519Signer(self.key, executable=OPENSSL)

    def test_malformed_signature_is_rejected(self):
        for signature in ('!', '', 'a' * 64):
            envelope = self.envelope()
            envelope['signature']['sig_base64'] = signature
            self.assertFalse(verify_envelope(envelope, self.signer.public_key_der, executable=OPENSSL))

    def test_actual_engine_transcript_round_trip(self):
        definition = json.loads((ROOT / 'tests/fixtures/proctor/fixed.json').read_text())
        cart_path = self.root / 'cartridge.db'
        compile_cartridge(definition, cart_path)
        conn = open_state(self.root / 'state.db')
        self.addCleanup(conn.close)
        now = [1_000_000]
        engine = Proctor(Cartridge(cart_path), conn, callers={'host': Caller(digest('secret'))},
                         token_secret=os.urandom(32), boot_id='fixture-boot', signer=self.signer, clock=lambda: now[0])
        enrollment = engine.enroll('host', 'secret', 'enroll', form_id='fixed-a', tier='assessment',
            subject={'lineage_id': 'fixture', 'memory_id': None, 'subject_type': 'raw_model_driver',
                     'model_tag': 'fixture:model', 'model_digest': 'a' * 64, 'configuration': {}},
            policy={'enforcement_level': 'declared', 'assistance_policy': 'closed_book'})
        sid, token = enrollment['session_id'], enrollment['examinee_token']
        engine.begin_module(sid, token, 'm1', 'begin')
        engine.record_answer(sid, token, 'm1', 'q1', 'B', 1, 'answer')
        now[0] += 10_000_000_000
        engine.tick()
        envelope = engine.get_transcript(sid, token)
        self.assertTrue(verify_envelope(envelope, self.signer.public_key_der, executable=OPENSSL))
        self.assertEqual(json.loads(envelope['payload_json'])['accepted_correct'], 1)


if __name__ == '__main__':
    unittest.main()
