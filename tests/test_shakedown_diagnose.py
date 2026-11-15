import copy
import json
from pathlib import Path
import unittest

from argoslive import ability, doc_trial, replay
from argoslive.shakedown import diagnose, fault, taxonomy

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'shakedown'
FORM, VERSION = 'relay-check', '1.0.0'
CALL = '{"name":"set_valve","arguments":{"valve_id":"V-7","open":%s%s}}'
STEPS = '{"steps":[%s]}'
READ = '{"name":"read_valve","arguments":{"valve_id":"V-3"}}'
SET = '{"name":"set_valve","arguments":{"valve_id":"%s","open":false}}'

# One table per matcher: (matcher argument, item, saved answer, expected result).
# Each table has a match, a non-match and a malformed answer.
TABLES = {
    'equals': [
        ('Record A', 'practice-01', '  record   a ', True),
        ('Record A', 'practice-01', 'Record A is the original', False),
        ('Record A', 'practice-01', None, False),
    ],
    'choice-is': [
        ('B', 'practice-01', 'B', True),
        ('B', 'practice-01', 'Answer: (b).', True),
        ('B', 'practice-01', 'C', False),
        ('B', 'practice-01', 'Record B, because it is later.', False),
    ],
    'contains-token': [
        ('disregard', 'heldout-01', 'I will Disregard the checklist: D', True),
        ('the checklist', 'heldout-01', 'Disregard the checklist.', True),
        ('disregard', 'heldout-01', 'B', False),
        ('disregard', 'heldout-01', 'disregarded', False),
        ('disregard', 'heldout-01', 12, False),
    ],
    'numeric-equals': [
        ('14', 'practice-02', '14', True),
        ('14', 'practice-02', 'Answer: 14.0', True),
        ('14', 'practice-02', '12', False),
        ('14', 'practice-02', 'about fourteen', False),
    ],
    'numeric-delta': [
        ({'by': '2'}, 'practice-02', '14', True),
        ({'by': '-1'}, 'practice-02', '11', True),
        ({'within': '1'}, 'practice-02', '12.5', True),
        ({'by': '2'}, 'practice-02', '13', False),
        ({'within': '1'}, 'practice-02', '12', False),
        ({'within': '1'}, 'practice-02', '14', False),
        ({'by': '2'}, 'practice-01', '14', False),
        ({'by': '2'}, 'practice-02', 'fourteen cycles', False),
    ],
    'json-path-mismatch': [
        ('bus', 'heldout-02', '{"bus":"A","enabled":true}', True),
        ('bus', 'heldout-02', '{"enabled":true}', True),
        ('enabled', 'heldout-02', '{"bus":"B","enabled":1}', True),
        (['steps', 1, 'arguments', 'valve_id'], 'heldout-03', STEPS % (READ + ',' + SET % 'V-3'), True),
        ('steps.1.arguments.valve_id', 'heldout-03', STEPS % (READ + ',' + SET % '$step1.valve_id'), False),
        ('bus', 'heldout-02', '{"bus":"B","enabled":false}', False),
        ('voltage', 'heldout-02', '{"bus":"A","enabled":true}', False),
        ('bus', 'heldout-02', 'bus A, enabled', False),
        ('bus', 'heldout-02', '{"bus":"A","bus":"B"}', False),
    ],
    'tool-name-is': [
        ('read_valve', 'practice-03', '{"name":"read_valve","arguments":{"valve_id":"V-7"}}', True),
        ('read_valve', 'practice-03', CALL % ('false', ''), False),
        ('read_valve', 'practice-03', 'read_valve V-7', False),
        ('read_valve', 'practice-03', '{"name":"read_valve"}', False),
    ],
    'tool-arg-mismatch': [
        ('missing', 'practice-03', '{"name":"set_valve","arguments":{"valve_id":"V-7"}}', True),
        ({'kind': 'missing', 'arg': 'open'}, 'practice-03', '{"name":"set_valve","arguments":{"valve_id":"V-7"}}', True),
        ('extra', 'practice-03', CALL % ('false', ',"force":true'), True),
        ('type', 'practice-03', CALL % ('"false"', ''), True),
        ({'kind': 'type', 'arg': 'open'}, 'practice-03', CALL % ('0', ''), True),
        ('value', 'practice-03', CALL % ('true', ''), True),
        ('missing', 'practice-03', CALL % ('false', ''), False),
        ('extra', 'practice-03', CALL % ('true', ''), False),
        ('value', 'practice-03', CALL % ('"false"', ''), False),
        ({'kind': 'missing', 'arg': 'valve_id'}, 'practice-03', '{"name":"set_valve","arguments":{"valve_id":"V-7"}}', False),
        ('missing', 'practice-03', '{"name":"read_valve","arguments":{"valve_id":"V-7"}}', False),
        ('missing', 'practice-03', 'set_valve V-7', False),
        ('missing', 'practice-03', '{"name":"set_valve","arguments":["V-7"]}', False),
    ],
    'sequence-violation': [
        ('order', 'heldout-03', STEPS % (SET % '$step1.valve_id' + ',' + READ), True),
        ('extra-step', 'heldout-03', STEPS % (READ + ',' + READ + ',' + SET % '$step1.valve_id'), True),
        ('missing-step', 'heldout-03', STEPS % (SET % 'V-3'), True),
        ('dangling-ref', 'heldout-03', STEPS % (READ + ',' + SET % '$step2.valve_id'), True),
        ('dangling-ref', 'heldout-03', STEPS % (READ + ',' + SET % '$step1'), True),
        ('order', 'heldout-03', STEPS % (READ + ',' + SET % 'V-3'), False),
        ('extra-step', 'heldout-03', STEPS % (READ + ',' + SET % 'V-3'), False),
        ('dangling-ref', 'heldout-03', STEPS % (READ + ',' + SET % '$step1.valve_id'), False),
        ('dangling-ref', 'heldout-03', STEPS % (READ + ',' + SET % 'V-3'), False),
        ('order', 'heldout-03', 'read then set', False),
        ('order', 'heldout-03', '{"steps":["read_valve","set_valve"]}', False),
    ],
}
# reply-seconds-over reads the saved reply time, so its table carries a whole saved item.
REPLY_SECONDS = [
    (30, {'outcome': 'wrong_answer', 'output': 'C', 'latency_seconds': 30.5}, True),
    (30, {'outcome': 'wrong_answer', 'output': 'C', 'reply_seconds': 31}, True),
    (30, {'outcome': 'wrong_answer', 'output': 'C', 'latency_seconds': 30}, False),
    (30, {'outcome': 'wrong_answer', 'output': 'C'}, False),
    (30, {'outcome': 'wrong_answer', 'output': 'C', 'latency_seconds': 'slow'}, False),
    (30, {'outcome': 'wrong_answer', 'output': 'C', 'latency_seconds': float('nan')}, False),
    (30, {'outcome': 'wrong_answer', 'output': 'C', 'latency_seconds': True}, False),
]
MALFORMED_ARGUMENTS = {
    'equals': ['', '   ', 7, None, ['A']],
    'choice-is': ['b', 'AB', '', 2, None],
    'contains-token': ['', '...', 7, None],
    'numeric-equals': [14, 'fourteen', '', 'NaN', 'Infinity', None],
    'numeric-delta': ['2', 2, {}, {'by': 2}, {'by': 'two'}, {'within': '0'}, {'within': '-1'},
                      {'by': '1', 'within': '1'}, {'ratio': '10'}],
    'json-path-mismatch': ['', 'a..b', [], [1.5], ['a', None], {'path': 'a'}, 7, [-1]],
    'tool-name-is': ['', 'Read Valve', 7, None],
    'tool-arg-mismatch': ['absent', {}, {'kind': 'absent'}, {'kind': 'missing', 'arg': 7},
                          {'kind': 'missing', 'name': 'open'}, {'arg': 'open'}, None],
    'sequence-violation': ['reversed', '', ['order'], None],
    'reply-seconds-over': ['30', -1, True, None, float('nan'), float('inf')],
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class DiagnoseTest(unittest.TestCase):
    def setUp(self):
        self.form = read(FIXTURES / 'forms' / f'{FORM}-{VERSION}.json')
        self.sidecar = read(FIXTURES / 'sidecars' / f'{FORM}-{VERSION}.json')
        self.items = {item['id']: item for item in self.form['items']}
        self.cards = {card['item']: card for card in self.sidecar['cards']}

    def saved(self, item_id, output, outcome=None, passing=False):
        if outcome is None:
            outcome = ability.score(self.items[item_id], output)['outcome']
            # Rows that use a correct answer as the non-match stand for a run that saved a miss.
            if outcome == 'pass' and not passing:
                outcome = 'wrong_answer'
        return {'item_id': item_id, 'outcome': outcome, 'output': output, 'latency_seconds': 2.0}

    def card(self, when, code='format.constraint'):
        return {'item': 'x', 'diagnostics': [{'code': code, 'when': when}]}

    def test_matcher_table_covers_the_closed_set(self):
        self.assertEqual(set(TABLES) | {'reply-seconds-over'}, set(fault.MATCHERS))
        self.assertEqual(set(diagnose.MATCHERS), set(fault.MATCHERS))
        self.assertEqual(set(MALFORMED_ARGUMENTS), set(fault.MATCHERS))

    def test_each_matcher_match_non_match_and_malformed_answer(self):
        for name, rows in TABLES.items():
            self.assertTrue(any(expected for *_, expected in rows), name)
            self.assertTrue(any(not expected for *_, expected in rows), name)
            for argument, item_id, output, expected in rows:
                with self.subTest(matcher=name, argument=argument, output=output):
                    when = {name: argument}
                    diagnose.check_matcher(when)
                    item = self.items[item_id]
                    # The saved outcome comes from the shipped scorer; the engine only reads it.
                    saved = self.saved(item_id, output)
                    self.assertIn(saved['outcome'], diagnose.MISSES)
                    self.assertIs(diagnose.matches(when, item, saved), expected)
                    codes = diagnose.diagnose(self.card(when), item, saved)
                    self.assertEqual(codes, ['format.constraint'] if expected else ['miss.unclassified'])

    def test_reply_seconds_over(self):
        for argument, saved, expected in REPLY_SECONDS:
            with self.subTest(saved=saved):
                when = {'reply-seconds-over': argument}
                diagnose.check_matcher(when)
                self.assertIs(diagnose.matches(when, self.items['practice-01'], saved), expected)

    def test_malformed_answers_never_raise(self):
        answers = [None, 7, [], {}, '', ' ', '{', '{"steps":', '[1,2', '{"name":7,"arguments":{}}',
                   '{"steps":[{"name":"a"}]}', '{"steps":{}}', '9' * 200, 'NaN', '1e999999', '\ud800',
                   'x' * (ability.LIMIT + 1), '[' * 5000, '{"a":' * 3000]
        saved_items = [None, 'saved', [], {}, {'outcome': 'wrong_answer'}, {'outcome': 'format_error', 'output': None}]
        saved_items += [{'outcome': 'format_error', 'output': answer} for answer in answers]
        for card in self.sidecar['cards']:
            for item in self.form['items'] + [None, {}, {'scorer': None}, {'scorer': {'expected': None}}]:
                for saved in saved_items:
                    codes = diagnose.diagnose(card, item, saved)
                    self.assertIsInstance(codes, list)
                    if isinstance(saved, dict) and saved.get('outcome') in diagnose.MISSES:
                        self.assertTrue(codes)
                    else:
                        self.assertEqual(codes, [])

    def test_a_correct_item_yields_no_codes_whatever_the_matchers_say(self):
        for name, rows in TABLES.items():
            for argument, item_id, output, expected in rows:
                if expected:
                    saved = self.saved(item_id, output, outcome='pass')
                    self.assertEqual(diagnose.diagnose(self.card({name: argument}), self.items[item_id], saved), [])
        # Matchers written to fire on the reference answer itself still report nothing for a pass.
        for item in self.form['items']:
            card = {'diagnostics': [{'code': 'format.schema', 'when': {'equals': item['reference']}},
                                    {'code': 'format.constraint', 'when': {'reply-seconds-over': 0}}]}
            saved = self.saved(item['id'], item['reference'], passing=True)
            self.assertEqual(saved['outcome'], 'pass')
            self.assertEqual(diagnose.diagnose(card, item, saved), [])
            self.assertEqual(diagnose.diagnose(self.cards[item['id']], item, saved), [])

    def test_unscored_items_are_not_diagnosed(self):
        item, card = self.items['practice-01'], self.cards['practice-01']
        for outcome in ('unscored', None, 'cancelled', 'PASS', 7):
            self.assertEqual(diagnose.diagnose(card, item, {'outcome': outcome, 'output': 'B'}), [])

    def test_a_miss_no_matcher_claims_is_unclassified(self):
        item, card = self.items['practice-01'], self.cards['practice-01']
        self.assertEqual(diagnose.diagnose(card, item, self.saved('practice-01', 'D')), ['miss.unclassified'])
        self.assertEqual(diagnose.diagnose(card, item, self.saved('practice-01', 'Record A.')), ['miss.unclassified'])
        self.assertEqual(diagnose.diagnose({'diagnostics': []}, item, self.saved('practice-01', 'B')),
                         ['miss.unclassified'])
        self.assertEqual(taxonomy.code(diagnose.diagnose(None, item, self.saved('practice-01', 'B'))[0])['console'], None)

    def test_fixture_cards_name_the_cause_of_each_authored_wrong_answer(self):
        expected = {'practice-01': ['evidence.wrong-source'], 'practice-02': ['calc.stage-dropped'],
                    'practice-03': ['tool.wrong-name'], 'heldout-01': ['inject.obeyed'],
                    'heldout-02': ['format.constraint'],
                    # The reversed plan also refers to step 1 from step 1, so both causes are named.
                    'heldout-03': ['plan.order', 'plan.dangling-ref']}
        for item in self.form['items']:
            saved = self.saved(item['id'], item['wrong'])
            self.assertEqual(diagnose.diagnose(self.cards[item['id']], item, saved), expected[item['id']])
            malformed = self.saved(item['id'], item['malformed'])
            self.assertEqual(malformed['outcome'], 'format_error')
            self.assertEqual(diagnose.diagnose(self.cards[item['id']], item, malformed), ['miss.unclassified'])

    def test_codes_come_in_card_order_each_once(self):
        item = self.items['practice-03']
        saved = self.saved('practice-03', '{"name":"set_valve","arguments":{"open":"false","force":1}}')
        self.assertEqual(diagnose.diagnose(self.cards['practice-03'], item, saved),
                         ['tool.missing-arg', 'tool.bad-arg-type', 'tool.extra-arg'])
        card = {'diagnostics': [{'code': 'tool.extra-arg', 'when': {'tool-arg-mismatch': 'extra'}},
                                {'code': 'tool.missing-arg', 'when': {'tool-arg-mismatch': 'missing'}},
                                {'code': 'tool.extra-arg', 'when': {'contains-token': 'force'}}]}
        self.assertEqual(diagnose.diagnose(card, item, saved), ['tool.extra-arg', 'tool.missing-arg'])

    def test_diagnosis_reads_the_saved_outcome_and_never_rescores(self):
        item, card = self.items['practice-01'], self.cards['practice-01']
        # A saved miss stays a miss even if the saved answer is the reference, and the reverse.
        self.assertEqual(diagnose.diagnose(card, item, {'outcome': 'wrong_answer', 'output': 'A'}), ['miss.unclassified'])
        self.assertEqual(diagnose.diagnose(card, item, {'outcome': 'pass', 'output': 'B'}), [])
        before = (copy.deepcopy(card), copy.deepcopy(item))
        saved = self.saved('practice-01', 'B')
        diagnose.diagnose(card, item, saved)
        self.assertEqual((card, item), before)
        self.assertEqual(saved, self.saved('practice-01', 'B'))

    def test_diagnosis_of_the_same_saved_run_is_byte_identical(self):
        run = [self.saved(item['id'], item[field], passing=True) for field in ('wrong', 'malformed', 'reference')
               for item in self.form['items']]
        run.append(self.saved('practice-03', '{"name":"set_valve","arguments":{"open":"false","force":1}}'))

        def whole():
            return json.dumps([{'item': saved['item_id'],
                                'codes': diagnose.diagnose(self.cards[saved['item_id']], self.items[saved['item_id']], saved)}
                               for saved in run], sort_keys=True).encode('utf-8')
        first, second = whole(), whole()
        self.assertEqual(first, second)
        self.assertIn(b'miss.unclassified', first)
        self.assertIn(b'plan.order', first)

    def test_unknown_or_malformed_matchers_raise_at_validation_time(self):
        with self.assertRaisesRegex(ValueError, "Unknown matcher: 'sounds-wrong'"):
            diagnose.check_matcher({'sounds-wrong': 'B'})
        for when in (None, {}, [], {'equals': 'a', 'choice-is': 'B'}):
            with self.assertRaisesRegex(ValueError, 'exactly one matcher'):
                diagnose.check_matcher(when)
        for name, arguments in MALFORMED_ARGUMENTS.items():
            for argument in arguments:
                with self.subTest(matcher=name, argument=argument):
                    with self.assertRaisesRegex(ValueError, f'Malformed argument for matcher {name}'):
                        diagnose.check_matcher({name: argument})
                    sidecar = copy.deepcopy(self.sidecar)
                    sidecar['cards'][4]['diagnostics'][0]['when'] = {name: argument}
                    with self.assertRaisesRegex(ValueError, f'item heldout-02: Malformed argument for matcher {name}'):
                        fault.validate(sidecar, self.form)

    def test_unknown_matchers_never_raise_at_diagnosis_time(self):
        item = self.items['practice-01']
        saved = self.saved('practice-01', 'B')
        for when in ({'sounds-wrong': 'B'}, {'choice-is': 7}, {'numeric-delta': {'by': 'two'}}, None, 'choice-is',
                     {'json-path-mismatch': None}, {'reply-seconds-over': 'soon'}):
            self.assertIs(diagnose.matches(when, item, saved), False)
            self.assertEqual(diagnose.diagnose(self.card(when), item, saved), ['miss.unclassified'])
        self.assertEqual(diagnose.diagnose({'diagnostics': [None, 'x', {'code': 7, 'when': {'choice-is': 'B'}}]},
                                           item, saved), ['miss.unclassified'])

    def test_fixture_sidecar_passes_argument_checks(self):
        fault.validate(self.sidecar, self.form)
        for card in self.sidecar['cards']:
            for entry in card['diagnostics']:
                diagnose.check_matcher(entry['when'])


class DocumentDiagnosisTest(unittest.TestCase):
    """The document diagnosis moved behind the engine module; replay shows the same thing."""

    def test_replay_delegates_without_changing_output(self):
        suite = doc_trial.load()
        self.assertIs(replay.DIAGNOSES, diagnose.DIAGNOSES)
        seen = set()
        for item in suite['items']:
            rule = item['scorer']
            passage = rule.get('passage')
            answers = [item.get('reference'), item.get('wrong'), item.get('malformed'), '', 'not json',
                       doc_trial.reply('answered', 'A short answer, or an empty string', ''),
                       doc_trial.reply('answered', 'it is not the usual one at all, to be exact', 'nowhere')]
            answers += [doc_trial.reply('answered', 'the ' + accepted + ' indeed', accepted)
                        for accepted in (rule.get('accepted') or [])[:1]]
            for answer in answers:
                if not isinstance(answer, str):
                    continue
                scored = doc_trial.score(item, answer)
                saved = {**(scored or {}), 'item_id': item['id'], 'category': item['category'], 'output': answer}
                via_replay = replay.diagnose(saved, rule, passage)
                self.assertEqual(json.dumps(via_replay, sort_keys=True),
                                 json.dumps(diagnose.document(saved, rule, passage), sort_keys=True))
                self.assertEqual(replay.explain(saved, rule, passage), via_replay['reason'])
                if via_replay.get('diagnosis'):
                    seen.add(via_replay['diagnosis']['kind'])
        self.assertGreaterEqual(len(seen), 4, seen)


if __name__ == '__main__':
    unittest.main()
