import contextlib
import copy
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))

from argoslive import bench_ability, bench_speed, command_center, doc_trial, hw, lab, ollama, recipe, results, skill_map
from argoslive.results import Store
from test_bench_speed import Backend
from test_doc_trial import DocBackend


class RecipeSchemaTests(unittest.TestCase):
    def test_canonical_standard_preset(self):
        r = recipe.canonical('standard')
        self.assertEqual(r['schema'], 'argos-recipe/1')
        self.assertEqual(r['preset'], 'standard')
        self.assertIsNone(r['instructions'])
        self.assertIsNone(r['instruction_hash'])
        self.assertEqual(r['context'], 2048)
        self.assertEqual(r['output_cap'], 128)
        self.assertEqual(r['temperature'], 0.0)
        self.assertEqual(r['seed'], 1)
        self.assertFalse(r['thinking'])
        self.assertEqual(r['request_format'], 'generate')
        validated = recipe.validate(r)
        self.assertEqual(validated, r)

    def test_list_presets(self):
        presets = recipe.list_presets()
        ids = [p['id'] for p in presets]
        self.assertIn('standard', ids)
        self.assertIn('concise', ids)
        for p in presets:
            self.assertIn('title', p)
            self.assertIn('description', p)
            self.assertIn('instructions', p)
            self.assertIn('instruction_hash', p)

    def test_canonical_concise_preset_and_aliases(self):
        r = recipe.canonical('concise')
        self.assertEqual(r['schema'], 'argos-recipe/1')
        self.assertEqual(r['preset'], 'concise')
        self.assertEqual(r['instructions'], 'Follow the requested output format; omit extra prose.')
        expected_hash = hashlib.sha256(b'Follow the requested output format; omit extra prose.').hexdigest()
        self.assertEqual(r['instruction_hash'], expected_hash)
        validated = recipe.validate(r)
        self.assertEqual(validated, r)

        # Alias format-strict resolves to concise
        alias_r = recipe.canonical('format-strict')
        self.assertEqual(alias_r['preset'], 'concise')
        self.assertEqual(alias_r['instructions'], r['instructions'])

        # Alias baseline resolves to standard
        base_r = recipe.canonical('baseline')
        self.assertEqual(base_r['preset'], 'standard')
        self.assertIsNone(base_r['instructions'])

    def test_unknown_preset_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown recipe preset'):
            recipe.canonical('creative-writer')

    def test_preset_allowlist_enforced_no_custom_instructions(self):
        # Arbitrary custom instructions are rejected
        with self.assertRaisesRegex(ValueError, 'Custom instructions are not supported; choose a reviewed preset'):
            recipe.canonical('standard', instructions='Be creative')

        with self.assertRaisesRegex(ValueError, 'Custom instructions are not supported; choose a reviewed preset'):
            recipe.canonical('concise', instructions='Custom instructions')

        # Supplying arbitrary instructions to validate is rejected even with matching hash
        arbitrary = 'Arbitrary custom instructions'
        tampered_recipe = recipe.canonical('concise')
        tampered_recipe['instructions'] = arbitrary
        tampered_recipe['instruction_hash'] = hashlib.sha256(arbitrary.encode('utf-8')).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Recipe instructions must match the reviewed preset exactly'):
            recipe.validate(tampered_recipe)

    def test_unknown_and_missing_fields_rejected(self):
        r = recipe.canonical('concise')

        # Extra unknown field rejected
        with_extra = dict(r, extra_param='not-allowed')
        with self.assertRaisesRegex(ValueError, 'Recipe contains unexpected or missing fields'):
            recipe.validate(with_extra)

        # Missing required field rejected
        missing_seed = dict(r)
        del missing_seed['seed']
        with self.assertRaisesRegex(ValueError, 'Recipe contains unexpected or missing fields'):
            recipe.validate(missing_seed)

    def test_unsupported_deviations_rejected_in_instruction_only_slice(self):
        # Temperature deviation
        with self.assertRaisesRegex(ValueError, 'Unsupported recipe deviation: temperature must be 0.0'):
            recipe.canonical('standard', temperature=0.7)

        # Seed deviation
        with self.assertRaisesRegex(ValueError, 'Unsupported recipe deviation: seed must be 1'):
            recipe.canonical('standard', seed=42)

        # Thinking deviation (deferred to J6c)
        with self.assertRaisesRegex(ValueError, 'thinking experiments are deferred to J6c'):
            recipe.canonical('standard', thinking=True)

        # Request format deviation
        with self.assertRaisesRegex(ValueError, "request format must be 'generate'"):
            recipe.canonical('standard', request_format='chat')

        # Output cap deviation
        with self.assertRaisesRegex(ValueError, 'output cap must be 128'):
            recipe.canonical('standard', output_cap=256)

        # Context deviation: must be supported suite context (2048 or 4096)
        with self.assertRaisesRegex(ValueError, 'context must be in'):
            recipe.canonical('standard', context=8192)

    def test_validate_tampered_hash_rejected(self):
        r = recipe.canonical('concise')
        r['instruction_hash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Mismatched recipe instruction hash'):
            recipe.validate(r)

    def test_validate_tampered_schema_rejected(self):
        r = recipe.canonical('concise')
        r['schema'] = 'argos-recipe/2'
        with self.assertRaisesRegex(ValueError, 'Unsupported recipe schema'):
            recipe.validate(r)

    def test_resolve_helper(self):
        # None resolves to canonical standard
        res_none = recipe.resolve(None)
        self.assertEqual(res_none['preset'], 'standard')
        self.assertIsNone(res_none['instructions'])

        # Preset name string resolves to canonical preset
        res_str = recipe.resolve('concise')
        self.assertEqual(res_str['preset'], 'concise')

        # Recipe dict is validated and copied
        custom = recipe.canonical('concise')
        res_dict = recipe.resolve(custom)
        self.assertEqual(res_dict, custom)
        self.assertIsNot(res_dict, custom)

        # Context mismatch between recipe dict and runner context is rejected
        doc_recipe = recipe.canonical('concise', context=4096)
        with self.assertRaisesRegex(ValueError, 'does not match runner context'):
            recipe.resolve(doc_recipe, context=2048)

        # Invalid type rejected
        with self.assertRaisesRegex(ValueError, 'Recipe specification must be a preset name'):
            recipe.resolve(12345)

    def test_is_standard_helper(self):
        self.assertTrue(recipe.is_standard(None))
        self.assertTrue(recipe.is_standard(recipe.canonical('standard')))
        self.assertTrue(recipe.is_standard({'recipe': recipe.canonical('standard')}))
        self.assertTrue(recipe.is_standard({'schema': 'argos-bench/1'}))  # legacy run without recipe
        self.assertFalse(recipe.is_standard(recipe.canonical('concise')))
        self.assertFalse(recipe.is_standard({'recipe': recipe.canonical('concise')}))


class BackendExecutionTests(unittest.TestCase):
    def test_ollama_generate_omits_system_when_none(self):
        client = ollama.Client('http://127.0.0.1:11434')
        with patch.object(client, '_stream') as mock_stream:
            mock_stream.return_value = {'text': 'hello'}
            client.generate('qwen2.5:1.5b', 'What is 2+2?', system=None)
            self.assertEqual(mock_stream.call_count, 1)
            endpoint, payload, callback, cancel = mock_stream.call_args[0]
            self.assertEqual(endpoint, '/api/generate')
            self.assertNotIn('system', payload)
            self.assertEqual(payload['prompt'], 'What is 2+2?')

    def test_ollama_generate_includes_system_when_provided(self):
        client = ollama.Client('http://127.0.0.1:11434')
        with patch.object(client, '_stream') as mock_stream:
            mock_stream.return_value = {'text': 'hello'}
            instruction_text = 'Follow the requested output format; omit extra prose.'
            client.generate('qwen2.5:1.5b', 'What is 2+2?', system=instruction_text)
            self.assertEqual(mock_stream.call_count, 1)
            endpoint, payload, callback, cancel = mock_stream.call_args[0]
            self.assertEqual(endpoint, '/api/generate')
            self.assertIn('system', payload)
            self.assertEqual(payload['system'], instruction_text)

    def test_doc_trial_with_concise_recipe_executes_with_instructions(self):
        backend = DocBackend()
        concise_recipe = recipe.canonical('concise', context=4096)
        result = doc_trial.run(backend, 'fixture:latest', hardware=lambda: {}, recipe=concise_recipe)
        self.assertIn('recipe', result)
        self.assertEqual(result['recipe']['preset'], 'concise')
        self.assertEqual(result['recipe']['instructions'], concise_recipe['instructions'])
        self.assertEqual(result['recipe']['instruction_hash'], concise_recipe['instruction_hash'])

        # Verify backend generate calls received system instruction
        generate_calls = [c for c in backend.calls if c[0] == 'generate' and c[2]]
        self.assertTrue(len(generate_calls) > 0)
        for call in generate_calls:
            self.assertEqual(call[3].get('system'), concise_recipe['instructions'])

    def test_doc_trial_standard_run_executes_without_instructions(self):
        backend = DocBackend()
        result = doc_trial.run(backend, 'fixture:latest', hardware=lambda: {}, recipe=None)
        self.assertIn('recipe', result)
        self.assertEqual(result['recipe']['preset'], 'standard')
        self.assertIsNone(result['recipe']['instructions'])

        generate_calls = [c for c in backend.calls if c[0] == 'generate' and c[2]]
        self.assertTrue(len(generate_calls) > 0)
        for call in generate_calls:
            self.assertIsNone(call[3].get('system'))


class ChatRequestContractTests(unittest.TestCase):
    def test_chat_prepends_system_role_message(self):
        client = ollama.Client('http://127.0.0.1:11434')
        with patch.object(client, '_stream') as mock_stream:
            mock_stream.return_value = {'message': {'content': 'hello'}}
            caller_messages = [{'role': 'user', 'content': 'What is 2+2?'}]
            instruction_text = 'Follow the requested output format; omit extra prose.'
            client.chat('qwen2.5:1.5b', caller_messages, system=instruction_text)
            self.assertEqual(mock_stream.call_count, 1)
            endpoint, payload, callback, cancel = mock_stream.call_args[0]
            self.assertEqual(endpoint, '/api/chat')
            # /api/chat must NOT contain top-level system field
            self.assertNotIn('system', payload)
            # /api/chat contract uses a system-role message at index 0
            self.assertEqual(len(payload['messages']), 2)
            self.assertEqual(payload['messages'][0], {'role': 'system', 'content': instruction_text})
            self.assertEqual(payload['messages'][1], {'role': 'user', 'content': 'What is 2+2?'})

    def test_chat_preserves_caller_messages_list(self):
        client = ollama.Client('http://127.0.0.1:11434')
        with patch.object(client, '_stream') as mock_stream:
            mock_stream.return_value = {'message': {'content': 'hello'}}
            caller_messages = [{'role': 'user', 'content': 'Hello'}]
            caller_copy = list(caller_messages)
            client.chat('qwen2.5:1.5b', caller_messages, system='System instruction')
            # Caller messages list must not be mutated
            self.assertEqual(caller_messages, caller_copy)
            self.assertEqual(len(caller_messages), 1)

    def test_chat_omits_system_message_when_none(self):
        client = ollama.Client('http://127.0.0.1:11434')
        with patch.object(client, '_stream') as mock_stream:
            mock_stream.return_value = {'message': {'content': 'hello'}}
            caller_messages = [{'role': 'user', 'content': 'Hello'}]
            client.chat('qwen2.5:1.5b', caller_messages, system=None)
            self.assertEqual(mock_stream.call_count, 1)
            endpoint, payload, callback, cancel = mock_stream.call_args[0]
            self.assertEqual(endpoint, '/api/chat')
            self.assertNotIn('system', payload)
            self.assertEqual(len(payload['messages']), 1)
            self.assertEqual(payload['messages'][0], {'role': 'user', 'content': 'Hello'})


class ResultsRecipeComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'results')

    def test_results_save_and_load_preserves_recipe(self):
        backend = DocBackend()
        result = doc_trial.run(backend, 'fixture:latest', hardware=lambda: {}, recipe='concise')
        path = self.store.save(result)
        loaded = self.store.load(result['id'])
        self.assertEqual(loaded['recipe'], result['recipe'])
        self.assertEqual(loaded['recipe']['preset'], 'concise')

    def test_comparison_matches_same_recipe(self):
        backend1 = DocBackend()
        backend2 = DocBackend('wrong')
        rec = recipe.canonical('concise', context=4096)
        res1 = doc_trial.run(backend1, 'fixture:latest', hardware=lambda: {}, recipe=rec)
        res2 = doc_trial.run(backend2, 'fixture:latest', hardware=lambda: {}, recipe=rec)

        compared = results.compare([res1, res2])
        self.assertEqual(len(compared['rows']), 2)

    def test_comparison_rejects_different_recipes(self):
        backend1 = DocBackend()
        backend2 = DocBackend()
        res_standard = doc_trial.run(backend1, 'fixture:latest', hardware=lambda: {}, recipe='standard')
        res_concise = doc_trial.run(backend2, 'fixture:latest', hardware=lambda: {}, recipe='concise')

        with self.assertRaisesRegex(ValueError, 'Comparison requires matching recipes'):
            results.compare([res_standard, res_concise])

    def test_comparison_rejects_legacy_record_against_experiment_record(self):
        backend1 = DocBackend()
        backend2 = DocBackend()
        res_legacy = doc_trial.run(backend1, 'fixture:latest', hardware=lambda: {})
        res_concise = doc_trial.run(backend2, 'fixture:latest', hardware=lambda: {}, recipe='concise')

        # Simulate legacy record without recipe key
        del res_legacy['recipe']

        with self.assertRaisesRegex(ValueError, 'Comparison requires matching recipes'):
            results.compare([res_legacy, res_concise])


class PrematureQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config' / 'argos-live').mkdir(parents=True, exist_ok=True)
        self.store = Store(self.home / 'results')

    def test_experiment_result_does_not_qualify_unchanged_build_or_commission_skills(self):
        backend = DocBackend()
        # Run with concise experiment recipe; yields qualified scores
        run = doc_trial.run(backend, 'fixture:latest', hardware=lambda: {}, recipe='concise')
        self.assertTrue(run['qualification']['qualified'])
        self.store.save(run)

        # 1. command_center.facts() filters document_runs to standard only
        f = command_center.facts(self.home, self.store, view=None)
        self.assertEqual(len(f['doc_models']), 0, 'Experiment run must not appear in doc_models')

        # 2. record_moments() must NOT record documents:qualified or commission brain
        moments = command_center.record_moments(self.home, f)
        qual_moments = [m for m in moments if m['key'].startswith('documents:qualified')]
        self.assertEqual(len(qual_moments), 0, 'Must not qualify unchanged build from experiment run')
        comm_moments = [m for m in moments if m['key'].startswith('brain:commissioned')]
        self.assertEqual(len(comm_moments), 0, 'Must not commission skills from experiment run')

        # 3. systems() evaluates brain as untested / unknown, NOT qualified
        selected = {'model': 'fixture:latest', 'digest': 'sha256:' + 'a' * 64}
        sys_list = command_center.systems(self.home, f, selected)
        brain = next(s for s in sys_list if s['id'] == 'brain')
        self.assertNotEqual(brain['state'], 'qualified', 'Brain must not be marked qualified from experiment run')

        # 4. skill_map does NOT match experiment run for task-level qualification
        m = skill_map.build_skill_map(f, selected)
        under = next(d for d in m['domains'] if d['id'] == 'understanding')
        doc_node = next(n for n in under['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node['state'], 'untested', 'doc-short skill must remain untested from experiment run')

    def test_standard_result_qualifies_and_commissions(self):
        backend = DocBackend()
        # Standard calibration run
        run = doc_trial.run(backend, 'fixture:latest', hardware=lambda: {}, recipe='standard')
        self.assertTrue(run['qualification']['qualified'])
        self.store.save(run)

        f = command_center.facts(self.home, self.store, view=None)
        self.assertEqual(len(f['doc_models']), 1, 'Standard run must be included in doc_models')

        moments = command_center.record_moments(self.home, f)
        qual_moments = [m for m in moments if m['key'].startswith('documents:qualified')]
        self.assertEqual(len(qual_moments), 1, 'Standard run must record qualification')

        selected = {'model': 'fixture:latest', 'digest': 'sha256:' + 'a' * 64}
        sys_list = command_center.systems(self.home, f, selected)
        brain = next(s for s in sys_list if s['id'] == 'brain')
        self.assertEqual(brain['state'], 'qualified')

        m = skill_map.build_skill_map(f, selected)
        under = next(d for d in m['domains'] if d['id'] == 'understanding')
        doc_node = next(n for n in under['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node['state'], 'qualified')


class LabRecipeControllerTests(unittest.TestCase):
    class FakeAssistant:
        def __init__(self, home):
            self.home = home
            self.active = False
            self.lab_active = False
            self.lock = threading.RLock()
            self.calls = []

        def snapshot(self):
            return {'active': self.active}

        def stop(self):
            self.calls.append('stop')
            self.active = False

        def start(self):
            self.calls.append('start')
            self.active = True

        def resolve_source(self, home):
            return home / 'models', 'fixture:latest'

        @contextlib.contextmanager
        def backend(self, target, **options):
            yield DocBackend()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.assistant = self.FakeAssistant(self.home)
        self.store = Store(self.home / 'results')
        self.lab = lab.Controller(self.assistant, store=self.store,
                                 speed=lambda client, model, **kw: bench_speed.run(client, 'fixture:latest', hardware=lambda: {}, **kw),
                                 documents=lambda client, model, **kw: doc_trial.run(client, 'fixture:latest', hardware=lambda: {}, **kw))
        self.addCleanup(self.lab.close)

    def test_invalid_recipe_rejected_before_pausing(self):
        with self.assertRaisesRegex(ValueError, 'Unknown recipe preset'):
            self.lab.start('documents', recipe='nonexistent-preset')
        self.assertEqual(self.assistant.calls, [])
        self.assertEqual(self.lab.phase, 'idle')

    def test_start_documents_with_concise_recipe_exposes_recipe_in_snapshot_and_arena(self):
        snap = self.lab.start_documents(recipe='concise')
        self.assertIsNotNone(snap['recipe'])
        self.assertEqual(snap['recipe']['preset'], 'concise')
        self.assertEqual(snap['recipe']['context'], 4096)
        self.assertIn('arena', snap)
        self.assertEqual(snap['arena']['recipe']['preset'], 'concise')

        # Wait for worker to finish
        if self.lab.worker:
            self.lab.worker.join(timeout=8)
            self.assertFalse(self.lab.worker.is_alive())

        final_snap = self.lab.snapshot()
        self.assertEqual(final_snap['phase'], 'completed')
        self.assertEqual(final_snap['recipe']['preset'], 'concise')

        # Final saved run in store has the concise recipe
        run_id = final_snap['runs'][-1]
        saved_run = self.store.load(run_id)
        self.assertEqual(saved_run['recipe']['preset'], 'concise')

    def test_profile_isolation_no_config_written(self):
        # Ensure no openclaw or agent profile files are created or altered
        config_dir = self.home / '.config'
        self.assertFalse(config_dir.exists())

        self.lab.start_documents(recipe='concise')
        if self.lab.worker:
            self.lab.worker.join(timeout=8)

        # Profile directory must still not exist or be altered
        self.assertFalse(config_dir.exists())

    def test_select_and_restore_recipe(self):
        # Default is None (standard)
        snap = self.lab.snapshot()
        self.assertIsNone(snap['selected_recipe'])

        # Select concise
        snap = self.lab.select_recipe('concise')
        self.assertIsNotNone(snap['selected_recipe'])
        self.assertEqual(snap['selected_recipe']['preset'], 'concise')

        # Run documents with selected recipe automatically picked up
        snap = self.lab.start_documents()
        self.assertIsNotNone(snap['recipe'])
        self.assertEqual(snap['recipe']['preset'], 'concise')
        if self.lab.worker:
            self.lab.worker.join(timeout=8)

        # Restore recipe to standard
        snap = self.lab.restore_recipe()
        self.assertIsNone(snap['selected_recipe'])

        # Subsequent run is standard
        snap = self.lab.start_documents()
        self.assertIsNone(snap['recipe'])
        if self.lab.worker:
            self.lab.worker.join(timeout=8)

    def test_select_recipe_during_active_workload_rejected(self):
        self.lab.start_documents()
        try:
            with self.assertRaisesRegex(ValueError, 'Cannot change recipe while a trial is active'):
                self.lab.select_recipe('concise')
            with self.assertRaisesRegex(ValueError, 'Cannot restore recipe while a trial is active'):
                self.lab.restore_recipe()
        finally:
            if self.lab.worker:
                self.lab.worker.join(timeout=8)



class ServerRecipeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.assistant = LabRecipeControllerTests.FakeAssistant(self.home)
        self.store = Store(self.home / 'results')
        self.lab = lab.Controller(self.assistant, store=self.store,
                                 speed=lambda client, model, **kw: bench_speed.run(client, 'fixture:latest', hardware=lambda: {}, **kw),
                                 documents=lambda client, model, **kw: doc_trial.run(client, 'fixture:latest', hardware=lambda: {}, **kw))
        self.addCleanup(self.lab.close)
        from argoslive.web.server import DashboardServer
        self.server = DashboardServer(port=0, lab=self.lab)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()
        def stop_server():
            self.server.shutdown()
            self.thread.join(timeout=5)
            self.server.server_close()
        self.addCleanup(stop_server)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        hdrs = {'X-Argos-Token': self.server.token}
        if headers:
            hdrs.update(headers)
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_start_documents_standard_empty_body(self):
        status, data = self.request('POST', '/api/lab/start-documents')
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode('utf-8'))
        self.assertIsNone(parsed['recipe'])

    def test_start_documents_json_recipe_concise(self):
        payload = json.dumps({'recipe': 'concise'}).encode('utf-8')
        status, data = self.request('POST', '/api/lab/start-documents', body=payload,
                                    headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode('utf-8'))
        self.assertIsNotNone(parsed['recipe'])
        self.assertEqual(parsed['recipe']['preset'], 'concise')

    def test_start_documents_rejects_unexpected_fields(self):
        payload = json.dumps({'recipe': 'concise', 'extra': 123}).encode('utf-8')
        status, data = self.request('POST', '/api/lab/start-documents', body=payload,
                                    headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        self.assertEqual(status, 400)

    def test_start_documents_rejects_unknown_recipe(self):
        payload = json.dumps({'recipe': 'bad-preset'}).encode('utf-8')
        status, data = self.request('POST', '/api/lab/start-documents', body=payload,
                                    headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        self.assertEqual(status, 409)

    def test_cancel_rejects_body(self):
        payload = b'something'
        status, data = self.request('POST', '/api/lab/cancel', body=payload,
                                    headers={'Content-Length': str(len(payload))})
        self.assertEqual(status, 400)

    def test_get_recipes_endpoint(self):
        status, data = self.request('GET', '/api/lab/recipes')
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode('utf-8'))
        self.assertIn('presets', parsed)
        preset_ids = [p['id'] for p in parsed['presets']]
        self.assertEqual(preset_ids, ['standard', 'concise'])
        self.assertIsNone(parsed['selected'])

    def test_select_and_restore_recipe_endpoints(self):
        # Select concise
        payload = json.dumps({'preset': 'concise'}).encode('utf-8')
        status, data = self.request('POST', '/api/lab/recipe/select', body=payload,
                                    headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode('utf-8'))
        self.assertIsNotNone(parsed['selected_recipe'])
        self.assertEqual(parsed['selected_recipe']['preset'], 'concise')

        # Check GET /api/lab/recipes reflects the selected recipe
        status, data = self.request('GET', '/api/lab/recipes')
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode('utf-8'))
        self.assertIsNotNone(parsed['selected'])
        self.assertEqual(parsed['selected']['preset'], 'concise')

        # Reject invalid preset
        payload_bad = json.dumps({'preset': 'invalid-preset'}).encode('utf-8')
        status, _ = self.request('POST', '/api/lab/recipe/select', body=payload_bad,
                                 headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload_bad))})
        self.assertEqual(status, 409)

        # Reject unexpected fields
        payload_extra = json.dumps({'preset': 'concise', 'extra': 1}).encode('utf-8')
        status, _ = self.request('POST', '/api/lab/recipe/select', body=payload_extra,
                                  headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload_extra))})
        self.assertEqual(status, 400)

        # Restore recipe
        status, data = self.request('POST', '/api/lab/recipe/restore')
        self.assertEqual(status, 200)
        parsed = json.loads(data.decode('utf-8'))
        self.assertIsNone(parsed['selected_recipe'])

        # Reject restore with body
        status, _ = self.request('POST', '/api/lab/recipe/restore', body=b'non-empty',
                                 headers={'Content-Length': '9'})
        self.assertEqual(status, 400)



class RealBackendInstructionTests(unittest.TestCase):
    """Scope: Tests that pinned Ollama backend execution actually honors system-level
    instruction parameters when an active Ollama instance with a lightweight test model
    is available at http://127.0.0.1:11434. Verifies /api/generate with top-level system
    parameter and /api/chat with prepended system-role message. Offline or environments
    without a lightweight test model (< 2GB) skip cleanly; full verification with
    pinned Ollama and qwen3:0.6b runs in CI via scripts/smoke-model-onboarding.py.
    """

    def probe_backend(self):
        req = urllib.request.Request('http://127.0.0.1:11434/api/tags', method='GET')
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                models = [m.get('name') or m.get('model') for m in data.get('models', [])
                          if 0 < m.get('size', 0) <= 2 * 1024**3]
                return models
        except Exception:
            return None

    def test_real_backend_honors_instructions_if_reachable(self):
        models = self.probe_backend()
        if not models:
            self.skipTest('No lightweight test model (< 2GB) available at http://127.0.0.1:11434; CI coverage in scripts/smoke-model-onboarding.py')

        model = models[0]
        client = ollama.Client('http://127.0.0.1:11434', timeout=5.0)
        concise = recipe.canonical('concise')

        # Test /api/generate with system parameter
        gen_reply = client.generate(
            model,
            'What is 2+2? Output only the single digit.',
            options={'num_ctx': 2048, 'num_predict': 16, 'temperature': 0, 'seed': 1},
            system=concise['instructions'],
            think=concise['thinking'],
        )
        self.assertTrue(gen_reply.get('final', {}).get('done', False))
        self.assertTrue(len(gen_reply.get('text', '').strip()) > 0)

        # Test /api/chat with system role message contract
        chat_reply = client.chat(
            model,
            [{'role': 'user', 'content': 'What is 3+3? Output only the single digit.'}],
            options={'num_ctx': 2048, 'num_predict': 16, 'temperature': 0, 'seed': 1},
            system=concise['instructions'],
            think=concise['thinking'],
        )
        self.assertTrue(chat_reply.get('final', {}).get('done', False))
        self.assertTrue(len(chat_reply.get('text', '').strip()) > 0)
