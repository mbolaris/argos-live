import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('smoke_hard_form_real', ROOT / 'scripts/smoke-hard-form-real.py')
CALIBRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALIBRATION)


class EV2CalibrationTests(unittest.TestCase):
    def result(self, suite, total, category_names):
        per_category = CALIBRATION.SAMPLE_PER_CATEGORY
        correct_per_category = 2
        categories = {name: {'correct': correct_per_category,
                             'total': per_category, 'format_errors': 0}
                      for name in category_names}
        sample_total = per_category * len(category_names)
        correct = correct_per_category * len(category_names)
        return {'suite': 'openclaw-' + suite, 'suite_version': 'argos-openclaw-ability/' + suite + '/1.0.0',
                'model': 'ollama/qwen3:4b-instruct-2507-q4_K_M', 'state': 'completed',
                'coverage': {'completed': sample_total, 'total': sample_total, 'complete': True},
                'summary': {'correct': correct, 'total': sample_total,
                            'format_errors': 0, 'categories': categories,
                            'partitions': {'practice': {'correct': correct, 'total': sample_total,
                                                        'format_errors': 0}},
                            'items': [{'item_id': 'heldout-secret-id', 'output': 'private answer'}]}}

    def test_public_calibration_receipt_contains_aggregates_only(self):
        cases = [('challenge-hard', 80, ['numeric', 'choice', 'instruction', 'json', 'tool-call']),
                 ('documents-long', 40, ['answer', 'quote', 'not_stated', 'summary'])]
        for suite, total, categories in cases:
            with self.subTest(suite=suite):
                sample_total = CALIBRATION.SAMPLE_PER_CATEGORY * len(categories)
                receipt = CALIBRATION.public_receipt(self.result(suite, total, categories), sample_total)
                rendered = str(receipt)
                self.assertEqual(receipt['score']['percent'], round(200 / 3, 1))
                self.assertTrue(receipt['in_target_band'])
                self.assertEqual(receipt['coverage']['full_suite_items'], total)
                self.assertEqual(receipt['coverage']['heldout_items_sampled'], 0)
                self.assertFalse(receipt['raw_answers_exported'])
                self.assertFalse(receipt['prompts_exported'])
                self.assertNotIn('heldout-secret-id', rendered)
                self.assertNotIn('private answer', rendered)

    def test_public_calibration_refuses_partial_or_heldout_evidence(self):
        data = self.result('challenge-hard', 80, ['numeric', 'choice', 'instruction', 'json', 'tool-call'])
        sample_total = CALIBRATION.SAMPLE_PER_CATEGORY * 5
        data['coverage']['completed'] = sample_total - 1
        with self.assertRaisesRegex(ValueError, 'complete'):
            CALIBRATION.public_receipt(data, sample_total)
        data = self.result('challenge-hard', 80, ['numeric', 'choice', 'instruction', 'json', 'tool-call'])
        data['summary']['partitions']['heldout'] = {'correct': 0, 'total': 0, 'format_errors': 0}
        with self.assertRaisesRegex(ValueError, 'practice-sample category or partition coverage'):
            CALIBRATION.public_receipt(data, sample_total)

    def test_practice_sample_is_reproducible_balanced_and_excludes_heldout(self):
        for suite in ('challenge-hard', 'documents-long'):
            with self.subTest(suite=suite):
                _data, tasks, _path, _omitted = CALIBRATION.bench_openclaw.suite_content(suite)
                first = CALIBRATION.practice_sample(suite, tasks)
                second = CALIBRATION.practice_sample(suite, tasks)
                self.assertEqual([item['id'] for item in first], [item['id'] for item in second])
                self.assertTrue(all(item['scorer'].get('partition') == 'practice' for item in first))
                names = ({'numeric', 'choice', 'instruction', 'json', 'tool-call'} if suite == 'challenge-hard'
                         else {'answer', 'quote', 'not_stated', 'summary'})
                counts = {}
                for item in first:
                    name = item.get('category') if suite == 'documents-long' else item['scorer']['kind']
                    counts[name] = counts.get(name, 0) + 1
                self.assertEqual(counts, {name: CALIBRATION.SAMPLE_PER_CATEGORY for name in names})


if __name__ == '__main__':
    unittest.main()
