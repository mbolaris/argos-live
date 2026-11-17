import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('smoke_hard_form_real', ROOT / 'scripts/smoke-hard-form-real.py')
CALIBRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALIBRATION)


class EV2CalibrationTests(unittest.TestCase):
    def result(self, suite, total, category_names):
        correct_per_category = 10 if total == 80 else 6
        categories = {name: {'correct': correct_per_category,
                             'total': total // len(category_names), 'format_errors': 0}
                      for name in category_names}
        practice_total = total // 2
        heldout_correct = 25 if total == 80 else 12
        practice_correct = 25 if total == 80 else 12
        return {'suite': 'openclaw-' + suite, 'suite_version': 'argos-openclaw-ability/' + suite + '/1.0.0',
                'model': 'ollama/qwen3:4b-instruct-2507-q4_K_M', 'state': 'completed',
                'coverage': {'completed': total, 'total': total, 'complete': True},
                'summary': {'correct': practice_correct + heldout_correct, 'total': total,
                            'format_errors': 0, 'categories': categories,
                            'partitions': {'practice': {'correct': practice_correct, 'total': practice_total,
                                                        'format_errors': 0},
                                           'heldout': {'correct': heldout_correct, 'total': practice_total,
                                                       'format_errors': 0}},
                            'items': [{'item_id': 'heldout-secret-id', 'output': 'private answer'}]}}

    def test_public_calibration_receipt_contains_aggregates_only(self):
        cases = [('challenge-hard', 80, ['numeric', 'choice', 'instruction', 'json', 'tool-call']),
                 ('documents-long', 40, ['answer', 'quote', 'not_stated', 'summary'])]
        for suite, total, categories in cases:
            with self.subTest(suite=suite):
                receipt = CALIBRATION.public_receipt(self.result(suite, total, categories), total)
                rendered = str(receipt)
                self.assertEqual(receipt['score']['percent'], 62.5 if total == 80 else 60.0)
                self.assertTrue(receipt['in_target_band'])
                self.assertFalse(receipt['raw_answers_exported'])
                self.assertFalse(receipt['prompts_exported'])
                self.assertNotIn('heldout-secret-id', rendered)
                self.assertNotIn('private answer', rendered)

    def test_public_calibration_refuses_partial_or_unbalanced_evidence(self):
        data = self.result('challenge-hard', 80, ['numeric', 'choice', 'instruction', 'json', 'tool-call'])
        data['coverage']['completed'] = 79
        with self.assertRaisesRegex(ValueError, 'complete'):
            CALIBRATION.public_receipt(data, 80)
        data = self.result('challenge-hard', 80, ['numeric', 'choice', 'instruction', 'json', 'tool-call'])
        data['summary']['partitions']['heldout']['total'] = 39
        with self.assertRaisesRegex(ValueError, 'partition coverage'):
            CALIBRATION.public_receipt(data, 80)


if __name__ == '__main__':
    unittest.main()
