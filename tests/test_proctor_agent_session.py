import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.proctor import AgentSession, Caller, Cartridge, Proctor, compile_cartridge, open_state
from argoslive.proctor.engine import digest
from argoslive import controller_bridge, workload


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now


class Signer:
    def sign(self, payload):
        return {'algorithm': 'TEST-ONLY', 'sha256': hashlib.sha256(payload).hexdigest()}


class AgentSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        source = json.loads((ROOT / 'tests/fixtures/proctor/fixed.json').read_text())
        self.cart_path = root / 'cartridge.db'
        compile_cartridge(source, self.cart_path)
        self.db = open_state(root / 'state.db')
        self.addCleanup(self.db.close)
        self.clock = Clock()
        self.subject = {'lineage_id': 'model-lineage', 'memory_id': 'model-memory',
            'subject_type': 'deployed_agent_profile', 'model_tag': 'fixture:model',
            'model_digest': 'a' * 64, 'configuration': {'temperature': 0}}
        self.policy = {'enforcement_level': 'declared', 'assistance_policy': 'closed_book'}
        self.engine = Proctor(Cartridge(self.cart_path), self.db,
            callers={'host': Caller(digest('host-secret'))}, token_secret=secrets.token_bytes(32),
            boot_id='boot-test', signer=Signer(), clock=self.clock)

    def session(self, *, tier='assessment', subject=None, policy=None):
        return AgentSession(self.engine, caller_id='host', caller_token='host-secret',
            form_id='fixed-a', tier=tier, subject=subject or self.subject,
            policy=policy or self.policy)

    def test_agent_surface_is_host_preselected_and_does_not_expose_score_or_keys(self):
        exam = self.session(tier='held_out')
        started = exam.start('host-start-0001')
        self.assertEqual(started['state'], 'ACTIVE')
        self.assertNotIn('session_id', started)
        self.assertNotIn('examinee_token', started)
        self.assertNotIn('accepted_correct', started)

        item = exam.item('q1')
        self.assertEqual(item['prompt'], 'Which number is even?')
        self.assertNotIn('correct', item)
        self.assertNotIn('routes', item)
        self.assertEqual(exam.answer('q1', 'B', 'answer-call-0001'),
                         {'status': 'accepted', 'revision': 1})
        status = exam.submit('m1', 'submit-call-0001')
        self.assertEqual(status['state'], 'BREAK')
        self.assertNotIn('accepted_correct', status)
        self.assertNotIn('score', status)
        self.clock.now += 500_000_000
        self.assertEqual(exam.continue_module('continue-call-0001')['state'], 'ACTIVE')

        with self.assertRaises(AttributeError):
            exam.transcript()

    def test_host_conditions_are_snapshotted_and_not_agent_mutable(self):
        subject = dict(self.subject, configuration={'temperature': 0})
        policy = dict(self.policy)
        exam = self.session(tier='assessment', subject=subject, policy=policy)
        subject['configuration']['temperature'] = 1
        policy['assistance_policy'] = 'reference_aided'
        exam.start('host-start-0002')
        saved = self.db.execute('SELECT subject_json,policy_json,tier FROM sessions').fetchone()
        self.assertIn('"temperature":0', saved['subject_json'])
        self.assertIn('"assistance_policy":"closed_book"', saved['policy_json'])
        self.assertEqual(saved['tier'], 'assessment')

    def test_exam_tier_and_form_cannot_be_selected_through_agent_methods(self):
        exam = self.session()
        with self.assertRaises(TypeError):
            exam.start('host-start-0003', tier='held_out')
        with self.assertRaises(TypeError):
            exam.start('host-start-0004', form_id='other-form')

    def test_adapter_refuses_aid_policy_without_host_aid_workers(self):
        reference_policy = {'enforcement_level': 'declared', 'assistance_policy': 'reference_aided'}
        with self.assertRaisesRegex(ValueError, 'closed-book'):
            self.session(policy=reference_policy)

    def test_agent_cannot_submit_a_nonactive_or_hidden_module(self):
        exam = self.session()
        exam.start('host-start-submit-check')
        with self.assertRaisesRegex(ValueError, 'server-selected active module'):
            exam.submit('m2', 'wrong-module-submit')

    def test_practice_feedback_supports_learning_but_assessments_withhold_scores(self):
        exam = self.session(tier='practice')
        exam.start('practice-start')
        exam.answer('q1', 'B', 'practice-q1')
        exam.answer('q2', '4', 'practice-q2')
        exam.submit('m1', 'practice-submit-1')
        self.clock.now += 500_000_000
        exam.continue_module('practice-continue')
        exam.answer('q3', 'A', 'practice-q3')
        exam.answer('q4', '-1.25', 'practice-q4')
        exam.submit('m2', 'practice-submit-2')
        feedback = exam.practice_feedback()
        self.assertEqual((feedback['correct'], feedback['total'], feedback['unanswered']), (4, 4, 0))
        self.assertEqual(feedback['domains']['reasoning'], {'correct': 2, 'total': 2, 'answered': 2})
        held_out = self.session(tier='held_out', subject=dict(self.subject,
            lineage_id='heldout-lineage', memory_id='heldout-memory'))
        held_out.start('heldout-no-feedback')
        with self.assertRaisesRegex(ValueError, 'withheld'):
            held_out.practice_feedback()

    def test_agent_answer_cannot_choose_revision_or_rewrite_condition(self):
        exam = self.session()
        exam.start('host-start-0005')
        self.assertEqual(exam.answer('q1', 'B', 'answer-call-0005'),
                         {'status': 'accepted', 'revision': 1})
        self.assertEqual(exam.answer('q1', 'B', 'answer-call-retry'),
                         {'status': 'accepted', 'revision': 1, 'idempotent_replay': True})
        with self.assertRaises(TypeError):
            exam.answer('q1', 'B', 'answer-call-0005', revision=99)
        self.assertEqual(exam.status()['answer_revisions'], {'q1': 1})
        self.assertEqual(exam.answer('q1', 'A', 'answer-correction')['revision'], 2)

    def test_dedicated_bridge_admits_only_scoped_exam_tools_and_keeps_signed_result_host_side(self):
        exam = self.session(tier='held_out')
        with workload.reserve(Path(self.tmp.name), 'proctor') as parent:
            bridge = controller_bridge.Bridge(Path(self.tmp.name), parent,
                session_key='agent:main:proctor-session', exam_session=exam)
            begin = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'exam-run',
                'session_id': 'exam-sdk-session', 'session_key': 'agent:main:proctor-session',
                'trigger': 'user'}
            turn = bridge.dispatch(begin)
            host = {'auth': bridge.secret, 'run_id': 'exam-run', 'turn_token': turn['turn_token'], 'op': 'tool'}

            def call(call_id, kind, params=None):
                value = bridge.dispatch({**host, 'call_id': call_id, 'kind': kind, 'params': params or {}})
                return value['value']

            start = call('start-exam', 'proctor_start')
            self.assertNotIn('session_id', start)
            with self.assertRaises(ValueError):
                call('try-evaluate', 'evaluation', {'suite': 'quick'})
            item = call('get-q1', 'proctor_item', {'item_id': 'q1'})
            self.assertNotIn('correct', item)
            self.assertEqual(call('answer-q1', 'proctor_answer', {'item_id': 'q1', 'answer': 'B'})['status'], 'accepted')
            call('answer-q2', 'proctor_answer', {'item_id': 'q2', 'answer': '4'})
            self.assertEqual(call('submit-one', 'proctor_submit', {'module_id': 'm1'})['state'], 'BREAK')
            self.clock.now += 500_000_000
            self.assertEqual(call('continue', 'proctor_continue')['state'], 'ACTIVE')
            call('answer-q3', 'proctor_answer', {'item_id': 'q3', 'answer': 'A'})
            call('answer-q4', 'proctor_answer', {'item_id': 'q4', 'answer': '-1.25'})
            self.assertEqual(call('submit-two', 'proctor_submit', {'module_id': 'm2'})['state'], 'COMPLETED')
            with self.assertRaisesRegex(ValueError, 'withheld'):
                call('heldout-feedback', 'proctor_feedback')

            class Worker:
                @staticmethod
                def poll():
                    return 0

            bridge.worker = Worker()
            bridge.verified = True
            bridge._complete()
            envelope = exam.host_transcript()
            self.assertEqual(parent.record['result_id'], exam.session_id.removeprefix('sess_'))
            payload = json.loads(envelope['payload_json'])
            self.assertEqual(payload['accepted_correct'], 4)
            self.assertEqual(payload['exposure_tier'], 'held_out')
            with self.assertRaisesRegex(ValueError, 'withheld'):
                exam.practice_feedback()
            self.assertNotIn('accepted_correct', json.dumps(bridge.outcomes))
            self.assertNotIn('payload_json', json.dumps(bridge.outcomes))

    def test_incomplete_exam_cannot_release_its_proctor_reservation(self):
        exam = self.session(tier='held_out')
        home = Path(self.tmp.name)
        with workload.reserve(home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(home, parent,
                session_key='agent:main:proctor-session', exam_session=exam)
            request = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'incomplete-run',
                'session_id': 'incomplete-sdk-session', 'session_key': 'agent:main:proctor-session',
                'trigger': 'user'}
            bridge.dispatch(request)
            exam.start('host-start-incomplete')

            class Worker:
                @staticmethod
                def poll():
                    return 0

            bridge.worker = Worker()
            bridge.verified = True
            with self.assertRaises(workload.Busy):
                bridge._complete()
            self.assertTrue(bridge.uncertain)
        reservation = json.loads((home / '.local/state/argos-live/workload/reservation.json').read_text())
        self.assertEqual(reservation['kind'], 'proctor')
        self.assertEqual(reservation['state'], 'quarantined')
        with self.assertRaises(workload.Busy):
            with workload.reserve(home, 'evaluation'):
                self.fail('Unfinished exam released exclusive admission')


if __name__ == '__main__':
    unittest.main()
