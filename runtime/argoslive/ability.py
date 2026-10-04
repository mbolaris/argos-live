"""Deterministic nonexecuting ability scorers and versioned original suites."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

DATA = Path(__file__).with_name('data') / 'ability'
KINDS = {'numeric', 'choice', 'instruction', 'json', 'tool-call'}
LIMIT = 65536


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def decode(text):
    def reject(value):
        raise ValueError('Nonfinite JSON number')
    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject)


def shape(value, expected):
    """Closed reference-derived schema; booleans are not integers."""
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return value.keys() == expected.keys() and all(shape(value[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(value) == len(expected) and all(shape(v, e) for v, e in zip(value, expected))
    return type(expected) in (str, int, bool, type(None))


def answer_text(text):
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0] in ('```', '```json', '```text'):
            text = '\n'.join(lines[1:-1]).strip()
    return text


def numeric(text):
    text = re.sub(r'^(?:answer|result|final answer|the answer is)\s*:?\s*', '', text, flags=re.I)
    text = text[:-1] if text.endswith('.') else text
    text = text.strip()
    if not re.fullmatch(r'[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?', text):
        raise ValueError('Expected one numeric answer')
    try:
        result = Decimal(text.replace(',', ''))
    except InvalidOperation as exc:
        raise ValueError('Invalid numeric answer') from exc
    if not result.is_finite():
        raise ValueError('Nonfinite answer')
    return result


def score(item, response):
    result = {'item_id': item['id'], 'score': 0, 'outcome': 'format_error',
              'format_valid': False, 'tool_execution_verified': False}
    if not isinstance(response, str) or len(response) > LIMIT:
        return result
    try:
        if len(response.encode('utf-8')) > LIMIT:
            return result
    except UnicodeError:
        return result
    text = answer_text(response)
    rule = item['scorer']
    try:
        kind = rule['kind']
        if kind == 'numeric':
            correct = numeric(text) == Decimal(rule['expected'])
        elif kind == 'choice':
            text = re.sub(r'^(?:answer|the answer is)\s*:?\s*', '', text, flags=re.I).strip('(). ')
            if not re.fullmatch(r'[A-Da-d]', text):
                raise ValueError('Expected a choice letter')
            correct = text.upper() == rule['expected']
        elif kind == 'instruction':
            if not text:
                raise ValueError('Empty answer')
            words = re.findall(r"\b[\w'-]+\b", text)
            correct = (rule['min_words'] <= len(words) <= rule['max_words']
                       and all(word.lower() in {w.lower() for w in words} for word in rule['keywords'])
                       and ('\n' not in text if rule['one_line'] else True)
                       and (text.isupper() if rule.get('uppercase') else True))
        elif kind in ('json', 'tool-call'):
            value = decode(text)
            if not shape(value, rule['expected']):
                raise ValueError('Expected closed JSON schema')
            if kind == 'tool-call' and not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value['name']):
                raise ValueError('Invalid tool name')
            correct = value == rule['expected']
        else:
            raise ValueError('Unsupported scorer')
    except (ValueError, TypeError, KeyError, RecursionError, InvalidOperation):
        return result
    result.update(score=int(correct), outcome='pass' if correct else 'wrong_answer', format_valid=True)
    return result


def validate(data):
    if (not isinstance(data, dict) or data.get('schema') != 'argos-ability-suite/1'
            or data.get('suite') not in ('quick', 'standard')
            or not re.fullmatch(r'\d+\.\d+\.\d+', data.get('version', ''))
            or data.get('license') != 'MIT' or data.get('source') != 'original-argos-live'
            or data.get('omitted_categories') != ['code-execution']
            or not isinstance(data.get('items'), list)
            or len(data['items']) != (20 if data['suite'] == 'quick' else 70)):
        raise ValueError('Invalid ability suite')
    seen, kinds = set(), set()
    for item in data['items']:
        if (not isinstance(item, dict) or not re.fullmatch(r'[a-z]+-\d{2}', item.get('id', ''))
                or item['id'] in seen or not isinstance(item.get('prompt'), str)
                or not 1 <= len(item['prompt']) <= 4096
                or not isinstance(item.get('scorer'), dict) or item['scorer'].get('kind') not in KINDS):
            raise ValueError('Invalid ability item')
        seen.add(item['id'])
        kinds.add(item['scorer']['kind'])
        rule = item['scorer']
        kind = rule['kind']
        if kind == 'instruction':
            if (type(rule.get('min_words')) is not int or type(rule.get('max_words')) is not int
                    or not 0 <= rule['min_words'] <= rule['max_words'] <= 256
                    or type(rule.get('one_line')) is not bool or type(rule.get('uppercase', False)) is not bool
                    or not isinstance(rule.get('keywords'), list) or not rule['keywords']
                    or any(not isinstance(word, str) or not re.fullmatch(r'[a-zA-Z]{1,64}', word) for word in rule['keywords'])):
                raise ValueError('Invalid instruction constraints')
        elif kind == 'numeric':
            if not isinstance(rule.get('expected'), str) or len(rule['expected']) > 128:
                raise ValueError('Invalid numeric reference')
        elif kind == 'choice':
            if rule.get('expected') not in ('A', 'B', 'C', 'D'):
                raise ValueError('Invalid choice reference')
        elif kind == 'tool-call':
            expected = rule.get('expected')
            if (not isinstance(expected, dict) or set(expected) != {'name', 'arguments'}
                    or not isinstance(expected['arguments'], dict) or not isinstance(expected['name'], str)
                    or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', expected['name'])):
                raise ValueError('Invalid inert tool reference')
        for field, outcome in [('reference', 'pass'), ('wrong', 'wrong_answer'), ('malformed', 'format_error')]:
            if not isinstance(item.get(field), str) or score(item, item[field])['outcome'] != outcome:
                raise ValueError('Reference/wrong/format fixtures do not match scorer')
    if kinds != KINDS:
        raise ValueError('Missing scorer category')
    return data


def load(suite='quick'):
    if suite not in ('quick', 'standard'):
        raise ValueError('Choose quick or standard')
    with (DATA / (suite + '.json')).open('rb') as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Suite exceeds metadata limit')
    return validate(decode(raw))
