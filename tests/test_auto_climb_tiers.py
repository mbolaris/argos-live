"""Auto Climb curriculum tiers: the harder task data, and moving up when practice is saturated."""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from argoslive import assistant_trial, auto_climb
from test_auto_climb import ControllableClock, FakeStartup


def sentence_with(passage, answer):
    for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])', passage):
        if assistant_trial.contains(sentence, answer) and len(sentence) >= 15:
            return sentence
    return None


def quotable(task, passages):
    """The first accepted form the notice itself uses, and the sentence holding it."""
    for answer in task['accepted']:
        sentence = sentence_with(passages[task['passage']], answer)
        if sentence:
            return answer, sentence
    return None, None


def all_sets(path):
    data = auto_climb.load_task_file(path)
    return [data] if 'partitions' not in data else data['partitions']


class TierTwoDataTests(unittest.TestCase):
    def setUp(self):
        self.practice = auto_climb.load_task_file(auto_climb.TIER2_PRACTICE_TASKS_PATH)
        self.partitions = auto_climb.load_validation_partitions(auto_climb.TIER2_VALIDATION_TASKS_PATH)

    def test_shape_matches_the_first_tier(self):
        self.assertEqual(self.practice['schema'], 'argos-assistant-tasks/1')
        self.assertEqual(len(self.partitions), 16)
        for task_set in [self.practice, *self.partitions]:
            kinds = [t['kind'] for t in task_set['tasks']]
            self.assertEqual((kinds.count('answer'), kinds.count('not_stated'), kinds.count('control')), (3, 3, 2))

    def test_every_set_is_disjoint_from_every_other_set_in_both_tiers(self):
        first = all_sets(auto_climb.PRACTICE_TASKS_PATH) + auto_climb.load_validation_partitions(auto_climb.VALIDATION_TASKS_PATH)
        second = [self.practice] + self.partitions
        text = lambda sets: [t.get('question') or t.get('message') for s in sets for t in s['tasks']]
        passages = [v for s in second for v in s['passages'].values()]
        self.assertEqual(len(passages), len(set(passages)))
        self.assertFalse(set(passages) & {v for s in first for v in s['passages'].values()})
        self.assertEqual(len(text(second)), len(set(text(second))))
        self.assertFalse(set(text(second)) & set(text(first)))
        task_ids = [t['id'] for s in second for t in s['tasks']]
        self.assertEqual(len(task_ids), len(set(task_ids)))
        ids = [p['id'] for p in auto_climb.load_validation_partitions(auto_climb.VALIDATION_TASKS_PATH)] + \
              [p['id'] for p in self.partitions]
        self.assertEqual(len(ids), len(set(ids)))

    def test_answers_are_quotable_and_scored_by_the_unchanged_scorer(self):
        for task_set in [self.practice, *self.partitions]:
            for task in task_set['tasks']:
                passages = task_set['passages']
                if task['kind'] == 'answer':
                    answer, sentence = quotable(task, passages)
                    self.assertIsNotNone(sentence, task['id'])
                    reply = f'{answer}. "{sentence}"'
                    self.assertTrue(assistant_trial.score(task, passages, reply)['passed'], task['id'])
                    self.assertFalse(assistant_trial.score(task, passages, answer)['passed'], task['id'])
                elif task['kind'] == 'not_stated':
                    self.assertTrue(assistant_trial.score(task, passages, 'The notice does not say.')['passed'])
                    self.assertFalse(assistant_trial.score(task, passages, 'It is $20.')['passed'])
                else:
                    self.assertTrue(assistant_trial.score(task, passages, 'Try a warm scarf.')['passed'])


class TierRunner:
    """Perfect on the tasks of the tiers named in perfect_on, unhelpful on everything else."""

    def __init__(self, tiers, perfect_on):
        self.tasks = {}
        for name, data in tiers.items():
            for task in data['tasks']:
                prompt = assistant_trial.message(task, data['passages'])
                self.tasks[prompt] = (name, task, data['passages'])
        self.perfect_on = set(perfect_on)
        self.prompts = []

    def turn(self, prompt):
        self.prompts.append(prompt)
        name, task, passages = self.tasks.get(prompt, (None, None, None))
        if task is None or name not in self.perfect_on:
            return 'I am not sure.'
        if task['kind'] == 'answer':
            answer, sentence = quotable(task, passages)
            return f'{answer}. "{sentence}"'
        if task['kind'] == 'not_stated':
            return 'The notice does not say.'
        return 'Try a warm scarf.'


class TierSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        ws = self.home / '.openclaw/workspace'
        ws.mkdir(parents=True)
        (self.home / '.openclaw/openclaw.json').write_text(json.dumps({'agents': {'defaults': {'workspace': str(ws)}}}))
        (self.home / '.config/argos-live').mkdir(parents=True)
        (self.home / '.config/argos-live/state.json').write_text('{"model": "test-model"}')
        for name in ('SOUL.md', 'IDENTITY.md', 'USER.md'):
            (ws / name).write_text('Test\n')
        (ws / 'AGENTS.md').write_text('# Operating notes\nBe concise.\n')
        self.startup = FakeStartup(self.home)
        self.tiers = {
            'one': auto_climb.load_task_file(auto_climb.PRACTICE_TASKS_PATH),
            'two': auto_climb.load_task_file(auto_climb.TIER2_PRACTICE_TASKS_PATH),
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_to_end(self, perfect_on):
        runner = TierRunner(self.tiers, perfect_on)
        controller = auto_climb.Controller(self.startup, home=self.home, runner=runner,
                                           clock=ControllableClock().monotonic, sleep_fn=lambda s: None,
                                           candidates=[])
        try:
            controller.start()
            deadline = time.time() + 10.0
            while time.time() < deadline:
                snap = controller.snapshot()
                if snap['phase'] in ('options-exhausted', 'plateau', 'budget-exhausted', 'stopped', 'blocked'):
                    break
                time.sleep(0.05)
            return controller.snapshot(), controller.session, runner
        finally:
            controller.close()

    def test_default_controller_has_both_tiers_and_starts_on_the_first(self):
        controller = auto_climb.Controller(self.startup, home=self.home, runner=TierRunner(self.tiers, ()))
        try:
            self.assertEqual([t['version'] for t in controller.curricula], ['argos-foundation/1', 'argos-foundation/2'])
            self.assertEqual(controller.curriculum_version, 'argos-foundation/1')
        finally:
            controller.close()

    def test_explicit_task_paths_keep_a_single_tier(self):
        controller = auto_climb.Controller(self.startup, home=self.home, runner=TierRunner(self.tiers, ()),
                                           practice_path=auto_climb.TIER2_PRACTICE_TASKS_PATH)
        try:
            self.assertEqual(len(controller.curricula), 1)
        finally:
            controller.close()

    def test_unsaturated_first_tier_stays_on_the_first_tier(self):
        snap, session, runner = self.run_to_end(perfect_on=())
        self.assertEqual(session['curriculum_version'], 'argos-foundation/1')
        self.assertEqual(session['starting_level']['practice_total'], 8)
        self.assertNotIn('saturated_curricula', session)
        self.assertEqual(len(runner.prompts), 8)

    def test_saturated_first_tier_moves_up_and_records_why(self):
        snap, session, runner = self.run_to_end(perfect_on=('one',))
        self.assertEqual(session['curriculum_version'], 'argos-foundation/2')
        self.assertEqual(snap['curriculum_version'], 'argos-foundation/2')
        self.assertEqual([s['curriculum_version'] for s in session['saturated_curricula']], ['argos-foundation/1'])
        self.assertEqual(session['starting_level']['practice_passed'], 2)  # the two controls
        self.assertEqual(len(runner.prompts), 16)
        self.assertIn('Practice options exhausted', snap['stopping_reason'])

    def test_saturated_top_tier_stops_without_experiments(self):
        snap, session, runner = self.run_to_end(perfect_on=('one', 'two'))
        self.assertEqual(snap['phase'], 'options-exhausted')
        self.assertIn('Practice saturated', snap['stopping_reason'])
        self.assertIn('Nothing was changed', snap['stopping_reason'])
        self.assertEqual(len(session['saturated_curricula']), 2)
        self.assertEqual(session['budgets_used']['completed_experiments'], 0)
        self.assertEqual(len(runner.prompts), 16)
        self.assertEqual((self.home / '.openclaw/workspace/AGENTS.md').read_text(), '# Operating notes\nBe concise.\n')


if __name__ == '__main__':
    unittest.main()
