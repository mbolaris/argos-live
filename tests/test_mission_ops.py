"""mission-ops 1.0.0: every expected answer is re-derived from the prompt text alone.

The solvers here share no code with the generator, so a generator bug that makes an
expected answer wrong, or a prompt that leaves the answer ambiguous, fails this test.
"""
from collections import Counter
import copy
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability

FRACTIONS = {'third': 3, 'quarter': 4, 'fifth': 5}


def solve_ledger(prompt):
    level = int(re.search(r'Start: (\d+) (?:kg|L)\.', prompt).group(1))
    reserve = int(re.search(r'A reserve of (\d+) ', prompt).group(1))
    entries = re.findall(r'^E(\d+): (.*)$', prompt, re.M)
    corrected = {int(number): int(amount) for number, amount in
                 re.findall(r'Correction: E(\d+) actually used (\d+) ', prompt)}
    for number, text in entries:
        number = int(number)
        if text.startswith(('CANCELLED', 'Correction')):
            continue
        if match := re.search(r'uses (\d+)% of the amount on hand', text):
            level -= level * int(match.group(1)) // 100
        elif match := re.search(r'sends out one (third|quarter|fifth) of the amount on hand', text):
            level -= level // FRACTIONS[match.group(1)]
        elif match := re.fullmatch(r'Resupply adds (\d+)\.(\d\d) (?:t|kL) \(1 (?:t|kL) = 1000 (?:kg|L)\)\.', text):
            level += int(match.group(1)) * 1000 + int(match.group(2)) * 10
        elif match := re.fullmatch(r'\w+ uses (\d+) (?:kg|L)\.', text):
            level -= corrected.get(number, int(match.group(1)))
        else:
            raise AssertionError('unparsed ledger entry: ' + text)
        assert level > 0
    return str(level - reserve)


def solve_gonogo(prompt):
    order = re.search(r'Authority order, highest first: (.*?)\. For each', prompt).group(1).split(' > ')
    rank = {source.lower(): position for position, source in enumerate(order)}
    facts = {}
    for _, source, time, text in re.findall(r'^\((\d+)\) (.+?) (\d\d:\d\d): (.*)$', prompt, re.M):
        if match := re.search(r'raises the .+ limit by (\d+) ', text):
            fact, value = 'waiver', int(match.group(1))
        elif match := re.fullmatch(r'.+ limit (\d+) \S+\.', text):
            fact, value = 'limit', int(match.group(1))
        elif match := re.fullmatch(r'measured .+ (\d+) \S+\.', text):
            fact, value = 'measured', int(match.group(1))
        elif match := re.fullmatch(r'.+ signature (received|not received)\.', text):
            fact, value = 'signature', match.group(1) == 'received'
        else:
            raise AssertionError('unparsed record: ' + text)
        facts.setdefault(fact, []).append((rank[source.lower()], time, value))

    def resolve(fact):
        records = facts.get(fact, [])
        if not records:
            return None
        top = min(record[0] for record in records)
        return max(record for record in records if record[0] == top)[2]

    limit, measured = resolve('limit'), resolve('measured')
    waiver, signed = resolve('waiver'), resolve('signature')
    effective = limit + waiver if waiver is not None and signed else limit
    decision = 'GO' if measured <= effective else 'NO-GO'
    options = re.findall(r'([ABCD]): (GO|NO-GO), measured (\d+) \S+, effective limit (\d+) \S+\.', prompt)
    assert len(options) == 4
    holding = [letter for letter, said, m, e in options
               if (said, int(m), int(e)) == (decision, measured, effective)]
    assert len(holding) == 1, holding
    return holding[0]


def solve_replay(prompt):
    state = json.loads(re.search(r'Initial state: (\{.*\})\n', prompt).group(1))
    events = json.loads(re.search(r'Events \(listed in no particular order\): (\[.*\])\n', prompt).group(1))
    rejected_key = re.search(r'"(\w+)" \(the rejected event IDs in time order\)', prompt).group(1)
    applied_key = re.search(r'"(\w+)" \(the integer count of applied events\)', prompt).group(1)
    flips = {'on': 'off', 'off': 'on', 'open': 'closed', 'closed': 'open'}
    rejected, applied = [], 0
    for event in sorted(events, key=lambda event: event['t']):
        if event['auth'] is not True:
            rejected.append(event['id'])
            continue
        state[event['target']] = event['value'] if event['action'] == 'set' else flips[state[event['target']]]
        applied += 1
    return dict(state, **{rejected_key: rejected, applied_key: applied})


def manifest_sums(prompt):
    rows = json.loads(prompt.split('\n', 1)[0].split(': ', 1)[1])
    rule = re.search(r'whose (\w+) is "verified", whose (\w+) is day (\d+) or later, and whose (\w+) is not '
                     r'"([^"]+)"\. For each (\w+), add up (\w+) over', prompt)
    status, day, cutoff, item, excluded, group, qty = rule.groups()
    sums, counts = Counter(), Counter()
    for row in rows:
        if row[status] == 'verified' and row[day] >= int(cutoff) and row[item] != excluded:
            sums[row[group]] += row[qty]
            counts[row[group]] += 1
    return sums, counts


def solve_manifest(prompt):
    keys = re.search(r'exactly these keys: "(\w+)" \(the name\), "(\w+)" \(that integer sum\) and "(\w+)"',
                     prompt).groups()
    sums, counts = manifest_sums(prompt)
    top = max(sums.values())
    winner = sorted(name for name, total in sums.items() if total == top)[0]
    return dict(zip(keys, (winner, top, counts[winner])))


def solve_procedure(prompt):
    tools = {tool['name']: tool for tool in json.loads(
        re.search(r'Available tool schemas: (\{.*\})\n', prompt).group(1))['tools']}
    readings = dict((name, int(value)) for name, value in
                    re.findall(r'([A-Z]{2}-\d) = (\d+) ', re.search(r'Current readings: (.*)\.\n', prompt).group(1)))
    read = re.search(r'1\. Call (\w+) once for each of (.*), in that order\.', prompt)
    act = re.search(r'call (\w+) for every one whose reading is strictly (greater|less) than (\d+) \S+, '
                    r'with (\w+) "([^"]+)"', prompt)
    ticket = re.search(r'call (\w+) with (\w+) "([^"]+)" and (\w+) equal to 1 plus', prompt)
    notify = re.search(r'Then call (\w+) with (\w+) "([^"]+)" if \w+ is 3, otherwise "([^"]+)", and (\w+) '
                       r'"(\w+)-<\w+>-(\w+)"', prompt)
    fallback = re.search(r'skip \w+ and call \w+ with \w+ "([^"]+)" and \w+ "NONE"', prompt)
    read_name, loops = read.group(1), read.group(2).split(', ')
    act_name, relation, threshold, cause_key, cause = act.groups()
    read_key, = tools[read_name]['arguments']
    loop_key, = [key for key in tools[act_name]['arguments'] if key != cause_key]
    steps = [{'name': read_name, 'arguments': {read_key: loop}} for loop in loops]
    chosen = [loop for loop in loops if (readings[loop] > int(threshold) if relation == 'greater'
                                         else readings[loop] < int(threshold))]
    steps += [{'name': act_name, 'arguments': {loop_key: loop, cause_key: cause}} for loop in chosen]
    notify_name, who_key, high, low, ref_key, ref_prefix, ref_suffix = notify.groups()
    if chosen:
        ticket_name, system_key, system, level_key = ticket.groups()
        level = min(3, 1 + len(chosen))
        steps.append({'name': ticket_name, 'arguments': {system_key: system, level_key: level}})
        steps.append({'name': notify_name, 'arguments': {who_key: high if level == 3 else low,
                                                         ref_key: f'{ref_prefix}-{level}-{ref_suffix}'}})
    else:
        steps.append({'name': notify_name, 'arguments': {who_key: fallback.group(1), ref_key: 'NONE'}})
    return {'steps': steps}


SOLVERS = {'ledger': solve_ledger, 'gonogo': solve_gonogo, 'replay': solve_replay,
           'manifest': solve_manifest, 'procedure': solve_procedure}


class MissionOpsTests(unittest.TestCase):
    def setUp(self):
        self.data = ability.load('mission-ops')

    def test_every_expected_answer_follows_from_the_prompt_alone(self):
        for item in self.data['items']:
            family = item['id'].split('-')[0]
            with self.subTest(item=item['id']):
                self.assertEqual(SOLVERS[family](item['prompt']), item['scorer']['expected'])

    def test_families_are_balanced_and_fit_the_campaign_limit(self):
        self.assertEqual(self.data['version'], '1.0.0')
        self.assertEqual(len(self.data['items']), 60)
        counts = Counter((item['id'].split('-')[0], item['scorer']['partition']) for item in self.data['items'])
        self.assertEqual(set(counts.values()), {6})
        self.assertEqual(len(counts), 10)
        choices = Counter(item['scorer']['expected'] for item in self.data['items']
                          if item['scorer']['kind'] == 'choice')
        self.assertLessEqual(max(choices.values()) - min(choices.values()), 1)

    def test_hard_parts_are_present_in_every_partition(self):
        for partition in ('practice', 'heldout'):
            items = [item for item in self.data['items'] if item['scorer']['partition'] == partition]
            ledger = [item['prompt'] for item in items if item['id'].startswith('ledger')]
            self.assertTrue(all('CANCELLED' in p and 'Correction:' in p for p in ledger))
            procedures = [item['scorer']['expected']['steps'] for item in items if item['id'].startswith('procedure')]
            self.assertEqual(Counter(len(steps) for steps in procedures), {4: 2, 6: 2, 7: 1, 8: 1})
            ties = 0
            for item in items:
                if item['id'].startswith('manifest'):
                    ranking = sorted(manifest_sums(item['prompt'])[0].values(), reverse=True)
                    ties += ranking[0] == ranking[1]
            self.assertGreaterEqual(ties, 1)

    def test_practice_and_heldout_share_no_vocabulary(self):
        def words(partition):
            return {word for item in self.data['items'] if item['scorer']['partition'] == partition
                    for word in re.findall(r'[a-z]+_[a-z0-9_]+', item['prompt'])}
        self.assertFalse(words('practice') & words('heldout'))
        sites = {partition: {item['prompt'].split(' ', 1)[0] for item in self.data['items']
                             if item['scorer']['partition'] == partition and not item['id'].startswith(('gonogo', 'procedure'))}
                 for partition in ('practice', 'heldout')}
        self.assertEqual(sites, {'practice': {'Kestrel'}, 'heldout': {'Tycho'}})

    def test_validator_rejects_unstated_keys_and_unbalanced_families(self):
        missing_key = copy.deepcopy(self.data)
        replay = next(item for item in missing_key['items'] if item['id'] == 'replay-01')
        replay['prompt'] = replay['prompt'].replace('"applied"', 'applied')
        with self.assertRaisesRegex(ValueError, 'name every output key'):
            ability.validate(missing_key)
        moved = copy.deepcopy(self.data)
        next(item for item in moved['items'] if item['id'] == 'ledger-01')['scorer']['partition'] = 'heldout'
        with self.assertRaisesRegex(ValueError, 'family or partition'):
            ability.validate(moved)
        unstated = copy.deepcopy(self.data)
        procedure = next(item for item in unstated['items'] if item['id'] == 'procedure-01')
        procedure['prompt'] = procedure['prompt'].replace('"name" and "arguments"', 'a name and arguments')
        with self.assertRaisesRegex(ValueError, 'state the step shape'):
            ability.validate(unstated)


if __name__ == '__main__':
    unittest.main()
