"""A read-only replay of one saved document trial: every response, in order, with its verdict.

Nothing here scores. Verdicts are the outcomes saved when the run was scored;
reasons only explain them, using the scorer's own parsing so an explanation
never disagrees with the score. Summaries stay unscored.
"""
from . import doc_trial

SCHEMA = 'argos-replay/1'
OUTPUT_LIMIT = 1200
ORDER = {'answer': 0, 'quote': 1, 'not_stated': 2, 'summary': 3}


def rules(run):
    """Scorer rules for the exact suite version the run used, or nothing if it differs."""
    try:
        data = doc_trial.load()
    except (OSError, ValueError):
        return {}
    if run.get('suite_version') != 'documents/short/' + data['version']:
        return {}
    return {item['id']: item['scorer'] for item in data['items']}


# Diagnostic labels (added 2026-10-10). They describe a saved miss; they never change a score,
# accepted answers, suite version or qualification threshold.
DIAGNOSES = {
    'wording': ('Right meaning, rejected for wording', 'wording'),
    'unsupported_quote': ('Quote copied exactly, but it doesn’t support the answer', 'quote'),
    'quote_not_exact': ('Quote not copied exactly from the passage', 'requirement'),
    'long_answer': ('Not a short answer', 'requirement'),
    'instruction_echo': ('Copied the instructions instead of answering', 'wrong'),
    'answered_missing': ('Answered something the passage doesn’t say', 'wrong'),
    'wrong': ('Wrong answer', 'wrong'),
    'format': ('Not in the required answer format', 'format'),
}
SHORT_WORDS = 6
NEGATIONS = {'not', 'no', 'never', 'none', 'nothing'}


def contains_phrase(text, phrase):
    """Whole-word containment after the scorer's own normalization."""
    words, target = doc_trial.normal(text).split(), doc_trial.normal(phrase).split()
    return bool(target) and any(words[i:i + len(target)] == target for i in range(len(words) - len(target) + 1))


def diagnose(item, rule, passage):
    """Explain a saved verdict with separate answer and quote checks. Never rescores."""
    category, outcome, output = item.get('category'), item.get('outcome'), item.get('output') or ''
    if category == 'summary':
        return {'reason': 'A summary written for you to read. Summaries are not scored.'}
    if outcome == 'pass':
        return {'reason': {'answer': 'Correct: the answer matches the passage.',
                           'quote': 'Correct: an accepted answer, backed by a quote copied exactly from the passage.',
                           'not_stated': 'Correct: it said the passage doesn’t give this.'}.get(category, 'Correct.')}
    if outcome == 'format_error':
        return labelled('format', 'Not scorable: the reply wasn’t the required answer format, so it counts as a miss.')
    if category == 'not_stated':
        return labelled('answered_missing', 'Wrong: the passage doesn’t give this, but it answered anyway.')
    accepted = (rule or {}).get('accepted') or []
    expected = ' or '.join(f'“{a}”' for a in accepted[:3])
    try:
        value = doc_trial.parse(output)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        value = None
    if value is None or not rule:
        return {'reason': f'Wrong: expected {expected}.' if expected else 'Wrong: the answer doesn’t match the passage.'}
    answer, quote = value['answer'], value['quote']
    words = doc_trial.normal(answer).split()
    checks = {'answer_accepted': value['status'] == 'answered' and doc_trial.normal(answer) in {doc_trial.normal(a) for a in accepted},
              'answer_contains_accepted': any(contains_phrase(answer, a) for a in accepted),
              'answer_words': len(words)}
    if category == 'quote':
        exact = bool(doc_trial.collapse(quote)) and doc_trial.collapse(quote) in doc_trial.collapse(passage or '')
        checks.update(quote_exact=exact, quote_supports=doc_trial.supported(rule, value))
    shown = answer[:80]
    if 'a short answer' in doc_trial.normal(answer) or 'or an empty string' in doc_trial.normal(answer):
        return labelled('instruction_echo', f'Wrong: the answer copies the instruction text (“{shown}”) instead of answering.', checks)
    if category == 'quote' and not checks['quote_supports']:
        if not checks['quote_exact']:
            return labelled('quote_not_exact', 'Wrong: the quote isn’t copied exactly from the passage.', checks)
        return labelled('unsupported_quote', 'Wrong: the quote is copied exactly, but it doesn’t contain an accepted answer, '
                        'so it doesn’t support the answer.', checks)
    if not checks['answer_accepted'] and checks['answer_contains_accepted'] and not NEGATIONS & set(words):
        same_as_quote = category == 'quote' and doc_trial.collapse(answer) == doc_trial.collapse(quote)
        if len(words) > SHORT_WORDS or same_as_quote:
            return labelled('long_answer', f'Wrong: the task asks for a short answer, but this answer is a full sentence '
                            f'({len(words)} words). It includes an accepted answer ({expected}), which must be given on its own.', checks)
        return labelled('wording', f'Wrong as scored: “{shown}” includes the accepted answer ({expected}) but isn’t exactly it. '
                        'Answers must match word for word, ignoring case and surrounding punctuation.', checks)
    return labelled('wrong', f'Wrong: expected {expected}.' if expected else 'Wrong: the answer doesn’t match the passage.', checks)


def labelled(kind, reason, checks=None):
    label, group = DIAGNOSES[kind]
    return {'reason': reason, 'diagnosis': {'kind': kind, 'label': label, 'group': group}, 'checks': checks}


def explain(item, rule, passage):
    return diagnose(item, rule, passage)['reason']


def diagnose_fields(item, rule, passage):
    value = diagnose(item, rule, passage)
    return {'reason': value['reason'], 'diagnosis': value.get('diagnosis'), 'checks': value.get('checks')}


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
        quote = None
        if category in ('quote', 'answer'):
            try:
                quote = doc_trial.parse(output)['quote'] or None
            except (ValueError, TypeError, UnicodeError, RecursionError):
                quote = None
        items.append({
            'item_id': item['item_id'], 'category': category, 'passage_id': item.get('passage_id'),
            'question': item.get('question'),
            'outcome': 'unscored' if category == 'summary' else item.get('outcome'),
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
