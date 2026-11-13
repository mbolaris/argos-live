"""Auto Climb tier 3: exact answer formats, their scorer, and the exact-format candidate."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from argoslive import assistant_trial, auto_climb
from test_auto_climb_tiers import all_sets, quotable


def score(task, reply, passages=None):
    return assistant_trial.score(task, passages or {}, reply)


LETTER = {'id': 'x', 'kind': 'format', 'format': 'letter', 'passage': 'p', 'question': 'Q?',
          'options': ['a', 'b', 'c', 'd'], 'expected': 'B'}


class FormatScorerTests(unittest.TestCase):
    def test_exact_value_passes_with_harmless_wrapping(self):
        for reply in ('B', ' B\n', 'B.', '**B**', '`B`'):
            self.assertTrue(score(LETTER, reply)['passed'], reply)

    def test_right_value_with_extra_text_is_a_format_miss_only(self):
        result = score(LETTER, 'B "Dr. Mendes works only at the Riverside office, on Mondays."')
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks'], {'correct_value': True, 'exact_format': False})

    def test_wrong_value_fails_both_ways_it_can(self):
        self.assertEqual(score(LETTER, 'C')['checks'], {'correct_value': False, 'exact_format': True})
        self.assertFalse(score(LETTER, 'The answer is B')['checks']['correct_value'])

    def test_each_format(self):
        cases = [('yesno', 'no', 'No.', 'No. "Children\'s books have no late fees."'),
                 ('number', '14', '14', '14 "Beginner woodworking meets in Room 14."'),
                 ('number', '18', '$18', '$18 per adult'),
                 ('date', '2027-05-30', '2027-05-30', '2027-05-30 "Please RSVP by May 30, 2027."')]
        for fmt, expected, good, extra in cases:
            task = dict(LETTER, format=fmt, expected=expected)
            self.assertTrue(score(task, good)['passed'], (fmt, good))
            self.assertEqual(score(task, extra)['checks'], {'correct_value': True, 'exact_format': False}, (fmt, extra))

    def test_message_carries_options_and_the_format_instruction(self):
        text = assistant_trial.message(LETTER, {'p': 'A notice.'})
        self.assertTrue(text.endswith('Q?\nA) a\nB) b\nC) c\nD) d\nAnswer with one letter only.'))

    def test_compare_reports_format_totals_only_when_present(self):
        row = {'id': 'x', 'kind': 'format', 'passed': False, 'checks': {'correct_value': True, 'exact_format': False}}
        after = dict(row, passed=True, checks={'correct_value': True, 'exact_format': True})
        result = assistant_trial.compare([row], [after])
        self.assertEqual(result['totals']['format'], {'before': 0, 'after': 1, 'total': 1})
        self.assertEqual(result['gains'], ['x'])
        plain = {'id': 'y', 'kind': 'answer', 'passed': True, 'checks': {'answer_present': True}}
        self.assertNotIn('format', assistant_trial.compare([plain], [plain])['totals'])


class TierThreeDataTests(unittest.TestCase):
    def setUp(self):
        self.practice = auto_climb.load_task_file(auto_climb.TIER3_PRACTICE_TASKS_PATH)
        self.partitions = auto_climb.load_validation_partitions(auto_climb.TIER3_VALIDATION_TASKS_PATH)

    def sets(self):
        return [self.practice, *self.partitions]

    def test_shape(self):
        self.assertEqual(self.practice['curriculum'], 'argos-foundation/3')
        self.assertEqual(len(self.partitions), 16)
        for task_set in self.sets():
            kinds = [t['kind'] for t in task_set['tasks']]
            self.assertEqual((kinds.count('format'), kinds.count('answer'), kinds.count('not_stated')), (6, 1, 1))

    def test_format_tasks_are_well_formed_and_answerable_from_the_notice(self):
        for task_set in self.sets():
            for task in task_set['tasks']:
                if task['kind'] != 'format':
                    continue
                self.assertIn(task['format'], assistant_trial.FORMATS)
                self.assertTrue(assistant_trial.FORMATS[task['format']][1].fullmatch(task['expected']), task['id'])
                if task['format'] == 'letter':
                    self.assertEqual(len(set(task['options'])), 4, task['id'])
                    chosen = task['options']['ABCD'.index(task['expected'])]
                    self.assertIn(chosen.split(' only')[0].lower(), task_set['passages'][task['passage']].lower())
                self.assertTrue(score(task, task['expected'])['passed'], task['id'])
                self.assertFalse(score(task, task['expected'] + ' "Supporting quote."')['passed'], task['id'])

    def test_answer_and_unanswerable_tasks_use_the_unchanged_scorer(self):
        for task_set in self.sets():
            for task in task_set['tasks']:
                if task['kind'] == 'answer':
                    answer, sentence = quotable(task, task_set['passages'])
                    self.assertIsNotNone(sentence, task['id'])
                    self.assertTrue(score(task, f'{answer}. "{sentence}"', task_set['passages'])['passed'])
                elif task['kind'] == 'not_stated':
                    self.assertTrue(score(task, 'The notice does not say.')['passed'])

    def test_disjoint_from_every_other_set_in_all_tiers(self):
        earlier = []
        for practice, validation in ((auto_climb.PRACTICE_TASKS_PATH, auto_climb.VALIDATION_TASKS_PATH),
                                     (auto_climb.TIER2_PRACTICE_TASKS_PATH, auto_climb.TIER2_VALIDATION_TASKS_PATH)):
            earlier += all_sets(practice) + auto_climb.load_validation_partitions(validation)
        passages = [v for s in self.sets() for v in s['passages'].values()]
        questions = [t.get('question') for s in self.sets() for t in s['tasks']]
        self.assertEqual(len(passages), len(set(passages)))
        self.assertEqual(len(questions), len(set(questions)))
        self.assertFalse(set(passages) & {v for s in earlier for v in s['passages'].values()})
        self.assertFalse(set(questions) & {t.get('question') for s in earlier for t in s['tasks']})
        ids = [t['id'] for s in self.sets() for t in s['tasks']] + [t['id'] for s in earlier for t in s['tasks']]
        self.assertEqual(len(ids), len(set(ids)))
        partition_ids = [p['id'] for p in earlier if 'id' in p and p['id'].startswith(('val-', 't2-val-'))]
        self.assertFalse({p['id'] for p in self.partitions} & set(partition_ids))


class ExactFormatCandidateTests(unittest.TestCase):
    def controller(self, misses, practice_path):
        c = auto_climb.Controller.__new__(auto_climb.Controller)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        c.home = Path(temp.name)
        (c.home / '.openclaw').mkdir()
        (c.home / '.openclaw/openclaw.json').write_text('{}')
        c.candidate_pool = copy.deepcopy(auto_climb.INSTRUCTION_CANDIDATES)
        c.model_recommender = mock.Mock(return_value=None)
        c.practice_tasks = auto_climb.load_task_file(practice_path)
        c.session = {'practice_baseline': misses}
        return c

    FORMAT_MISS = {'kind': 'format', 'passed': False, 'checks': {'correct_value': True, 'exact_format': False}}

    def test_format_only_misses_try_the_exact_format_rule_first(self):
        c = self.controller([self.FORMAT_MISS] * 2, auto_climb.TIER3_PRACTICE_TASKS_PATH)
        chosen = c._select_next_candidate()
        self.assertEqual(chosen['id'], 'exact-format')
        self.assertIn('requested answer format', chosen['rationale'])

    def test_never_offered_on_a_tier_without_format_challenges(self):
        c = self.controller([self.FORMAT_MISS] * 2, auto_climb.PRACTICE_TASKS_PATH)
        offered = []
        while (chosen := c._select_next_candidate()) is not None:
            offered.append(chosen['id'])
            c.session.setdefault('completed_candidates', []).append(chosen['id'])
        self.assertEqual(offered, ['answer-first', 'quote-evidence', 'honest-uncertainty'])

    def test_the_rule_is_reviewed_and_stays_out_of_the_starter_trial(self):
        change = assistant_trial.change_for('exact-format')
        self.assertEqual(change['target_check'], 'exact_format')
        self.assertNotIn('exact-format', [c['id'] for c in assistant_trial.CHANGES])
        self.assertEqual(assistant_trial.MAX_EXPERIMENTS, 3)
        staged = assistant_trial.staged('# Notes\n', 'exact-format')
        self.assertIn('<!-- argos-trial:exact-format v1', staged)
        self.assertTrue(staged.endswith('<!-- /argos-trial:exact-format -->\n'))


if __name__ == '__main__':
    unittest.main()
