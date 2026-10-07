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
                   'quote': 'Show the evidence', 'not_stated': 'Know when it is missing'}


def summarize(runs):
    speed = next((r for r in runs if r['kind'] == 'speed'), None)
    ability = next((r for r in runs if r['kind'] == 'ability'), None)
    receipt = {'speed': None, 'ability': None}
    if speed:
        prompt = next((p for p in speed['prompts'] if p['size'] == 'short' and not p['skipped']), None)
        if prompt:
            receipt['speed'] = {'run': speed['id'],
                                'tokens_per_second': results.median_of(prompt, 'generation_tokens_per_second')['median'],
                                'first_token_seconds': results.median_of(prompt, 'time_to_first_token_seconds')['median']}
    if ability:
        summary = ability['summary']
        receipt['ability'] = {'run': ability['id'], 'suite': ability['suite'], 'created': ability['created'],
                              'correct': summary['correct'], 'total': summary['total'],
                              'format_errors': summary['format_errors'],
                              'categories': [{'id': k, 'label': CATEGORY_LABELS.get(k, k.replace('_', ' ')),
                                              'correct': v['correct'], 'total': v['total']}
                                             for k, v in summary['categories'].items()],
                              'qualified': (ability.get('qualification') or {}).get('qualified'),
                              'scope': 'These fixed exercises only; not an intelligence score or proof of tool use.'}
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
              'Choose an experiment: read a short fictional mission brief, spot a missing fact, '
              'or compare a repair plan. This is your opinion; the scores are fixed by code. '
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
