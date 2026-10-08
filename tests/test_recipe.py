import contextlib
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))

from argoslive import bench_ability, bench_speed, doc_trial, hw, lab, ollama, recipe, results
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

    def test_standard_with_custom_instructions_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Standard calibration cannot carry custom instructions'):
            recipe.canonical('standard', instructions='Be creative')

    def test_instructions_validation_and_bounds(self):
        # Empty string rejected
        with self.assertRaisesRegex(ValueError, 'Instructions must be 1 to 1024 characters'):
            recipe.canonical('concise', instructions='')

        # Too long rejected
        with self.assertRaisesRegex(ValueError, 'Instructions must be 1 to 1024 characters'):
            recipe.canonical('concise', instructions='a' * 1025)

        # Control characters rejected
        with self.assertRaisesRegex(ValueError, 'Instructions contain invalid control characters'):
            recipe.canonical('concise', instructions='Hello\x00World')
        with self.assertRaisesRegex(ValueError, 'Instructions contain invalid control characters'):
            recipe.canonical('concise', instructions='Hello\x1bWorld')

        # Valid custom instruction within bounds
        custom = recipe.canonical('concise', instructions='Answer strictly in JSON.')
        self.assertEqual(custom['instructions'], 'Answer strictly in JSON.')
        self.assertEqual(custom['instruction_hash'], hashlib.sha256(b'Answer strictly in JSON.').hexdigest())

    def test_numeric_and_enum_bounds(self):
        # Context bounds: 256 to 131072
        with self.assertRaisesRegex(ValueError, 'Context must be an integer between 256 and 131072'):
            recipe.canonical('standard', context=100)
        with self.assertRaisesRegex(ValueError, 'Context must be an integer between 256 and 131072'):
            recipe.canonical('standard', context=200000)

        # Output cap bounds: 1 to 131072
        with self.assertRaisesRegex(ValueError, 'Output cap must be an integer'):
            recipe.canonical('standard', output_cap=0)
        with self.assertRaisesRegex(ValueError, 'Output cap must be an integer'):
            recipe.canonical('standard', output_cap=200000)

        # Temperature bounds: 0.0 to 2.0
        with self.assertRaisesRegex(ValueError, 'Temperature must be a number between 0 and 2.0'):
            recipe.canonical('standard', temperature=-0.1)
        with self.assertRaisesRegex(ValueError, 'Temperature must be a number between 0 and 2.0'):
            recipe.canonical('standard', temperature=2.5)

        # Seed: non-negative integer
        with self.assertRaisesRegex(ValueError, 'Seed must be a non-negative integer'):
            recipe.canonical('standard', seed=-1)

        # Thinking: True, False, None
        with self.assertRaisesRegex(ValueError, 'Thinking mode must be True, False, or None'):
            recipe.canonical('standard', thinking='yes')

        # Request format: 'generate' or 'chat'
        with self.assertRaisesRegex(ValueError, "Request format must be 'generate' or 'chat'"):
            recipe.canonical('standard', request_format='completion')

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
        custom = recipe.canonical('concise', instructions='Be brief.')
        res_dict = recipe.resolve(custom)
        self.assertEqual(res_dict, custom)
        self.assertIsNot(res_dict, custom)

        # Invalid type rejected
        with self.assertRaisesRegex(ValueError, 'Recipe specification must be a preset name'):
            recipe.resolve(12345)


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
        concise_recipe = recipe.canonical('concise')
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
        rec = recipe.canonical('concise')
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
        import http.client
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
