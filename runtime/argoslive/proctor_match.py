"""Read-only match view of saved evaluation rounds: replay, baseline comparison, kept or rolled back.

Nothing here scores, ranks, or decides. Verdicts are the outcomes saved when a
run was scored. A comparison is descriptive: the host keep policy in
``instruction_changes`` remains the only authority on whether a change stays.
Answer keys, scorer rules, hidden reasoning, session IDs, hardware details and
private paths are never projected.
"""
import json
from pathlib import Path

from . import bench_openclaw
from .results import Store, identifier
from .storage import safe_local

SCHEMA = 'argos-proctor-match/1'
QUESTION_LIMIT = 6000
ANSWER_LIMIT = 8192
JOURNAL_LIMIT = 1024 ** 2
JOURNAL_SCAN = 256
RECENT_LIMIT = 24
OUTCOMES = {'pass', 'wrong_answer', 'format_error', 'unscored'}
REASONS = {
    'pass': 'Counted correct by the fixed scorer for this question.',
    'wrong_answer': 'Readable reply, but not what the fixed scorer accepts. The answer key stays hidden.',
    'format_error': 'Not in the required answer format, so it counts as a miss.',
    'unscored': 'Recorded without a score.',
}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _median(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def questions(run):
    """Prompts for the exact suite version the run used; empty when the bundled suite differs."""
    suite = run.get('suite')
    if not isinstance(suite, str) or not suite.startswith('openclaw-'):
        return {}
    name = suite.removeprefix('openclaw-')
    try:
        data, items, _path, _omitted = bench_openclaw.suite_content(name)
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if run.get('suite_version') != 'argos-openclaw-ability/' + name + '/' + str(data.get('version')):
        return {}
    return {item['id']: item['prompt'] for item in items
            if isinstance(item.get('id'), str) and isinstance(item.get('prompt'), str)}


def round_view(run):
    """Project one saved ability run into a replayable round. Raises ValueError for other runs."""
    if not isinstance(run, dict) or run.get('kind') != 'ability' or not isinstance(run.get('items'), list):
        raise ValueError('A match replay is available for saved ability evaluations')
    prompts = questions(run)
    items = []
    for item in run['items'][:200]:
        if not isinstance(item, dict) or not isinstance(item.get('item_id'), str):
            continue
        question = item.get('question') if isinstance(item.get('question'), str) else prompts.get(item['item_id'], '')
        answer = item.get('output') if isinstance(item.get('output'), str) else ''
        outcome = item.get('outcome') if item.get('outcome') in OUTCOMES else None
        partition = item.get('partition') if item.get('partition') in ('practice', 'heldout') else None
        items.append({
            'item_id': item['item_id'][:128],
            'category': item.get('category')[:80] if isinstance(item.get('category'), str) else '',
            'partition': partition,
            'question': question[:QUESTION_LIMIT], 'question_truncated': len(question) > QUESTION_LIMIT,
            'answer': answer[:ANSWER_LIMIT],
            'answer_truncated': item.get('output_truncated') is True or len(answer) > ANSWER_LIMIT,
            'outcome': outcome, 'score': item.get('score') if item.get('score') in (0, 1) else None,
            'latency_seconds': _number(item.get('latency_seconds')),
            'reason': REASONS.get(outcome, 'No verdict was saved for this question.'),
        })
    summary = run.get('summary') if isinstance(run.get('summary'), dict) else {}
    coverage = run.get('coverage') if isinstance(run.get('coverage'), dict) else {}
    partitions = {}
    for name in ('practice', 'heldout'):
        scored = [item for item in items if item['partition'] == name and item['score'] is not None]
        if scored:
            partitions[name] = {'correct': sum(item['score'] for item in scored), 'total': len(scored)}
    failure = run.get('failure_code')
    fingerprint = run.get('prompt_fingerprint') if isinstance(run.get('prompt_fingerprint'), dict) else {}
    instructions = fingerprint.get('workspace_agents_sha256')
    return {
        'run_id': run['id'], 'created': run.get('created'), 'suite': run.get('suite'),
        'suite_version': run.get('suite_version'), 'model': run.get('model'),
        'state': run.get('state') if run.get('state') in ('completed', 'cancelled', 'failed') else 'unknown',
        'failure_code': failure[:80] if isinstance(failure, str) else None,
        'complete': coverage.get('complete') is True,
        'completed': coverage.get('completed') if type(coverage.get('completed')) is int else len(items),
        'total': coverage.get('total') if type(coverage.get('total')) is int else len(items),
        'correct': summary.get('correct') if type(summary.get('correct')) is int else None,
        'scored_total': summary.get('total') if type(summary.get('total')) is int else None,
        'format_errors': summary.get('format_errors') if type(summary.get('format_errors')) is int else None,
        'partitions': partitions,
        'median_latency_seconds': _median([item['latency_seconds'] for item in items]),
        'elapsed_seconds': _number(run.get('elapsed_seconds')),
        # Used only to say whether two rounds ran under the same instructions; removed before replying.
        '_instructions': instructions if isinstance(instructions, str) else None,
        'questions_available': bool(items) and all(item['question'] for item in items),
        'items': items,
    }


def comparable(baseline, candidate):
    """Same fixed test, both fully covered, same question order. Returns a refusal code or None."""
    if baseline['run_id'] == candidate['run_id']:
        return 'same-run'
    if not baseline['suite_version'] or baseline['suite_version'] != candidate['suite_version']:
        return 'different-test-version'
    if not baseline['complete'] or not candidate['complete']:
        return 'incomplete-round'
    if [item['item_id'] for item in baseline['items']] != [item['item_id'] for item in candidate['items']]:
        return 'different-questions'
    return None


def compare(baseline, candidate):
    """Question-by-question movement between two comparable rounds. Descriptive only."""
    refusal = comparable(baseline, candidate)
    if refusal:
        return {'comparable': False, 'reason': refusal}
    rows, wins, regressions = [], [], []
    partitions = {}
    for before, after in zip(baseline['items'], candidate['items']):
        change = 'same'
        if before['score'] == 0 and after['score'] == 1:
            change = 'win'
            wins.append(after['item_id'])
        elif before['score'] == 1 and after['score'] == 0:
            change = 'regression'
            regressions.append(after['item_id'])
        delta = None
        if before['latency_seconds'] is not None and after['latency_seconds'] is not None:
            delta = after['latency_seconds'] - before['latency_seconds']
        rows.append({'item_id': after['item_id'], 'category': after['category'], 'partition': after['partition'],
                     'change': change, 'baseline_outcome': before['outcome'], 'outcome': after['outcome'],
                     'baseline_latency_seconds': before['latency_seconds'],
                     'latency_seconds': after['latency_seconds'], 'latency_delta_seconds': delta})
        if after['partition']:
            part = partitions.setdefault(after['partition'], {'baseline_correct': 0, 'correct': 0, 'total': 0,
                                                              'wins': 0, 'regressions': 0})
            if before['score'] is not None and after['score'] is not None:
                part['total'] += 1
                part['baseline_correct'] += before['score']
                part['correct'] += after['score']
            part['wins'] += change == 'win'
            part['regressions'] += change == 'regression'
    before_median, after_median = baseline['median_latency_seconds'], candidate['median_latency_seconds']
    return {
        'comparable': True, 'baseline_id': baseline['run_id'], 'run_id': candidate['run_id'],
        'baseline_correct': baseline['correct'], 'correct': candidate['correct'],
        'scored_total': candidate['scored_total'],
        'correct_delta': (candidate['correct'] - baseline['correct']
                          if baseline['correct'] is not None and candidate['correct'] is not None else None),
        'wins': wins, 'regressions': regressions,
        'baseline_median_latency_seconds': before_median, 'median_latency_seconds': after_median,
        'median_latency_delta_seconds': (after_median - before_median
                                         if before_median is not None and after_median is not None else None),
        'partitions': partitions,
        'same_model': baseline['model'] == candidate['model'],
        'same_instructions': (baseline['_instructions'] == candidate['_instructions']
                              if baseline['_instructions'] and candidate['_instructions'] else None),
        'items': rows,
    }


def _read_json(path):
    with path.open('rb') as stream:
        raw = stream.read(JOURNAL_LIMIT + 1)
    if len(raw) > JOURNAL_LIMIT:
        raise ValueError('journal-file-too-large')
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('journal-file-invalid')
    return value


def _ids(value):
    if not isinstance(value, list):
        return []
    found = []
    for item in value[:8]:
        try:
            found.append(identifier(item))
        except ValueError:
            pass
    return found


def decision(home, run_id):
    """The host journal's kept/rolled-back record naming this run, or None. Never creates or repairs it."""
    root = Path(home) / '.local/state/argos-live/instruction-changes'
    try:
        root = safe_local(root)
        if not root.is_dir():
            return None
        directories = sorted((path for path in root.iterdir() if path.is_dir()),
                             key=lambda path: path.name, reverse=True)[:JOURNAL_SCAN]
    except (OSError, ValueError):
        return None
    for directory in directories:
        try:
            resolved = _read_json(directory / 'resolved.json')
        except (OSError, ValueError, UnicodeError):
            continue
        baselines, candidates = _ids(resolved.get('baseline_ids')), _ids(resolved.get('candidate_ids'))
        if run_id not in baselines and run_id not in candidates:
            continue
        action = resolved.get('action')
        if action not in ('keep', 'restore', 'adopted-external'):
            continue
        try:
            from . import instruction_changes
            intent = _read_json(directory / 'intent.json')
            policy = instruction_changes.keep_policy(intent.get('keep_policy')) if intent.get('keep_policy') \
                else instruction_changes._POLICY_V1
            policy_id = policy['id']
        except Exception:
            policy, policy_id = None, None
        rejected = resolved.get('rejected_evidence_code')
        return {
            'change_id': directory.name[:64], 'action': action,
            'role': 'candidate' if run_id in candidates else 'baseline',
            'baseline_ids': baselines, 'candidate_ids': candidates,
            'qualified_experiment': resolved.get('qualified_experiment') is True,
            'independent_gain_verified': resolved.get('independent_gain_verified') is True,
            'rejected_evidence_code': rejected[:80] if isinstance(rejected, str) else None,
            'observed': resolved.get('observed') if isinstance(resolved.get('observed'), str) else None,
            'policy_id': policy_id, '_policy': policy, 'required_correct_delta': None,
        }
    return None


def _load_round(store, run_id):
    try:
        return round_view(store.load(identifier(run_id)))
    except (ValueError, OSError):
        return None


def _summary(view):
    return {key: view[key] for key in ('run_id', 'created', 'suite', 'suite_version', 'model', 'state',
                                       'complete', 'correct', 'scored_total', 'median_latency_seconds',
                                       'partitions')}


def find_baseline(store, view, record):
    """Journal baselines first; otherwise the latest earlier complete round of the same test."""
    if record and record['role'] == 'candidate':
        for run_id in record['baseline_ids']:
            found = _load_round(store, run_id)
            if found and comparable(found, view) is None:
                return found, 'journal'
    try:
        listing = store.list()['runs']
    except (OSError, ValueError):
        listing = []
    for row in listing:
        if (row.get('kind') != 'ability' or row.get('suite_version') != view['suite_version'] or
                row.get('state') != 'completed' or row.get('id') == view['run_id'] or
                not isinstance(row.get('created'), str) or not isinstance(view['created'], str) or
                row['created'] >= view['created']):
            continue
        found = _load_round(store, row['id'])
        if found and comparable(found, view) is None:
            return found, 'previous-same-test'
    return None, None


def match(home, store, run_id):
    """One saved round with its replay, its baseline comparison and the host's keep/restore record."""
    view = round_view(store.load(identifier(run_id)))
    record = decision(home, view['run_id'])
    policy = record.pop('_policy', None) if record else None
    if record and policy:
        minimum = policy.get('minimum_correct_delta', {}).get(view['suite'])
        record['required_correct_delta'] = minimum if type(minimum) is int else None
        record['runs'] = [_summary(found) for found in
                          (_load_round(store, item) for item in record['baseline_ids'] + record['candidate_ids'])
                          if found]
    # An unfinished round is saved for the record but never compared.
    baseline, source = find_baseline(store, view, record) if view['complete'] else (None, None)
    comparison = (compare(baseline, view) if baseline else
                  {'comparable': False, 'reason': 'no-baseline' if view['complete'] else 'incomplete-round'})
    if baseline:
        comparison['baseline_source'] = source
    view.pop('_instructions', None)
    return {'schema': SCHEMA, 'round': view,
            'baseline': _summary(baseline) if baseline else None,
            'comparison': comparison, 'decision': record}


def recent(store, limit=RECENT_LIMIT):
    """Newest saved ability rounds, for the replay picker."""
    try:
        listing = store.list()['runs']
    except (OSError, ValueError):
        return []
    rounds = []
    for row in listing:
        if row.get('kind') != 'ability' or not isinstance(row.get('id'), str):
            continue
        found = _load_round(store, row['id'])
        if found:
            rounds.append(_summary(found))
        if len(rounds) >= limit:
            break
    return rounds


def default_store(home):
    return Store(Path(home) / '.local/share/argos-live/results')
