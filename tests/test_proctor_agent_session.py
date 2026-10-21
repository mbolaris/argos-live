import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.proctor import AgentSession, Caller, Cartridge, Proctor, compile_cartridge, open_state
from argoslive.proctor.engine import digest
from argoslive import controller_bridge, workload, proctor_service


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
                         {'status': 'accepted', 'revision': 1, 'next_step':
                          {'tool': 'argos_proctor_item', 'arguments': {'item_id': 'q2'}}})
        status = exam.submit('m1', 'submit-call-0001')
        self.assertEqual(status['state'], 'BREAK')
        self.assertNotIn('accepted_correct', status)
        self.assertNotIn('score', status)
        self.clock.now += 500_000_000
        self.assertEqual(exam.continue_module('continue-call-0001')['state'], 'ACTIVE')

        with self.assertRaises(AttributeError):
            exam.transcript()

    def test_host_sdk_thread_can_use_engine_created_on_setup_thread(self):
        exam = self.session()
        result = []
        failures = []
        def start():
            try:
                result.append(exam.start('host-start-cross-thread'))
            except BaseException as error:
                failures.append(error)
        worker = threading.Thread(target=start)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(result[0]['state'], 'ACTIVE')
        self.assertEqual(exam.status()['state'], 'ACTIVE')

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
        exam.answer('q2', '3', 'practice-q2')
        exam.submit('m1', 'practice-submit-1')
        self.clock.now += 500_000_000
        exam.continue_module('practice-continue')
        exam.answer('q3', 'A', 'practice-q3')
        exam.answer('q4', '-1.25', 'practice-q4')
        exam.submit('m2', 'practice-submit-2')
        feedback = exam.practice_feedback()
        self.assertEqual((feedback['correct'], feedback['total'], feedback['unanswered']), (3, 4, 0))
        self.assertEqual(feedback['domains']['reasoning'], {'correct': 2, 'total': 2, 'answered': 2})
        items = {item['item_id']: item for item in feedback['items']}
        self.assertEqual(items['q2'], {'item_id': 'q2', 'domain': 'math', 'submitted_answer': '3',
                                       'is_correct': False, 'expected_answer': '4'})
        held_out = self.session(tier='held_out', subject=dict(self.subject,
            lineage_id='heldout-lineage', memory_id='heldout-memory'))
        held_out.start('heldout-no-feedback')
        with self.assertRaisesRegex(ValueError, 'withheld'):
            held_out.practice_feedback()

    def test_host_abandon_saves_signed_partial_practice_and_invalidates_remaining_modules(self):
        exam = self.session(tier='practice')
        exam.start('practice-abandon-start')
        exam.answer('q1', 'B', 'practice-abandon-answer')
        status = exam.host_abandon()
        self.assertEqual((status['state'], status['reason']), ('ABANDONED', 'HOST_TURN_ENDED'))
        feedback = exam.practice_feedback()
        self.assertEqual((feedback['state'], feedback['correct'], feedback['total']), ('ABANDONED', 1, 2))
        self.assertEqual(feedback['unanswered'], 1)
        envelope = exam.host_transcript()
        payload = json.loads(envelope['payload_json'])
        self.assertEqual((payload['outcome'], payload['reason']), ('ABANDONED', 'HOST_TURN_ENDED'))
        self.assertTrue(all(module['state'] == 'INVALIDATED' for module in payload['modules']))
        again = exam.host_abandon()
        self.assertEqual((again['state'], again['reason']), ('ABANDONED', 'HOST_TURN_ENDED'))

    def test_agent_answer_cannot_choose_revision_or_rewrite_condition(self):
        exam = self.session()
        exam.start('host-start-0005')
        self.assertEqual(exam.answer('q1', 'B', 'answer-call-0005'),
                         {'status': 'accepted', 'revision': 1, 'next_step':
                          {'tool': 'argos_proctor_item', 'arguments': {'item_id': 'q2'}}})
        self.assertEqual(exam.answer('q1', 'B', 'answer-call-retry'),
                         {'status': 'accepted', 'revision': 1, 'idempotent_replay': True,
                          'next_step': {'tool': 'argos_proctor_item', 'arguments': {'item_id': 'q2'}}})
        with self.assertRaises(TypeError):
            exam.answer('q1', 'B', 'answer-call-0005', revision=99)
        self.assertEqual(exam.status()['answer_revisions'], {'q1': 1})
        self.assertEqual(exam.answer('q1', 'A', 'answer-correction')['revision'], 2)

    def test_navigation_completes_practice_without_correctness_hints(self):
        exam = self.session(tier='practice')
        status = exam.start('navigation-start')
        for number, module in enumerate(('m1', 'm2')):
            for item_id in (('q1', 'q2'), ('q3', 'q4'))[number]:
                step = status['next_step']
                self.assertEqual(step, {'tool': 'argos_proctor_item',
                                        'arguments': {'item_id': item_id}})
                item = exam.item(**step['arguments'])
                self.assertNotIn('correct', item)
                # Wrong answers advance navigation exactly like correct answers.
                wrong = {'q1': 'A', 'q2': '3', 'q3': 'B', 'q4': '0'}[item_id]
                status = exam.answer(item_id, wrong, 'navigation-' + item_id)
                self.assertNotIn('correct', status)
                self.assertNotIn('score', status)
            self.assertEqual(status['next_step'], {'tool': 'argos_proctor_submit',
                                                   'arguments': {'module_id': module}})
            status = exam.submit(**status['next_step']['arguments'],
                                 operation_id='navigation-submit-' + module)
            if number == 0:
                self.assertEqual(status['next_step']['tool'], 'argos_proctor_status')
                with self.assertRaises(ValueError):
                    exam.practice_feedback()
                self.clock.now += 500_000_000
                self.engine.tick()
                status = exam.status()
                self.assertEqual(status['state'], 'ACTIVE')
        self.assertEqual(status['state'], 'COMPLETED')
        self.assertEqual(status['next_step'], {'tool': 'argos_proctor_feedback', 'arguments': {}})
        self.assertEqual(exam.practice_feedback()['correct'], 0)

    def test_navigation_never_offers_feedback_for_held_out_or_abandoned_exam(self):
        exam = self.session(tier='held_out')
        exam.start('navigation-heldout')
        self.assertIsNone(exam._public_status({'state': 'COMPLETED'})['next_step'])
        self.assertIsNone(exam.host_abandon()['next_step'])

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

    def test_drained_practice_saves_abandoned_transcript_before_release(self):
        exam = self.session(tier='practice')
        home = Path(self.tmp.name)
        with workload.reserve(home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(home, parent,
                session_key='agent:main:proctor-session', exam_session=exam)
            bridge.dispatch({'auth': bridge.secret, 'op': 'begin', 'run_id': 'partial-run',
                'session_id': 'partial-sdk-session', 'session_key': 'agent:main:proctor-session',
                'trigger': 'user'})
            exam.start('host-start-partial')
            exam.answer('q1', 'B', 'partial-answer')

            class Worker:
                @staticmethod
                def poll():
                    return 0

            bridge.worker = Worker()
            bridge.verified = True
            bridge._complete()
            payload = json.loads(exam.host_transcript()['payload_json'])
            self.assertEqual(payload['outcome'], 'ABANDONED')
            self.assertEqual(parent.record['result_id'], exam.session_id.removeprefix('sess_'))
            self.assertTrue(parent.drained)
        reservation = json.loads((home / '.local/state/argos-live/workload/reservation.json').read_text())
        self.assertEqual(reservation['state'], 'released')

    def test_practice_continuation_keeps_reservation_and_fences_old_turn(self):
        exam = self.session(tier='practice')
        home = Path(self.tmp.name)
        with workload.reserve(home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(home, parent, session_key='agent:main:first', exam_session=exam)
            request = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'first-run',
                'session_id': 'first-session', 'session_key': 'agent:main:first', 'trigger': 'user'}
            token = bridge.dispatch(request)['turn_token']
            exam.start('first-start')
            class Worker:
                def poll(self): return 0
            bridge.worker = Worker()
            with self.assertRaises(workload.Busy):
                bridge.next_practice_turn('agent:main:second')
            bridge.verified = True
            bridge.uncertain = True
            with self.assertRaises(workload.Busy):
                bridge.next_practice_turn('agent:main:second')
            bridge.uncertain = False
            bridge.tool_lock.acquire()
            with self.assertRaises(workload.Busy):
                bridge.next_practice_turn('agent:main:second')
            bridge.tool_lock.release()
            bridge.last_stdout, bridge.session_id = 'fixture-worker', 'first-session'
            self.assertFalse(bridge.submit_answered_practice_module())
            exam.answer('q1', 'A', 'wrong-a1')
            self.assertFalse(bridge.submit_answered_practice_module())
            exam.answer('q2', '3', 'wrong-a2')
            self.assertTrue(bridge.submit_answered_practice_module())
            self.assertEqual(exam.status()['state'], 'BREAK')
            self.assertFalse(bridge.submit_answered_practice_module())
            bridge.next_practice_turn('agent:main:second')
            self.assertFalse(parent.drained)
            self.assertEqual(exam.status()['state'], 'BREAK')
            with self.assertRaises(workload.Busy):
                with workload.reserve(home, 'evaluation'):
                    self.fail('A second workload must not be admitted between practice turns')
            with self.assertRaises(workload.Busy):
                bridge.dispatch({'auth': bridge.secret, 'op': 'tool', 'run_id': 'first-run',
                    'turn_token': token, 'call_id': 'stale-call', 'kind': 'proctor_status', 'params': {}})
            bridge.dispatch({**request, 'run_id': 'second-run', 'session_id': 'second-session',
                             'session_key': 'agent:main:second'})
            bridge.worker, bridge.verified = Worker(), True
            bridge._complete()
            self.assertEqual(exam.status()['state'], 'ABANDONED')
            self.assertTrue(parent.drained)

    def test_host_navigation_records_agent_answers_across_short_turns(self):
        exam = self.session(tier='practice')
        messages = []
        clock = self.clock
        actions = [lambda: exam.start('start'),
            lambda: exam.answer('q1', 'A', 'a1'), lambda: exam.answer('q2', '3', 'a2'),
            lambda: exam.answer('q3', 'B', 'a3'),
            lambda: exam.answer('q4', '0', 'a4')]
        class ShortTurns:
            completed = False
            def launch(self, executable, message, **kwargs): messages.append(message)
            def finish(self, **kwargs):
                self_test.assertFalse(kwargs['finalize'])
                actions.pop(0)()
                return {'payloads': [{'text': 'The exam is complete; all answers are correct.'}]}, ''
            def next_practice_turn(self, key): pass
            def submit_answered_practice_module(self):
                status = exam.status()
                if status['state'] == 'ACTIVE' and all(status['answer_revisions'].get(i) for i in status['item_ids']):
                    exam.submit(status['module_id'], 'host-submit-' + status['module_id'])
            def _complete(self): self.completed = True
        self_test = self
        bridge = ShortTurns()
        with patch.object(proctor_service.time, 'sleep',
                          side_effect=lambda seconds: setattr(clock, 'now', clock.now + int(seconds * 10**9))):
            result = proctor_service.run_practice_turns(bridge, exam, 'fixture', 'fixture-config')
        self.assertTrue(bridge.completed)
        self.assertEqual(result['host_turns'], 5)
        self.assertIn('argos_proctor_item', messages[1])
        self.assertIn('"item_id": "q3"', messages[3])
        self.assertNotIn('expected_answer', messages[3])
        self.assertIn('Do not write a tool call as ordinary text', messages[3])
        self.assertTrue(all('expected_answer' not in message for message in messages))
        self.assertEqual(exam.practice_feedback()['correct'], 0)
        self.assertEqual(exam.practice_feedback()['unanswered'], 0)

    def test_host_navigation_stops_after_two_turns_without_progress(self):
        exam = self.session(tier='practice')
        class StalledTurns:
            count = 0
            def launch(self, *args, **kwargs): pass
            def finish(self, **kwargs):
                if not self.count: exam.start('start-stalled')
                self.count += 1
                return {'payloads': [{'text': 'The exam is complete; all answers are correct.'}]}, ''
            def next_practice_turn(self, key): pass
            def submit_answered_practice_module(self): pass
            def _complete(self): exam.host_abandon()
        result = proctor_service.run_practice_turns(StalledTurns(), exam, 'fixture', 'fixture-config')
        self.assertEqual(result['host_turns'], 3)
        self.assertEqual(exam.status()['state'], 'ABANDONED')

    def test_clean_unstarted_practice_records_zero_item_abandonment(self):
        exam = self.session(tier='practice')
        home = Path(self.tmp.name)
        with workload.reserve(home, 'proctor') as parent:
            bridge = controller_bridge.Bridge(home, parent,
                session_key='agent:main:proctor-session', exam_session=exam)
            bridge.dispatch({'auth': bridge.secret, 'op': 'begin', 'run_id': 'no-tools-run',
                'session_id': 'no-tools-session', 'session_key': 'agent:main:proctor-session',
                'trigger': 'user'})
            class Worker:
                @staticmethod
                def poll():
                    return 0
            bridge.worker = Worker()
            bridge.verified = True
            bridge._complete()
            payload = json.loads(exam.host_transcript()['payload_json'])
            self.assertEqual(payload['outcome'], 'ABANDONED')
            self.assertEqual(payload['total_items'], 0)
            self.assertEqual(exam.practice_feedback()['total'], 0)
            self.assertTrue(parent.drained)
            self.assertTrue(all(row['started_ns'] is None for row in payload['modules']))

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
