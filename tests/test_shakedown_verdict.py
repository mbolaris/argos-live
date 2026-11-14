from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.shakedown import verdict


def run(scores, *, suite_version='ability/quick/1.0.0', slice_name='full'):
    return {'suite_version': suite_version, 'slice': slice_name, 'state': 'completed',
            'items': [{'id': f'item-{index:02}', 'score': score} for index, score in enumerate(scores)]}


class VerdictTests(unittest.TestCase):
    def test_identical_runs_are_too_close_with_all_shared_counts(self):
        result = verdict.compare(run([1, 0, 1]), run([1, 0, 1]))
        self.assertEqual((result['verdict'], result['wins'], result['losses'], result['ties']),
                         ('too-close', 0, 0, 3))

    def test_repeated_paired_gain_and_loss_use_exact_sign_test(self):
        gain = verdict.compare(run([0] * 8), run([1] * 8))
        loss = verdict.compare(run([1] * 8), run([0] * 8))
        self.assertEqual(gain['verdict'], 'better')
        self.assertAlmostEqual(gain['p_value'], 2 / 256)
        self.assertEqual(loss['verdict'], 'worse')

    def test_small_difference_reports_additional_questions_at_observed_rate(self):
        baseline, candidate = run([0, 0]), run([1, 1])
        baseline['suite_total'] = candidate['suite_total'] = 8
        result = verdict.compare(baseline, candidate)
        self.assertEqual(result['verdict'], 'too-close')
        self.assertEqual(result['additional_shared_questions'], 4)

    def test_refuses_no_shared_items_or_mismatched_form_or_slice(self):
        with self.assertRaisesRegex(ValueError, 'no shared scored items'):
            verdict.compare(run([1]), {'suite_version': 'ability/quick/1.0.0', 'slice': 'full',
                                       'state': 'completed',
                                       'items': [{'id': 'another-item', 'score': 1}]})
        with self.assertRaisesRegex(ValueError, 'different form versions'):
            verdict.compare(run([1]), run([1], suite_version='other'))
        with self.assertRaisesRegex(ValueError, 'different slices'):
            verdict.compare(run([1]), run([1], slice_name='quick'))

    def test_refuses_incomplete_runs_and_unknown_form_versions(self):
        incomplete = run([1])
        incomplete['state'] = 'cancelled'
        with self.assertRaisesRegex(ValueError, 'Incomplete runs'):
            verdict.compare(incomplete, run([1]))
        unknown = run([1])
        unknown.pop('suite_version')
        with self.assertRaisesRegex(ValueError, 'version is not recorded'):
            verdict.compare(unknown, run([1]))

    def test_speed_compares_repeated_measurements_and_spread(self):
        result = verdict.compare_speed({'measurements': [{'tokens_per_second': 20},
                                                           {'tokens_per_second': 21}]},
                                       {'measurements': [{'tokens_per_second': 25},
                                                           {'tokens_per_second': 26}]})
        self.assertEqual(result['verdict'], 'better')
        self.assertEqual(result['measurements'], {'baseline': 2, 'candidate': 2})


if __name__ == '__main__':
    unittest.main()
