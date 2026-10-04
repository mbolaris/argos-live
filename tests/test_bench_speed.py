import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_speed as bench
from argoslive.ollama import Interrupted

FIXTURE = json.loads((ROOT / 'tests/fixtures/ollama/responses.json').read_text())


class Backend:
    def __init__(self, context=4096, previous=True):
        self.context = context
        self.calls = []
        self.loaded = [{'name': 'previous:fixture', 'context_length': 2048}] if previous else []
        self.responses = 0
        self.fail = False

    def version(self):
        return '0.35.0'

    def list(self):
        return {'models': [{'name': 'fixture:latest', 'digest': 'sha256:' + 'a' * 64}]}

    def show(self, model):
        value = copy.deepcopy(FIXTURE['show'])
        value['model_info']['general.architecture'] = 'fixture'
        value['model_info']['fixture.context_length'] = self.context
        return value

    def ps(self):
        return {'models': copy.deepcopy(self.loaded)}

    def unload(self, model):
        self.calls.append(('unload', model))
        self.loaded = []

    def generate(self, model, prompt, **kwargs):
        self.calls.append(('generate', model, prompt, kwargs))
        if not prompt:
            self.loaded = [{'name': model, 'context_length': kwargs['options'].get('num_ctx')}]
            return {'final': {'done': True}}
        if self.fail:
            raise Interrupted('authored interrupted fixture')
        self.responses += 1
        self.loaded = [{'name': model, 'size': 1000, 'size_vram': 0}]
        final = copy.deepcopy(FIXTURE['generate'][-1])
        # Warmups are obvious outliers; measured values give deterministic median/range.
        final['eval_count'] = [1000, 10, 20, 30][(self.responses - 1) % 4]
        final['eval_duration'] = 10**9
        return {'final': final, 'text': 'Authored reply', 'time_to_first_token_seconds': 0.2,
                'elapsed_seconds': 1.2}


class BenchTests(unittest.TestCase):
    def test_three_measured_runs_exclude_warmup_and_separate_cold_load(self):
        backend = Backend()
        times = iter([10, 20])
        result = bench.run(backend, 'fixture:latest', hardware=lambda: {'fixture': True},
                           clock=lambda: next(times))
        self.assertEqual(result['schema'], 'argos-bench/1')
        self.assertEqual(result['cold']['measurement']['raw']['load_duration'], 200000000)
        self.assertEqual(result['cold']['measurement']['raw']['eval_count'], 1000)
        self.assertFalse(result['cold']['filesystem_caches_cleared'])
        for prompt in result['prompts'][:2]:
            self.assertEqual(len(prompt['runs']), 3)
            self.assertEqual(prompt['summary']['generation_tokens_per_second'],
                             {'median': 20, 'min': 10, 'max': 30, 'reported_runs': 3, 'total_runs': 3})
            self.assertEqual(prompt['runs'][0]['backend']['mode'], 'CPU')
            self.assertIsNone(prompt['runs'][0]['backend']['offloaded_layers'])
        self.assertTrue(result['prompts'][2]['skipped'])
        self.assertEqual(result['elapsed_seconds'], 10)
        self.assertTrue(result['restoration']['succeeded'])
        self.assertEqual(backend.calls[-1][1:3], ('previous:fixture', ''))
        self.assertEqual(backend.calls[-1][3]['options'], {'num_ctx': 2048})
        for call in backend.calls:
            if call[0] == 'generate' and call[2]:
                self.assertFalse(call[3]['think'])
                self.assertEqual(call[3]['options']['num_predict'], 128)

    def test_long_context_and_unknown_context_have_explicit_coverage(self):
        large = bench.run(Backend(context=32768, previous=False), 'fixture:latest', hardware=lambda: {})
        self.assertEqual([p['skipped'] for p in large['prompts']], [False, False, False])
        unknown = bench.run(Backend(context=None, previous=False), 'fixture:latest', hardware=lambda: {})
        self.assertTrue(all(p['skipped'] for p in unknown['prompts']))
        self.assertIsNone(unknown['cold'])

    def test_missing_timings_and_invalid_numeric_values_are_null(self):
        result = bench.measurement({'final': {'eval_count': 2}, 'elapsed_seconds': float('inf')}, [], 'x')
        self.assertIsNone(result['generation_tokens_per_second'])
        self.assertIsNone(result['elapsed_seconds'])
        self.assertIsNone(result['backend']['mode'])
        self.assertIsNone(bench.rate(10, 0))
        self.assertIsNone(bench.numeric(True))
        self.assertEqual(bench.summary([None, 2, 4]),
                         {'median': 3, 'min': 2, 'max': 4, 'reported_runs': 2, 'total_runs': 3})
        self.assertIsNone(bench.summary([None])['median'])

    def test_backend_modes_are_reported_without_guessed_layer_counts(self):
        for vram, expected in ((0, 'CPU'), (500, 'split'), (1000, 'GPU'), (None, None), (2000, None)):
            record = bench.placement([{'name': 'x', 'size': 1000, 'size_vram': vram}], 'x')
            self.assertEqual(record['mode'], expected)
            self.assertIsNone(record['offloaded_layers'])

    def test_failure_restores_previous_and_multiple_loaded_models_refused(self):
        backend = Backend()
        backend.fail = True
        with self.assertRaises(Interrupted):
            bench.run(backend, 'fixture:latest', hardware=lambda: {})
        self.assertEqual(backend.loaded[0]['name'], 'previous:fixture')
        backend = Backend()
        backend.loaded.append({'name': 'second:fixture'})
        with self.assertRaises(ValueError):
            bench.run(backend, 'fixture:latest', hardware=lambda: {})
        self.assertEqual(backend.calls, [])

    def test_cli_saves_result_without_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bench, 'Client', return_value=Backend()), patch.object(bench.hw, 'snapshot'):
                # Pass real public fixture hardware because run's default is bound at definition.
                original = bench.run
                with patch.object(bench, 'run', side_effect=lambda client, model, **kw: original(client, model, hardware=lambda: {}, **kw)):
                    with patch('builtins.print'):
                        bench.main(['--model', 'fixture:latest', '--results-dir', tmp, '--json'])
            files = list(Path(tmp).glob('*.json'))
            self.assertEqual(len(files), 1)
            result = json.loads(files[0].read_text())
            self.assertEqual(result['kind'], 'speed')
            self.assertEqual(result['suite_version'], 'speed/1')

    def test_short_only_selection_is_recorded_and_validated(self):
        result = bench.run(Backend(previous=False), 'fixture:latest', sizes=['short'], hardware=lambda: {})
        self.assertEqual(result['settings']['prompt_sizes'], ['short'])
        self.assertEqual(len(result['prompts']), 1)
        self.assertEqual(len(result['prompts'][0]['runs']), 3)
        for sizes in ([], ['short', 'short'], ['invalid']):
            with self.assertRaises(ValueError):
                bench.run(Backend(), 'fixture:latest', sizes=sizes)

    def test_timeout_bounds_and_cli_backend_failure_are_clear(self):
        for timeout in ('0', '601'):
            with self.assertRaises(ValueError):
                bench.main(['--model', 'fixture:latest', '--timeout', timeout])
        with patch.object(bench, 'run', side_effect=Interrupted('fixture')):
            with self.assertRaisesRegex(ValueError, 'No successful result'):
                bench.main(['--model', 'fixture:latest', '--timeout', '600', '--size', 'long'])
