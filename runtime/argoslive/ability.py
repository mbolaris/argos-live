"""Deterministic nonexecuting ability scorers and versioned original suites."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

DATA = Path(__file__).with_name('data') / 'ability'
KINDS = {'numeric', 'choice', 'instruction', 'json', 'tool-call', 'tool-sequence'}
DEFAULT_KINDS = {'numeric', 'choice', 'instruction', 'json', 'tool-call'}
SUITE_COUNTS = {'quick': 20, 'standard': 70, 'challenge': 40, 'tool-schema': 40,
                'tool-plan': 40, 'tool-sequence': 40}
SUITE_KINDS = {'tool-schema': {'tool-call'}, 'tool-plan': {'tool-call'},
               'tool-sequence': {'tool-sequence'}}
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
        elif kind in ('json', 'tool-call', 'tool-sequence'):
            value = decode(text)
            if not shape(value, rule['expected']):
                raise ValueError('Expected closed JSON schema')
            if kind == 'tool-call' and not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value['name']):
                raise ValueError('Invalid tool name')
            if kind == 'tool-sequence' and any(
                    not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', call['name'])
                    for call in value['steps']):
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
            or not isinstance(data.get('suite'), str)
            or data.get('suite') not in SUITE_COUNTS
            or not re.fullmatch(r'\d+\.\d+\.\d+', data.get('version', ''))
            or data.get('license') != 'MIT' or data.get('source') != 'original-argos-live'
            or data.get('omitted_categories') != ['code-execution']
            or not isinstance(data.get('items'), list)
            or len(data['items']) != SUITE_COUNTS[data['suite']]):
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
        elif kind in ('tool-call', 'tool-sequence'):
            expected = rule.get('expected')
            if kind == 'tool-call':
                if (not isinstance(expected, dict) or set(expected) != {'name', 'arguments'}
                        or not isinstance(expected['arguments'], dict) or not isinstance(expected['name'], str)
                        or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', expected['name'])):
                    raise ValueError('Invalid inert tool reference')
                targets = [expected]
            else:
                if (data['suite'] != 'tool-sequence' or not isinstance(expected, dict)
                        or set(expected) != {'steps'} or not isinstance(expected['steps'], list)
                        or len(expected['steps']) not in (2, 3)):
                    raise ValueError('Invalid inert tool sequence reference')
                targets = expected['steps']
                if any(not isinstance(call, dict) or set(call) != {'name', 'arguments'}
                       or not isinstance(call['name'], str)
                       or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', call['name'])
                       or not isinstance(call['arguments'], dict) for call in targets):
                    raise ValueError('Invalid inert tool sequence step')
                if len({call['name'] for call in targets}) != len(targets):
                    raise ValueError('Tool sequence steps must use distinct tools')
            has_schemas = 'available_tools' in rule
            if data['suite'] in ('tool-schema', 'tool-plan', 'tool-sequence') and not has_schemas:
                raise ValueError('Missing provided tool schemas')
            if ((kind == 'tool-call' and data['suite'] == 'challenge' and
                 ((data['version'] == '1.0.0' and has_schemas) or
                  (data['version'] != '1.0.0' and not has_schemas))) or
                    has_schemas and data['suite'] not in ('challenge', 'tool-schema', 'tool-plan', 'tool-sequence')):
                raise ValueError('Challenge tool-schema version mismatch')
            if has_schemas:
                partition = rule.get('partition')
                schemas = rule.get('available_tools')
                schema_count = {'tool-schema': 3, 'tool-plan': 4,
                                'tool-sequence': 4}.get(data['suite'], 4)
                partition_valid = (partition in ('practice', 'heldout')
                                   if data['suite'] in ('tool-schema', 'tool-plan', 'tool-sequence')
                                   else partition is None)
                if (not partition_valid or not isinstance(schemas, list)
                        or len(schemas) != schema_count):
                    raise ValueError('Invalid tool-suite partition or available tools')
                names = set()
                targets_by_name = {}
                for schema in schemas:
                    if (not isinstance(schema, dict) or set(schema) != {'name', 'description', 'arguments'}
                            or not isinstance(schema['name'], str)
                            or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', schema['name'])
                            or not isinstance(schema['description'], str)
                            or not 1 <= len(schema['description']) <= 256
                            or schema['name'] in names or not isinstance(schema['arguments'], dict)
                            or not schema['arguments']):
                        raise ValueError('Invalid provided tool schema')
                    names.add(schema['name'])
                    targets_by_name[schema['name']] = schema
                    if any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key)
                           or value not in ('string', 'integer', 'boolean')
                           for key, value in schema['arguments'].items()):
                        raise ValueError('Invalid provided argument schema')
                type_names = {str: 'string', int: 'integer', bool: 'boolean'}
                for target_call in targets:
                    target = targets_by_name.get(target_call['name'])
                    if (target is None or set(target_call['arguments']) != set(target['arguments']) or
                            any(type_names.get(type(value)) != target['arguments'][key]
                                for key, value in target_call['arguments'].items())):
                        raise ValueError('Expected tool call does not match a provided schema')
                if json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False) not in item['prompt']:
                    raise ValueError('Prompt does not include its available tool schemas')
        for field, outcome in [('reference', 'pass'), ('wrong', 'wrong_answer'), ('malformed', 'format_error')]:
            if not isinstance(item.get(field), str) or score(item, item[field])['outcome'] != outcome:
                raise ValueError('Reference/wrong/format fixtures do not match scorer')
    expected_kinds = SUITE_KINDS.get(data['suite'], DEFAULT_KINDS)
    if kinds != expected_kinds:
        raise ValueError('Missing scorer category')
    if data['suite'] == 'challenge' and data['version'] in ('1.1.0', '1.2.0'):
        action_items = [item for item in data['items'] if item['scorer']['kind'] == 'tool-call']
        positions = []
        for item in action_items:
            schemas = item['scorer']['available_tools']
            positions.append(next(index for index, schema in enumerate(schemas)
                                  if schema['name'] == item['scorer']['expected']['name']))
        if (len(action_items) != 8 or any(not 0 <= position < 4 for position in positions) or
                sorted(positions.count(position) for position in range(4)) != [2, 2, 2, 2]):
            raise ValueError('Challenge tool target position must be balanced')
    if data['suite'] in ('tool-schema', 'tool-plan', 'tool-sequence'):
        partitions = {partition: [item for item in data['items']
                                  if item['scorer'].get('partition') == partition]
                      for partition in ('practice', 'heldout')}
        if any(len(items) != 20 for items in partitions.values()):
            raise ValueError('Tool-schema suite requires balanced practice and held-out partitions')
        names, argument_keys = {}, {}
        for partition, items in partitions.items():
            names[partition] = {schema['name'] for item in items
                                for schema in item['scorer']['available_tools']}
            argument_keys[partition] = {key for item in items for schema in item['scorer']['available_tools']
                                        for key in schema['arguments']}
            target_positions = [0] * (3 if data['suite'] == 'tool-schema' else 4)
            counts = {}
            for item in items:
                expected = item['scorer']['expected']
                if data['suite'] == 'tool-sequence':
                    targets = expected['steps']
                    for call in targets:
                        counts[call['name']] = counts.get(call['name'], 0) + 1
                    expected_name = targets[0]['name']
                else:
                    expected_name = expected['name']
                    counts[expected_name] = counts.get(expected_name, 0) + 1
                position = next(index for index, schema in enumerate(item['scorer']['available_tools'])
                                if schema['name'] == expected_name)
                target_positions[position] += 1
                if data['suite'] == 'tool-sequence':
                    if len(targets) not in (2, 3):
                        raise ValueError('Tool sequence length must be two or three')
                    for index, call in enumerate(targets[1:], 1):
                        expected_refs = [value for value in call['arguments'].values()
                                         if isinstance(value, str) and value.startswith('$step')]
                        matches = [re.fullmatch(r'\$step([1-9][0-9]*)\.[a-z][a-z0-9_]*', ref)
                                   for ref in expected_refs]
                        if (not matches or any(match is None for match in matches) or
                                any(int(match.group(1)) > index for match in matches) or
                                max(int(match.group(1)) for match in matches) != index):
                            raise ValueError('Each later tool step requires a reference to the previous result')
                    if 'Reference bindings:' not in item['prompt']:
                        raise ValueError('Tool sequence prompt must state exact reference bindings')
            if data['suite'] == 'tool-sequence':
                if len(counts) != 10 or set(counts.values()) != {5}:
                    raise ValueError('Each tool sequence partition requires ten balanced target tools')
                lengths = [len(item['scorer']['expected']['steps']) for item in items]
                if lengths.count(2) != 10 or lengths.count(3) != 10:
                    raise ValueError('Tool sequence partitions require balanced two- and three-step tasks')
            elif len(counts) != 4 or set(counts.values()) != {5}:
                raise ValueError('Each tool partition requires four balanced target tools')
            if max(target_positions) - min(target_positions) > 1:
                raise ValueError('Tool target position must be balanced across available tools')
        if (names['practice'] & names['heldout'] or
                argument_keys['practice'] & argument_keys['heldout']):
            raise ValueError('Practice and held-out tool names and argument keys must be disjoint')
    return data


ARCHIVED_SUITE_FILES = {('challenge', '1.0.0'): 'archive/challenge-1.0.0.json',
                        ('challenge', '1.1.0'): 'archive/challenge-1.1.0.json',
                        ('tool-plan', '1.0.0'): 'archive/tool-plan-1.0.0.json'}


def load(suite='quick', version=None):
    if not isinstance(suite, str) or suite not in SUITE_COUNTS:
        raise ValueError('Choose quick, standard, challenge, tool-schema, tool-plan, or tool-sequence')
    if version is not None and not isinstance(version, str):
        raise ValueError('Unknown version for ability suite')
    archived = ARCHIVED_SUITE_FILES.get((suite, version)) if version is not None else None
    path = DATA / archived if archived is not None else DATA / (suite + '.json')
    with path.open('rb') as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Suite exceeds metadata limit')
    data = validate(decode(raw))
    if version is not None and data.get('version') != version:
        raise ValueError('Unknown version for ability suite')
    return data
