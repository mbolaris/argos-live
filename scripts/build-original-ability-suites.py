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


def challenge_items():
    """A separate higher-difficulty form; do not derive it from quick/standard."""
    groups = {kind: [] for kind in ('numeric', 'choice', 'instruction', 'json', 'tool-call')}
    prefixes = {'numeric': 'calc', 'choice': 'logic', 'instruction': 'format',
                'json': 'record', 'tool-call': 'action'}

    def add(kind, index, prompt, expected, reference, wrong, malformed):
        groups[kind].append({'id': f'{prefixes[kind]}-{index:02}', 'prompt': prompt,
            'scorer': {'kind': kind, 'expected': expected}, 'reference': reference,
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
    for i, (name, arguments, prompt) in enumerate(actions, 1):
        expected = {'name': name, 'arguments': arguments}
        add('tool-call', i, prompt + ' Return only a JSON tool-call object; do not execute it.',
            expected, json.dumps(expected), json.dumps({'name': 'wrong_tool', 'arguments': arguments}), 'Execute the action now.')
    return groups


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
                f"the deadline is {offset} days later, and the API needs the absolute day. Convert urgency "
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


def build(suite):
    if suite == 'challenge':
        selected = [item for group in challenge_items().values() for item in group]
    elif suite == 'tool-schema':
        selected = tool_schema_items()
    elif suite == 'tool-plan':
        selected = tool_plan_items()
    elif suite in ('quick', 'standard'):
        count = 4 if suite == 'quick' else 14
        selected = [item for group in items().values() for item in group[:count]]
    else:
        raise ValueError('Unknown suite')
    version = ('1.2.0' if suite == 'tool-schema' else
               '1.1.0' if suite == 'tool-plan' else '1.0.0')
    return validate({'schema': 'argos-ability-suite/1', 'suite': suite, 'version': version,
        'license': 'MIT', 'source': 'original-argos-live', 'omitted_categories': ['code-execution'],
        'items': selected})


if __name__ == '__main__':
    destination = ROOT / 'runtime/argoslive/data/ability'
    destination.mkdir(parents=True, exist_ok=True)
    for suite in ('quick', 'standard', 'challenge', 'tool-schema', 'tool-plan'):
        (destination / (suite + '.json')).write_text(json.dumps(build(suite), indent=2) + '\n', encoding='utf-8')
