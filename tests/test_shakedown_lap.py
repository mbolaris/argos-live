from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.shakedown import lap


class LapTests(unittest.TestCase):
    def test_slices_are_fixed_nested_and_plan_starts_with_speed(self):
        for suite in lap.DEFAULT_FORMS:
            quick = lap.slice_item_ids(suite, 'quick')
            standard = lap.slice_item_ids(suite, 'standard')
            full = lap.slice_item_ids(suite, 'full')
            self.assertTrue(set(quick) <= set(standard), suite)
            self.assertTrue(set(standard) <= set(full), suite)
        plan = lap.build('quick', ('quick', 'tool-schema'))
        self.assertEqual(plan['steps'][0], {'kind': 'speed', 'suite_version': 'speed/1'})
        self.assertEqual([step['suite'] for step in plan['steps'][1:]], ['quick', 'tool-schema'])
        self.assertTrue(lap.validate(plan))

    def test_plan_rejects_changed_slice_ids_and_unknown_or_duplicate_forms(self):
        plan = lap.build('quick', ('quick',))
        tampered = copy.deepcopy(plan)
        tampered['steps'][1]['item_ids'][0] = 'invented-item'
        with self.assertRaisesRegex(ValueError, 'fixed form slice'):
            lap.validate(tampered)
        with self.assertRaisesRegex(ValueError, 'supported'):
            lap.build('quick', ('owner-recovery-decision',))
        with self.assertRaisesRegex(ValueError, 'unique'):
            lap.build('quick', ('quick', 'quick'))

    def test_estimate_is_unknown_without_both_prior_measurements(self):
        plan = lap.build('quick', ('quick',))
        self.assertEqual(lap.estimate(plan, {})['label'], 'unknown until the first lap')
        self.assertEqual(lap.estimate(plan, {'latest_speed': {'elapsed_seconds': 300}})['known'], False)

    def test_estimate_uses_speed_elapsed_and_last_run_median(self):
        plan = lap.build('quick', ('quick', 'tool-schema'))
        loadout = {'latest_speed': {'elapsed_seconds': 180},
                   'last_run': {'items': [{'latency_seconds': 2}, {'latency_seconds': 4},
                                          {'latency_seconds': 6}]}}
        result = lap.estimate(plan, loadout)
        expected = 180 + (10 + 10) * 4
        self.assertEqual(result['expected_seconds'], expected)
        self.assertIn('about', result['label'])
        self.assertLess(result['minimum_seconds'], result['expected_seconds'])
        self.assertGreater(result['maximum_seconds'], result['expected_seconds'])

    def test_execution_runs_speed_then_each_form_one_at_a_time(self):
        class JobsFixture:
            def __init__(self):
                self.calls = []
                self.active = False

            def start(self, suite, **options):
                if self.active:
                    raise AssertionError('overlapping evaluation jobs')
                self.active = True
                self.calls.append((suite, options))
                return {'status': 'running', 'job_id': str(len(self.calls))}

            def wait(self, job_id, **_options):
                self.active = False
                return {'status': 'completed', 'job_id': job_id,
                        'result': {'id': 'f' * 32, 'state': 'completed'}}

            def cancel_owner(self, _job_id):
                raise AssertionError('unexpected cancellation')

        jobs = JobsFixture()
        plan = lap.build('quick', ('quick', 'tool-schema'))
        result = lap.execute(plan, jobs, poll_seconds=.1)
        self.assertTrue(result['complete'])
        self.assertEqual([call[0] for call in jobs.calls], ['speed', 'quick', 'tool-schema'])
        self.assertEqual(jobs.calls[0][1]['lap_id'], result['lap_id'])
        self.assertEqual(jobs.calls[1][1]['slice_name'], 'quick')
        self.assertEqual(jobs.calls[2][1]['slice_version'], lap.SLICE_VERSION)


if __name__ == '__main__':
    unittest.main()
