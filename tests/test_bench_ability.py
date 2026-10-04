import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, bench_ability as bench
from argoslive.ollama import Cancelled, Interrupted
from test_bench_speed import Backend


class AbilityBackend(Backend):
    def __init__(self, answer='reference', suite='quick', **kwargs):
        super().__init__(**kwargs)
        self.answers = {item['prompt']: item[answer] for item in ability.load(suite)['items']}
        self.error_after = None

    def generate(self, model, prompt, **kwargs):
        if prompt and self.error_after == self.responses:
            raise Interrupted('Authored interruption')
        result = super().generate(model, prompt, **kwargs)
        if prompt:
            result['text'] = self.answers[prompt]
        return result


class AbilityRunTests(unittest.TestCase):
    def test_exact_scores_and_measurements_for_all_fixture_outcomes(self):
        for field, correct, format_errors in [('reference', 20, 0), ('wrong', 0, 0), ('malformed', 0, 20)]:
            with self.subTest(field=field):
                backend = AbilityBackend(field)
                progress = []
                result = bench.run(backend, 'fixture:latest', hardware=lambda: {}, progress=progress.append)
                self.assertEqual(result['summary']['correct'], correct)
                self.assertEqual(result['summary']['format_errors'], format_errors)
                self.assertEqual(result['summary']['total'], 20)
                self.assertEqual(len(result['summary']['categories']), 5)
                self.assertEqual(result['suite_version'], 'ability/quick/1.0.0')
                self.assertEqual(result['omitted_categories'], ['code-execution'])
                self.assertTrue(result['coverage']['complete'])
                self.assertTrue(result['restoration']['succeeded'])
                self.assertEqual(backend.loaded[0]['name'], 'previous:fixture')
                self.assertIsNone(progress[0]['eta_seconds'])
                self.assertEqual(progress[-1]['eta_seconds'], 0)
                self.assertEqual(progress[-1]['completed'], 20)
                for item in result['items']:
                    self.assertEqual(item['measurement']['backend']['mode'], 'CPU')
                    self.assertGreaterEqual(item['latency_seconds'], 0)
                    self.assertFalse(item['tool_execution_verified'])
                for call in backend.calls:
                    if call[0] == 'generate' and call[2]:
                        self.assertEqual(call[3]['options'], {'num_ctx': 2048, 'num_predict': 128,
                                                            'temperature': 0, 'seed': 1})
                        self.assertFalse(call[3]['think'])

    def test_standard_has_separate_version_and_coverage(self):
        result = bench.run(AbilityBackend(suite='standard', previous=False), 'fixture:latest',
                           suite='standard', hardware=lambda: {})
        self.assertEqual(result['summary']['correct'], 70)
        self.assertEqual(result['suite_version'], 'ability/standard/1.0.0')
        self.assertIsNone(result['restoration']['previous_model'])

    def test_cancel_preserves_partial_evidence_and_restores(self):
        backend = AbilityBackend()
        event = threading.Event()
        def progress(value):
            if value['completed'] == 3:
                event.set()
        result = bench.run(backend, 'fixture:latest', hardware=lambda: {}, cancel=event, progress=progress)
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(result['coverage'], {'completed': 3, 'total': 20, 'complete': False})
        self.assertEqual(result['summary']['correct'], 3)
        self.assertTrue(result['restoration']['succeeded'])
        self.assertEqual(backend.loaded[0]['name'], 'previous:fixture')
        event.set()
        result = bench.run(AbilityBackend(), 'fixture:latest', hardware=lambda: {}, cancel=event)
        self.assertIsNone(result['summary']['accuracy'])

    def test_generation_cancel_and_failure_cleanup(self):
        backend = AbilityBackend()
        backend.error_after = 2
        with self.assertRaises(Interrupted):
            bench.run(backend, 'fixture:latest', hardware=lambda: {})
        self.assertEqual(backend.loaded[0]['name'], 'previous:fixture')
        original = backend.generate
        def cancelled(model, prompt, **kwargs):
            if prompt:
                raise Cancelled('fixture')
            return original(model, prompt, **kwargs)
        backend.generate = cancelled
        result = bench.run(backend, 'fixture:latest', hardware=lambda: {})
        self.assertEqual(result['state'], 'cancelled')
        self.assertTrue(result['restoration']['succeeded'])

    def test_prerequisites_checked_before_mutating_backend(self):
        for backend, model in [(AbilityBackend(context=None), 'fixture:latest'),
                               (AbilityBackend(context=1024), 'fixture:latest'),
                               (AbilityBackend(), 'missing:tag')]:
            with self.assertRaises(ValueError):
                bench.run(backend, model, hardware=lambda: {})
            self.assertEqual(backend.calls, [])
        backend = AbilityBackend()
        backend.loaded.append({'name': 'second:fixture'})
        with self.assertRaises(ValueError):
            bench.run(backend, 'fixture:latest', hardware=lambda: {})
        self.assertEqual(backend.calls, [])

    def test_raw_output_bounded_and_think_unknown_not_assumed(self):
        backend = AbilityBackend()
        backend.answers = {prompt: 'x' * (ability.LIMIT + 1) for prompt in backend.answers}
        show = backend.show
        backend.show = lambda model: dict(show(model), capabilities=[])
        result = bench.run(backend, 'fixture:latest', hardware=lambda: {})
        self.assertIsNone(result['settings']['think'])
        self.assertEqual(result['summary']['format_errors'], 20)
        for item in result['items']:
            self.assertTrue(item['output_truncated'])
            self.assertEqual(len(item['output']), bench.OUTPUT_LIMIT)

    def test_cli_round_trip_and_timeout_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            original = bench.run
            with patch.object(bench, 'Client', return_value=AbilityBackend()), patch.object(
                    bench, 'run', side_effect=lambda client, model, **kw: original(client, model, hardware=lambda: {}, **kw)), patch('builtins.print'):
                self.assertEqual(bench.main(['--model', 'fixture:latest', '--results-dir', temp, '--json']), 0)
            result = json.loads(next(Path(temp).glob('*.json')).read_text())
            self.assertEqual(result['summary']['accuracy'], 1)
        for timeout in ('0', '601'):
            with self.assertRaises(ValueError):
                bench.main(['--model', 'fixture:latest', '--timeout', timeout])


if __name__ == '__main__':
    unittest.main()
