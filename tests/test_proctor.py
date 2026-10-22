import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.proctor import Caller, Cartridge, Proctor, ProctorError, compile_cartridge, open_state
from argoslive.proctor.cartridge import json_text, validate
from argoslive.proctor.engine import MS, digest, transaction

FIXTURE = ROOT / 'tests/fixtures/proctor/fixed.json'


class Clock:
    def __init__(self):
        self.now = MS

    def __call__(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds * MS


class FixtureSigner:
    """Explicitly test-only. Production signing is tested separately against OpenSSL."""
    def __init__(self, connection):
        self.connection = connection
        self.calls = 0

    def sign(self, payload):
        if self.connection.in_transaction:
            raise AssertionError('Signing held the database writer lock')
        self.calls += 1
        return {'algorithm': 'TEST-ONLY', 'payload_sha256': hashlib.sha256(payload).hexdigest()}


class ProctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.definition = json.loads(FIXTURE.read_text())
        self.cart_path = self.root / 'fixture.exam.db'
        compile_cartridge(self.definition, self.cart_path)
        self.cart = Cartridge(self.cart_path)
        self.state_path = self.root / 'state.db'
        self.db = open_state(self.state_path)
        self.addCleanup(self.db.close)
        self.clock = Clock()
        self.secret = secrets.token_bytes(32)
        self.callers = {'host': Caller(digest('host-secret'))}
        self.signer = FixtureSigner(self.db)
        self.engine = self.new_engine(self.db)
        self.subject = {'lineage_id': 'agent-a', 'memory_id': 'memory-a', 'subject_type': 'raw_model_driver',
                        'model_tag': 'fixture:model', 'model_digest': 'a' * 64,
                        'configuration': {'prompt': 'Original fixture instructions', 'temperature': 0}}
        self.policy = {'enforcement_level': 'declared', 'assistance_policy': 'reference_aided'}

    def new_engine(self, connection, boot='boot-a', signer=None):
        return Proctor(self.cart, connection, callers=self.callers, token_secret=self.secret,
                       boot_id=boot, signer=signer or FixtureSigner(connection), clock=self.clock)

    def enroll(self, key='enroll', tier='assessment', subject=None, engine=None, policy=None):
        return (engine or self.engine).enroll('host', 'host-secret', key, form_id='fixed-a', tier=tier,
                                            subject=subject or self.subject, policy=policy or self.policy)

    def begin(self, enrollment=None):
        e = enrollment or self.enroll()
        self.engine.begin_module(e['session_id'], e['examinee_token'], 'm1', 'begin')
        return e

    def answer(self, e, answer='B', revision=1, key='answer', item='q1', module='m1'):
        return self.engine.record_answer(e['session_id'], e['examinee_token'], module, item, answer, revision, key)

    def assert_error(self, code, call):
        with self.assertRaises(ProctorError) as exc:
            call()
        self.assertEqual(exc.exception.code, code)

    def test_enrollment_and_answer_retry_preserve_identity_and_one_write(self):
        e = self.enroll()
        retry = self.enroll()
        self.assertEqual(e['session_id'], retry['session_id'])
        self.assertEqual(e['examinee_token'], retry['examinee_token'])
        self.assertTrue(retry['idempotent_replay'])
        stored = self.db.execute('SELECT response_json FROM operations').fetchone()[0]
        self.assertNotIn(e['examinee_token'], stored)
        self.begin(e)
        self.answer(e)
        self.clock.advance(10000)
        self.assertTrue(self.answer(e)['idempotent_replay'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT revision FROM answers').fetchone()[0], 1)

    def test_malformed_and_stale_rejections_commit_and_replay(self):
        e = self.begin()
        for _ in range(2):
            self.assert_error('INVALID_ANSWER_FORMAT', lambda: self.answer(e, 'B) four', key='malformed'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT state FROM operations WHERE operation_key='malformed'").fetchone()[0], 'COMPLETED')
        self.answer(e, key='corrected')
        for _ in range(2):
            self.assert_error('STALE_REVISION', lambda: self.answer(e, revision=1, key='stale'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 3)
        self.assertEqual(self.db.execute('SELECT revision FROM answers').fetchone()[0], 1)

    def test_idempotency_conflict_does_not_change_answer(self):
        e = self.begin()
        self.answer(e)
        self.assert_error('IDEMPOTENCY_CONFLICT', lambda: self.answer(e, 'A'))
        self.assertEqual(self.db.execute('SELECT answer FROM answers').fetchone()[0], 'B')

    def test_authentication_precedes_replay_and_deadline_work(self):
        e = self.begin()
        self.answer(e)
        self.clock.advance(10000)
        self.assert_error('UNAUTHORIZED_SESSION', lambda: self.engine.record_answer(e['session_id'], 'wrong', 'm1', 'q1', 'B', 1, 'answer'))
        self.assertEqual(self.db.execute('SELECT state FROM sessions').fetchone()[0], 'ACTIVE')
        self.assert_error('UNAUTHORIZED_CALLER', lambda: self.engine.enroll('host', 'wrong', 'enroll', form_id='fixed-a',
                          tier='assessment', subject=self.subject, policy=self.policy))

    def test_boundary_expiration_rejects_without_late_write(self):
        e = self.begin()
        self.clock.advance(1000)
        for _ in range(2):
            self.assert_error('MODULE_NOT_ACTIVE', lambda: self.answer(e))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM answers').fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT state FROM session_modules WHERE module_id='m1'").fetchone()[0], 'EXPIRED')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)

    def test_delayed_tick_cascades_through_break_and_final_module(self):
        e = self.begin()
        self.answer(e)
        self.clock.advance(10000)
        self.engine.tick()
        status = self.engine.status(e['session_id'], e['examinee_token'])
        self.assertEqual(status['state'], 'COMPLETED')
        modules = self.db.execute('SELECT * FROM session_modules ORDER BY started_ns').fetchall()
        self.assertEqual(modules[1]['started_ns'], modules[0]['deadline_ns'] + 500 * MS)
        self.assertEqual(modules[1]['deadline_ns'], modules[1]['started_ns'] + 1000 * MS)
        transcript = json.loads(self.engine.get_transcript(e['session_id'], e['examinee_token'])['payload_json'])
        self.assertEqual((transcript['accepted_correct'], transcript['total_items'], transcript['unanswered']), (1, 4, 3))
        self.assertIsNone(transcript['scaled_score'])
        self.assertIsNone(transcript['discipline']['client_rejected_tool_calls'])

    def test_late_manual_begin_preserves_auto_started_deadline(self):
        e = self.begin()
        self.clock.advance(1700)
        result = self.engine.begin_module(e['session_id'], e['examinee_token'], 'm2', 'begin-two')
        self.assertEqual(result['deadline_ns'], MS + 2500 * MS)
        self.assertLess(result['deadline_ns'], self.clock() + 1000 * MS)

    def test_submit_is_idempotent_and_numeric_answers_use_exact_decimal_or_fraction(self):
        e = self.begin()
        self.answer(e)
        self.answer(e, '04.00', item='q2', key='numeric')
        self.engine.submit_module(e['session_id'], e['examinee_token'], 'm1', 'submit-one')
        self.assertTrue(self.engine.submit_module(e['session_id'], e['examinee_token'], 'm1', 'submit-one')['idempotent_replay'])
        self.engine.begin_module(e['session_id'], e['examinee_token'], 'm2', 'begin-two')
        self.answer(e, 'A', item='q3', module='m2', key='third')
        self.answer(e, '-5/4', item='q4', module='m2', key='fourth')
        self.engine.submit_module(e['session_id'], e['examinee_token'], 'm2', 'submit-two')
        self.engine.issue_transcripts()
        t = json.loads(self.engine.get_transcript(e['session_id'], e['examinee_token'])['payload_json'])
        self.assertEqual(t['accepted_correct'], 4)
        self.assertEqual(t['unanswered'], 0)
        self.assertEqual(t['grader_version'], 'choice-numeric/2')

    def test_numeric_fraction_is_exact_and_rejects_expressions_and_zero_denominator(self):
        e = self.begin()
        for index, invalid in enumerate(('-5 / 0', '-5/4+0', 'answer -5/4', '1,25')):
            self.assert_error('INVALID_ANSWER_FORMAT', lambda value=invalid, number=index:
                self.answer(e, value, item='q2', key='invalid-' + str(number)))

    def test_get_item_is_pure_and_never_releases_keys(self):
        e = self.enroll()
        self.assert_error('MODULE_NOT_ACTIVE', lambda: self.engine.get_item(e['session_id'], e['examinee_token'], 'm1', 'q1'))
        self.begin(e)
        before = self.db.total_changes
        item = self.engine.get_item(e['session_id'], e['examinee_token'], 'm1', 'q1')
        self.assertNotIn('correct', item)
        self.assertEqual(set(item['choices']), set('ABCD'))
        item['choices']['B'] = 'mutated'
        self.assertEqual(self.engine.get_item(e['session_id'], e['examinee_token'], 'm1', 'q1')['choices']['B'], '4')
        self.assertEqual(before, self.db.total_changes)
        self.assert_error('MODULE_NOT_ACTIVE', lambda: self.engine.get_item(e['session_id'], e['examinee_token'], 'm2', 'q3'))
        self.clock.advance(1000)
        self.assert_error('MODULE_DEADLINE_EXPIRED', lambda: self.engine.get_item(e['session_id'], e['examinee_token'], 'm1', 'q1'))

    def test_aid_denies_before_begin_and_wrong_aid(self):
        e = self.enroll()
        reserve = lambda name, key: self.engine.reserve_aid(e['session_id'], e['examinee_token'], 'm1', name, {'expression': '2+2'}, key)
        self.assert_error('MODULE_NOT_ACTIVE', lambda: reserve('calculator', 'before'))
        self.begin(e)
        self.assert_error('AID_NOT_ALLOWED', lambda: reserve('sandbox_test', 'wrong'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM aids').fetchone()[0], 0)
        a = reserve('calculator', 'allowed')
        self.assertEqual(reserve('calculator', 'allowed')['aid_id'], a['aid_id'])
        self.assert_error('UNAUTHORIZED_CALLER', lambda: self.engine.complete_aid('host', 'wrong', a['aid_id'], {'value': '4'}))
        self.engine.complete_aid('host', 'host-secret', a['aid_id'], {'value': '4'})
        self.engine.complete_aid('host', 'host-secret', a['aid_id'], {'value': '4'})
        self.assert_error('AID_COMPLETION_CONFLICT', lambda: self.engine.complete_aid('host', 'host-secret', a['aid_id'], {'value': '5'}))
        self.assertEqual(self.engine.aid_status(e['session_id'], e['examinee_token'], a['aid_id'])['output'], {'value': '4'})

    def test_closed_book_denies_declared_aids_and_late_completion_is_discarded(self):
        e = self.enroll(policy=dict(self.policy, assistance_policy='closed_book'))
        self.begin(e)
        self.assert_error('AID_NOT_ALLOWED', lambda: self.engine.reserve_aid(e['session_id'], e['examinee_token'], 'm1', 'calculator', {}, 'aid'))
        e2 = self.begin(self.enroll('second'))
        a = self.engine.reserve_aid(e2['session_id'], e2['examinee_token'], 'm1', 'calculator', {}, 'aid')
        self.clock.advance(1000)
        self.assert_error('AID_NO_LONGER_ACTIVE', lambda: self.engine.complete_aid('host', 'host-secret', a['aid_id'], {'value': 4}))
        self.assertEqual(self.db.execute('SELECT state,output_json FROM aids').fetchone()[:], ('DISCARDED', None))

    def test_restart_invalidates_sessions_and_running_aids(self):
        e = self.begin()
        a = self.engine.reserve_aid(e['session_id'], e['examinee_token'], 'm1', 'calculator', {}, 'aid')
        restarted = self.new_engine(self.db)
        # Creating a worker must never run global recovery.
        self.assertEqual(restarted.status(e['session_id'], e['examinee_token'])['state'], 'ACTIVE')
        restarted.recover()
        self.assertEqual(restarted.status(e['session_id'], e['examinee_token'])['reason'], 'DAEMON_RESTART')
        self.assertEqual(self.db.execute('SELECT state FROM aids WHERE aid_id=?', (a['aid_id'],)).fetchone()[0], 'UNCERTAIN')
        self.assert_error('MODULE_NOT_ACTIVE', lambda: self.answer(e, key='after-restart'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM transcripts').fetchone()[0], 1)

    def test_reboot_and_recovery_are_idempotent(self):
        e = self.begin()
        restarted = self.new_engine(self.db, boot='boot-b')
        restarted.recover()
        restarted.recover()
        self.assertEqual(restarted.status(e['session_id'], e['examinee_token'])['reason'], 'SYSTEM_REBOOT')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM transcripts').fetchone()[0], 1)

    def test_reservations_are_not_exposures_and_abandonment_releases_reservation(self):
        e = self.enroll(tier='held_out')
        self.assert_error('HELD_OUT_EXPOSURE_OR_RESERVATION', lambda: self.enroll('blocked', subject=dict(self.subject, lineage_id='other')))
        self.clock.advance(60000)
        e2 = self.enroll('new', tier='held_out')
        self.assertEqual(e2['prior_lineage_exposures'], 0)
        self.assertEqual(e2['prior_memory_exposures'], 0)
        self.assertEqual(self.db.execute('SELECT questions_released FROM exposures WHERE session_id=?', (e['session_id'],)).fetchone()[0], 0)

    def test_exposure_survives_prompt_edit_memory_reset_and_cartridge_rebuild(self):
        self.begin()
        changed = dict(self.subject, memory_id='fresh', configuration={'prompt': 'new'})
        self.assert_error('HELD_OUT_EXPOSURE_OR_RESERVATION', lambda: self.enroll('retake', tier='held_out', subject=changed))
        shared = dict(self.subject, lineage_id='other')
        e = self.enroll('shared', subject=shared)
        self.assertEqual((e['prior_lineage_exposures'], e['prior_memory_exposures']), (0, 1))
        changed_definition = copy.deepcopy(self.definition)
        changed_definition['manifest']['version'] = '1.0.1'
        path = self.root / 'rebuilt.db'
        compile_cartridge(changed_definition, path)
        rebuilt = self.new_engine(self.db)
        rebuilt.cart = Cartridge(path)
        self.assert_error('HELD_OUT_EXPOSURE_OR_RESERVATION', lambda: self.enroll('rebuilt', tier='held_out', subject=changed, engine=rebuilt))

    def test_empty_memory_does_not_create_shared_dummy_identity(self):
        self.begin(self.enroll(subject=dict(self.subject, memory_id=None)))
        e = self.enroll('other', tier='held_out', subject=dict(self.subject, lineage_id='unrelated', memory_id=None))
        self.assertEqual(e['prior_memory_exposures'], 0)

    def test_transcripts_and_audit_are_immutable_and_signing_is_outside_lock(self):
        e = self.begin()
        self.answer(e)
        self.clock.advance(10000)
        self.engine.tick()
        saved = self.engine.get_transcript(e['session_id'], e['examinee_token'])
        self.engine.issue_transcripts()
        self.assertEqual(saved, self.engine.get_transcript(e['session_id'], e['examinee_token']))
        for statement in ('DELETE FROM attempts', "UPDATE attempts SET answer='A'", 'DELETE FROM exposures',
                          'UPDATE exposures SET questions_released=0', 'UPDATE exposures SET memory_id=NULL',
                          'DELETE FROM transcripts', "UPDATE transcripts SET envelope_json='{}'", 'DELETE FROM transcript_payloads'):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(statement)

    def test_signing_failure_can_retry_without_regrading(self):
        e = self.begin()
        self.clock.advance(10000)
        class BrokenSigner:
            def sign(self, payload):
                raise ValueError('fixture signing failure')
        self.engine.signer = BrokenSigner()
        with self.assertRaises(ValueError):
            self.engine.tick()
        self.assertEqual(self.engine.status(e['session_id'], e['examinee_token'])['state'], 'COMPLETED')
        self.assert_error('TRANSCRIPT_NOT_ISSUED', lambda: self.engine.get_transcript(e['session_id'], e['examinee_token']))
        payload = self.db.execute('SELECT payload_json FROM transcript_payloads').fetchone()[0]
        self.engine.signer = self.signer
        self.engine.tick()
        self.assertEqual(self.engine.get_transcript(e['session_id'], e['examinee_token'])['payload_json'], payload)

    def test_file_backed_parallel_held_out_enrollment(self):
        barrier, results, failures = threading.Barrier(2), [], []
        def worker(index):
            conn = None
            try:
                conn = open_state(self.state_path)
                engine = self.new_engine(conn)
                barrier.wait(timeout=10)
                try:
                    results.append(self.enroll('parallel-' + str(index), tier='held_out', engine=engine,
                                               subject=dict(self.subject, lineage_id='lineage-' + str(index))))
                except ProctorError as exc:
                    results.append(exc.code)
            except BaseException as exc:
                failures.append(repr(exc))
            finally:
                if conn is not None:
                    conn.close()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(failures, [])
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn('HELD_OUT_EXPOSURE_OR_RESERVATION', results)

    def test_writer_contention_samples_clock_after_lock_and_cannot_write_closed_module(self):
        e = self.begin()
        entered, finished = threading.Event(), threading.Event()
        failures = []
        def worker():
            conn = open_state(self.state_path)
            engine = self.new_engine(conn)
            conn.set_trace_callback(lambda sql: entered.set() if sql == 'BEGIN IMMEDIATE' else None)
            try:
                engine.record_answer(e['session_id'], e['examinee_token'], 'm1', 'q1', 'B', 1, 'contended')
            except ProctorError as exc:
                failures.append(exc.code)
            except BaseException as exc:
                failures.append(repr(exc))
            finally:
                conn.close()
                finished.set()
        thread = threading.Thread(target=worker)
        try:
            with transaction(self.db):
                thread.start()
                self.assertTrue(entered.wait(10))
                self.clock.advance(1000)
                self.engine._catch_up(e['session_id'], self.clock())
                self.assertFalse(finished.is_set())
        finally:
            thread.join(timeout=15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, ['MODULE_NOT_ACTIVE'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM answers').fetchone()[0], 0)

    def test_compiler_constraints_reject_bad_content(self):
        cases = []
        d = copy.deepcopy(self.definition); d['manifest']['start_window_ms'] = -1; cases.append(d)
        d = copy.deepcopy(self.definition); d['manifest']['calibration_status'] = 'empirically_normed'; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['entry_module_id'] = 'missing'; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][0]['duration_ms'] = -1; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][0]['routes'][0]['minimum'] = 2; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][1]['routes'][0]['next_module_id'] = 'm1'; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][0]['routes'][0]['next_module_id'] = None; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][0]['items'][0]['response_type'] = 'code_submission'; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][0]['aids'] = ['shell']; cases.append(d)
        d = copy.deepcopy(self.definition); d['forms'][0]['modules'][0]['items'][0]['correct'] = 'Z'; cases.append(d)
        for index, definition in enumerate(cases):
            path = self.root / ('bad-' + str(index) + '.db')
            with self.subTest(index=index), self.assertRaises((ValueError, sqlite3.IntegrityError)):
                compile_cartridge(definition, path)
            self.assertFalse(path.exists())

    def test_foreign_key_violations_are_not_discarded(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.deserialize(self.cart_path.read_bytes())
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute("UPDATE items SET module_id='missing' WHERE item_id='q1'")
        conn.commit()
        self.assertTrue(conn.execute('PRAGMA foreign_key_check').fetchall())
        with self.assertRaisesRegex(ValueError, 'foreign key'):
            validate(conn)

    def test_compiler_never_overwrites_and_snapshot_survives_path_change(self):
        original = self.cart_path.read_bytes()
        with self.assertRaises(FileExistsError):
            compile_cartridge(self.definition, self.cart_path)
        self.assertEqual(self.cart_path.read_bytes(), original)
        self.cart_path.write_bytes(b'changed')
        e = self.begin()
        self.assertEqual(self.engine.get_item(e['session_id'], e['examinee_token'], 'm1', 'q1')['prompt'], 'Which number is even?')
        self.assertEqual(self.cart.digest, hashlib.sha256(original).hexdigest())

    def test_compiler_command_and_runtime_package_resources(self):
        destination = self.root / 'cli.db'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/compile-proctor-cartridge.py'), str(FIXTURE), str(destination)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Cartridge(destination).digest, self.cart.digest)

    def test_token_secret_cannot_silently_change_on_restart(self):
        self.enroll()
        with self.assertRaisesRegex(ValueError, 'token key changed'):
            Proctor(self.cart, self.db, callers=self.callers, token_secret=secrets.token_bytes(32),
                    boot_id='boot-a', signer=self.signer, clock=self.clock)

    def test_unexpected_failure_rolls_back_answer_evidence_and_operation(self):
        e = self.begin()
        self.db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON answers BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.answer(e)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM operations WHERE operation_key='answer'").fetchone()[0], 0)
        self.db.execute('DROP TRIGGER fixture_failure')
        self.assertEqual(self.answer(e)['revision'], 1)

    def test_abort_policy_and_zero_break_are_enforced(self):
        definition = copy.deepcopy(self.definition)
        definition['manifest']['abort_on_timeout'] = True
        definition['forms'][0]['modules'][1]['break_ms'] = 0
        path = self.root / 'abort.db'
        compile_cartridge(definition, path)
        self.engine.cart = Cartridge(path)
        e = self.begin()
        self.engine.submit_module(e['session_id'], e['examinee_token'], 'm1', 'submit')
        self.assertEqual(self.engine.status(e['session_id'], e['examinee_token'])['module_id'], 'm2')
        self.assertEqual(self.engine.status(e['session_id'], e['examinee_token'])['state'], 'ACTIVE')
        self.clock.advance(1000)
        self.engine.tick()
        self.assertEqual(self.engine.status(e['session_id'], e['examinee_token'])['state'], 'TIMED_OUT')

    def test_branching_route_uses_accepted_correct_answers(self):
        definition = copy.deepcopy(self.definition)
        modules = definition['forms'][0]['modules']
        hard = copy.deepcopy(modules[1])
        hard['module_id'], hard['ordinal'] = 'm3', 3
        hard['items'][0]['item_id'], hard['items'][1]['item_id'] = 'q5', 'q6'
        modules.append(hard)
        modules[0]['routes'] = [{'minimum': 0, 'maximum': 0, 'next_module_id': 'm2'},
                                {'minimum': 1, 'maximum': 2, 'next_module_id': 'm3'}]
        path = self.root / 'branch.db'
        compile_cartridge(definition, path)
        self.engine.cart = Cartridge(path)
        e = self.begin()
        self.answer(e)
        self.engine.submit_module(e['session_id'], e['examinee_token'], 'm1', 'submit')
        self.assertEqual(self.engine.status(e['session_id'], e['examinee_token'])['module_id'], 'm3')


if __name__ == '__main__':
    unittest.main()
