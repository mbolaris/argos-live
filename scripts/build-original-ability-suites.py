#!/usr/bin/env python3
"""Reproduce original MIT-licensed v1 fixtures; never fetch external datasets."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.ability import validate

CHOICES = [
    ('Which number is prime?', ['15', '17', '21', '27'], 'B'),
    ('Which planet is closest to the Sun?', ['Earth', 'Mars', 'Mercury', 'Venus'], 'C'),
    ('What is binary 10 in decimal?', ['1', '2', '10', '16'], 'B'),
    ('Which is the chemical formula for water?', ['CO2', 'O2', 'H2O', 'NaCl'], 'C'),
    ('Which shape has three sides?', ['Triangle', 'Square', 'Pentagon', 'Hexagon'], 'A'),
    ('What is hexadecimal F in decimal?', ['12', '13', '14', '15'], 'D'),
    ('Which ocean is largest by area?', ['Arctic', 'Indian', 'Atlantic', 'Pacific'], 'D'),
    ('Which mammal lays eggs?', ['Cat', 'Platypus', 'Horse', 'Whale'], 'B'),
    ('Which unit measures electric current?', ['Ampere', 'Metre', 'Kelvin', 'Second'], 'A'),
    ('What is the chemical symbol for oxygen?', ['Ox', 'Og', 'O', 'On'], 'C'),
    ('Which pair contains exactly the binary digits?', ['1 and 2', '0 and 1', '0 and 2', '2 and 3'], 'B'),
    ('Which word comes first alphabetically?', ['Pear', 'Plum', 'Peach', 'Apple'], 'D'),
    ('Which number is divisible by both 2 and 3?', ['14', '15', '18', '25'], 'C'),
    ('Which data structure follows first-in first-out order?', ['Queue', 'Stack', 'Set', 'Tree'], 'A'),
]


def items():
    groups = {kind: [] for kind in ('numeric', 'choice', 'instruction', 'json', 'tool-call')}
    def add(kind, index, prompt, scorer, reference, wrong, malformed):
        prefix = {'numeric': 'math', 'choice': 'choice', 'instruction': 'instruction', 'json': 'json', 'tool-call': 'tool'}[kind]
        groups[kind].append({'id': f'{prefix}-{index:02}', 'prompt': prompt,
            'scorer': dict(kind=kind, **scorer), 'reference': reference, 'wrong': wrong, 'malformed': malformed})
    for i in range(1, 15):
        a, b = 7 * i + 3, i + 2
        value = a * b - i
        add('numeric', i, f'Calculate {a} * {b} - {i}. Answer with one number only.',
            {'expected': str(value)}, str(value), str(value + 1), 'No numeric answer.')
        question, choices, correct = CHOICES[i - 1]
        prompt = question + '\n' + '\n'.join(f'{letter}. {text}' for letter, text in zip('ABCD', choices)) + '\nAnswer with one letter only.'
        add('choice', i, prompt, {'expected': correct}, correct, 'A' if correct != 'A' else 'B', 'Unknown')
        keyword = ['ready', 'local', 'private', 'model', 'memory', 'voice', 'image',
                   'browser', 'files', 'network', 'storage', 'assistant', 'offline', 'workspace'][i - 1]
        uppercase = i % 2 == 0
        reference = f'{keyword} is ready'
        if uppercase:
            reference = reference.upper()
        prompt = f'Write one line of two to five words including the whole word "{keyword}".'
        if uppercase:
            prompt += ' Use uppercase letters only.'
        add('instruction', i, prompt, {'min_words': 2, 'max_words': 5, 'keywords': [keyword],
            'one_line': True, 'uppercase': uppercase}, reference, 'WRONG ANSWER' if uppercase else 'wrong answer', '')
        expected = {'name': f'item-{i}', 'count': i + 3, 'enabled': i % 2 == 0}
        prompt = f'Return only JSON with exactly three keys: name="item-{i}", count=the sum of {i} and 3, enabled={str(expected["enabled"]).lower()}. Use a string, integer and boolean respectively.'
        wrong = dict(expected, count=i + 4)
        add('json', i, prompt, {'expected': expected}, json.dumps(expected), json.dumps(wrong), '{invalid}')
        expected = {'name': 'add_numbers', 'arguments': {'a': i, 'b': i + 5}}
        prompt = f'Format a proposed tool call as JSON only: name "add_numbers", arguments containing integer a={i} and b={i + 5}. Do not run any tool. Use exactly name and arguments at the top level.'
        wrong = {'name': 'subtract_numbers', 'arguments': expected['arguments']}
        add('tool-call', i, prompt, {'expected': expected}, json.dumps(expected), json.dumps(wrong), 'Run add_numbers now')
    return groups


def challenge_items(version='1.3.1'):
    """A separate higher-difficulty form; do not derive it from quick/standard."""
    if version not in ('1.0.0', '1.1.0', '1.2.0', '1.3.0', '1.3.1'):
        raise ValueError('Unknown challenge suite version')
    groups = {kind: [] for kind in ('numeric', 'choice', 'instruction', 'json', 'tool-call')}
    prefixes = {'numeric': 'calc', 'choice': 'logic', 'instruction': 'format',
                'json': 'record', 'tool-call': 'action'}

    def add(kind, index, prompt, expected, reference, wrong, malformed, **scorer_fields):
        groups[kind].append({'id': f'{prefixes[kind]}-{index:02}', 'prompt': prompt,
            'scorer': {'kind': kind, 'expected': expected, **scorer_fields}, 'reference': reference,
            'wrong': wrong, 'malformed': malformed})

    numeric = [
        ('A workshop has 240 minutes. It schedules three 35-minute sessions, two 12-minute breaks, and 28 minutes of setup. How many minutes remain?', '83'),
        ('A device costs $80. Apply a 15% discount first, then 8% tax to the discounted price. What is the final price in dollars?', '73.44'),
        ('A score is 72 with weight 2, 88 with weight 3, and 94 with weight 5. What is the weighted mean?', '87.8'),
        ('A recipe uses 4 cups of oats for every 3 cups of water. How many cups of water are needed for 10 cups of oats?', '7.5'),
        ('A shipment contains 432 parts. Remove 24 damaged parts, then divide the remainder equally among 6 teams. How many parts per team?', '68'),
        ('Inventory starts at 37 units, receives four boxes of 18, then ships three orders of 15. How many units remain?', '64'),
        ('Five workers each process 6 tickets per hour for 4 hours. If 15% of processed tickets need rework, how many are accepted?', '102'),
        ('A tank is one quarter full at 48 liters capacity. Add three containers of 7.5 liters each, then drain 5 liters. How many liters remain?', '29.5'),
    ]
    for i, (prompt, answer) in enumerate(numeric, 1):
        add('numeric', i, prompt + ' Answer with one number only.', answer, answer,
            str(int(float(answer)) + 1) if '.' not in answer else str(float(answer) + 1), 'The answer is about ' + answer)

    choices = [
        ('A team can do one task next. A is due at 14:00 and takes 20 minutes; B is due at 13:00 and takes 45 minutes; C is due at 13:30 and takes 10 minutes. It is now 12:00. Choose the task with the earliest deadline, not the shortest duration.', ['A', 'B', 'C', 'They have the same deadline'], 'B'),
        ('Publish a report only when status is approved and at least two reviewers signed. Which record qualifies? A: approved, 1 signer; B: pending, 3 signers; C: approved, 2 signers; D: approved, 0 signers.', ['Record A', 'Record B', 'Record C', 'Record D'], 'C'),
        ('A delivery must use a route under 30 km and with no toll. North is 24 km with a toll; East is 31 km without a toll; South is 27 km without a toll; West is 20 km with a toll. Which route meets both rules?', ['North', 'East', 'South', 'West'], 'C'),
        ('A note says: “The spare key is stored in the cabinet. The cabinet code is not recorded.” Which claim is supported by the note?', ['The key is in the cabinet.', 'The code is 0000.', 'The cabinet is locked.', 'The key is missing.'], 'A'),
        ('Choose a supplier that meets all requirements: delivery within 5 days, warranty at least 2 years, and price below $500. Alder: 4 days, 1 year, $420. Birch: 6 days, 3 years, $390. Cedar: 5 days, 2 years, $480. Dogwood: 3 days, 3 years, $510.', ['Alder', 'Birch', 'Cedar', 'Dogwood'], 'C'),
        ('A job may start only after both review and backup are complete. Review is complete; backup is pending. What is the correct status?', ['Ready to start', 'Blocked until backup completes', 'Cancelled', 'Unknown because review is incomplete'], 'B'),
        ('A sequence follows this rule: add 3, then multiply by 2, repeating those operations. It begins 2, 5, 10, 13, ... What is the next value?', ['16', '26', '32', '29'], 'B'),
        ('A file is eligible for deletion only if it is duplicated, backed up, and not marked keep. Which file is eligible? A: duplicate, backed up, keep. B: duplicate, not backed up, not keep. C: unique, backed up, not keep. D: duplicate, backed up, not keep.', ['A', 'B', 'C', 'D'], 'D'),
    ]
    for i, (question, options, answer) in enumerate(choices, 1):
        prompt = question + '\n' + '\n'.join(f'{letter}. {value}' for letter, value in zip('ABCD', options)) + '\nAnswer with one letter only.'
        add('choice', i, prompt, answer, answer, 'A' if answer != 'A' else 'B', 'Option C')

    instructions = [
        (['backup', 'verify', 'owner'], False), (['private', 'review', 'first'], True),
        (['measure', 'compare', 'repeat'], False), (['evidence', 'before', 'claim'], True),
        (['restore', 'snapshot', 'safely'], False), (['uncertain', 'report', 'honestly'], True),
        (['scope', 'limit', 'resources'], False), (['test', 'record', 'result'], True),
    ]
    for i, (keywords, uppercase) in enumerate(instructions, 1):
        words = 6 if i % 2 else 7
        casing = ' Use uppercase letters only.' if uppercase else ''
        prompt = f'Write one line of {words} to {words + 2} words. Include every whole word: ' + ', '.join(f'"{word}"' for word in keywords) + '.' + casing
        reference = ' '.join(keywords + ['carefully', 'before', 'proceeding', 'today'])
        reference = ' '.join(reference.split()[:words])
        if uppercase:
            reference = reference.upper()
        scorer = {'kind': 'instruction', 'min_words': words, 'max_words': words + 2,
                  'keywords': keywords, 'one_line': True, 'uppercase': uppercase}
        groups['instruction'].append({'id': f'format-{i:02}', 'prompt': prompt,
            'scorer': scorer, 'reference': reference,
            'wrong': 'WRONG ANSWER NOW' if uppercase else 'wrong answer now', 'malformed': ''})

    records = [
        ('From a repair log, report ticket 17, 2 attempts, resolved=true.',
         {'ticket': 17, 'attempts': 2, 'resolved': True}, 'Return JSON with integer ticket=17, integer attempts=2, boolean resolved=true.'),
        ('A crate has 12 items; 3 are damaged. Report received, damaged, usable.',
         {'received': 12, 'damaged': 3, 'usable': 9}, 'Return JSON with integer received=12, damaged=3, usable=9.'),
        ('A study has group A with 8 people and group B with 11. Report both counts and the total.',
         {'groups': {'A': 8, 'B': 11}, 'total': 19}, 'Return JSON with groups object A=8 and B=11, and integer total=19.'),
        ('A device is named Atlas, has 64 GB free, and is encrypted. Report these fields.',
         {'device': 'Atlas', 'free_gb': 64, 'encrypted': True}, 'Return JSON with string device="Atlas", integer free_gb=64, boolean encrypted=true.'),
        ('Three checks have statuses pass, pass, fail. Report the ordered statuses and pass count.',
         {'statuses': ['pass', 'pass', 'fail'], 'passed': 2}, 'Return JSON with statuses array ["pass","pass","fail"] and integer passed=2.'),
        ('A meeting starts at 09:15 and lasts 50 minutes. Report start and end as 24-hour HH:MM strings.',
         {'start': '09:15', 'end': '10:05'}, 'Return JSON with string start="09:15" and end="10:05".'),
        ('A request has id R-8, priority high, and is waiting. Report all three fields.',
         {'id': 'R-8', 'priority': 'high', 'waiting': True}, 'Return JSON with string id="R-8", string priority="high", boolean waiting=true.'),
        ('A batch expected 7 records and all 7 were processed: 5 accepted and 2 rejected. Report both counts and complete=true.',
         {'accepted': 5, 'rejected': 2, 'complete': True}, 'Return JSON with integer accepted=5, integer rejected=2, boolean complete=true.'),
    ]
    def altered(value):
        if type(value) is bool:
            return not value
        if type(value) is int:
            return value + 1
        if isinstance(value, str):
            return value + 'x'
        if isinstance(value, list):
            return [altered(value[0]), *value[1:]]
        if isinstance(value, dict):
            result = dict(value)
            key = next(iter(result))
            result[key] = altered(result[key])
            return result
        raise ValueError('Unsupported challenge reference')

    if version in ('1.3.0', '1.3.1'):
        # A fresh, higher-composition form aimed at the 100% ceiling in the
        # earlier challenge. Keep the deterministic scorer and save exact
        # prompts/results; this is a new baseline, not a matched comparison.
        groups = {kind: [] for kind in ('numeric', 'choice', 'instruction', 'json', 'tool-call')}
        numeric = [
            ('A run creates 3,200 samples. Exactly 12.5% fail first inspection; 60% of failures are repaired, and all other failed samples are discarded. How many usable samples remain?', '3040'),
            ('Five route legs measure 18.4, 21.6, 17.5, 22.5, and 20 km. A final detour adds 12% of their total distance. What is the final distance?', '112'),
            ('A well-mixed 800 mL solution has 15% solute. Remove 200 mL, then add 200 mL pure water. How many mL of solute remain?', '90'),
            ('A team processes 8 records per minute for a 5-hour shift. Breaks total 30 minutes; utilization during the remaining time is 75%. How many records are processed?', '1620'),
            ('A device worth $1,200 loses 20% of its value, then 10% of its new value. A repair adds $48 to resale value. What is the net resale value?', '912'),
            ('A queue contains 640 jobs. Archive 3/8 of them; then retry 1/5 of the non-archived remainder. How many non-archived jobs are not retried?', '320'),
            ('Four regions score 82, 91, 76, and 95 with respective population weights 2, 1, 3, and 4. What is the weighted mean?', '86.3'),
            ('A spool contains 12.5 m. Remove 2.5 m, then use 3/5 of what remains. How many metres remain?', '4'),
        ]
        for i, (question, answer) in enumerate(numeric, 1):
            wrong = str(int(float(answer)) + 1) if float(answer).is_integer() else str(float(answer) + 1)
            add('numeric', i, question + ' Answer with one number only.', answer, answer,
                wrong, 'No numeric answer.')

        choices = [
            ('An export is permitted only when it is encrypted and its destination is approved. Which record qualifies?',
             ['Encrypted, approved', 'Encrypted, unapproved', 'Unencrypted, approved', 'Unencrypted, unapproved'], 'A'),
            ('A release may proceed only if its checksum matches and at least two independent reviewers approved. Build A: match, two; B: mismatch, three; C: match, one; D: unknown, three. Which build may proceed?',
             ['Build A', 'Build B', 'Build C', 'Build D'], 'A'),
            ('A note says checks A and C passed, B timed out, and D was not sampled. Which statement is supported?',
             ['A and C passed', 'B failed', 'D passed', 'All four checks completed'], 'A'),
            ('At 08:00, backup takes 35 minutes and scan takes 50 minutes; they run in parallel. Review then takes 20 minutes, followed by a 15-minute deploy. What is the earliest finish time?',
             ['09:10', '09:15', '09:25', '09:40'], 'C'),
            ('An archive is deletable only if it is a duplicate, its backup is verified, retention expired, and it is not marked keep. P: yes/yes/yes/no; Q: yes/no/yes/no; R: yes/yes/no/no; S: yes/yes/yes/yes. Which is deletable?',
             ['P only', 'P and Q', 'P and R', 'P and S'], 'A'),
            ('Order incidents newest first, preserving source order for equal timestamps. Source order: A 10:05, B 10:03, C 10:05, D 10:06. Which order is correct?',
             ['D, A, C, B', 'D, C, A, B', 'A, C, D, B', 'B, A, C, D'], 'A'),
            ('A policy retains ordinary logs for 30 days and confirmed security-incident logs for 90 days. ' + ('Logs from unconfirmed incidents are classified as ordinary. ' if version == '1.3.1' else '') + 'A suspected incident is not confirmed. How long should these logs be retained?',
             ['30 days', '60 days', '90 days', 'The policy gives no duration'], 'A'),
            ('A note says a report is ready and its content is approved, but gives no publishing window. What exact time should it be published?',
             ['Immediately', 'At 09:00', 'At the next hour', 'Cannot be determined from the note'], 'D'),
        ]
        for i, (question, options, answer) in enumerate(choices, 1):
            prompt = question + '\n' + '\n'.join(
                f'{letter}. {value}' for letter, value in zip('ABCD', options))
            prompt += '\nAnswer with one letter only.'
            add('choice', i, prompt, answer, answer,
                'A' if answer != 'A' else 'B', 'Option C')

        instruction_keywords = [
            ['snapshot', 'verify', 'encrypted', 'records', 'owner', 'before'],
            ['baseline', 'candidate', 'evidence', 'compare', 'result', 'repeat'],
            ['private', 'data', 'never', 'share', 'without', 'approval'],
            ['model', 'change', 'retain', 'only', 'measured', 'improvement'],
            ['gateway', 'restart', 'readiness', 'verify', 'before', 'claim'],
            ['uncertainty', 'report', 'missing', 'evidence', 'clearly', 'now'],
            ['human', 'approval', 'required', 'before', 'storage', 'write'],
            ['practice', 'heldout', 'keep', 'separate', 'verify', 'transfer'],
        ]
        for i, keywords in enumerate(instruction_keywords, 1):
            uppercase = i % 2 == 0
            prompt = ('Write exactly 14 words on one line. Include each whole word: '
                      + ', '.join(f'"{word}"' for word in keywords) + '.')
            if uppercase:
                prompt += ' Use uppercase letters only.'
            reference = ' '.join(keywords +
                                 ['carefully', 'and', 'record', 'each', 'result',
                                  'without', 'guessing', 'today'])
            if uppercase:
                reference = reference.upper()
            groups['instruction'].append({
                'id': f'format-{i:02}', 'prompt': prompt,
                'scorer': {'kind': 'instruction', 'min_words': 14, 'max_words': 14,
                           'keywords': keywords, 'one_line': True, 'uppercase': uppercase},
                'reference': reference,
                'wrong': 'WRONG ANSWER' if uppercase else 'wrong answer', 'malformed': ''})

        records = [
            ('Events: A pass and verified; B pass but unverified; C fail but verified; D pass and verified. A record passes only when both conditions are true. Preserve source order.',
             {'passed_ids': ['A', 'D'], 'passed_count': 2, 'needs_review': ['B', 'C']}),
            ('A job starts at 23:35 and lasts 95 minutes. Report its start, 24-hour end time, and whether it crosses midnight.',
             {'start': '23:35', 'end': '01:10', 'crosses_midnight': True}),
            ('In source order, archive rows are C-3 duplicate/backup-verified/not-keep; B-2 duplicate/not-verified/not-keep; A-1 duplicate/verified/not-keep; D-4 unique/verified/not-keep. Only duplicates with verified backups and no keep mark qualify. Report IDs in source order and the count.',
             {'eligible_ids': ['C-3', 'A-1'], 'eligible_count': 2}),
            ('Valid weighted samples are A: score 80, weight 2; B: score 90, weight 3. C has score 100 but is invalid. Report the weighted mean and number of valid samples.',
             {'weighted_mean': 86, 'valid_samples': 2}),
            ('Three batches accepted/rejected: 14/3, 12/5, and 9/1. The expected total is 44. Report aggregate accepted, rejected, total, and whether processing is complete.',
             {'accepted': 35, 'rejected': 9, 'total': 44, 'complete': True}),
            ('Record: owner Mina; roles viewer then exporter; private data requested; owner approval is false. Private data may be included only with owner approval. Report owner, roles in order, and include_private.',
             {'owner': 'Mina', 'roles': ['viewer', 'exporter'], 'include_private': False}),
            ('Jobs: R-7 starts 11:50 and lasts 45 minutes; R-3 starts 11:20 and lasts 30 minutes; R-8 starts 11:55 and lasts 20 minutes. Report the earliest finishing ID, end time, and duration.',
             {'earliest_id': 'R-3', 'end': '11:50', 'duration_minutes': 30}),
            ('A record qualifies only when approved, backup-verified, and signed by at least two reviewers. A: approved/verified/2; B: approved/unverified/3; C: pending/verified/3; D: approved/verified/1. Report eligible IDs and their count.',
             {'eligible_ids': ['A'], 'eligible_count': 1}),
        ]
        for i, (context, expected) in enumerate(records, 1):
            if version == '1.3.1':
                if i == 1:
                    context += ' Records that do not pass need review.'
                elif i == 5:
                    context += ' Processing is complete exactly when the aggregate total equals the expected total.'
                type_names = {str: 'string', int: 'integer', bool: 'boolean', list: 'array of strings'}
                schema = {key: type_names[type(value)] for key, value in expected.items()}
                prompt = context + ' Return only a JSON object with exactly these fields and types: ' + json.dumps(schema, separators=(',', ':')) + '.'
            else:
                prompt = context + ' Return only JSON with exactly the fields and types shown by the request.'
            add('json', i, prompt, expected, json.dumps(expected),
                json.dumps(altered(expected)), '{not json}')

        actions = [
            ('lookup_record', {'record_id': 'R-208', 'include_history': False},
             'Retrieve record R-208 but do not include its history.'),
            ('compare_runs', {'baseline_id': 'build-41', 'candidate_id': 'build-17'},
             'Compare build-41 as the baseline with build-17 as the candidate, even though the candidate number is lower.'),
            ('create_report', {'title': 'Quarterly checksum review', 'format': 'json', 'include_private': False},
             'Create a public report titled Quarterly checksum review. Use exactly lowercase json as its format.'),
            ('request_clarification', {'field': 'timezone', 'question': 'Which timezone should I use for 09:00?'},
             'The requested reservation starts at 09:00 local time, but no timezone or default is supplied. Obtain the missing required detail without guessing.'),
            ('set_filter', {'field': 'status', 'value': 'complete', 'exact': True},
             'Filter records whose status is exactly complete; partial or case-different matches must not count.'),
            ('summarize_range', {'start': 23, 'end': 31, 'unit': 'rows'},
             'Summarize source rows numbered 23 through 31, including both endpoints.'),
            ('request_review', {'change_id': 'chg-52', 'reviewer': 'owner'},
             'Request owner review for change chg-52.'),
            ('export_receipt', {'run_id': 'run-93', 'redact_paths': True},
             'Export run-93 and redact every path in the receipt.'),
        ]
        descriptions = {
            'lookup_record': 'Retrieve a record by exact ID and optionally include its history.',
            'compare_runs': 'Compare a baseline run with a candidate run.',
            'create_report': 'Create a report with a title, format, and private-data inclusion flag.',
            'request_clarification': 'Ask for one missing required field without inventing a default.',
            'set_filter': 'Apply a field/value filter and choose exact matching.',
            'summarize_range': 'Summarize an inclusive range of items and specify the unit.',
            'request_review': 'Request review for a change and specify the reviewer.',
            'export_receipt': 'Export a run receipt and choose whether paths are redacted.',
        }
        catalog = []
        for name, arguments, _request in actions:
            types = {str: 'string', int: 'integer', bool: 'boolean'}
            catalog.append({'name': name, 'description': descriptions[name],
                            'arguments': {key: types[type(value)]
                                          for key, value in arguments.items()}})
        for i, (name, arguments, request) in enumerate(actions, 1):
            if version == '1.3.1' and name == 'request_clarification':
                request += ' Use exactly "Which timezone should I use for 09:00?" as the question argument.'
            expected = {'name': name, 'arguments': arguments}
            reference = json.dumps(expected)
            wrong = json.dumps({'name': 'wrong_tool', 'arguments': arguments})
            schemas = [catalog[(i - 1 + offset) % len(catalog)] for offset in range(4)]
            target = schemas.pop(0)
            schemas.insert((i - 1) % 4, target)
            prompt = ('Choose the available action that satisfies the full request. Available tool schemas: '
                      + json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False)
                      + '\nRequest: ' + request
                      + '\nReturn only the exact JSON tool-call object with top-level keys "name" and "arguments". '
                      'Set "name" to the selected tool\'s exact name and include every argument required by its '
                      'schema with the listed primitive types. Use no extra fields, do not use Markdown fences, '
                      'and do not execute the action.')
            add('tool-call', i, prompt, expected, reference, wrong, '{not json}',
                available_tools=schemas)
        return groups
    for i, (context, expected, instruction) in enumerate(records, 1):
        prompt = context + ' ' + instruction + ' Return only JSON with exactly the requested fields.'
        wrong = altered(expected)
        add('json', i, prompt, expected, json.dumps(expected), json.dumps(wrong), '{not json}')

    actions = [
        ('lookup_record', {'record_id': 'R-14', 'include_history': True}, 'Propose lookup_record for record R-14 and include history.'),
        ('compare_runs', {'baseline_id': 'base-3', 'candidate_id': 'cand-8'}, 'Propose compare_runs for baseline base-3 and candidate cand-8.'),
        ('create_report', {'title': 'Cycle audit', 'format': 'json', 'include_private': False}, 'Propose a JSON Cycle audit report and exclude private data.'),
        ('schedule_task', {'task': 'backup verification', 'hour': 6, 'enabled': True}, 'Propose scheduling backup verification at hour 6, enabled.'),
        ('set_filter', {'field': 'state', 'value': 'completed', 'exact': True}, 'Propose an exact filter for state=completed.'),
        ('summarize_range', {'start': 12, 'end': 18, 'unit': 'items'}, 'Propose summarizing items 12 through 18.'),
        ('request_review', {'change_id': 'chg-21', 'reviewer': 'owner'}, 'Propose owner review for change chg-21.'),
        ('export_receipt', {'run_id': 'run-44', 'redact_paths': True}, 'Propose exporting run-44 with paths redacted.'),
    ]
    descriptions = {
        'lookup_record': 'Retrieve a record by exact ID and optionally include its history.',
        'compare_runs': 'Compare a baseline run with a candidate run.',
        'create_report': 'Create a report with a title, format, and private-data inclusion flag.',
        'schedule_task': 'Schedule a named task for an hour and choose whether it is enabled.',
        'set_filter': 'Apply a field/value filter and choose exact matching.',
        'summarize_range': 'Summarize an inclusive range of items and specify the unit.',
        'request_review': 'Request review for a change and specify the reviewer.',
        'export_receipt': 'Export a run receipt and choose whether paths are redacted.',
    }
    requests = [
        'Look up record R-14 and include its history.',
        'Compare baseline base-3 with candidate cand-8.',
        'Create a report titled Cycle audit in JSON format; exclude private data.',
        'Schedule backup verification at hour 6 and enable the task.',
        'Set an exact filter on field state with value completed.',
        'Summarize items 12 through 18, inclusive.',
        'Request owner review for change chg-21.',
        'Export run-44 with paths redacted.',
    ]
    for i, (name, arguments, legacy_prompt) in enumerate(actions, 1):
        expected = {'name': name, 'arguments': arguments}
        reference = json.dumps(expected)
        wrong = json.dumps({'name': 'wrong_tool', 'arguments': arguments})
        if version == '1.0.0':
            add('tool-call', i, legacy_prompt + ' Return only a JSON tool-call object; do not execute it.',
                expected, reference, wrong, 'Execute the action now.')
            continue
        types = {str: 'string', int: 'integer', bool: 'boolean'}
        catalog = []
        for candidate_name, candidate_arguments, _candidate_prompt in actions:
            catalog.append({'name': candidate_name, 'description': descriptions[candidate_name],
                            'arguments': {key: types[type(value)]
                                          for key, value in candidate_arguments.items()}})
        start = i - 1
        schemas = [catalog[(start + offset) % len(catalog)] for offset in range(4)]
        target = schemas.pop(0)
        schemas.insert((i - 1) % 4, target)
        request = requests[i - 1]
        if version == '1.2.0' and i == 3:
            request += ' Use the exact lowercase string "json" as the format argument.'
        prompt = ('Choose the available action that satisfies the complete request. Available tool schemas: '
                  + json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False)
                  + '\nRequest: ' + request
                  + '\nReturn only the exact JSON tool-call object with top-level keys "name" and "arguments". '
                  'Set "name" to the selected tool\'s exact name and include every argument required by its '
                  'schema with the listed primitive types. Use no extra fields, do not use Markdown fences, and do not execute the action.')
        add('tool-call', i, prompt, expected, reference, wrong, '{not json}', available_tools=schemas)
    return groups


def challenge_hard_items():
    """Build 80 original higher-composition tasks with a fixed 40/40 partition split."""
    groups = {kind: [] for kind in ('numeric', 'choice', 'instruction', 'json', 'tool-call')}
    prefixes = {'numeric': 'calc', 'choice': 'logic', 'instruction': 'format',
                'json': 'record', 'tool-call': 'action'}

    def add(kind, index, prompt, expected, reference, wrong, malformed, **fields):
        partition = 'practice' if index <= 8 else 'heldout'
        scorer = {'kind': kind, 'partition': partition}
        scorer.update(expected if kind == 'instruction' else {'expected': expected})
        scorer.update(fields)
        groups[kind].append({'id': f'{prefixes[kind]}-{index:02}', 'prompt': prompt,
            'scorer': scorer,
            'reference': reference, 'wrong': wrong, 'malformed': malformed})

    equations = [(840,17,9,7,2), (1250,12,18,5,3), (960,15,24,8,4), (735,22,15,5,2),
        (1440,11,27,9,3), (1080,14,16,7,4), (1680,13,20,8,5), (910,19,21,6,3),
        (1320,16,28,7,4), (1560,18,30,9,5), (1170,23,24,8,3), (1890,12,35,10,4),
        (1020,21,18,6,2), (1750,17,32,7,5), (1260,25,27,9,4), (2040,14,33,11,3)]
    for index, (stock, used, reserved, kits, group_size) in enumerate(equations, 1):
        answer = (stock - used * kits - reserved) // group_size
        prompt = (f'A depot starts with {stock} sealed units. It issues {kits} kits of {used} units, '
                  f'reserves {reserved} for inspection, then sorts the remainder into groups of '
                  f'{group_size}. How many complete groups are there? Give one number only.')
        add('numeric', index, prompt, str(answer), str(answer), str(answer + 1), 'About ' + str(answer))

    logic = [
        ('A release needs two approvals and a checksum. Which record is ready? A: 2 approvals, checksum missing. B: 3 approvals, checksum valid. C: 1 approval, checksum valid. D: 2 approvals, checksum invalid.', 'B'),
        ('Rules: review before publish; backup before delete. Which schedule is valid? A: publish, review, backup, delete. B: review, backup, publish, delete. C: backup, delete, review, publish. D: review, publish, delete, backup.', 'B'),
        ('A lot passes only if defects are below 2% and sample size is at least 500. Which passes? A: 1.9%, 480. B: 2.0%, 900. C: 1.8%, 520. D: 0.5%, 300.', 'C'),
        ('Only the newest signed policy overrides an older one. R is signed Monday; S is unsigned Tuesday; T is signed Wednesday. Which controls? A: R. B: S. C: T. D: whichever is stricter.', 'C'),
        ('A route must take under 50 minutes and have no transfer. A: 42 min, 1 transfer. B: 50 min, none. C: 48 min, none. D: 55 min, none.', 'C'),
        ('A job runs only if its lock is held and input verified. Lock held; input verification failed. A: run. B: wait for verification. C: cancel lock. D: run read-only.', 'B'),
        ('All archived items have digests; some digested items are not archived. Which must be true? A: no digest means archived. B: archived items have digests. C: all digested items are archived. D: no archived items have digests.', 'B'),
        ('A shipment qualifies when sealed, labeled, and below 20 kg. Which qualifies? A: sealed, labeled, 20 kg. B: unsealed, labeled, 12 kg. C: sealed, unlabeled, 10 kg. D: sealed, labeled, 19.8 kg.', 'D'),
        ('If the primary sensor is stale, use the secondary only when calibrated. Primary is stale; secondary calibration is unknown. A: use primary. B: use secondary. C: report no verified reading. D: average both.', 'C'),
        ('A report may be shared internally after review, externally only after owner approval. Review passed; approval pending. A: share externally. B: share internally only. C: share nowhere. D: publish publicly.', 'B'),
        ('A batch is valid when exactly one of X or Y is present and Z is present. Which is valid? A: X and Z. B: X, Y and Z. C: Y only. D: X only.', 'A'),
        ('The spare is in cabinets A–D. It is not in A or C. B is sealed; D is open. Which location is supported? A: A. B: B. C: C. D: D.', 'D'),
        ('Priority is urgent over normal, then earlier deadline. Which ranks first? A: normal, 09:00. B: urgent, 11:00. C: urgent, 10:00. D: normal, 08:00.', 'C'),
        ('A checksum mismatch blocks restore unless a second independent copy matches. Primary mismatches; second copy matches. A: restore primary. B: restore second copy. C: refuse all restore. D: ignore checksums.', 'B'),
        ('A log is complete only if every page has a timestamp and the final page is signed. All timestamps exist; final page unsigned. A: complete. B: incomplete. C: complete if page one signed. D: timestamps are irrelevant.', 'B'),
        ('A test is independent only if it shares neither seed nor prompt with training. It shares the prompt but has a new seed. A: independent. B: not independent. C: independent if score is low. D: cannot tell without the answer.', 'B')]
    for index, (prompt, expected) in enumerate(logic, 1):
        add('choice', index, prompt + '\nAnswer with one letter only.', expected, expected,
            'A' if expected != 'A' else 'D', 'Option B')

    constraints = [
        (['verify','source','before','release'],7,False), (['private','records','stay','local'],8,True),
        (['uncertain','values','remain','unknown'],7,False), (['compare','matching','versions','only'],8,True),
        (['backup','restore','after','review'],7,False), (['reject','unsigned','policy','changes'],8,True),
        (['measure','latency','separately','from','accuracy'],9,False), (['sealed','prompts','never','enter','reports'],9,True),
        (['confirm','identity','before','restarting'],7,False), (['report','partial','coverage','plainly'],8,True),
        (['preserve','owner','changes','during','evaluation'],9,False), (['cancelled','runs','cannot','rank','beside','complete'],10,True),
        (['state','what','the','evidence','supports'],8,False), (['restore','the','same','verified','profile'],8,True),
        (['tools','remain','plans','unless','execution','is','verified'],11,False),
        (['different','suite','versions','must','not','be','compared'],11,True)]
    for index, (keywords, exact, uppercase) in enumerate(constraints, 1):
        reference = ' '.join(keywords + ['carefully'] * (exact - len(keywords)))
        if uppercase:
            reference = reference.upper()
        prompt = (f'Write exactly {exact} words on one line. Include every whole word: '
                  + ', '.join(f'"{word}"' for word in keywords) + '.')
        prompt += ' Use uppercase letters only.' if uppercase else ''
        add('instruction', index, prompt,
            {'min_words': exact, 'max_words': exact, 'keywords': keywords,
             'one_line': True, 'uppercase': uppercase}, reference,
            'UNRELATED WORDS ONLY' if uppercase else 'unrelated words only', '')

    for index in range(1, 17):
        a, b, c = index + 7, index * 3 + 11, index + 2
        expected = {'record': f'R-{index:02}', 'usable': a * b - c,
                    'reviewed': index % 2 == 0, 'owners': [f'ops-{index:02}', f'audit-{index:02}']}
        prompt = (f'Return JSON only with exactly keys record, usable, reviewed, owners. For record use '
                  f'"R-{index:02}". Set usable to ({a} times {b}) minus {c}. Set reviewed to '
                  f'{str(expected["reviewed"]).lower()}. Set owners to the ordered array '
                  f'["ops-{index:02}", "audit-{index:02}"]. Preserve string, integer, boolean and array types.')
        add('json', index, prompt, expected, json.dumps(expected),
            json.dumps(dict(expected, usable=expected['usable'] + 1)), '{not json}')

    for index in range(1, 17):
        partition = 'practice' if index <= 8 else 'heldout'
        target, distractor = f'archive_{partition}_{index:02}', f'export_{partition}_{index:02}'
        arguments = {'batch': f'B-{index:02}', 'limit': index * 7 + 20, 'dry_run': True}
        schemas = [
            {'name': distractor, 'description': 'Exports the batch to a public destination.',
             'arguments': {'batch': 'string', 'limit': 'integer', 'dry_run': 'boolean'}},
            {'name': target, 'description': 'Stages the batch privately without executing it.',
             'arguments': {'batch': 'string', 'limit': 'integer', 'dry_run': 'boolean'}},
            {'name': f'inspect_{partition}_{index:02}', 'description': 'Reads archive metadata only.',
             'arguments': {'batch': 'string'}},
            {'name': f'delete_{partition}_{index:02}', 'description': 'Deletes the selected batch.',
             'arguments': {'batch': 'string', 'confirm': 'boolean'}}]
        expected = {'name': target, 'arguments': arguments}
        prompt = ('Available tool schemas:\n' + json.dumps({'tools': schemas}, separators=(',', ':'))
                  + f'\nRequest: Stage batch B-{index:02} privately in the archive, retain the newest '
                    f'{arguments["limit"]} records, and do not execute the change. Return JSON only '
                    'with exactly name and arguments.')
        add('tool-call', index, prompt, expected, json.dumps(expected),
            json.dumps({'name': distractor, 'arguments': arguments}), 'Run the tool now.',
            available_tools=schemas)
    return groups


def challenge_deep_items():
    """Build 100 original compositional probes, balanced by type and split."""
    result = []
    kinds = ('numeric', 'choice', 'instruction', 'json', 'tool-call')
    prefixes = {'numeric': 'calc', 'choice': 'logic', 'instruction': 'format',
                'json': 'record', 'tool-call': 'action'}

    def add(kind, index, prompt, expected, reference, wrong, malformed, **fields):
        partition = 'practice' if index <= 10 else 'heldout'
        scorer = {'kind': kind, 'partition': partition}
        scorer.update(expected if kind == 'instruction' else {'expected': expected})
        scorer.update(fields)
        result.append({'id': f'{prefixes[kind]}-{index:02}', 'prompt': prompt,
                       'scorer': scorer, 'reference': reference, 'wrong': wrong,
                       'malformed': malformed})

    # Two or three dependent operations, including sequential percentage changes.
    for i in range(1, 21):
        base = 480 + i * 37
        first = 11 + (i % 7) * 3
        divisor = 4 + (i % 5)
        reserve = 13 + i * 2
        if i % 4 == 0:
            expected = (base * (100 - first) * (100 + divisor) // 10000) - reserve
            prompt = (f'A service has {base} units. It loses {first}% of capacity, then gains '
                      f'{divisor}% of the remaining capacity, then sets aside {reserve} units. '
                      'Using exact arithmetic and flooring only the final result, how many remain? Give one number.')
            answer = str(expected)
        else:
            numerator = base * first + reserve
            answer = str(numerator // divisor)
            prompt = (f'A ledger starts at {base}. Multiply by {first}, add {reserve}, then divide by '
                      f'{divisor}. Return the exact quotient rounded down to one integer.')
        add('numeric', i, prompt, answer, answer, str(float(answer) + 1), 'The result is ' + answer)

    # Require selecting the sole option satisfying all conditions and ordering rules.
    logic = [
        ('A deployment requires approval, a passing check, and a backup newer than the build. A: approved, pass, older backup. B: approved, fail, newer backup. C: approved, pass, newer backup. D: pending, pass, newer backup.', 'C'),
        ('Choose a route under 40 minutes, with no transfer, and accessible. A: 32 min, one transfer, accessible. B: 40 min, none, accessible. C: 39 min, none, inaccessible. D: 38 min, none, accessible.', 'D'),
        ('Exactly one of P and Q must be true, and R must be false. A: P true, Q false, R false. B: P true, Q true, R false. C: P false, Q false, R false. D: P false, Q true, R true.', 'A'),
        ('A record is current only when signed by the owner and newer than the prior record. A: owner signed, older. B: reviewer signed, newer. C: owner signed, newer. D: unsigned, newest.', 'C'),
        ('A task is eligible if it is urgent OR (approved AND has a verified input). A: normal, approved, unverified. B: urgent, unapproved, unverified. C: normal, unapproved, verified. D: normal, unapproved, verified.', 'B'),
        ('Pick the item with the lowest risk score among those with complete evidence. A: score 2, incomplete. B: score 5, complete. C: score 3, complete. D: score 1, incomplete.', 'C'),
        ('A restore is allowed only from a signed snapshot, and if the checksum mismatches it needs an independent matching copy. Which mismatch case is safe to restore? A: signed, mismatch, no copy. B: unsigned, match. C: signed, mismatch, independent copy matches. D: unsigned, match.', 'C'),
        ('A batch passes only when defects < 1% and sample >= 800. An audited exception allows up to 1.2% defects only when sample >= 1000. A: 0.9%, 799, no exception. B: 1%, 900, exception. C: 1.1%, 900, no exception. D: 0.8%, 800, no exception.', 'D'),
        ('Priority order is blocked first, then urgent, then ordinary; within a class use earlier deadline. A: urgent 09:00. B: blocked 11:00. C: urgent 08:00. D: ordinary 07:00.', 'B'),
        ('A file can be shared externally only after owner approval AND redaction. A: approved, not redacted. B: redacted, approval pending. C: approved and redacted. D: neither.', 'C'),
        ('Exactly two of A, B, C are true. A: A and B true, C false. B: A true, B false, C false. C: A false, B false, C true. D: all true.', 'A'),
        ('Choose a schedule where backup precedes migration, migration precedes verification, and verification precedes deletion. A: backup, migration, verify, delete. B: migration, backup, verify, delete. C: backup, verify, migration, delete. D: backup, migration, delete, verify.', 'A'),
        ('A candidate is valid if it matches the required model digest and either has two successful runs or one success plus independent review. A: digest match, one success, no review. B: digest mismatch, two successes. C: match, one success, independent review. D: match, one failed run, review.', 'C'),
        ('Choose the only entry that is both newer than 12:00 and has severity at least 3. A: 12:01, severity 2. B: 12:00, severity 4. C: 12:10, severity 3. D: 11:59, severity 5.', 'C'),
        ('An item is retained when it is tagged keep, unless it contains a confirmed secret. A: keep tag, no secret. B: no keep tag, no secret. C: keep tag, confirmed secret. D: no keep tag, secret.', 'A'),
        ('A test is independent only when both its prompt and seed differ from training. A: same prompt, new seed. B: new prompt, same seed. C: both new. D: both same.', 'C'),
        ('Select the single least costly plan that meets at least 99% coverage and completes by Friday. A: $8, 99%, Saturday. B: $10, 99%, Friday. C: $9, 98%, Thursday. D: $12, 100%, Friday.', 'B'),
        ('A release needs two of three reviewers, including security, and no unresolved blocker. A: security+ops, blocker open. B: ops+owner, no blocker. C: security+owner, no blocker. D: security only, no blocker.', 'C'),
        ('A sensor reading is usable when calibrated and recent; if primary is not usable, secondary is usable only if independently checked. Primary: recent, uncalibrated. Secondary: calibrated, recent, unchecked. A: use primary. B: use secondary. C: report no verified reading. D: average them.', 'C'),
        ('Pick the valid chain: each step must cite the immediately prior ID, and final approval must follow verification. A: intake, verify cites intake, approve cites verify. B: intake, verify cites old, approve cites verify. C: intake, approve cites intake, verify cites approve. D: verify, intake cites verify, approve cites intake.', 'A'),
    ]
    for i, (prompt, expected) in enumerate(logic, 1):
        add('choice', i, prompt + '\nAnswer with one letter only.', expected, expected,
            'A' if expected != 'A' else 'D', 'Choice C')

    # Exact-length, multi-constraint output with lexical and case constraints.
    for i in range(1, 21):
        required = ['item', 'source', 'verified', 'before', 'release'] if i % 2 else \
                   ['private', 'data', 'remain', 'local', 'case']
        count = 8 + (i % 4)
        uppercase = i % 3 == 0
        reference_words = required + ['carefully'] * (count - len(required))
        reference = ' '.join(reference_words)
        if uppercase:
            reference = reference.upper()
        prompt = (f'Write exactly {count} words on one line. Include every whole word: '
                  + ', '.join(f'"{word}"' for word in required) + '.')
        if uppercase:
            prompt += ' Use uppercase letters only.'
        add('instruction', i, prompt,
            {'min_words': count, 'max_words': count, 'keywords': required,
             'one_line': True, 'uppercase': uppercase}, reference,
            'UNRELATED WORDS ONLY' if uppercase else 'unrelated words only', '')

    # Records require combining independently supplied fields into exact typed JSON.
    for i in range(1, 21):
        rows = [{'id': f'X-{i:02}-{j}', 'qty': i + j * 2, 'unit': j + 3,
                 'ok': (i + j) % 2 == 0} for j in range(1, 4)]
        target = 1 + (i % 3)
        row = rows[target - 1]
        expected = {'case': f'C-{i:02}', 'selected': row['id'],
                    'extended': row['qty'] * row['unit'], 'confirmed': row['ok'],
                    'remaining': [entry['id'] for idx, entry in enumerate(rows) if idx != target - 1]}
        prompt = (f'Here are three rows: {json.dumps(rows, separators=(",", ":"))}. Select row {target}. '
                  f'For case use C-{i:02}; calculate qty times unit as extended; copy ok as confirmed; '
                  'put the other two IDs in remaining in their original order. Return JSON only with exactly '
                  'case, selected, extended, confirmed, remaining and preserve the value types.')
        add('json', i, prompt, expected, json.dumps(expected, separators=(',', ':')),
            json.dumps(dict(expected, extended=expected['extended'] + 1)), '{bad json}')

    # Schema selection with decoys, exact arguments, and safe non-execution language.
    for i in range(1, 21):
        partition = 'practice' if i <= 10 else 'heldout'
        n = i if partition == 'practice' else i - 10
        prefix = 'trial' if partition == 'practice' else 'sealed'
        target_name = f'{prefix}_stage_{n:02}'
        case_key, count_key, execute_key = (('case_id', 'count', 'execute') if partition == 'practice'
                                            else ('record_ref', 'keep_count', 'apply_now'))
        confirm_key = 'confirm' if partition == 'practice' else 'approve_drop'
        schemas = [
            {'name': f'{prefix}_publish_{n:02}', 'description': 'Publishes records to an external destination.',
             'arguments': {case_key: 'string', count_key: 'integer', execute_key: 'boolean'}},
            {'name': target_name, 'description': 'Stages records in a private review queue without executing.',
             'arguments': {case_key: 'string', count_key: 'integer', execute_key: 'boolean'}},
            {'name': f'{prefix}_inspect_{n:02}', 'description': 'Reads metadata for the case only.',
             'arguments': {case_key: 'string'}},
            {'name': f'{prefix}_discard_{n:02}', 'description': 'Discards the named case after confirmation.',
             'arguments': {case_key: 'string', confirm_key: 'boolean'}}]
        position = (n - 1) % 4
        target_schema = schemas.pop(1)
        schemas.insert(position, target_schema)
        arguments = {case_key: f'CASE-{n:02}', count_key: n * 13 + 7, execute_key: False}
        expected = {'name': target_name, 'arguments': arguments}
        prompt = ('Available tool schemas: ' + json.dumps({'tools': schemas}, separators=(',', ':'))
                  + f'\nRequest: Stage CASE-{n:02} privately in the review queue, retain {n * 13 + 7} '
                  'records, and do not execute anything. Return only the exact JSON tool-call object; do not '
                  'perform the action.')
        add('tool-call', i, prompt, expected, json.dumps(expected, separators=(',', ':')),
            json.dumps({'name': schemas[(position + 1) % 4]['name'], 'arguments': arguments}),
            'execute now', available_tools=schemas)
    return result


def tool_schema_items():
    """Schema-grounded tool calls with fully disjoint practice and held-out vocabularies."""
    descriptions = {
        'lookup_record': 'Find a record by ID and optionally include its history.',
        'compare_runs': 'Compare the baseline run with the candidate run.',
        'set_threshold': 'Set the minimum for a metric and enable or disable that threshold.',
        'schedule_backup': 'Schedule a labeled backup at a UTC hour and choose whether to notify.',
        'fetch_invoice': 'Retrieve an invoice by reference and optionally include its line items.',
        'diff_snapshots': 'Compare an older snapshot with a newer snapshot.',
        'set_retention': 'Set how many days to retain an artifact kind and activate or deactivate it.',
        'queue_audit': 'Queue an audit for a scope at a specified urgency and choose whether to notify the owner.',
    }
    definitions = {
        'practice': [
            ('lookup_record', {'record_id': 'string', 'include_history': 'boolean'},
             lambda n: {'record_id': f'R-{n:02}', 'include_history': n % 2 == 0},
             lambda args: f"Find record {args['record_id']} and include its history: {str(args['include_history']).lower()}."),
            ('compare_runs', {'baseline_id': 'string', 'candidate_id': 'string'},
             lambda n: {'baseline_id': f'base-{n}', 'candidate_id': f'cand-{n + 3}'},
             lambda args: f"Compare baseline {args['baseline_id']} with candidate {args['candidate_id']}."),
            ('set_threshold', {'metric': 'string', 'minimum': 'integer', 'enabled': 'boolean'},
             lambda n: {'metric': f'latency_{n}', 'minimum': n * 10, 'enabled': n % 2 == 1},
             lambda args: f"Set {args['metric']} minimum to {args['minimum']} and enabled={str(args['enabled']).lower()}."),
            ('schedule_backup', {'label': 'string', 'hour_utc': 'integer', 'notify': 'boolean'},
             lambda n: {'label': f'archive-{n}', 'hour_utc': n + 1, 'notify': n % 2 == 0},
             lambda args: f"Schedule backup {args['label']} at UTC hour {args['hour_utc']}; notify={str(args['notify']).lower()}."),
        ],
        'heldout': [
            ('fetch_invoice', {'invoice_ref': 'string', 'with_lines': 'boolean'},
             lambda n: {'invoice_ref': f'INV-{n:03}', 'with_lines': n % 2 == 0},
             lambda args: f"Retrieve invoice {args['invoice_ref']} with line items={str(args['with_lines']).lower()}."),
            ('diff_snapshots', {'older_snapshot': 'string', 'newer_snapshot': 'string'},
             lambda n: {'older_snapshot': f'snap-{n}', 'newer_snapshot': f'snap-{n + 4}'},
             lambda args: f"Compare older snapshot {args['older_snapshot']} to newer snapshot {args['newer_snapshot']}."),
            ('set_retention', {'artifact_kind': 'string', 'retention_days': 'integer', 'active': 'boolean'},
             lambda n: {'artifact_kind': f'log-{n}', 'retention_days': n * 7, 'active': n % 2 == 1},
             lambda args: f"Set {args['artifact_kind']} retention to {args['retention_days']} days; active={str(args['active']).lower()}."),
            ('queue_audit', {'audit_scope': 'string', 'urgency_rank': 'integer', 'notify_owner': 'boolean'},
             lambda n: {'audit_scope': f'workspace-{n}', 'urgency_rank': n, 'notify_owner': n % 2 == 0},
             lambda args: f"Queue an audit for {args['audit_scope']} at urgency {args['urgency_rank']}; notify owner={str(args['notify_owner']).lower()}."),
        ],
    }
    result = []
    for partition, tools in definitions.items():
        for tool_index, (name, properties, values, request) in enumerate(tools):
            for variant in range(1, 6):
                arguments = values(variant)
                available = [tools[index % len(tools)] for index in
                             (tool_index, tool_index + 1, tool_index + 2)]
                target = available.pop(0)
                target_position = (tool_index * 5 + variant - 1) % 3
                available.insert(target_position, target)
                schemas = [{'name': entry[0], 'description': descriptions[entry[0]],
                            'arguments': entry[1]} for entry in available]
                prompt = ('Choose the available tool that performs the request. Available tool schemas: '
                          + json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False)
                          + '\nRequest: ' + request(arguments)
                          + '\nReturn only a JSON object with exactly two top-level keys: "name" and "arguments". '
                          'Set "name" to the selected tool\'s exact name, and set "arguments" to an object '
                          'matching that tool schema. Do not use "tool" as a key, add other keys, use Markdown '
                          'fences, or execute the tool.')
                expected = {'name': name, 'arguments': arguments}
                wrong = {'name': 'not_a_provided_tool', 'arguments': arguments}
                result.append({'id': f'{partition}-{tool_index * 5 + variant:02}', 'prompt': prompt,
                    'scorer': {'kind': 'tool-call', 'expected': expected, 'partition': partition,
                               'available_tools': schemas},
                    'reference': json.dumps(expected), 'wrong': json.dumps(wrong), 'malformed': '{not json}'})
    return result


def tool_plan_items():
    """Multi-constraint tool selection and argument planning with explicit schemas."""
    def reserve_args(n):
        people, sessions = n + 2, n % 3 + 2
        return {'resource': f'Room-{n:02}', 'date_utc': f'2026-11-{n + 2:02}',
                'start_hour_utc': n + 6, 'duration_hours': n % 3 + 1,
                'units': people * sessions, 'notify_owner': n % 2 == 0}

    def reserve_prompt(a, n):
        people, sessions = n + 2, n % 3 + 2
        return (f"Hold {people} attendee seats in each of {sessions} identical sessions. The API's units "
                f"field is the total seats across every session, not the seats in one session. Reserve "
                f"{a['resource']} on {a['date_utc']} at {a['start_hour_utc']:02}:00 UTC; each session "
                f"lasts {a['duration_hours']} hours. Notify the owner only for an even-numbered request "
                f"(request {n}); there are no external guests.")

    def filter_args(n):
        groups, per_group = n % 4 + 2, n % 3 + 2
        return {'owner_key': f'owner-{n:02}', 'from_utc': f'2026-11-{n + 1:02}T00:00Z',
                'to_utc': f'2026-11-{n + 3:02}T23:59Z', 'status_code': ('ready', 'held', 'closed')[n % 3],
                'sort_order': 'newest_first' if n % 2 else 'oldest_first',
                'max_rows': groups * per_group, 'include_metadata': n % 2 == 1}

    def filter_prompt(a, n):
        groups, per_group = n % 4 + 2, n % 3 + 2
        return (f"For {a['owner_key']}, find records from {a['from_utc']} through {a['to_utc']} whose "
                f"status is {a['status_code']}. Order them {a['sort_order'].replace('_', ' ')}. There are "
                f"{groups} teams and the request allows {per_group} records per team; the API expects "
                f"one global row cap, so multiply those counts. Include metadata only when the request "
                f"number ({n}) is odd.")

    def diff_args(n):
        return {'earlier_build': f'build-{n + 20}', 'later_build': f'build-{n + 4}',
                'include_prerelease': n % 2 == 0, 'compare_dependencies': n % 3 != 0}

    def diff_prompt(a, n):
        earlier_date, later_date = f'2026-11-{n + 4:02}', f'2026-11-{n + 20:02}'
        return (f"The release ledger lists {a['later_build']} on {later_date} and {a['earlier_build']} "
                f"on {earlier_date}. Compare the earlier release to the later release, regardless of "
                f"the order in which they were listed. Include prereleases only for even request {n}. "
                f"Compare dependencies unless request {n} is divisible by three.")

    def review_args(n):
        day, offset = n + 10, n % 4 + 1
        urgency = ('low', 'normal', 'high', 'urgent')[n % 4]
        priority = {'low': 1, 'normal': 2, 'high': 3, 'urgent': 4}[urgency]
        return {'change_key': f'change-{n:02}', 'reviewer_role': ('owner', 'security', 'release')[n % 3],
                'due_day': day + offset, 'priority_level': priority,
                'require_backup': n % 2 == 0, 'notify_reviewer': n % 3 != 0}

    def review_prompt(a, n):
        day, offset = n + 10, n % 4 + 1
        urgency = ('low', 'normal', 'high', 'urgent')[n % 4]
        return (f"Route {a['change_key']} to the {a['reviewer_role']} reviewer. Today is cycle day {day}; "
                f"the deadline is {offset} calendar days from today, and the API needs the absolute cycle "
                f"day. Convert urgency {urgency} to its numeric level using low=1, normal=2, high=3, "
                f"urgent=4. Require a backup for even requests; notify the reviewer unless the request "
                f"number ({n}) is divisible by three.")

    def book_args(n):
        people, sessions = n % 5 + 3, n % 3 + 2
        return {'asset_code': f'Asset-{n:02}', 'day_utc': f'2026-12-{n + 2:02}',
                'hour_utc': n + 7, 'span_hours': n % 3 + 1,
                'quantity': people * sessions, 'send_alert': n % 2 == 0}

    def book_prompt(a, n):
        people, sessions = n % 5 + 3, n % 3 + 2
        return (f"Reserve {people} seats for each of {sessions} repeated sessions. The booking quantity "
                f"is the total seats across the sessions. Use asset {a['asset_code']} on {a['day_utc']} "
                f"at {a['hour_utc']:02}:00 UTC, for {a['span_hours']} hours per session. Send an alert "
                f"only for even request {n}.")

    def scan_args(n):
        groups, per_group = n % 3 + 2, n % 4 + 2
        return {'account_code': f'acct-{n:02}', 'after_utc': f'2026-12-{n + 1:02}T00:00Z',
                'before_utc': f'2026-12-{n + 3:02}T23:59Z', 'state_label': ('queued', 'active', 'done')[n % 3],
                'order_by': 'recent_first' if n % 2 else 'oldest_first',
                'row_cap': groups * per_group, 'expand_context': n % 2 == 1}

    def scan_prompt(a, n):
        groups, per_group = n % 3 + 2, n % 4 + 2
        return (f"For {a['account_code']}, locate sessions from {a['after_utc']} through {a['before_utc']} "
                f"in state {a['state_label']}. Sort {a['order_by'].replace('_', ' ')}. The report needs "
                f"{per_group} rows from each of {groups} groups; the service takes one total row cap, so "
                f"multiply them. Expand context only for odd request {n}.")

    def package_args(n):
        return {'prior_pkg': f'pkg-{n + 4}', 'current_pkg': f'pkg-{n + 20}',
                'allow_preview': n % 2 == 1, 'compare_lockfile': n % 3 != 1}

    def package_prompt(a, n):
        older_date, newer_date = f'2026-12-{n + 4:02}', f'2026-12-{n + 20:02}'
        return (f"The package ledger lists {a['current_pkg']} on {newer_date} and {a['prior_pkg']} on "
                f"{older_date}. Compare the older package to the newer one, not the listed order. Allow "
                f"preview builds only for odd request {n}. Compare lockfiles unless {n} is one more than a "
                f"multiple of three.")

    def audit_args(n):
        day, offset = n + 20, n % 4 + 1
        urgency = ('routine', 'standard', 'elevated', 'critical')[n % 4]
        priority = {'routine': 1, 'standard': 2, 'elevated': 3, 'critical': 4}[urgency]
        return {'ticket_ref': f'ticket-{n:02}', 'assignee_group': ('owner', 'risk', 'ops')[n % 3],
                'deadline_day': day + offset, 'urgency_rank': priority,
                'backup_gate': n % 2 == 1, 'alert_assignee': n % 3 != 1}

    def audit_prompt(a, n):
        day, offset = n + 20, n % 4 + 1
        urgency = ('routine', 'standard', 'elevated', 'critical')[n % 4]
        return (f"Assign {a['ticket_ref']} to the {a['assignee_group']} group. Today is cycle day {day}; "
                f"the deadline is {offset} days later, and the API needs the absolute day. The ticket urgency "
                f"is {urgency}. Convert urgency "
                f"routine=1, standard=2, elevated=3, critical=4 to its numeric rank. Set the backup gate "
                f"for odd request {n}. Alert the assignee except when the request number is one more than "
                f"a multiple of three.")

    definitions = {
        'practice': [
            ('reserve_slot', 'Reserve a resource and time block; units counts all seats across repeated sessions.',
             {'resource': 'string', 'date_utc': 'string', 'start_hour_utc': 'integer', 'duration_hours': 'integer', 'units': 'integer', 'notify_owner': 'boolean'}, reserve_args, reserve_prompt),
            ('filter_events', 'Filter records by owner, time range and status; sort_order must be newest_first or oldest_first; max_rows is one global cap.',
             {'owner_key': 'string', 'from_utc': 'string', 'to_utc': 'string', 'status_code': 'string', 'sort_order': 'string', 'max_rows': 'integer', 'include_metadata': 'boolean'}, filter_args, filter_prompt),
            ('diff_releases', 'Compare two software releases and optionally include prerelease and dependency changes.',
             {'earlier_build': 'string', 'later_build': 'string', 'include_prerelease': 'boolean', 'compare_dependencies': 'boolean'}, diff_args, diff_prompt),
            ('route_review', 'Route a change to a reviewer with a cycle-day deadline, priority, backup gate and notification; reviewer_role must be owner, security or release.',
             {'change_key': 'string', 'reviewer_role': 'string', 'due_day': 'integer', 'priority_level': 'integer', 'require_backup': 'boolean', 'notify_reviewer': 'boolean'}, review_args, review_prompt),
        ],
        'heldout': [
            ('book_resource', 'Book an asset and time block; quantity counts all seats across repeated sessions.',
             {'asset_code': 'string', 'day_utc': 'string', 'hour_utc': 'integer', 'span_hours': 'integer', 'quantity': 'integer', 'send_alert': 'boolean'}, book_args, book_prompt),
            ('scan_sessions', 'Find sessions by account, time range and state; order_by must be recent_first or oldest_first; row_cap is one total cap.',
             {'account_code': 'string', 'after_utc': 'string', 'before_utc': 'string', 'state_label': 'string', 'order_by': 'string', 'row_cap': 'integer', 'expand_context': 'boolean'}, scan_args, scan_prompt),
            ('compare_packages', 'Compare two packages and optionally include preview builds and lockfile changes.',
             {'prior_pkg': 'string', 'current_pkg': 'string', 'allow_preview': 'boolean', 'compare_lockfile': 'boolean'}, package_args, package_prompt),
            ('assign_audit', 'Assign an audit ticket with a cycle-day deadline, urgency rank, backup gate and alert.',
             {'ticket_ref': 'string', 'assignee_group': 'string', 'deadline_day': 'integer', 'urgency_rank': 'integer', 'backup_gate': 'boolean', 'alert_assignee': 'boolean'}, audit_args, audit_prompt),
        ],
    }
    result = []
    for partition, tools in definitions.items():
        for tool_index, (name, description, properties, argument_builder, prompt_builder) in enumerate(tools):
            for variant in range(1, 6):
                arguments = argument_builder(variant)
                available = [tools[index % len(tools)] for index in
                             (tool_index, tool_index + 1, tool_index + 2, tool_index + 3)]
                target = available.pop(0)
                target_position = (tool_index * 5 + variant - 1) % 4
                available.insert(target_position, target)
                schemas = [{'name': entry[0], 'description': entry[1], 'arguments': entry[2]}
                           for entry in available]
                prompt = ('Choose the available action that satisfies the complete request. Available tool schemas: '
                          + json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False)
                          + '\nRequest: ' + prompt_builder(arguments, variant)
                          + '\nReturn only the exact JSON tool-call object with top-level keys "name" and "arguments". '
                          'Treat every listed argument as required; use its listed primitive type and no extra fields. '
                          'Do not execute the action.')
                expected = {'name': name, 'arguments': arguments}
                wrong = {'name': 'not_a_provided_tool', 'arguments': arguments}
                result.append({'id': f'{partition}-{tool_index * 5 + variant:02}', 'prompt': prompt,
                    'scorer': {'kind': 'tool-call', 'expected': expected, 'partition': partition,
                               'available_tools': schemas},
                    'reference': json.dumps(expected), 'wrong': json.dumps(wrong), 'malformed': '{not json}'})
    return result


def tool_sequence_items():
    """Two- and three-step tool plans with explicit result-reference semantics."""
    def tool(name, description, arguments, build_arguments):
        return {'name': name, 'description': description, 'arguments': arguments,
                'build_arguments': build_arguments}

    workflows = {
        'practice': [
            {
                'steps': [
                    tool('find_backup', 'Find a backup by label; returns backup_id.',
                         {'label': 'string'}, lambda n: {'label': f'weekly-{n:02}'}),
                    tool('verify_backup', 'Verify a backup by ID and optionally check its SHA-256.',
                         {'backup_id': 'string', 'verify_sha256': 'boolean'},
                         lambda n: {'backup_id': '$step1.backup_id', 'verify_sha256': True}),
                ],
                'request': lambda n: (f"Verify backup weekly-{n:02} and require a SHA-256 check. "
                                      'Find it first, then pass the returned backup_id to verification.'),
            },
            {
                'steps': [
                    tool('search_release', 'Find a release by product and version; returns release_id.',
                         {'product_name': 'string', 'release_version': 'string'},
                         lambda n: {'product_name': 'Atlas', 'release_version': f'4.{n}'}),
                    tool('inspect_release', 'Read a release manifest by release ID; returns manifest_id.',
                         {'release_id': 'string'},
                         lambda n: {'release_id': '$step1.release_id'}),
                    tool('check_manifest', 'Check a manifest and optionally include its lockfile.',
                         {'manifest_id': 'string', 'include_lockfile': 'boolean'},
                         lambda n: {'manifest_id': '$step2.manifest_id', 'include_lockfile': n % 2 == 1}),
                ],
                'request': lambda n: (f"Check the lockfile for Atlas release 4.{n}. Find the release, "
                                      'inspect its manifest, then check the returned manifest. Include the '
                                      f"lockfile only for odd request numbers (request {n})."),
            },
            {
                'steps': [
                    tool('search_session', 'Find a session by user and state; returns session_id.',
                         {'user_key': 'string', 'state_label': 'string'},
                         lambda n: {'user_key': f'user-{n:02}', 'state_label': 'active'}),
                    tool('read_session', 'Read session events by session ID and optionally include tool events.',
                         {'session_id': 'string', 'include_tool_events': 'boolean'},
                         lambda n: {'session_id': '$step1.session_id', 'include_tool_events': n % 2 == 0}),
                ],
                'request': lambda n: (f"Read active session events for user-{n:02}. Search by the user and "
                                      'active state first, then read the returned session. Include tool events '
                                      f"only for even request numbers (request {n})."),
            },
            {
                'steps': [
                    tool('find_document', 'Find a document by exact title; returns document_id.',
                         {'document_title': 'string'},
                         lambda n: {'document_title': f'change-{n:02}'}),
                    tool('extract_record', 'Extract named fields from a document; returns record_ref.',
                         {'document_id': 'string', 'fields_csv': 'string'},
                         lambda n: {'document_id': '$step1.document_id', 'fields_csv': 'commit,reviewer'}),
                    tool('validate_record', 'Validate an extracted record against a schema version.',
                         {'record_ref': 'string', 'schema_version': 'string'},
                         lambda n: {'record_ref': '$step2.record_ref', 'schema_version': 'change-v2'}),
                ],
                'request': lambda n: (f"For document change-{n:02}, extract commit and reviewer, then validate "
                                      'the extracted record with schema change-v2. Locate the document before '
                                      'extracting, and use the returned record reference for validation.'),
            },
        ],
        'heldout': [
            {
                'steps': [
                    tool('locate_receipt', 'Locate a receipt by reference code; returns receipt_key.',
                         {'reference_code': 'string'},
                         lambda n: {'reference_code': f'RCPT-{n:03}'}),
                    tool('verify_receipt', 'Verify a receipt by key and optionally check its signature.',
                         {'receipt_key': 'string', 'check_signature': 'boolean'},
                         lambda n: {'receipt_key': '$step1.receipt_key', 'check_signature': True}),
                ],
                'request': lambda n: (f"Verify receipt RCPT-{n:03} and check its signature. Locate it first, "
                                      'then use the returned receipt key.'),
            },
            {
                'steps': [
                    tool('lookup_asset', 'Find an asset by tag; returns asset_ref.',
                         {'asset_tag': 'string'}, lambda n: {'asset_tag': f'ASSET-{n:03}'}),
                    tool('inspect_revision', 'Inspect one asset revision; returns snapshot_ref.',
                         {'asset_ref': 'string', 'revision_label': 'string'},
                         lambda n: {'asset_ref': '$step1.asset_ref', 'revision_label': 'current'}),
                    tool('compare_snapshots', 'Compare an asset with a snapshot and optionally include metadata.',
                         {'asset_ref': 'string', 'snapshot_ref': 'string', 'include_metadata': 'boolean'},
                         lambda n: {'asset_ref': '$step1.asset_ref', 'snapshot_ref': '$step2.snapshot_ref',
                                    'include_metadata': n % 2 == 1}),
                ],
                'request': lambda n: (f"Compare current revision of asset ASSET-{n:03} to its inspected snapshot. "
                                      'Look up the asset, inspect its current revision, then compare using the '
                                      f"returned references. Include metadata only for odd request numbers (request {n})."),
            },
            {
                'steps': [
                    tool('search_case', 'Find a case by queue and state; returns case_ref.',
                         {'queue_code': 'string', 'state_code': 'string'},
                         lambda n: {'queue_code': f'Q-{n:03}', 'state_code': 'open'}),
                    tool('read_case_history', 'Read a case history by reference and optionally include notes.',
                         {'case_ref': 'string', 'include_notes': 'boolean'},
                         lambda n: {'case_ref': '$step1.case_ref', 'include_notes': n % 2 == 0}),
                ],
                'request': lambda n: (f"Read the open case history for queue Q-{n:03}. Search by queue and open "
                                      'state first, then read the returned case. Include notes only for even '
                                      f"request numbers (request {n})."),
            },
            {
                'steps': [
                    tool('find_package', 'Find a package by name and channel; returns package_ref.',
                         {'package_name': 'string', 'release_channel': 'string'},
                         lambda n: {'package_name': f'package-{n:03}', 'release_channel': 'stable'}),
                    tool('read_manifest', 'Read a package manifest by reference; returns manifest_ref.',
                         {'package_ref': 'string'}, lambda n: {'package_ref': '$step1.package_ref'}),
                    tool('check_dependencies', 'Check dependencies declared by a manifest.',
                         {'manifest_ref': 'string', 'include_development': 'boolean'},
                         lambda n: {'manifest_ref': '$step2.manifest_ref', 'include_development': n % 2 == 0}),
                ],
                'request': lambda n: (f"Check development dependencies for stable package-{n:03}. Find the "
                                      'package, read its manifest, then check that manifest. Include development '
                                      f"dependencies only for even request numbers (request {n})."),
            },
        ],
    }

    result = []
    for partition, group in workflows.items():
        catalog = [entry for workflow in group for entry in workflow['steps']]
        first_id = 1 if partition == 'practice' else 21
        for variant in range(1, 6):
            for workflow_index, workflow in enumerate(group):
                targets = workflow['steps']
                target_names = {entry['name'] for entry in targets}
                decoys = [entry for entry in catalog if entry['name'] not in target_names]
                available = targets + decoys[:4 - len(targets)]
                first = available.pop(0)
                available.insert((workflow_index * 5 + variant - 1) % 4, first)
                schemas = [{'name': entry['name'], 'description': entry['description'],
                            'arguments': entry['arguments']} for entry in available]
                expected = {'steps': [
                    {'name': entry['name'], 'arguments': entry['build_arguments'](variant)}
                    for entry in targets]}
                request = workflow['request'](variant)
                bindings = []
                for step_index, call in enumerate(expected['steps'], 1):
                    for argument, value in call['arguments'].items():
                        if isinstance(value, str) and value.startswith('$step'):
                            bindings.append(f'step {step_index} argument {argument} = "{value}"')
                prompt = ('Plan the required calls; do not execute any tool. Available tool schemas: '
                          + json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False)
                          + '\nRequest: ' + request
                          + '\nReference bindings: ' + '; '.join(bindings)
                          + '\nFor any dependent identifier, use the exact reference string stated above '
                          'rather than guessing a returned value. Each call must have exactly "name" and "arguments". '
                          'Return only a JSON object with exactly one top-level key "steps", containing the '
                          'minimal calls in required order. Use only listed tools, include every required argument, '
                          'and add no extra fields or commentary.')
                wrong = {'steps': [dict(expected['steps'][0], name='wrong_tool'), *expected['steps'][1:]]}
                ordinal = first_id + (variant - 1) * len(group) + workflow_index
                result.append({'id': f'{partition}-{ordinal:02}', 'prompt': prompt,
                    'scorer': {'kind': 'tool-sequence', 'expected': expected, 'partition': partition,
                               'available_tools': schemas},
                    'reference': json.dumps(expected), 'wrong': json.dumps(wrong),
                    'malformed': '{not json}'})
    return result


def mission_ops_items():
    """Build 60 original deep operations probes: five families, six practice and six held-out each.

    Difficulty comes from dependency depth, conflicting records and tracked state. Every prompt
    states its data, its rules and the exact output shape, so each answer is unique and checkable.
    """
    import hashlib

    class Draw:
        """Small deterministic generator, stable across Python versions."""
        def __init__(self, label):
            self.label, self.counter = label, 0

        def below(self, n):
            self.counter += 1
            digest = hashlib.sha256(f'{self.label}:{self.counter}'.encode()).digest()
            return int.from_bytes(digest[:8], 'big') % n

        def between(self, low, high):
            return low + self.below(high - low + 1)

        def pick(self, values):
            return values[self.below(len(values))]

        def shuffle(self, values):
            values = list(values)
            for i in range(len(values) - 1, 0, -1):
                j = self.below(i + 1)
                values[i], values[j] = values[j], values[i]
            return values

    result = []

    def add(prefix, index, kind, prompt, expected, reference, wrong, malformed, **fields):
        partition = 'practice' if index <= 6 else 'heldout'
        scorer = {'kind': kind, 'partition': partition, 'expected': expected, **fields}
        result.append({'id': f'{prefix}-{index:02}', 'prompt': prompt, 'scorer': scorer,
                       'reference': reference, 'wrong': wrong, 'malformed': malformed})

    def compact(value):
        return json.dumps(value, separators=(',', ':'), ensure_ascii=False)

    def clock(minutes):
        return f'{minutes // 60:02}:{minutes % 60:02}'

    def sides():
        for index in range(1, 13):
            yield index, ('practice' if index <= 6 else 'heldout')

    # 1. Telemetry ledger: seven dependent entries with a cancelled entry, a retroactive
    # correction, a percentage, a fraction and a resupply in a larger unit.
    ledger_sides = {
        'practice': {'site': 'Kestrel station', 'resource': 'propellant', 'unit': 'kg',
                     'big': 't', 'use': 'Burn', 'out': 'Transfer to the tug'},
        'heldout': {'site': 'Tycho base', 'resource': 'potable water', 'unit': 'L',
                    'big': 'kL', 'use': 'Draw', 'out': 'Transfer to the rover tank'},
    }
    fractions = {3: 'one third', 4: 'one quarter', 5: 'one fifth'}
    for index, partition in sides():
        side = ledger_sides[partition]
        unit = side['unit']
        draw = Draw(f'mission-ops/ledger/{index}')
        while True:
            start = draw.between(1500, 3200)
            reserve = draw.between(30, 80) * 10
            kinds = draw.shuffle(['use', 'use', 'cancel', 'pct', 'frac', 'resupply'])
            entries = []
            for kind in kinds:
                if kind == 'use':
                    entries.append({'kind': 'use', 'amount': draw.between(80, 320)})
                elif kind == 'cancel':
                    entries.append({'kind': 'cancel', 'amount': draw.between(150, 400)})
                elif kind == 'pct':
                    entries.append({'kind': 'pct', 'percent': draw.between(6, 19)})
                elif kind == 'frac':
                    entries.append({'kind': 'frac', 'denominator': draw.pick([3, 4, 5])})
                else:
                    entries.append({'kind': 'resupply', 'hundredths': draw.between(25, 95)})
            uses = [i for i, entry in enumerate(entries) if entry['kind'] == 'use']
            target = draw.pick(uses)
            position = draw.between(target + 1, len(entries))
            corrected = entries[target]['amount'] + draw.pick([-1, 1]) * draw.between(12, 60)
            # The correction comes after the entry it corrects, so that index is unchanged.
            entries.insert(position, {'kind': 'correct', 'target': target, 'amount': corrected})
            amounts = {target: corrected}
            level, ok = start, True
            plain_level = start
            for i, entry in enumerate(entries):
                for track in ('true', 'plain'):
                    current = level if track == 'true' else plain_level
                    if entry['kind'] == 'use':
                        used = amounts.get(i, entry['amount']) if track == 'true' else entry['amount']
                        current -= used
                    elif entry['kind'] == 'pct':
                        current -= current * entry['percent'] // 100
                    elif entry['kind'] == 'frac':
                        current -= current // entry['denominator']
                    elif entry['kind'] == 'resupply':
                        current += entry['hundredths'] * 10
                    if track == 'true':
                        level = current
                    else:
                        plain_level = current
                if level <= 0:
                    ok = False
            answer = level - reserve
            # The correction must change the result, and the answer must stay positive.
            if ok and answer > 0 and plain_level != level:
                break
        lines = []
        for i, entry in enumerate(entries, 1):
            if entry['kind'] == 'use':
                text = f'{side["use"]} uses {entry["amount"]} {unit}.'
            elif entry['kind'] == 'cancel':
                text = f'CANCELLED. It planned to use {entry["amount"]} {unit}; ignore it.'
            elif entry['kind'] == 'pct':
                text = (f'{side["use"]} uses {entry["percent"]}% of the amount on hand, '
                        f'rounded down to a whole {unit}.')
            elif entry['kind'] == 'frac':
                text = (f'{side["out"]} sends out {fractions[entry["denominator"]]} of the amount on hand, '
                        f'rounded down to a whole {unit}.')
            elif entry['kind'] == 'resupply':
                text = (f'Resupply adds {entry["hundredths"] / 100:.2f} {side["big"]} '
                        f'(1 {side["big"]} = 1000 {unit}).')
            else:
                original = entries[entry['target']]['amount']
                text = (f'Correction: E{entry["target"] + 1} actually used {entry["amount"]} {unit}, '
                        f'not {original} {unit}. Apply E{entry["target"] + 1} as {entry["amount"]} {unit} '
                        'and recompute every later entry.')
            lines.append(f'E{i}: {text}')
        prompt = (f'{side["site"]} {side["resource"]} log. Start: {start} {unit}. Entries in order:\n'
                  + '\n'.join(lines)
                  + f'\nA reserve of {reserve} {unit} must stay untouched. After all entries, how many {unit} '
                  'are available above the reserve? Answer with the integer only, no units.')
        add('ledger', index, 'numeric', prompt, str(answer), str(answer), str(answer + 1),
            f'The answer is {answer} {unit}')

    # 2. Go/no-go under an explicit authority rule, with conditional waivers.
    gonogo_sides = {
        'practice': {'event': 'Launch go/no-go for pass', 'quantity': 'wind', 'unit': 'kt',
                     'sources': ['Flight Rules register', 'console log', 'briefing slide'],
                     'signer': 'range safety', 'low': 18, 'high': 34},
        'heldout': {'event': 'Surface EVA go/no-go for window', 'quantity': 'dust count', 'unit': 'ppm',
                    'sources': ['Base Safety manual', 'ops chat', 'shift handover note'],
                    'signer': 'medical officer', 'low': 40, 'high': 90},
    }
    letters = 'ABCD'
    for index, partition in sides():
        side = gonogo_sides[partition]
        unit, quantity, signer = side['unit'], side['quantity'], side['signer']
        draw = Draw(f'mission-ops/gonogo/{index}')
        want_letter = letters[(index - 1) % 4] if partition == 'practice' else letters[(index + 3) % 4]
        while True:
            order = draw.shuffle(side['sources'])
            rank = {source: position for position, source in enumerate(order)}
            times = draw.shuffle(list(range(7 * 60, 10 * 60, 5)))
            records = []

            def record(source, fact, value):
                records.append({'source': source, 'time': times[len(records)], 'fact': fact, 'value': value})

            limit = draw.between(side['low'], side['high'])
            # The limit: an older and a newer record in a higher source, a different value lower down.
            limit_high = draw.pick(order[:2])
            limit_low = draw.pick([source for source in order if rank[source] > rank[limit_high]])
            old_limit = limit + draw.pick([-1, 1]) * draw.between(2, 6)
            low_limit = limit + draw.between(3, 8)
            record(limit_high, 'limit', old_limit)
            record(limit_high, 'limit', limit)
            record(limit_low, 'limit', low_limit)
            # Order the two high-source limit records so the true one is later.
            a, b = records[0], records[1]
            if a['time'] > b['time']:
                a['time'], b['time'] = b['time'], a['time']
            waiver = draw.between(2, 6)
            waiver_source = draw.pick(order)
            record(waiver_source, 'waiver', waiver)
            signature_sources = draw.shuffle(order)[:2]
            signed = draw.pick([True, False])
            top_signature = min(signature_sources, key=rank.get)
            other_signature = max(signature_sources, key=rank.get)
            record(top_signature, 'signature', signed)
            record(other_signature, 'signature', not signed)
            effective = limit + waiver if signed else limit
            measured = effective + draw.pick([-3, -2, -1, 0, 1, 2, 3])
            measured_source = draw.pick(order[:2])
            measured_low = draw.pick([source for source in order if rank[source] > rank[measured_source]])
            stale = measured + draw.pick([-1, 1]) * draw.between(3, 7)
            record(measured_source, 'measured', stale)
            record(measured_source, 'measured', measured)
            record(measured_low, 'measured', measured + draw.pick([-1, 1]) * draw.between(4, 9))
            m_old, m_new = records[-3], records[-2]
            if m_old['time'] > m_new['time']:
                m_old['time'], m_new['time'] = m_new['time'], m_old['time']
            correct = (measured, effective)
            alternates = [(measured, (low_limit + waiver) if signed else low_limit),
                          (measured, (old_limit + waiver) if signed else old_limit),
                          (stale, effective),
                          (measured, limit if signed else limit + waiver),
                          (records[-1]['value'], effective)]
            distractors = []
            for option in alternates:
                if option != correct and option not in distractors and option[1] > 0 and option[0] > 0:
                    distractors.append(option)
            if len(distractors) < 3:
                continue
            distractors = draw.shuffle(distractors)[:3]
            # Both decisions must appear among the options.
            decisions = {option[0] <= option[1] for option in [correct] + distractors}
            if len(decisions) == 2 and min(min(o) for o in [correct] + distractors) > 0:
                break
        options = distractors[:]
        options.insert(letters.index(want_letter), correct)
        shown = draw.shuffle(records)
        lines = [f'({i}) {r["source"][0].upper() + r["source"][1:]} {clock(r["time"])}: ' + (
            f'{quantity} limit {r["value"]} {unit}.' if r['fact'] == 'limit' else
            f'measured {quantity} {r["value"]} {unit}.' if r['fact'] == 'measured' else
            f'a waiver raises the {quantity} limit by {r["value"]} {unit} only if the {signer} signature is received.'
            if r['fact'] == 'waiver' else
            f'{signer} signature {"received" if r["value"] else "not received"}.')
            for i, r in enumerate(shown, 1)]
        option_text = ' '.join(
            f'{letter}: {"GO" if m <= e else "NO-GO"}, measured {m} {unit}, effective limit {e} {unit}.'
            for letter, (m, e) in zip(letters, options))
        prompt = (f'{side["event"]} {index}. Authority order, highest first: ' + ' > '.join(order) + '. '
                  'For each fact (the limit, the measured value, the waiver, and the signature), use only the '
                  'highest-authority source that reports that fact; within that source, the latest time wins. '
                  'The effective limit is the limit plus the waiver amount when the waiver exists and the '
                  'signature is received; otherwise it is the limit. GO only if the measured value is at or '
                  'below the effective limit.\nRecords:\n' + '\n'.join(lines) + '\nOptions: ' + option_text
                  + '\nAnswer with one letter only.')
        add('gonogo', index, 'choice', prompt, want_letter, want_letter,
            letters[(letters.index(want_letter) + 1) % 4], f'Option {want_letter}')

    # 3. State replay: out-of-order events, authorization, set and toggle.
    replay_sides = {
        'practice': {'site': 'Kestrel life-support controller',
                     'systems': {'pump_a': 'power', 'pump_b': 'power', 'valve_3': 'flow',
                                 'heater_2': 'power', 'fan_1': 'power', 'valve_8': 'flow'},
                     'rejected': 'rejected', 'applied': 'applied'},
        'heldout': {'site': 'Tycho habitat controller',
                    'systems': {'drill_motor': 'power', 'airlock_inner': 'flow', 'airlock_outer': 'flow',
                                'rover_charger': 'power', 'scrubber_2': 'power', 'hatch_vent': 'flow'},
                    'rejected': 'refused', 'applied': 'executed'},
    }
    states = {'power': ('on', 'off'), 'flow': ('open', 'closed')}
    for index, partition in sides():
        side = replay_sides[partition]
        systems = side['systems']
        draw = Draw(f'mission-ops/replay/{index}')
        while True:
            initial = {name: draw.pick(states[kind]) for name, kind in systems.items()}
            times = sorted(draw.shuffle(list(range(9 * 60, 11 * 60, 3)))[:12])
            denied = set(draw.shuffle(range(12))[:draw.between(3, 4)])
            events = []
            for position, minute in enumerate(times):
                target = draw.pick(list(systems))
                if draw.below(5) < 2:
                    event = {'t': clock(minute), 'target': target, 'action': 'toggle'}
                else:
                    event = {'t': clock(minute), 'target': target, 'action': 'set',
                             'value': draw.pick(states[systems[target]])}
                event['auth'] = position not in denied
                events.append(event)
            listed = draw.shuffle(events)
            for number, event in enumerate(listed, 1):
                event['id'] = f'E{number:02}'

            def replay(sequence, check_auth=True):
                state = dict(initial)
                rejected, applied = [], 0
                for event in sequence:
                    if check_auth and not event['auth']:
                        rejected.append(event['id'])
                        continue
                    if event['action'] == 'set':
                        state[event['target']] = event['value']
                    else:
                        on, off = states[systems[event['target']]]
                        state[event['target']] = off if state[event['target']] == on else on
                    applied += 1
                return state, rejected, applied

            ordered = sorted(listed, key=lambda event: event['t'])
            final, rejected, applied = replay(ordered)
            ignoring_auth, _, _ = replay(ordered, check_auth=False)
            listed_order, _, _ = replay(listed)
            id_order = [event['id'] for event in sorted(ordered, key=lambda event: event['id'])
                        if not event['auth']]
            if final != ignoring_auth and final != listed_order and id_order != rejected:
                break
        expected = dict(final, **{side['rejected']: rejected, side['applied']: applied})
        shown_events = [{key: event[key] for key in ('id', 't', 'target', 'action', 'value', 'auth') if key in event}
                        for event in listed]
        key_text = ', '.join(f'"{name}" ("{states[kind][0]}" or "{states[kind][1]}")'
                             for name, kind in systems.items())
        prompt = (f'{side["site"]}. Initial state: {compact(initial)}\nEvents (listed in no particular order): '
                  f'{compact(shown_events)}\nApply the events in time order. An event whose auth is false is '
                  'rejected and changes nothing. "set" sets the target to value; "toggle" flips on/off or '
                  f'open/closed. Return JSON only, with exactly these keys: {key_text}, "{side["rejected"]}" '
                  f'(the rejected event IDs in time order) and "{side["applied"]}" (the integer count of applied '
                  'events). No other keys or text.')
        wrong = dict(expected, **{side['applied']: applied + 1})
        add('replay', index, 'json', prompt, expected, compact(expected), compact(wrong), '{bad json}')

    # 4. Table query: three filters, a grouped sum and a stated tie-break.
    manifest_sides = {
        'practice': {'title': 'Kestrel stowage manifest', 'group': 'module', 'item': 'item', 'qty': 'qty',
                     'status': 'status', 'day': 'expires', 'groups': ['Node-1', 'Node-2', 'Lab', 'Hab'],
                     'items': ['filters', 'LiOH canisters', 'ration packs', 'water bags'],
                     'out': ('module', 'total', 'rows')},
        'heldout': {'title': 'Tycho depot ledger', 'group': 'zone', 'item': 'supply', 'qty': 'units',
                    'status': 'state', 'day': 'use_by', 'groups': ['Shelter-A', 'Shelter-B', 'Garage', 'Greenhouse'],
                    'items': ['seed trays', 'suit batteries', 'drill bits', 'nutrient packs'],
                    'out': ('zone', 'sum', 'count')},
    }
    for index, partition in sides():
        side = manifest_sides[partition]
        draw = Draw(f'mission-ops/manifest/{index}')
        tie = index in (3, 10)
        while True:
            excluded = draw.pick(side['items'])
            cutoff = draw.between(110, 160)
            rows = []
            for number in range(1, 15):
                rows.append({'id': f'R{number:02}', side['group']: draw.pick(side['groups']),
                             side['item']: draw.pick(side['items']), side['qty']: draw.between(3, 40),
                             side['status']: draw.pick(['verified', 'verified', 'pending', 'rejected']),
                             side['day']: draw.between(cutoff - 40, cutoff + 60)})

            def counted(row):
                return (row[side['status']] == 'verified' and row[side['day']] >= cutoff
                        and row[side['item']] != excluded)

            def qualifying_sums():
                sums = {}
                for row in rows:
                    if counted(row):
                        sums[row[side['group']]] = sums.get(row[side['group']], 0) + row[side['qty']]
                return sums

            def best(use_status=True, use_day=True, use_item=True):
                totals, counts = {}, {}
                for row in rows:
                    if use_status and row[side['status']] != 'verified':
                        continue
                    if use_day and row[side['day']] < cutoff:
                        continue
                    if use_item and row[side['item']] == excluded:
                        continue
                    group = row[side['group']]
                    totals[group] = totals.get(group, 0) + row[side['qty']]
                    counts[group] = counts.get(group, 0) + 1
                if not totals:
                    return None
                top = max(totals.values())
                winner = sorted(group for group, total in totals.items() if total == top)[0]
                return winner, top, counts[winner], sorted(totals.values(), reverse=True)

            answer = best()
            if answer is None:
                continue
            winner, top, count, ranking = answer
            if len(ranking) < 2 or ranking[0] == ranking[1]:
                continue
            gap = ranking[0] - ranking[1]
            if tie:
                # Lift one counted row of the runner-up so only the alphabetical rule decides.
                if gap > 6:
                    continue
                sums = qualifying_sums()
                second = next(group for group, total in sums.items() if total == ranking[1])
                bump = next((row for row in rows if row[side['group']] == second and counted(row)), None)
                if bump is None:
                    continue
                bump[side['qty']] += gap
                expected_winner = min(winner, second)
                winner, top, count, ranking = best()
                if ranking[0] != ranking[1] or (len(ranking) > 2 and ranking[2] == ranking[0])                         or winner != expected_winner:
                    continue
            elif gap > 8:
                continue
            others = [best(use_status=False), best(use_day=False), best(use_item=False)]
            if all(other is not None and other[:2] != (winner, top) for other in others):
                break
        out_group, out_total, out_rows = side['out']
        expected = {out_group: winner, out_total: top, out_rows: count}
        prompt = (f'{side["title"]}: {compact(rows)}\nUse only rows whose {side["status"]} is "verified", whose '
                  f'{side["day"]} is day {cutoff} or later, and whose {side["item"]} is not "{excluded}". For each '
                  f'{side["group"]}, add up {side["qty"]} over those rows. Report the {side["group"]} with the largest '
                  f'sum; if sums tie, choose the {side["group"]} name that comes first alphabetically. Return JSON '
                  f'only, with exactly these keys: "{out_group}" (the name), "{out_total}" (that integer sum) and '
                  f'"{out_rows}" (the integer number of rows counted for it). No other keys or text.')
        wrong = dict(expected, **{out_total: top + 1})
        add('manifest', index, 'json', prompt, expected, compact(expected), compact(wrong), '{bad json}')

    # 5. Conditional procedure: read, act on readings, then branch on how many actions ran.
    procedure_sides = {
        'practice': {
            'site': 'Kestrel thermal control', 'prefix': 'CL', 'compare': 'above',
            'read': ('read_coolant', 'Reads one coolant loop temperature sensor.', 'sensor_id'),
            'act': ('isolate_loop', 'Isolates one coolant loop from the radiator bus.', 'loop_id', 'reason', 'overtemp'),
            'ticket': ('open_ticket', 'Opens one maintenance ticket.', 'system', 'severity', 'thermal'),
            'notify': ('page_role', 'Pages one on-duty role with a ticket reference.', 'role', 'ticket_ref'),
            'decoy': ('vent_loop', 'Vents a coolant loop overboard; irreversible.', 'loop_id', 'confirm'),
            'roles': ('flight-director', 'systems-lead'), 'ref': 'TKT', 'unit': 'C',
        },
        'heldout': {
            'site': 'Tycho pneumatics', 'prefix': 'PL', 'compare': 'below',
            'read': ('query_gauge', 'Queries one pressure line gauge.', 'gauge_ref'),
            'act': ('close_line', 'Closes one pressure line at its manifold.', 'line_ref', 'cause', 'underpressure'),
            'ticket': ('file_report', 'Files one engineering report.', 'area', 'level', 'pneumatics'),
            'notify': ('page_person', 'Pages one on-duty person with a report reference.', 'person', 'report_ref'),
            'decoy': ('purge_line', 'Purges a pressure line to vacuum; irreversible.', 'line_ref', 'approve'),
            'roles': ('base-commander', 'duty-engineer'), 'ref': 'RPT', 'unit': 'kPa',
        },
    }
    for index, partition in sides():
        side = procedure_sides[partition]
        draw = Draw(f'mission-ops/procedure/{index}')
        acted_target = (index - 1) % 4 if partition == 'practice' else (index + 1) % 4
        threshold = draw.between(40, 70) if partition == 'practice' else draw.between(180, 240)
        while True:
            loops = [f'{side["prefix"]}-{n}' for n in draw.shuffle([1, 2, 3, 4, 5, 6])[:3]]
            readings = {}
            for loop in loops:
                readings[loop] = threshold + draw.pick([-7, -4, -2, 0, 0, 2, 5, 9])
            if side['compare'] == 'above':
                acted = [loop for loop in loops if readings[loop] > threshold]
            else:
                acted = [loop for loop in loops if readings[loop] < threshold]
            if len(acted) == acted_target:
                break
        read_name, read_desc, read_key = side['read']
        act_name, act_desc, act_key, cause_key, cause = side['act']
        ticket_name, ticket_desc, system_key, level_key, system = side['ticket']
        notify_name, notify_desc, who_key, ref_key = side['notify']
        decoy_name, decoy_desc, decoy_key, decoy_flag = side['decoy']
        schemas = [
            {'name': read_name, 'description': read_desc, 'arguments': {read_key: 'string'}},
            {'name': act_name, 'description': act_desc, 'arguments': {act_key: 'string', cause_key: 'string'}},
            {'name': ticket_name, 'description': ticket_desc,
             'arguments': {system_key: 'string', level_key: 'integer'}},
            {'name': notify_name, 'description': notify_desc, 'arguments': {who_key: 'string', ref_key: 'string'}},
            {'name': decoy_name, 'description': decoy_desc, 'arguments': {decoy_key: 'string', decoy_flag: 'boolean'}},
        ]
        schemas = draw.shuffle(schemas)
        steps = [{'name': read_name, 'arguments': {read_key: loop}} for loop in loops]
        steps += [{'name': act_name, 'arguments': {act_key: loop, cause_key: cause}} for loop in acted]
        high, low = side['roles']
        if acted:
            level = min(3, 1 + len(acted))
            reference = f'{side["ref"]}-{level}-{system.upper()}'
            steps.append({'name': ticket_name, 'arguments': {system_key: system, level_key: level}})
            steps.append({'name': notify_name, 'arguments': {who_key: high if level == 3 else low,
                                                             ref_key: reference}})
        else:
            steps.append({'name': notify_name, 'arguments': {who_key: low, ref_key: 'NONE'}})
        expected = {'steps': steps}
        relation = 'greater than' if side['compare'] == 'above' else 'less than'
        reading_text = ', '.join(f'{loop} = {readings[loop]} {side["unit"]}' for loop in loops)
        prompt = ('Plan the required calls; do not execute any tool. Available tool schemas: '
                  + compact({'tools': schemas})
                  + f'\n{side["site"]} procedure. Current readings: {reading_text}.\n'
                  f'1. Call {read_name} once for each of {", ".join(loops)}, in that order.\n'
                  f'2. Then, in the same order, call {act_name} for every one whose reading is strictly '
                  f'{relation} {threshold} {side["unit"]}, with {cause_key} "{cause}".\n'
                  f'3. If at least one {act_name} call was made, call {ticket_name} with {system_key} "{system}" '
                  f'and {level_key} equal to 1 plus the number of {act_name} calls, but at most 3. Then call '
                  f'{notify_name} with {who_key} "{high}" if {level_key} is 3, otherwise "{low}", and {ref_key} '
                  f'"{side["ref"]}-<{level_key}>-{system.upper()}".\n'
                  f'4. If no {act_name} call was made, skip {ticket_name} and call {notify_name} with {who_key} '
                  f'"{low}" and {ref_key} "NONE".\n'
                  f'Never call {decoy_name}. Each call must have exactly "name" and "arguments". Return only a JSON '
                  'object with exactly one top-level key "steps", containing the calls in order. Add no extra '
                  'fields or commentary.')
        wrong_steps = [dict(step) for step in steps]
        last = wrong_steps[-1]
        last['arguments'] = dict(last['arguments'], **{who_key: high if last['arguments'][who_key] == low else low})
        add('procedure', index, 'tool-sequence', prompt, expected, compact(expected),
            compact({'steps': wrong_steps}), '{not json}', available_tools=schemas)

    order = {'ledger': 0, 'gonogo': 1, 'replay': 2, 'manifest': 3, 'procedure': 4}
    return sorted(result, key=lambda item: (order[item['id'].split('-')[0]], item['id']))


def build(suite, version=None):
    if suite == 'challenge':
        version = version or '1.3.1'
        selected = [item for group in challenge_items(version).values() for item in group]
    elif suite == 'challenge-hard':
        if version is not None:
            raise ValueError('No alternate version requested')
        selected = [item for group in challenge_hard_items().values() for item in group]
    elif suite == 'challenge-deep':
        if version not in (None, '1.0.0'):
            raise ValueError('No alternate version requested')
        selected = challenge_deep_items()
        version = '1.0.0'
    elif suite == 'mission-ops':
        if version not in (None, '1.0.0'):
            raise ValueError('No alternate version requested')
        selected = mission_ops_items()
        version = '1.0.0'
    elif suite == 'tool-schema':
        if version is not None:
            raise ValueError('No alternate version requested')
        selected = tool_schema_items()
    elif suite == 'tool-plan':
        if version is not None:
            raise ValueError('No alternate version requested')
        selected = tool_plan_items()
    elif suite == 'tool-sequence':
        if version is not None:
            raise ValueError('No alternate version requested')
        selected = tool_sequence_items()
    elif suite in ('quick', 'standard'):
        if version is not None:
            raise ValueError('No alternate version requested')
        count = 4 if suite == 'quick' else 14
        selected = [item for group in items().values() for item in group[:count]]
    else:
        raise ValueError('Unknown suite')
    version = version or ('1.2.0' if suite == 'tool-schema' else
                          '1.1.0' if suite == 'tool-plan' else
                          '1.0.0' if suite == 'tool-sequence' else '1.0.0')
    return validate({'schema': 'argos-ability-suite/1', 'suite': suite, 'version': version,
        'license': 'MIT', 'source': 'original-argos-live', 'omitted_categories': ['code-execution'],
        'items': selected})


if __name__ == '__main__':
    destination = ROOT / 'runtime/argoslive/data/ability'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / 'archive'
    archive.mkdir(parents=True, exist_ok=True)
    for version in ('1.2.0', '1.3.0'):
        path = archive / f'challenge-{version}.json'
        path.write_bytes((json.dumps(build('challenge', version=version), indent=2) + '\n').encode('utf-8'))
    for suite in ('quick', 'standard', 'challenge', 'challenge-hard', 'challenge-deep', 'tool-schema', 'tool-plan', 'tool-sequence',
                  'mission-ops'):
        (destination / (suite + '.json')).write_bytes(
            (json.dumps(build(suite), indent=2) + '\n').encode('utf-8'))
