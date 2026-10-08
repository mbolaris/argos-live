"""Short-document trials: original passages, closed-schema JSON scoring, fixed criteria.

Each passage yields three scored questions (a plain answer, a supported
quotation, and a question the passage cannot answer) plus an unscored summary
the owner judges. Scoring is programmatic with no model judge. A format error is
reported separately from a wrong answer. Qualification compares counts with the
criteria stored in the suite file; a baseline never moves those bars, and the
result says nothing about longer documents, file reading or real tasks.
"""
import argparse
import json
from pathlib import Path
import re
import sys

from . import ability, bench_ability
from .ollama import Client, OllamaError

DATA = Path(__file__).with_name('data') / 'documents'
CONTEXT = 4096
LIMIT = ability.LIMIT
CATEGORIES = ('answer', 'quote', 'not_stated')
KINDS = {'doc-answer', 'doc-quote', 'doc-not-stated', 'doc-summary'}
SCOPE = ('Short documents only (passages of roughly 150 words) at the recorded context. This does not show '
         'competence on longer documents, file reading, or your own tasks.')
MAX_QUOTE = 300


def collapse(text):
    return ' '.join(text.split())


def normal(text):
    return collapse(text).lower().strip(' .,;:!"\'')


def parse(text):
    value = ability.decode(ability.answer_text(text))
    if (type(value) is not dict or set(value) != {'status', 'answer', 'quote'}
            or value['status'] not in ('answered', 'not_stated')
            or type(value['answer']) is not str or type(value['quote']) is not str):
        raise ValueError('Expected the closed answer object')
    return value


def supported(rule, value):
    quote = collapse(value['quote'])
    passage = collapse(rule['passage'])
    accepted = [normal(a) for a in rule['accepted']]
    return (1 <= len(quote) <= MAX_QUOTE and quote in passage
            and any(a and a in normal(quote) for a in accepted))


def score(item, response):
    """Return a scored result, or None for an item the owner judges."""
    rule = item['scorer']
    if rule['kind'] == 'doc-summary':
        return None
    result = {'item_id': item['id'], 'score': 0, 'outcome': 'format_error',
              'format_valid': False, 'tool_execution_verified': False}
    if not isinstance(response, str) or len(response) > ability.LIMIT:
        return result
    try:
        if len(response.encode('utf-8')) > ability.LIMIT:
            return result
        value = parse(response)
        kind = rule['kind']
        if kind == 'doc-answer':
            correct = value['status'] == 'answered' and normal(value['answer']) in {normal(a) for a in rule['accepted']}
        elif kind == 'doc-quote':
            correct = (value['status'] == 'answered' and normal(value['answer']) in {normal(a) for a in rule['accepted']}
                       and supported(rule, value))
        elif kind == 'doc-not-stated':
            correct = value['status'] == 'not_stated' and not value['answer'].strip() and not value['quote'].strip()
        else:
            raise ValueError('Unsupported scorer')
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return result
    result.update(score=int(correct), outcome='pass' if correct else 'wrong_answer', format_valid=True)
    return result


def reply(status, answer='', quote=''):
    return json.dumps({'status': status, 'answer': answer, 'quote': quote})


def add_fixtures(item):
    rule = item['scorer']
    kind = rule['kind']
    if kind == 'doc-summary':
        return
    item['malformed'] = 'I could not find it.'
    if kind == 'doc-answer':
        item['reference'] = reply('answered', rule['accepted'][0])
        item['wrong'] = reply('answered', 'an unrelated value')
    elif kind == 'doc-quote':
        item['reference'] = reply('answered', rule['accepted'][0], rule['reference_quote'])
        item['wrong'] = reply('answered', rule['accepted'][0], 'This sentence is not in the passage.')
    else:
        item['reference'] = reply('not_stated')
        item['wrong'] = reply('answered', 'Yes')


def validate(data):
    if (not isinstance(data, dict) or data.get('schema') != 'argos-document-suite/1'
            or data.get('suite') != 'short' or not re.fullmatch(r'\d+\.\d+\.\d+', data.get('version', ''))
            or data.get('license') != 'MIT' or data.get('source') != 'original-argos-live'
            or data.get('context') != CONTEXT
            or data.get('omitted_categories') != ['long-documents', 'file-reading']
            or not isinstance(data.get('items'), list) or not data['items']):
        raise ValueError('Invalid document suite')
    criteria = data.get('criteria')
    if (not isinstance(criteria, dict) or type(criteria.get('version')) is not int
            or not isinstance(criteria.get('min_correct'), dict)
            or set(criteria['min_correct']) != set(CATEGORIES)
            or type(criteria.get('max_format_errors')) is not int or criteria['max_format_errors'] < 0
            or any(type(v) is not int or v < 1 for v in criteria['min_correct'].values())):
        raise ValueError('Invalid qualification criteria')
    seen, counts, per_passage = set(), {}, {}
    for item in data['items']:
        if (not isinstance(item, dict) or not re.fullmatch(r'[a-z]+-\d{2}', item.get('id', ''))
                or item['id'] in seen or not isinstance(item.get('prompt'), str)
                or not 1 <= len(item['prompt']) <= 8192
                or item.get('category') not in (*CATEGORIES, 'summary')
                or type(item.get('scored')) is not bool
                or not isinstance(item.get('scorer'), dict) or item['scorer'].get('kind') not in KINDS
                or not isinstance(item.get('passage_id'), str)
                or not isinstance(item.get('question'), str) or not 1 <= len(item['question']) <= 200):
            raise ValueError('Invalid document item')
        seen.add(item['id'])
        rule = item['scorer']
        counts[item['category']] = counts.get(item['category'], 0) + 1
        per_passage.setdefault(item['passage_id'], []).append(item['category'])
        if rule['kind'] == 'doc-summary':
            if item['scored'] or item['category'] != 'summary':
                raise ValueError('Summary items are unscored')
            continue
        if not item['scored'] or item['category'] == 'summary':
            raise ValueError('Scored items need a scored category')
        if (not isinstance(rule.get('passage'), str) or rule['passage'] not in item['prompt']):
            raise ValueError('Each item carries the passage it asks about')
        if rule['kind'] in ('doc-answer', 'doc-quote'):
            accepted = rule.get('accepted')
            if (not isinstance(accepted, list) or not accepted
                    or any(not isinstance(a, str) or not normal(a) for a in accepted)):
                raise ValueError('Invalid accepted answers')
        if rule['kind'] == 'doc-quote' and (
                not isinstance(rule.get('reference_quote'), str)
                or collapse(rule['reference_quote']) not in collapse(rule['passage'])):
            raise ValueError('Reference quotation must come from the passage')
        for field, outcome in (('reference', 'pass'), ('wrong', 'wrong_answer'), ('malformed', 'format_error')):
            if not isinstance(item.get(field), str) or score(item, item[field])['outcome'] != outcome:
                raise ValueError('Reference/wrong/format fixtures do not match scorer')
    if set(counts) != {*CATEGORIES, 'summary'}:
        raise ValueError('Missing document category')
    for category in CATEGORIES:
        if criteria['min_correct'][category] > counts[category]:
            raise ValueError('Criteria exceed the available items')
    if any(sorted(categories) != sorted((*CATEGORIES, 'summary')) for categories in per_passage.values()):
        raise ValueError('Each passage needs exactly one item per category')
    return data


def load(suite='short'):
    if suite != 'short':
        raise ValueError('Only the short-document suite exists')
    with (DATA / 'short.json').open('rb') as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Suite exceeds metadata limit')
    return validate(ability.decode(raw))


def qualify(items, criteria, *, complete):
    """Compare scored counts with the suite's fixed criteria."""
    correct = {c: sum(1 for i in items if i['category'] == c and i['score'] == 1) for c in CATEGORIES}
    format_errors = sum(1 for i in items if i['outcome'] == 'format_error')
    checks = [{'name': c, 'label': {'answer': 'Correct answers', 'quote': 'Supported quotations',
                                    'not_stated': 'Correct "not stated" answers'}[c],
               'required': criteria['min_correct'][c], 'observed': correct[c],
               'met': correct[c] >= criteria['min_correct'][c]} for c in CATEGORIES]
    checks.append({'name': 'format_errors', 'label': 'Format errors (at most)',
                   'required': criteria['max_format_errors'], 'observed': format_errors,
                   'met': format_errors <= criteria['max_format_errors']})
    return {'criteria_version': criteria['version'], 'complete': complete,
            'qualified': bool(complete and all(c['met'] for c in checks)), 'checks': checks, 'scope': SCOPE}


def passages(data):
    """Each passage once, so a result explains its own questions."""
    found = {}
    for item in data['items']:
        text = item['scorer'].get('passage')
        if text is not None:
            found.setdefault(item['passage_id'], text)
    return found


TASK_PROMPT = ('Read the document and answer using only the document. Do not use outside knowledge.\n\n'
               'DOCUMENT:\n{document}\n\nQUESTION: {question}\n\n'
               'Respond with only a JSON object with exactly these keys: '
               '{{"status": "answered" or "not_stated", "answer": "a short answer, or an empty string", '
               '"quote": "one sentence copied exactly from the document that supports the answer, or an empty string"}}. '
               'If the document does not contain the answer, use status "not_stated" with an empty answer and quote.')
TASK_DOCUMENT_LIMIT = 6000
TASK_QUESTION_LIMIT = 300


def ask(client, model, document, question, *, cancel=None):
    """One owner question about one pasted document. Nothing is saved here.

    The quotation is checked against the pasted text so the owner can see
    whether the answer is supported. A document that fills the context is
    refused rather than silently truncated.
    """
    if (not isinstance(document, str) or not document.strip() or len(document) > TASK_DOCUMENT_LIMIT
            or not isinstance(question, str) or not question.strip() or len(question) > TASK_QUESTION_LIMIT):
        raise ValueError(f'Paste up to {TASK_DOCUMENT_LIMIT} characters and ask a question of up to {TASK_QUESTION_LIMIT}')
    reply = client.generate(model, TASK_PROMPT.format(document=document.strip(), question=question.strip()),
                            options={'num_ctx': CONTEXT, 'num_predict': 400, 'temperature': 0, 'seed': 1},
                            think=False, keep_alive='5m', cancel=cancel)
    final = reply.get('final') if isinstance(reply.get('final'), dict) else {}
    used = final.get('prompt_eval_count')
    try:
        listed = client.list().get('models', [])
    except (OllamaError, OSError, ValueError, AttributeError):
        listed = []
    identity = next((m for m in listed if isinstance(m, dict) and model in (m.get('name'), m.get('model'))), None)
    result = {'model': model, 'context': CONTEXT, 'manifest_digest': identity.get('digest') if identity else None, 'prompt_tokens': used if isinstance(used, int) else None,
              'elapsed_seconds': reply.get('elapsed_seconds'),
              'time_to_first_token_seconds': reply.get('time_to_first_token_seconds')}
    if isinstance(used, int) and used >= CONTEXT - 32:
        return dict(result, outcome='too_long', status=None, answer='', quote='', quote_supported=False)
    try:
        value = parse(reply.get('text', ''))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return dict(result, outcome='format_error', status=None, answer='', quote='', quote_supported=False,
                    raw=str(reply.get('text', ''))[:600])
    quote = collapse(value['quote'])
    supported_quote = bool(quote) and len(quote) <= MAX_QUOTE and quote in collapse(document)
    return dict(result, outcome='answered' if value['status'] == 'answered' else 'not_stated', status=value['status'],
                answer=value['answer'][:600], quote=value['quote'][:MAX_QUOTE], quote_supported=supported_quote)


def run(client, model, *, hardware=None, clock=None, cancel=None, progress=None, recipe=None, **options):
    data = load()
    args = {key: value for key, value in (('hardware', hardware), ('clock', clock)) if value is not None}
    from . import recipe as recipe_mod
    resolved_recipe = recipe_mod.resolve(recipe, context=CONTEXT, output_cap=bench_ability.LIMIT, thinking=False)
    result = bench_ability.execute(
        client, model, data, suite='documents-short', suite_version='documents/short/' + data['version'],
        context=CONTEXT, score=score, category=lambda item: item['category'], cancel=cancel, progress=progress,
        annotate=lambda item: {'passage_id': item['passage_id'], 'question': item['question']},
        extra={'document_suite': {'criteria': data['criteria'], 'scope': SCOPE, 'passages': passages(data)}},
        recipe=resolved_recipe, **args)
    prompt_tokens = [i['measurement']['raw'].get('prompt_eval_count') for i in result['items']
                     if isinstance(i.get('measurement'), dict) and isinstance(i['measurement'].get('raw'), dict)]
    prompt_tokens = [t for t in prompt_tokens if isinstance(t, (int, float)) and t > 0]
    result['document_context'] = {'context': CONTEXT,
                                  'longest_prompt_tokens_tested': int(max(prompt_tokens)) if prompt_tokens else None}
    result['qualification'] = qualify(result['items'], data['criteria'], complete=result['coverage']['complete'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the short-document trial; summaries are for you to judge.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--ollama', default='http://127.0.0.1:11434')
    parser.add_argument('--timeout', type=int, default=120, help='API read timeout, 1–600 seconds.')
    parser.add_argument('--results-dir', type=Path, default=Path.home() / '.local/share/argos-live/results')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 600:
        raise ValueError('Trial timeout must be between 1 and 600 seconds')
    try:
        result = run(Client(args.ollama, timeout=args.timeout), args.model)
    except OllamaError as exc:
        raise ValueError('Document trial backend failed; no successful result was saved.') from exc
    from .results import Store
    path = Store(args.results_dir).save(result)
    print(f"Document trial {result['state']}: {path}")
    for check in result['qualification']['checks']:
        print(f"{check['label']}: {check['observed']} (needs {check['required']}) {'met' if check['met'] else 'not met'}")
    print('Qualified' if result['qualification']['qualified'] else 'Not qualified', '-', SCOPE)
    return 0 if result['coverage']['complete'] else 130


if __name__ == '__main__':
    sys.exit(main())
