"""A read-only replay of one saved document trial: every response, in order, with its verdict.

Nothing here scores. Verdicts are the outcomes saved when the run was scored;
reasons only explain them, using the scorer's own parsing so an explanation
never disagrees with the score. Older suite summaries stay unscored; suite v1.1
summaries show the saved format-and-coverage proxy verdict.
"""
from . import doc_trial
from .shakedown import diagnose as miss_diagnosis

SCHEMA = 'argos-replay/1'
OUTPUT_LIMIT = 1200
ORDER = {'answer': 0, 'quote': 1, 'not_stated': 2, 'summary': 3}


def rules(run):
    """Scorer rules for the exact suite version the run used, or nothing if it differs."""
    try:
        suite_version = run.get('suite_version')
        prefix = 'documents/short/'
        version = suite_version[len(prefix):] if isinstance(suite_version, str) and suite_version.startswith(prefix) else suite_version
        data = doc_trial.load(version=version)
    except (OSError, ValueError):
        return {}
    if suite_version not in (data['version'], 'documents/short/' + data['version']):
        return {}
    return {item['id']: item['scorer'] for item in data['items']}


# The diagnosis itself lives with the other miss diagnosis in shakedown/diagnose.py (SIM3).
# These names stay here for existing callers; the output is unchanged.
DIAGNOSES = miss_diagnosis.DIAGNOSES
SHORT_WORDS = miss_diagnosis.SHORT_WORDS
NEGATIONS = miss_diagnosis.NEGATIONS
contains_phrase = miss_diagnosis.contains_phrase
labelled = miss_diagnosis.labelled


def diagnose(item, rule, passage):
    """Explain a saved verdict with separate answer and quote checks. Never rescores."""
    return miss_diagnosis.document(item, rule, passage)


def explain(item, rule, passage):
    return diagnose(item, rule, passage)['reason']


def diagnose_fields(item, rule, passage):
    value = diagnose(item, rule, passage)
    return {'reason': value['reason'], 'diagnosis': value.get('diagnosis'), 'checks': value.get('checks')}


def miss_groups(run):
    """Diagnostic groups of a saved document run's misses (wording, requirement, quote, wrong, format)."""
    suite = run.get('document_suite') if isinstance(run, dict) else None
    if not isinstance(run, dict) or run.get('suite') != 'documents-short' or not isinstance(suite, dict):
        return {}
    passages = suite.get('passages') if isinstance(suite.get('passages'), dict) else {}
    scorer, groups = rules(run), {}
    for item in run.get('items') or []:
        if not isinstance(item, dict) or item.get('outcome') in ('pass', 'unscored'):
            continue
        rule = scorer.get(item.get('item_id'))
        if item.get('category') == 'summary' and (not rule or rule.get('kind') != 'doc-summary'):
            continue
        value = diagnose(item, rule, passages.get(item.get('passage_id')))
        group = (value.get('diagnosis') or {}).get('group', 'wrong')
        if (value.get('diagnosis') or {}).get('kind') == 'quote_not_exact':
            group = 'quote'
        groups[group] = groups.get(group, 0) + 1
    return groups


def kept_meaning_only(groups):
    """Every miss kept an accepted answer: only wording or response-requirement diagnoses."""
    return bool(groups) and set(groups) <= {'wording', 'requirement'}


def diagnosis_counts(items):
    counts = {}
    for item in items:
        if item.get('diagnosis'):
            counts[item['diagnosis']['kind']] = counts.get(item['diagnosis']['kind'], 0) + 1
    return counts


def build(run):
    """Project a saved document run into replay items. Raises ValueError for other runs."""
    suite = run.get('document_suite')
    if run.get('kind') != 'ability' or run.get('suite') != 'documents-short' or not isinstance(suite, dict):
        raise ValueError('Replay is available for document trials')
    passages = suite.get('passages') if isinstance(suite.get('passages'), dict) else {}
    scorer = rules(run)
    items = []
    for item in list(run.get('items') or []) + list(run.get('unscored') or []):
        if not isinstance(item, dict) or not isinstance(item.get('item_id'), str):
            continue
        output = item.get('output') if isinstance(item.get('output'), str) else ''
        rule = scorer.get(item['item_id'])
        passage = passages.get(item.get('passage_id'))
        category = item.get('category')
        scored_summary = (category == 'summary' and rule and rule.get('kind') == 'doc-summary' and 'score' in item)
        quote = None
        if category in ('quote', 'answer'):
            try:
                quote = doc_trial.parse(output)['quote'] or None
            except (ValueError, TypeError, UnicodeError, RecursionError):
                quote = None
        items.append({
            'item_id': item['item_id'], 'category': category, 'passage_id': item.get('passage_id'),
            'question': item.get('question'),
            'outcome': item.get('outcome') if category != 'summary' or scored_summary else 'unscored',
            'output': output[:OUTPUT_LIMIT],
            'output_truncated': bool(item.get('output_truncated')) or len(output) > OUTPUT_LIMIT,
            **diagnose_fields(item, rule, passage),
            # Shown only after the run, as the fixed reference; it never changes the verdict.
            'accepted': list((rule or {}).get('accepted') or [])[:3] if category in ('answer', 'quote') else [],
            'quote_in_passage': (doc_trial.collapse(quote) in doc_trial.collapse(passage or '')) if quote else None,
            'latency_seconds': item.get('latency_seconds'),
        })
    # Saved runs store keys sorted, so passage order comes from the item number (answer-01 is passage 1).
    def position(item):
        digits = item['item_id'].rsplit('-', 1)[-1]
        return (int(digits) if digits.isdigit() else 99, ORDER.get(item['category'], 9), item['item_id'])
    items.sort(key=position)
    summary = run.get('summary') or {}
    recipe = run.get('recipe') if isinstance(run.get('recipe'), dict) else {}
    return {'schema': SCHEMA,
            'run': {'id': run['id'], 'created': run.get('created'), 'model': run.get('model'),
                    'state': run.get('state'), 'complete': bool((run.get('coverage') or {}).get('complete')),
                    'recipe': recipe.get('preset') or 'standard',
                    'correct': summary.get('correct'), 'total': summary.get('total'),
                    'format_errors': summary.get('format_errors'),
                    'unscored': sum(1 for i in items if i['outcome'] == 'unscored'),
                    'diagnoses': diagnosis_counts(items)},
            'passages': {pid: text for pid, text in passages.items() if isinstance(text, str)},
            'items': items}
