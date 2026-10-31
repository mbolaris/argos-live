import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest

from argoslive.proctor import AgentSession, Caller, Cartridge, Proctor, compile_cartridge, open_state
from argoslive.proctor.cartridge import correct_answer
from argoslive.proctor.engine import digest

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / 'runtime/argoslive/data/proctor-practice-composed.json'


class ComposedPracticeTests(unittest.TestCase):
    def test_compiles_and_grades_original_practice_form(self):
        definition = json.loads(DEFINITION.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cartridge.sqlite3'
            compile_cartridge(definition, path)
            cartridge = Cartridge(path)
        self.assertEqual(cartridge.manifest['calibration_status'], 'uncalibrated')
        self.assertEqual(set(cartridge.forms), {'composed-a'})
        self.assertEqual(len(cartridge.items), 8)
        expected = {'c1q1': '840', 'c1q2': 'B', 'c1q3': 'A',
                    'c1q4': '{"name":"argos_evaluate_wait","arguments":{"job_id":"fedcba9876543210fedcba9876543210"}}',
                    'c2q1': '90', 'c2q2': 'C', 'c2q3': 'D', 'c2q4': '35'}
        for item_id, answer in expected.items():
            with self.subTest(item=item_id):
                self.assertTrue(correct_answer(cartridge.items[item_id], answer))
        self.assertFalse(correct_answer(cartridge.items['c1q1'], '720'))
        self.assertFalse(correct_answer(cartridge.items['c2q2'], 'B'))
        self.assertEqual(cartridge.items['c1q4']['domain'], 'tool_call_format')

    def test_two_modules_complete_with_host_observed_tool_call(self):
        class Signer:
            def sign(self, payload):
                return {'algorithm': 'TEST-ONLY', 'sha256': hashlib.sha256(payload).hexdigest()}

        definition = json.loads(DEFINITION.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'cartridge.sqlite3'
            compile_cartridge(definition, path)
            db = open_state(root / 'state.sqlite3')
            try:
                engine = Proctor(Cartridge(path), db,
                    callers={'host': Caller(digest('host-secret'))}, token_secret=secrets.token_bytes(32),
                    boot_id='boot-composed-test', signer=Signer(), clock=lambda: 1_000_000_000)
                subject = {'lineage_id': 'fixture-lineage', 'subject_type': 'deployed_agent_profile',
                           'model_tag': 'fixture:model', 'model_digest': 'a' * 64,
                           'configuration': {'temperature': 0}}
                exam = AgentSession(engine, caller_id='host', caller_token='host-secret',
                    form_id='composed-a', tier='practice', subject=subject,
                    policy={'enforcement_level': 'declared', 'assistance_policy': 'closed_book'})
                self.assertEqual(exam.start('start-composed-test')['state'], 'ACTIVE')
                for item_id, answer in [('c1q1', '840'), ('c1q2', 'B'), ('c1q3', 'A')]:
                    exam.item(item_id)
                    exam.answer(item_id, answer, 'answer-' + item_id)
                exam.item('c1q4')
                exam.host_record_tool_call('c1q4', 'argos_evaluate_wait',
                    {'job_id': 'fedcba9876543210fedcba9876543210'}, 'tool-call-c1q4')
                self.assertEqual(exam.submit('c1', 'submit-composed-c1')['state'], 'ACTIVE')
                self.assertEqual(exam.status()['module_id'], 'c2')
                for item_id, answer in [('c2q1', '90'), ('c2q2', 'C'), ('c2q3', 'D'), ('c2q4', '35')]:
                    exam.item(item_id)
                    exam.answer(item_id, answer, 'answer-' + item_id)
                self.assertEqual(exam.submit('c2', 'submit-composed-c2')['state'], 'COMPLETED')
                payload = json.loads(exam.host_transcript()['payload_json'])
                self.assertEqual((payload['accepted_correct'], payload['total_items']), (8, 8))
                self.assertEqual(len(payload['accepted_answers']), 8)
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
