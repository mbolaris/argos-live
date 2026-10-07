import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import bench_speed, mission_report
from argoslive.ollama import Cancelled
from test_bench_speed import Backend
from test_results import ability_result


class DebriefBackend:
    timeout = 120
    def generate(self, model, prompt, **kwargs):
        self.prompt, self.options, self.observed_timeout = prompt, kwargs, self.timeout
        return {'text': '<script>untrusted model output</script> ' + 'x' * 1500}


class MissionReportTests(unittest.TestCase):
    def setUp(self):
        self.speed = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {})
        self.ability = ability_result()
        self.runs = [self.speed, self.ability]

    def test_receipt_uses_measured_median_and_separate_ability_counts(self):
        receipt = mission_report.summarize(self.runs)
        self.assertEqual(receipt['speed']['tokens_per_second'], 20)
        self.assertEqual(receipt['ability']['correct'], 20)
        self.assertEqual(receipt['ability']['total'], 20)
        self.assertIsNone(receipt['ability']['qualified'])
        self.assertIn('not an intelligence score', receipt['ability']['scope'])

    def test_opinion_has_only_aggregate_input_and_cannot_change_scores(self):
        self.ability['items'][0]['output'] = 'PRIVATE_DOCUMENT_OR_TOKEN'
        backend = DebriefBackend()
        value = mission_report.debrief(backend, 'fixture:latest', self.runs)
        self.assertEqual(value['state'], 'completed')
        self.assertLessEqual(len(value['text']), 1200)
        self.assertNotIn('PRIVATE_DOCUMENT', backend.prompt)
        self.assertNotIn(self.ability['id'], backend.prompt)
        self.assertEqual(value['runs'], [r['id'] for r in self.runs])
        self.assertEqual(backend.timeout, 120)
        self.assertEqual(backend.observed_timeout, 45)
        self.assertFalse(backend.options['think'])
        self.assertEqual(self.ability['summary']['correct'], 20)

    def test_unidentified_mixed_or_incomplete_evidence_gets_no_opinion(self):
        for change in ({'manifest_digest': None}, {'manifest_digest': 'b' * 64}, {'state': 'cancelled'}):
            runs = [self.speed, dict(self.ability, **change)]
            self.assertEqual(mission_report.debrief(object(), 'fixture:latest', runs), {'state': 'unavailable'})

    def test_opinion_failure_is_private_and_does_not_fail_scores(self):
        class Broken(DebriefBackend):
            def generate(self, *a, **k):
                raise RuntimeError('PRIVATE_EXCEPTION')
        backend = Broken()
        self.assertEqual(mission_report.debrief(backend, 'fixture:latest', self.runs), {'state': 'unavailable'})
        self.assertEqual(backend.timeout, 120)
        self.assertEqual(self.ability['state'], 'completed')

    def test_cancel_propagates_and_timeout_is_restored(self):
        class Stopped(DebriefBackend):
            def generate(self, *a, **k):
                raise Cancelled('stopped')
        backend = Stopped()
        with self.assertRaises(Cancelled):
            mission_report.debrief(backend, 'fixture:latest', self.runs, cancel=threading.Event())
        self.assertEqual(backend.timeout, 120)

    def test_receipt_replay_resolves_prompts_and_explains_outcomes(self):
        receipt = mission_report.summarize(self.runs)
        rep = receipt['ability']['replay']
        self.assertGreater(len(rep['passed']), 0)
        first_pass = rep['passed'][0]
        self.assertIn('prompt', first_pass)
        self.assertTrue(len(first_pass['prompt']) > 0)
        self.assertTrue(first_pass['reason'].startswith('Passed:'))

        # Test failure resolution
        wrong_ability = ability_result('wrong')
        wrong_receipt = mission_report.summarize([self.speed, wrong_ability])
        wrong_rep = wrong_receipt['ability']['replay']
        self.assertGreater(len(wrong_rep['failed']), 0)
        first_fail = wrong_rep['failed'][0]
        self.assertIn('prompt', first_fail)
        self.assertTrue(len(first_fail['prompt']) > 0)
        self.assertTrue(first_fail['reason'].startswith('Missed:'))


if __name__ == '__main__':
    unittest.main()

