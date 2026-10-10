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


def explain(item, rule, passage):
    category, outcome, output = item.get('category'), item.get('outcome'), item.get('output') or ''
    if category == 'summary':
        return 'A summary written for you to read. Summaries are not scored.'
    if outcome == 'format_error':
        return 'Not scorable: the reply wasn’t the required answer format, so it counts as a miss.'
    if outcome == 'pass':
        return {'answer': 'Correct: the answer matches the passage.',
                'quote': 'Correct: the right answer, backed by a sentence copied exactly from the passage.',
                'not_stated': 'Correct: it said the passage doesn’t give this.'}.get(category, 'Correct.')
    if category == 'not_stated':
        return 'Wrong: the passage doesn’t give this, but it answered anyway.'
    accepted = (rule or {}).get('accepted') or []
    expected = ' or '.join(f'“{a}”' for a in accepted[:3])
    if category == 'answer':
        return f'Wrong: expected {expected}.' if expected else 'Wrong: the answer doesn’t match the passage.'
    if category == 'quote' and rule:
        try:
            value = doc_trial.parse(output)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            value = None
        if value is not None:
            answer_ok = (value['status'] == 'answered'
                         and doc_trial.normal(value['answer']) in {doc_trial.normal(a) for a in accepted})
            quote_ok = doc_trial.supported(rule, value)
            if answer_ok and not quote_ok:
                if doc_trial.collapse(value['quote']) not in doc_trial.collapse(passage or ''):
                    return 'Wrong: the answer was right, but the quote isn’t copied exactly from the passage.'
                return 'Wrong: the answer was right, but the quoted sentence doesn’t contain it.'
            if not answer_ok:
                if doc_trial.collapse(value['quote']) and doc_trial.collapse(value['quote']) in doc_trial.collapse(passage or ''):
                    # The evidence was right; only the answer's wording missed the exact accepted forms.
                    return (f'Wrong: the quote was copied exactly, but the answer “{value["answer"][:80]}” is not one of the '
                            f'accepted answers ({expected}). Answers must match word for word, ignoring case and '
                            'surrounding punctuation.')
                return f'Wrong: expected {expected}, with a sentence copied from the passage.' if expected else \
                    'Wrong: the answer doesn’t match the passage.'
    return 'Wrong: the answer or its quote didn’t match the passage.'


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
            'reason': explain(item, rule, passage),
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
                    'unscored': sum(1 for i in items if i['outcome'] == 'unscored')},
            'passages': {pid: text for pid, text in passages.items() if isinstance(text, str)},
            'items': items}
