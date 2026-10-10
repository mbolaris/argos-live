import copy
import contextlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive import bench_speed, command_center as cc, doc_trial, journal
from argoslive.results import Store
from argoslive.web.server import DashboardServer
from test_bench_speed import Backend
from test_doc_trial import DocBackend
from test_lab import Assistant
from argoslive import lab as lab_module

HW = {'cpu': {'model': 'Fixture CPU', 'cores': 8, 'threads': 16}, 'gpus': None, 'ram': {'total_bytes': 16 * 2**30}}
OTHER_HW = {'cpu': {'model': 'Different CPU', 'cores': 8, 'threads': 16}, 'gpus': None, 'ram': {'total_bytes': 16 * 2**30}}
DIGESTS = {'a:1b': 'a', 'b:4b': 'b', 'fixture:latest': 'a'}

BOOT = {'confirmed': True, 'configured': {'path': '/data/models'}, 'state': 'available',
        'locations': [{'key': 'models', 'reboot': {'state': 'pending'}, 'backing': {'encrypted': False}}]}


class TaggedBackend(DocBackend):
    def __init__(self, tag, digest, rate=1000, **kw):
        super().__init__(**kw)
        self.tag, self.digest, self.rate = tag, digest, rate

    def list(self):
        return {'models': [{'name': self.tag, 'digest': 'sha256:' + self.digest * 64}]}

    def generate(self, model, prompt, **kwargs):
        result = super().generate(model, prompt, **kwargs)
        if result.get('final') and 'eval_count' in result['final']:
            result['final']['eval_count'] = self.rate
        return result


class CommandCenterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / '.config/argos-live').mkdir(parents=True)
        self.store = Store(self.home / 'results')
        self.minute = 0

    def clock(self):
        self.minute += 1
        return f'2026-10-06T10:{self.minute:02d}:00+00:00'

    def add_documents(self, tag, digest, mode='reference', rate=1000, created=None, docs_hw=HW, speed_hw=HW, edit=None):
        backend = TaggedBackend(tag, digest, rate=rate, mode=mode)
        speed = bench_speed.run(backend, tag, hardware=lambda: copy.deepcopy(speed_hw), sizes=('short', 'medium'))
        docs = doc_trial.run(backend, tag, hardware=lambda: copy.deepcopy(docs_hw))
        if edit:
            edit(docs)
        for run, offset in ((speed, 0), (docs, 1)):
            run['created'] = f'2026-10-0{created}T10:0{offset}:00+00:00'
            self.store.save(run)
        return docs

    def snap(self, view=BOOT, selected='a:1b', digest=True, **kw):
        if isinstance(selected, str):
            selected = {'model': selected, 'digest': (DIGESTS[selected] * 64) if digest is True else digest}
        return cc.snapshot(self.home, self.store, view=view, selected=selected, clock=self.clock, **kw)

    def accept(self, model='a:1b', digest='a', task='a'):
        journal.record(self.home, 'task:' + task * 32, 'routine', 'Document answer accepted', 'accepted',
                       {'verdict': 'accepted', 'model': model, 'manifest_digest': 'sha256:' + digest * 64,
                        'quote_supported': True})

    def keys(self):
        return [e['key'] for e in journal.read(self.home)['entries']]

    def test_first_trial_does_not_require_a_new_storage_choice(self):
        value = self.snap(view={'state': 'not-configured', 'confirmed': False, 'locations': []})
        self.assertEqual(value['next_action']['id'], 'documents')
        self.assertEqual(value['next_action']['title'], 'Read this brief')
        self.assertIn('qualifies short-document reading', value['next_action']['reason'])
        self.assertEqual(value['build_path']['completed'], 0)
        self.assertEqual(value['build_path']['steps'][0]['state'], 'current')
        self.assertEqual({s['state'] for s in value['systems']}, {'unknown'})
        self.assertEqual(value['journal'], [])
        self.assertIsNone(value['moment'])

    def test_confirmed_storage_without_a_baseline_asks_for_documents(self):
        value = self.snap()
        self.assertEqual(value['next_action']['id'], 'documents')
        self.assertEqual(value['next_action']['title'], 'Read this brief')
        self.assertIn('Eight short passages', value['next_action']['reason'])
        self.assertEqual(self.keys(), ['storage:confirmed'])
        self.assertEqual(value['journal'][0]['tier'], 'routine')

    def test_completed_checklist_recommends_choosing_a_capability(self):
        self.add_documents('a:1b', 'a', created=4)
        self.accept()
        retained = {**BOOT, 'locations': [{'key': 'models', 'reboot': {'state': 'retained'},
                                             'backing': {'encrypted': False}}]}
        action = self.snap(view=retained)['next_action']
        self.assertEqual(action['id'], 'capabilities')
        self.assertEqual(action['title'], 'Choose the next capability you care about')

    def test_front_page_speed_does_not_carry_to_different_model_files(self):
        self.add_documents('a:1b', 'a', created=4)
        original = self.snap()
        core = next(s for s in original['systems'] if s['id'] == 'power-core')
        self.assertEqual(core['state'], 'bench-test')
        changed = self.snap(digest='b' * 64)
        core = next(s for s in changed['systems'] if s['id'] == 'power-core')
        self.assertEqual(core['state'], 'unknown')
        self.assertNotIn('Measured', core['detail'])

    def test_documents_are_the_next_step_after_a_baseline(self):
        self.store.save(bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {}))
        self.assertEqual(self.snap(selected='fixture:latest')['next_action']['id'], 'documents')

    def test_build_path_requires_current_task_evidence_and_matched_candidate(self):
        self.add_documents('a:1b', 'a', created=1)
        self.accept()
        value = self.snap()
        self.assertEqual(value['build_path']['completed'], 3)
        self.add_documents('b:4b', 'b', created=2, docs_hw=OTHER_HW)
        self.assertEqual(self.snap()['build_path']['completed'], 3)
        self.add_documents('b:4b', 'b', created=3)
        self.assertEqual(self.snap()['build_path']['completed'], 4)
        self.assertEqual(self.snap(digest=False)['build_path']['completed'], 0)

    def test_missed_criteria_require_storage_only_when_a_candidate_is_needed(self):
        self.add_documents('a:1b', 'a', mode='wrong', created=1)
        value = self.snap(view={'state': 'available', 'confirmed': False, 'locations': []})
        self.assertEqual(value['next_action']['id'], 'storage')
        reading = next(s for s in value['build_path']['steps'] if s['id'] == 'documents')
        self.assertEqual(reading['state'], 'attention')
        self.assertEqual(value['build_path']['completed'], 1)

    def test_temporary_model_storage_does_not_recommend_a_retention_test(self):
        self.add_documents('a:1b', 'a', created=1)
        self.accept()
        view = {**BOOT, 'configured': {'path': '/ram/models', 'temporary': True}}
        self.assertEqual(self.snap(view=view)['next_action']['id'], 'capabilities')

    def test_qualified_trial_is_journaled_once_and_leads_to_a_real_task(self):
        self.add_documents('a:1b', 'a', created=1)
        first = self.snap()
        self.assertEqual(first['next_action']['id'], 'task')
        self.assertEqual(first['moment']['tier'], 'qualified')
        self.assertIn('says nothing about longer documents', first['moment']['detail'])
        brain = next(s for s in first['systems'] if s['id'] == 'brain')
        self.assertEqual(brain['state'], 'qualified')
        self.assertIn('Other abilities are untested', brain['detail'])
        journal.mark_seen(self.home)
        before = self.keys()
        again = self.snap()
        self.assertEqual(self.keys(), before, 'a repeated snapshot never replays a milestone')
        self.assertIsNone(again['moment'])

    def test_one_moment_at_the_highest_tier_when_several_land_together(self):
        self.add_documents('a:1b', 'a', created=1)
        view = copy.deepcopy(BOOT)
        view['locations'][0]['reboot'] = {'state': 'retained', 'verified_at': '2026-10-06'}
        value = self.snap(view=view)
        self.assertEqual(value['moment']['tier'], 'commissioned')
        self.assertEqual(value['moment']['key'], 'storage:reboot-retained')
        self.assertIn('Not encrypted.', value['moment']['detail'])
        self.assertIn('does not test conversation recall', value['moment']['detail'])

    def test_quiet_hides_the_moment_but_keeps_progress(self):
        self.add_documents('a:1b', 'a', created=1)
        journal.set_quiet(self.home, True)
        value = self.snap()
        self.assertIsNone(value['moment'])
        self.assertTrue(value['journal'])

    def test_new_model_that_qualifies_where_the_old_one_did_not_is_recognized(self):
        self.add_documents('a:1b', 'a', mode='wrong', created=1)
        self.add_documents('b:4b', 'b', created=2)
        value = self.snap(selected='b:4b')
        improved = next(e for e in value['journal'] if e['key'].startswith('improved:'))
        self.assertEqual(improved['tier'], 'qualified')
        self.assertIn('under the same settings', improved['detail'])
        self.assertIn('restore', improved['detail'])
        self.assertNotIn('smarter', json.dumps(value).lower())

    def test_wording_only_misses_do_not_recommend_a_larger_model(self):
        def wording(item):
            # Right evidence, answer worded differently from every accepted form (audited Toronado pattern).
            if item['category'] != 'quote':
                return item['reference']
            value = json.loads(item['reference'])
            value['answer'] = 'to ' + value['answer']
            return json.dumps(value)
        self.add_documents('a:1b', 'a', mode=wording, created=1)
        value = self.snap()
        self.assertEqual(value['next_action']['id'], 'review')
        self.assertIn('diagnostic review (not a score)', value['next_action']['reason'])
        self.assertNotIn('larger model is not automatically better', value['next_action']['reason'])
        self.assertEqual(value['report']['ability']['diagnoses'], {'wording': 8})
        self.assertFalse(value['report']['ability']['qualified'])

    def test_wrong_facts_still_point_past_the_current_model(self):
        self.add_documents('a:1b', 'a', mode='wrong', created=1)
        self.assertNotEqual(self.snap()['next_action']['id'], 'review')

    def test_regression_is_acknowledged_and_restore_is_offered(self):
        self.add_documents('a:1b', 'a', created=1)
        self.add_documents('b:4b', 'b', mode='wrong', created=2)
        value = self.snap(selected='b:4b')
        self.assertEqual(value['next_action']['id'], 'restore')
        self.assertEqual(value['next_action']['model'], 'a:1b')
        entry = next(e for e in value['journal'] if e['key'].startswith('regression:'))
        self.assertEqual(entry['tier'], 'routine')
        self.assertIn('restoring the previous selection is available', entry['detail'])

    def test_leaner_build_needs_a_real_speed_gain_and_both_qualified(self):
        self.add_documents('a:1b', 'a', rate=100, created=1)
        self.add_documents('b:4b', 'b', rate=150, created=2)
        self.snap(selected='b:4b')
        self.assertTrue(any(k.startswith('leaner:') for k in self.keys()))

    def test_small_speed_difference_is_not_a_gain(self):
        self.add_documents('a:1b', 'a', rate=100, created=1)
        self.add_documents('b:4b', 'b', rate=110, created=2)
        self.snap(selected='b:4b')
        self.assertFalse(any(k.startswith('leaner:') for k in self.keys()))

    def test_commissioning_needs_a_qualified_model_and_an_accepted_task(self):
        self.add_documents('a:1b', 'a', created=1)
        self.snap()
        self.assertFalse(any(k.startswith('brain:commissioned') for k in self.keys()))
        self.accept()
        value = self.snap()
        self.assertIn('brain:commissioned:a:1b:' + 'a' * 12, self.keys())
        self.assertEqual(next(s for s in value['systems'] if s['id'] == 'sensors')['state'], 'commissioned')
        self.assertEqual(self.snap()['next_action']['id'], 'reboot')

    def test_rejected_task_never_commissions(self):
        self.add_documents('a:1b', 'a', created=1)
        journal.record(self.home, 'task:' + 'b' * 32, 'routine', 'Document answer rejected', 'rejected',
                       {'verdict': 'rejected', 'model': 'a:1b', 'manifest_digest': 'sha256:' + 'a' * 64,
                        'quote_supported': False})
        self.snap()
        self.assertFalse(any(k.startswith('brain:commissioned') for k in self.keys()))

    # ---- comparisons must be supported ----
    def test_no_improvement_claim_when_hardware_differs(self):
        self.add_documents('a:1b', 'a', mode='wrong', created=1)
        self.add_documents('b:4b', 'b', created=2, docs_hw=OTHER_HW)
        value = self.snap(selected='b:4b')
        self.assertFalse(any(k.startswith(('improved:', 'regression:', 'leaner:')) for k in self.keys()))
        self.assertNotIn('under the same settings', json.dumps(value))

    def test_no_improvement_claim_when_context_or_suite_differ(self):
        for edit in (lambda r: r['settings'].update(context=8192),
                     lambda r: r.update(suite_version='documents/short/2.0.0')):
            self.tmp.cleanup()
            self.setUp()
            self.add_documents('a:1b', 'a', mode='wrong', created=1)
            self.add_documents('b:4b', 'b', created=2, edit=edit)
            self.snap(selected='b:4b')
            self.assertFalse(any(k.startswith(('improved:', 'regression:', 'leaner:')) for k in self.keys()), edit)

    def test_no_regression_or_restore_when_the_pair_is_not_comparable(self):
        self.add_documents('a:1b', 'a', created=1)
        self.add_documents('b:4b', 'b', mode='wrong', created=2, docs_hw=OTHER_HW)
        value = self.snap(selected='b:4b')
        self.assertNotEqual(value['next_action']['id'], 'restore')
        self.assertFalse(any(k.startswith('regression:') for k in self.keys()))

    def test_leaner_build_needs_matched_speed_runs_not_just_matched_documents(self):
        self.add_documents('a:1b', 'a', rate=100, created=1)
        self.add_documents('b:4b', 'b', rate=200, created=2, speed_hw=OTHER_HW)
        self.snap(selected='b:4b')
        self.assertFalse(any(k.startswith('leaner:') for k in self.keys()))

    def test_runs_without_hardware_evidence_support_no_comparison(self):
        self.add_documents('a:1b', 'a', mode='wrong', created=1, docs_hw={})
        self.add_documents('b:4b', 'b', created=2, docs_hw={})
        self.snap(selected='b:4b')
        self.assertFalse(any(k.startswith('improved:') for k in self.keys()))

    # ---- identity is the manifest digest, not the tag ----
    def test_same_tag_with_changed_weights_inherits_nothing(self):
        self.add_documents('a:1b', 'a', created=1)
        self.accept()
        self.snap()
        self.assertIn('brain:commissioned:a:1b:' + 'a' * 12, self.keys())
        value = self.snap(selected={'model': 'a:1b', 'digest': 'c' * 64})
        brain = next(s for s in value['systems'] if s['id'] == 'brain')
        sensors = next(s for s in value['systems'] if s['id'] == 'sensors')
        self.assertEqual(brain['state'], 'unknown')
        self.assertIn('do not carry over', brain['detail'])
        self.assertEqual(sensors['state'], 'bench-test')
        self.assertNotEqual(value['next_action']['id'], 'task')
        self.assertEqual(value['next_action']['id'], 'documents')
        self.assertEqual(value['build_path']['completed'], 0)
        old = next(e for e in value['journal'] if e['key'].startswith('brain:commissioned'))
        self.assertIs(old['applies_to_selected'], False, 'history is kept but not offered as evidence for new weights')

    def test_two_versions_of_one_tag_keep_separate_results(self):
        self.add_documents('a:1b', 'a', created=1)
        self.add_documents('a:1b', 'c', mode='wrong', created=2)
        old = self.snap(selected={'model': 'a:1b', 'digest': 'a' * 64})
        self.assertEqual(next(s for s in old['systems'] if s['id'] == 'brain')['state'], 'qualified')
        new = self.snap(selected={'model': 'a:1b', 'digest': 'c' * 64})
        self.assertEqual(next(s for s in new['systems'] if s['id'] == 'brain')['state'], 'bench-test')

    def test_unidentified_selected_model_matches_nothing(self):
        self.add_documents('a:1b', 'a', created=1)
        self.accept()
        value = self.snap(selected={'model': 'a:1b', 'digest': None})
        self.assertEqual(next(s for s in value['systems'] if s['id'] == 'brain')['state'], 'unknown')
        self.assertEqual(next(s for s in value['systems'] if s['id'] == 'sensors')['state'], 'bench-test')

    def test_task_accepted_on_other_weights_never_commissions_a_qualified_run(self):
        self.add_documents('a:1b', 'a', created=1)
        self.accept(model='a:1b', digest='c')
        self.snap()
        self.assertFalse(any(k.startswith('brain:commissioned') for k in self.keys()))

    def test_accepted_task_without_a_digest_is_not_evidence(self):
        self.add_documents('a:1b', 'a', created=1)
        journal.record(self.home, 'task:' + 'd' * 32, 'routine', 'Document answer accepted', 'accepted',
                       {'verdict': 'accepted', 'model': 'a:1b', 'quote_supported': True})
        self.snap()
        self.assertFalse(any(k.startswith('brain:commissioned') for k in self.keys()))

    def test_selected_identity_reads_the_manifest_digest_from_the_store(self):
        import hashlib
        models = self.home / 'models'
        manifest = models / 'manifests/registry.ollama.ai/library/qwen3/0.6b'
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(b'{"schemaVersion": 2, "layers": []}')
        (self.home / '.config/argos-live/state.json').write_text(json.dumps({'storage': str(models), 'model': 'qwen3:0.6b'}))
        identity = cc.selected_identity(self.home)
        self.assertEqual(identity, {'model': 'qwen3:0.6b', 'digest': hashlib.sha256(manifest.read_bytes()).hexdigest()})
        manifest.write_bytes(b'{"schemaVersion": 2, "layers": [], "x": 1}')
        self.assertNotEqual(cc.selected_identity(self.home)['digest'], identity['digest'])
        manifest.unlink()
        self.assertEqual(cc.selected_identity(self.home)['digest'], None)

    def test_journal_rejects_bad_entries_and_is_bounded(self):
        for args in (('BAD KEY', 'routine', 't', 'd'), ('k', 'epic', 't', 'd'), ('k', 'routine', '', 'd'),
                     ('k', 'routine', 't', 'x' * 401)):
            with self.assertRaises(ValueError):
                journal.record(self.home, *args)
        for number in range(230):
            journal.record(self.home, f'k{number}', 'routine', 't', 'd')
        self.assertEqual(len(journal.read(self.home)['entries']), journal.MAX_ENTRIES)

    def test_corrupt_journal_needs_review_instead_of_being_replaced(self):
        journal.path(self.home).write_text('{"schema": "other"}')
        with self.assertRaises(ValueError):
            journal.record(self.home, 'k', 'routine', 't', 'd')
        self.assertEqual(journal.path(self.home).read_text(), '{"schema": "other"}')


class TaskTests(unittest.TestCase):
    PASSAGE = 'The Larkspur ferry crossing takes 35 minutes. Fares are $6 for adults.'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / '.config/argos-live').mkdir(parents=True)
        self.assistant = Assistant(self.home)
        self.store = Store(self.home / 'results')
        self.reply = json.dumps({'status': 'answered', 'answer': '35 minutes', 'quote': 'The Larkspur ferry crossing takes 35 minutes.'})

        class Fixed(Backend):
            def generate(inner, model, prompt, **kw):
                result = super().generate(model, prompt, **kw)
                if prompt:
                    result['text'] = self.reply
                    result['final']['prompt_eval_count'] = getattr(self, 'tokens', 100)
                return result
        self.backend = Fixed()

        @contextlib.contextmanager
        def provide(target, **options):
            yield self.backend
        self.assistant.backend = provide
        self.lab = lab_module.Controller(self.assistant, store=self.store)
        self.addCleanup(self.lab.close)
        self.command = cc.Controller(self.home, self.store, lab=self.lab)

    def run_task(self, document=None, question='How long is the crossing?'):
        self.lab.start_task(document or self.PASSAGE, question)
        self.lab.worker.join(5)
        return self.lab.snapshot()

    def test_answer_is_checked_against_the_pasted_text_and_never_saved(self):
        value = self.run_task()
        task = value['task']
        self.assertEqual((value['phase'], task['outcome'], task['answer']), ('completed', 'answered', '35 minutes'))
        self.assertTrue(task['quote_supported'])
        self.assertEqual(task['manifest_digest'], 'sha256:' + 'a' * 64)
        self.assertEqual(self.store.list()['runs'], [], 'a pasted-document answer is not a benchmark result')
        self.assertEqual(self.assistant.calls[0], 'pause')
        self.assertEqual(self.assistant.calls[-1], 'resume')

    def test_invented_quotation_is_flagged_unsupported(self):
        self.reply = json.dumps({'status': 'answered', 'answer': '35 minutes', 'quote': 'It takes about half an hour.'})
        self.assertFalse(self.run_task()['task']['quote_supported'])

    def test_document_that_fills_the_context_is_refused_not_truncated(self):
        self.tokens = doc_trial.CONTEXT
        self.assertEqual(self.run_task()['task']['outcome'], 'too_long')

    def test_malformed_reply_is_a_format_error(self):
        self.reply = 'It takes 35 minutes.'
        self.assertEqual(self.run_task()['task']['outcome'], 'format_error')

    def test_oversized_or_empty_input_never_pauses_chat(self):
        for document, question in (('', 'q'), ('x' * (doc_trial.TASK_DOCUMENT_LIMIT + 1), 'q'), ('text', ''),
                                   ('text', 'q' * (doc_trial.TASK_QUESTION_LIMIT + 1)), (5, 'q')):
            with self.assertRaises(ValueError):
                self.lab.start_task(document, question)
        self.assertEqual(self.assistant.calls, [])

    def test_verdict_is_recorded_once_without_the_document_or_answer(self):
        self.run_task()
        result = self.command.verdict('accepted')
        self.assertTrue(result['recorded'])
        self.assertFalse(self.command.verdict('accepted')['recorded'])
        raw = journal.path(self.home).read_text()
        for private in ('Larkspur', '35 minutes', 'crossing'):
            self.assertNotIn(private, raw)
        with self.assertRaises(ValueError):
            self.command.verdict('great')

    def test_accepting_needs_an_identified_model(self):
        self.backend.list = lambda: {'models': []}
        self.run_task()
        with self.assertRaisesRegex(ValueError, 'could not be identified'):
            self.command.verdict('accepted')
        self.assertTrue(self.command.verdict('rejected')['recorded'])

    def test_no_verdict_without_an_answer(self):
        with self.assertRaises(ValueError):
            self.command.verdict('accepted')
        self.reply = 'not json'
        self.run_task()
        with self.assertRaises(ValueError):
            self.command.verdict('accepted')


class HttpTests(TaskTests):
    def setUp(self):
        super().setUp()
        self.server = DashboardServer(port=0, lab=self.lab, command=self.command)
        threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, token=True, extra=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'X-Argos-Token': self.server.token} if token else {}
        raw = None
        if body is not None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        headers.update(extra or {})
        connection.request(method, path + ('?token=' + self.server.token if method == 'GET' else ''), raw, headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if data else None

    def test_snapshot_and_actions_require_the_session_token(self):
        self.assertEqual(self.call('GET', '/api/command-center')[0], 200)
        self.assertEqual(self.call('POST', '/api/command-center/seen', token=False)[0], 403)
        self.assertEqual(self.call('POST', '/api/lab/task', {'document': 'a', 'question': 'b'}, token=False)[0], 403)

    def test_task_roundtrip_over_http_with_bounds(self):
        status, _ = self.call('POST', '/api/lab/task', {'document': self.PASSAGE, 'question': 'How long?'})
        self.assertEqual(status, 200)
        self.lab.worker.join(5)
        self.assertEqual(self.call('GET', '/api/lab')[1]['task']['answer'], '35 minutes')
        self.assertEqual(self.call('POST', '/api/lab/task-verdict', {'verdict': 'accepted'})[1]['recorded'], True)
        self.assertEqual(self.call('POST', '/api/lab/task', {'document': 'a', 'question': 'b', 'x': 1})[0], 409)
        self.assertEqual(self.call('POST', '/api/lab/task', b'x' * 20000)[0], 400)
        self.assertEqual(self.call('POST', '/api/lab/task', {'document': 'a', 'question': 'b'},
                                   extra={'Content-Type': 'text/plain'})[0], 400)
        self.assertEqual(self.call('POST', '/api/command-center/quiet', {'quiet': 'yes'})[0], 409)
        self.assertEqual(self.call('POST', '/api/command-center/quiet', {'quiet': True})[1], {'quiet': True})
        self.assertEqual(self.call('POST', '/api/command-center/seen')[0], 200)


if __name__ == '__main__':
    unittest.main()
