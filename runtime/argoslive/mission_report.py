"""A readable trial receipt and optional local-model opinion. No new scores.

Only aggregate public trial measurements go into the debrief prompt. Personal
documents, answers, configuration and paths never do. Opinions stay in memory
and cannot qualify a system, change a model or trigger a tool.
"""
import json

from . import results
from .ollama import Cancelled

CATEGORY_LABELS = {'choice': 'Pick the right answer', 'instruction': 'Follow directions',
                   'json': 'Organize information', 'numeric': 'Work with numbers',
                   'tool-call': 'Describe a tool request', 'answer': 'Find the facts',
                   'quote': 'Answer with a supporting quote', 'not_stated': 'Know when it is missing'}
# The quote check passes only when the answer is accepted AND the quote supports it, so a miss can come
# from answer wording alone. Saved runs keep their original labels; this only renames them for display.
CHECK_LABELS = {'quote': 'Correct answers with a supporting quote'}


REPLAY_LIMIT = 400


def resolve_suite_item(suite, suite_version, item_id):
    """Resolve an item from the exact tested suite version."""
    if not isinstance(suite, str) or not isinstance(item_id, str):
        return None
    try:
        if suite in ('quick', 'standard'):
            from . import ability as ability_mod
            suite_data = ability_mod.load(suite)
            expected_ver = suite_data.get('version', '')
            if suite_version and suite_version not in (expected_ver, f"ability/{suite}/{expected_ver}"):
                return None
            return next((it for it in suite_data.get('items', []) if it.get('id') == item_id), None)
        elif suite in ('documents-short', 'short'):
            from . import doc_trial as doc_mod
            suite_data = doc_mod.load('short')
            expected_ver = suite_data.get('version', '')
            if suite_version and suite_version not in (expected_ver, f"documents/short/{expected_ver}"):
                return None
            return next((it for it in suite_data.get('items', []) if it.get('id') == item_id), None)
    except Exception:
        return None
    return None


def explain_outcome(outcome, category, output, rule=None):
    rule = rule or {}
    out_str = (output or '').strip()
    kind = rule.get('kind', category)
    if outcome == 'pass':
        if kind == 'numeric':
            return f"Passed: Output matched expected numeric answer ({rule.get('expected')})."
        elif kind == 'choice':
            return f"Passed: Correctly selected choice letter ({rule.get('expected')})."
        elif kind == 'instruction':
            kw = ', '.join(rule.get('keywords', []))
            return f"Passed: Followed directions ({rule.get('min_words')}–{rule.get('max_words')} words, keywords: {kw})."
        elif kind in ('json', 'tool-call'):
            return "Passed: Produced valid closed JSON schema matching expected structure."
        elif kind == 'doc-answer' or category == 'answer':
            return "Passed: Extracted accurate fact from document passage."
        elif kind == 'doc-quote' or category == 'quote':
            return "Passed: Supported answer with exact verbatim passage quotation."
        elif kind == 'doc-not-stated' or category == 'not_stated':
            return "Passed: Correctly recognized that the fact was not stated in the document."
        return "Passed: Verified against fixed benchmark criteria."

    elif outcome == 'wrong_answer':
        if kind == 'numeric' and 'expected' in rule:
            return f"Missed: Output was '{out_str}', but expected '{rule['expected']}'."
        elif kind == 'choice' and 'expected' in rule:
            return f"Missed: Output was '{out_str}', but expected choice '{rule['expected']}'."
        elif kind == 'instruction':
            kw = ', '.join(rule.get('keywords', []))
            return f"Missed: Did not satisfy directions (requires {rule.get('min_words', 0)}–{rule.get('max_words', 256)} words and keywords: {kw})."
        elif kind in ('json', 'tool-call') and 'expected' in rule:
            return "Missed: JSON structure or arguments did not match expected schema."
        elif kind == 'doc-answer' or category == 'answer':
            acc = ', '.join(rule.get('accepted', []))
            return f"Missed: Answer did not match reference facts ({acc})." if acc else "Missed: Answer did not match document facts."
        elif kind == 'doc-quote' or category == 'quote':
            return "Missed: Quotation was either not verbatim from passage or did not support the answer."
        elif kind == 'doc-not-stated' or category == 'not_stated':
            return "Missed: Claimed an answer for a fact that was not stated in the passage."
        return "Missed: Answer did not match the fixed reference solution."

    elif outcome == 'format_error':
        if kind == 'choice':
            return "Response contract failure: Did not respond with a single choice letter (A–D)."
        elif kind == 'numeric':
            return "Response contract failure: Output could not be parsed as the required single numeric value (format error)."
        elif kind == 'instruction':
            return "Response contract failure: Output violated line, case, or formatting constraints."
        elif kind in ('json', 'tool-call'):
            return "Response contract failure: Output was not valid closed JSON or had extra unrequested keys."
        elif kind == 'doc-quote' or category == 'quote':
            return "Response contract failure: Quotation was missing, not verbatim from passage, or exceeded length."
        elif kind == 'doc-not-stated' or category == 'not_stated':
            return "Response contract failure: Expected 'not_stated' JSON status with empty answer."
        return "Response contract failure: Output violated the required schema or formatting constraints."

    return "Challenge was not completed."


def plain_failure_reason(item):
    return explain_outcome(item.get('outcome'), item.get('category', ''), item.get('output', ''))


def recipe_preset(run):
    value = run.get('recipe')
    preset = value.get('preset') if isinstance(value, dict) else None
    return preset if isinstance(preset, str) and preset else 'standard'


def summarize(runs):
    speed = next((r for r in runs if r['kind'] == 'speed'), None)
    ability = next((r for r in runs if r['kind'] == 'ability'), None)
    receipt = {'speed': None, 'ability': None}
    if speed:
        prompt = next((p for p in speed['prompts'] if p['size'] == 'short' and not p['skipped']), None)
        if prompt:
            prompt_tps = results.median_of(prompt, 'prompt_tokens_per_second')['median']
            receipt['speed'] = {'run': speed['id'],
                                'tokens_per_second': results.median_of(prompt, 'generation_tokens_per_second')['median'],
                                'first_token_seconds': results.median_of(prompt, 'time_to_first_token_seconds')['median'],
                                'prompt_tokens_per_second': prompt_tps}
    if ability:
        summary = ability['summary']
        checks = []
        if isinstance(ability.get('qualification'), dict):
            for c in ability['qualification'].get('checks', []):
                checks.append({
                    'name': c.get('name'),
                    'label': CHECK_LABELS.get(c.get('name'), c.get('label')),
                    'required': c.get('required'),
                    'observed': c.get('observed'),
                    'met': c.get('met'),
                })
        replay_passed = []
        replay_failed = []
        suite_name = ability.get('suite')
        suite_version = ability.get('suite_version')
        for item in ability.get('items', []):
            outcome = item.get('outcome', 'pass' if item.get('score') == 1 else 'wrong_answer')
            cat = item.get('category', '')
            out_str = item.get('output', '')
            if not isinstance(out_str, str):
                out_str = ''

            # Resolve original public challenge and scorer rule against exact tested suite version
            suite_item = resolve_suite_item(suite_name, suite_version, item.get('item_id'))
            rule = suite_item.get('scorer') if suite_item else None
            prompt_text = (suite_item.get('prompt') if suite_item else None) or item.get('prompt') or item.get('question') or ''
            question_text = (suite_item.get('question') if suite_item else None) or item.get('question') or prompt_text

            rep_item = {
                'item_id': item.get('item_id'),
                'category': cat,
                'category_label': CATEGORY_LABELS.get(cat, cat.replace('_', ' ')),
                'outcome': outcome,
                'score': item.get('score', 0),
                'prompt': prompt_text,
                'question': question_text,
                'output': out_str[:REPLAY_LIMIT],
                'reason': explain_outcome(outcome, cat, out_str, rule),
                'latency_seconds': item.get('latency_seconds'),
            }
            if outcome == 'pass':
                if len(replay_passed) < 2:
                    replay_passed.append(rep_item)
            else:
                if len(replay_failed) < 3:
                    replay_failed.append(rep_item)

        correct = summary['correct']
        total = summary['total']
        format_errors = summary['format_errors']
        wrong_answers = total - correct - format_errors
        unscored = len(ability.get('unscored') or [])
        lead_sentence = (
            f"{correct} of {total} scored questions correct. "
            f"{wrong_answers} wrong, {format_errors} in the wrong answer format."
        )

        receipt['ability'] = {
            'run': ability['id'], 'suite': ability['suite'], 'created': ability['created'],
            'correct': correct, 'total': total,
            'format_errors': format_errors,
            'wrong_answers': wrong_answers,
            # Responses the code does not score, such as summaries left for the owner to read.
            'unscored': unscored,
            # Which lab instructions produced this result, so an experiment is never shown as the baseline.
            'recipe': {'preset': recipe_preset(ability)},
            'lead_sentence': lead_sentence,
            'categories': [{'id': k, 'label': CATEGORY_LABELS.get(k, k.replace('_', ' ')),
                            'correct': v['correct'], 'total': v['total']}
                           for k, v in summary['categories'].items()],
            'qualified': (ability.get('qualification') or {}).get('qualified'),
            'checks': checks,
            'replay': {'passed': replay_passed, 'failed': replay_failed},
            'scope': 'These fixed exercises only; not an intelligence score or proof of tool use.'
        }
    return receipt


def debrief(client, model, runs, *, cancel=None):
    """Bounded, optional opinion after scored tests, under the existing lab lease."""
    complete = [r for r in runs if r.get('state', 'completed') == 'completed' and
                (r['kind'] != 'ability' or r.get('coverage', {}).get('complete'))]
    identities = {r.get('manifest_digest') for r in complete}
    if (not runs or len(complete) != len(runs) or len(identities) != 1
            or not next(iter(identities), None) or any(r.get('model') != model for r in runs)):
        return {'state': 'unavailable'}
    receipt = summarize(complete)
    # Fixed keys/numeric scores only. Even model tags and run IDs are omitted.
    facts = {'ability': None, 'speed': None}
    if receipt['ability']:
        a = receipt['ability']
        facts['ability'] = {k: a[k] for k in ('correct', 'total', 'format_errors', 'qualified')}
        facts['ability']['categories'] = [{k: c[k] for k in ('id', 'correct', 'total')} for c in a['categories']]
    if receipt['speed']:
        facts['speed'] = {k: receipt['speed'][k] for k in ('tokens_per_second', 'first_token_seconds')}
    prompt = ('You are Argos, a local private AI companion being tested with your builder. '
              'Write a brief first-person debrief, at most three sentences: what these results suggest, '
              'one limitation, and which experiment you would like to try next and why. '
              'Be candid, curious and specific. You have no feelings or evidence beyond this receipt. '
              'Do not claim AGI, rank, improvement, GPU use or capabilities not tested. '
              'Only these experiments exist: strict format instructions for lab tests, a retest with nothing changed, '
              'or comparing a different local model. Suggest one of them or none. '
              'This is your opinion; the scores are fixed by code. '
              'Return plain text, no tools.\nMEASURED RECEIPT:\n' + json.dumps(facts, allow_nan=False))
    old_timeout = client.timeout
    try:
        client.timeout = min(old_timeout, 45)
        reply = client.generate(model, prompt, options={'num_ctx': 2048, 'num_predict': 180, 'temperature': .4},
                                think=False, keep_alive='5m', cancel=cancel)
        text = reply.get('text')
        if not isinstance(text, str) or not text.strip():
            return {'state': 'unavailable'}
        return {'state': 'completed', 'model': model, 'manifest_digest': next(iter(identities)),
                'runs': [r['id'] for r in complete], 'text': text.strip()[:1200],
                'label': 'Local model opinion, not a score. No tools or personal profile loaded.'}
    except Cancelled:
        raise
    except Exception:
        # Opinion failure must not discard scored results or expose exception text.
        return {'state': 'unavailable'}
    finally:
        client.timeout = old_timeout
