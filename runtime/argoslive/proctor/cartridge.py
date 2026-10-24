"""Bounded, validated, immutable assessment content. No imported code executes."""
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from ..ability import decode

DIRECTORY = Path(__file__).parent
MAX_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 1024
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z')
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\Z')
RATIONAL = re.compile(r'([+-]?[0-9]+)[ \t]*/[ \t]*([+-]?[0-9]+)\Z')
AIDS = {'calculator', 'reference_sheet'}
JSON_ANSWER_LIMIT = 4096
SCHEMA_TYPES = {'object', 'array', 'string', 'integer', 'boolean', 'null'}


def json_text(value):
    """Argos JSON encoding, deliberately not an RFC 8785 implementation."""
    result = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if len(result.encode('utf-8')) > MAX_BYTES:
        raise ValueError('JSON exceeds cartridge limit')
    return result


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('Expected a bounded identifier')
    return value


def valid_answer(item, answer):
    if not isinstance(answer, str):
        return False
    if item['response_type'] == 'mcq_single':
        return len(answer) <= 128 and answer in item['choices']
    if item['response_type'] == 'numeric_grid':
        return len(answer) <= 128 and numeric_value(answer) is not None
    try:
        answer_size = len(answer.encode('utf-8'))
    except UnicodeError:
        return False
    if answer_size > JSON_ANSWER_LIMIT:
        return False
    try:
        value = _decode_json_object(answer)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False
    return _matches_schema(value, item['schema'])


def _decode_json_object(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('Duplicate JSON object key')
            result[key] = item
        return result
    parsed = json.loads(value, object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    if not isinstance(parsed, dict):
        raise ValueError('Expected a JSON object')
    return parsed


def _matches_schema(value, schema, depth=0):
    if depth > 8 or not isinstance(schema, dict):
        return False
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, dict) or len(value) > 32:
            return False
        properties = schema.get('properties', {})
        if any(key not in properties for key in value):
            return False
        if any(key not in value for key in schema.get('required', [])):
            return False
        return all(_matches_schema(item, properties[key], depth + 1) for key, item in value.items())
    if kind == 'array':
        return (isinstance(value, list) and len(value) <= 64 and
                all(_matches_schema(item, schema['items'], depth + 1) for item in value))
    if kind == 'string':
        return isinstance(value, str) and len(value) <= schema.get('maxLength', JSON_ANSWER_LIMIT)
    if kind == 'integer':
        return type(value) is int
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'null':
        return value is None
    return False


def _validate_schema(schema, depth=0):
    if depth > 8 or not isinstance(schema, dict) or schema.get('type') not in SCHEMA_TYPES:
        raise ValueError('Invalid structured-answer schema')
    kind = schema['type']
    allowed = {'type'}
    if kind == 'object':
        allowed |= {'properties', 'required'}
        properties = schema.get('properties')
        required = schema.get('required')
        if (not isinstance(properties, dict) or len(properties) > 32 or
                not isinstance(required, list) or len(required) > len(properties) or
                any(not isinstance(k, str) for k in required) or
                len(set(required)) != len(required) or any(k not in properties for k in required)):
            raise ValueError('Invalid structured object schema')
        for key, child in properties.items():
            if not isinstance(key, str) or not key or len(key) > 96:
                raise ValueError('Invalid structured property name')
            _validate_schema(child, depth + 1)
    elif kind == 'array':
        allowed.add('items')
        _validate_schema(schema.get('items'), depth + 1)
    elif kind == 'string':
        allowed.add('maxLength')
        if type(schema.get('maxLength', JSON_ANSWER_LIMIT)) is not int or not 0 <= schema.get('maxLength', JSON_ANSWER_LIMIT) <= JSON_ANSWER_LIMIT:
            raise ValueError('Invalid structured string bound')
    elif kind in {'integer', 'boolean', 'null'}:
        pass
    if set(schema) - allowed:
        raise ValueError('Unsupported structured-answer schema keyword')


def _json_equal(left, right):
    return json_text(left) == json_text(right)


def numeric_value(answer):
    """Parse one exact decimal or rational value; never evaluate expressions."""
    if not isinstance(answer, str) or len(answer) > 128:
        return None
    if NUMBER.fullmatch(answer):
        return Fraction(Decimal(answer))
    match = RATIONAL.fullmatch(answer)
    if not match:
        return None
    numerator, denominator = (int(value) for value in match.groups())
    if denominator == 0:
        return None
    return Fraction(numerator, denominator)


def correct_answer(item, answer):
    if not valid_answer(item, answer):
        return False
    if item['response_type'] == 'numeric_grid':
        return numeric_value(answer) == numeric_value(item['correct'])
    if item['response_type'] == 'json_object':
        try:
            return _json_equal(_decode_json_object(answer), _decode_json_object(item['correct']))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return False
    return answer == item['correct']


def validate(conn):
    """Validate all rows, routing coverage, reachability, and supported scorers."""
    cartridge_version = conn.execute('PRAGMA user_version').fetchone()[0]
    if cartridge_version not in (1, 2):
        raise ValueError('Unsupported cartridge version')
    if [r[0] for r in conn.execute('PRAGMA integrity_check')] != ['ok']:
        raise ValueError('Invalid cartridge integrity')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Cartridge foreign key violations')
    manifests = conn.execute('SELECT * FROM manifest').fetchall()
    if len(manifests) != 1:
        raise ValueError('Expected exactly one cartridge manifest')
    manifest = dict(manifests[0])
    identifier(manifest['cartridge_id'])
    if any(not isinstance(manifest[k], str) or not 0 < len(manifest[k]) <= 4096 for k in ('title', 'version')):
        raise ValueError('Invalid cartridge metadata')
    if manifest['calibration_status'] != 'uncalibrated':
        raise ValueError('Only uncalibrated cartridges are supported in v1')
    forms = {r['form_id']: dict(r) for r in conn.execute('SELECT * FROM forms')}
    modules = {r['module_id']: dict(r) for r in conn.execute('SELECT * FROM modules')}
    items = {r['item_id']: dict(r) for r in conn.execute('SELECT * FROM items')}
    if cartridge_version == 1:
        for item in items.values():
            item['schema_json'] = '{}'
    if not forms or not modules or len(forms) > 32 or len(modules) > 128 or len(items) > MAX_ITEMS:
        raise ValueError('Cartridge size outside supported bounds')
    for item_id, item in items.items():
        identifier(item_id)
        if not isinstance(item['prompt'], str) or not 0 < len(item['prompt']) <= 16384:
            raise ValueError('Invalid item prompt')
        if not isinstance(item['domain'], str) or not 0 < len(item['domain']) <= 96:
            raise ValueError('Invalid item domain')
        if item['response_type'] not in ('mcq_single', 'numeric_grid', 'json_object'):
            raise ValueError('Unsupported response type; only choice, numeric and bounded JSON grading are enabled')
        choices = decode(item.pop('choices_json'))
        schema = decode(item.pop('schema_json'))
        if not isinstance(choices, dict):
            raise ValueError('Expected a choice mapping')
        if item['response_type'] == 'mcq_single':
            if not 2 <= len(choices) <= 8 or any(k not in 'ABCDEFGH' or len(k) != 1
                                                or not isinstance(v, str) or not 0 < len(v) <= 4096
                                                for k, v in choices.items()):
                raise ValueError('Invalid choices')
        elif choices:
            raise ValueError('Numeric questions must not carry choices')
        item['choices'] = choices
        if item['response_type'] == 'json_object':
            _validate_schema(schema)
            if schema['type'] != 'object':
                raise ValueError('Structured answers require an object schema')
            item['schema'] = schema
        else:
            if schema:
                raise ValueError('Only structured-answer items may declare a schema')
            item['schema'] = {}
        if not valid_answer(item, item['correct']):
            raise ValueError('Answer key violates response contract')
    for form_id, form in forms.items():
        identifier(form_id)
        members = {k: v for k, v in modules.items() if v['form_id'] == form_id}
        for mod_id, module in members.items():
            identifier(mod_id)
            aids = decode(module.pop('aids_json'))
            if (not isinstance(aids, list) or any(not isinstance(a, str) or a not in AIDS for a in aids)
                    or len(set(aids)) != len(aids)):
                raise ValueError('Unsupported or duplicate aid')
            module['aids'] = aids
            module['items'] = sorted((i for i in items.values() if i['module_id'] == mod_id),
                                     key=lambda i: i['position'])
            if not module['items'] or [i['position'] for i in module['items']] != list(range(1, len(module['items']) + 1)):
                raise ValueError('Items must have contiguous positions')
            rules = [dict(r) for r in conn.execute('SELECT * FROM routes WHERE module_id=? ORDER BY minimum', (mod_id,))]
            minimum = 0
            for rule in rules:
                if rule['form_id'] != form_id or rule['minimum'] != minimum or rule['maximum'] < minimum:
                    raise ValueError('Routing gap or overlap')
                minimum = rule['maximum'] + 1
                target = rule['next_module_id']
                if target is not None and (target not in members or members[target]['ordinal'] <= module['ordinal']):
                    raise ValueError('Routing must stay within a form and move forward')
            if minimum != len(module['items']) + 1:
                raise ValueError('Routing must cover every possible raw score')
            module['routes'] = rules
        reached = set()
        pending = [form['entry_module_id']]
        while pending:
            mod_id = pending.pop()
            if mod_id in reached:
                continue
            if mod_id not in members:
                raise ValueError('Invalid entry module')
            reached.add(mod_id)
            pending.extend(r['next_module_id'] for r in members[mod_id]['routes'] if r['next_module_id'] is not None)
        if reached != set(members):
            raise ValueError('Unreachable module')
    # Disabled FK enforcement must not allow unvalidated orphan rows to disappear.
    if any(m['form_id'] not in forms for m in modules.values()) or any(i['module_id'] not in modules for i in items.values()):
        raise ValueError('Orphan content')
    return manifest, forms, modules, items


class Cartridge:
    """Load a pinned byte snapshot, avoiding mutable paths during an assessment."""
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('Cartridge must be a bounded regular file')
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Oversized cartridge')
        self.digest = hashlib.sha256(data).hexdigest()
        conn = sqlite3.connect(':memory:')
        try:
            conn.deserialize(data)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA trusted_schema=OFF')
            conn.execute('PRAGMA query_only=ON')
            self.manifest, self.forms, self.modules, self.items = validate(conn)
        finally:
            conn.close()


def compile_cartridge(source, destination):
    """Compile trusted JSON definitions to a new file; never overwrite a cartridge."""
    # Bound and copy the definition before accessing any nested values.
    source = decode(json_text(source))
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        conn.executescript((DIRECTORY / 'cartridge.sql').read_text(encoding='utf-8'))
        with conn:
            m = source['manifest']
            if type(m['abort_on_timeout']) is not bool:
                raise ValueError('abort_on_timeout must be a boolean')
            conn.execute('INSERT INTO manifest VALUES (?,?,?,?,?,?,?)',
                         (m['cartridge_id'], m['version'], m['title'], m['content_origin'],
                          m['calibration_status'], m['start_window_ms'], int(m['abort_on_timeout'])))
            for form in source['forms']:
                conn.execute('INSERT INTO forms VALUES (?,?)', (form['form_id'], form['entry_module_id']))
                for module in form['modules']:
                    mod_id = module['module_id']
                    conn.execute('INSERT INTO modules VALUES (?,?,?,?,?,?)',
                                 (mod_id, form['form_id'], module['ordinal'], module['duration_ms'],
                                  module['break_ms'], json_text(module['aids'])))
                    for i in module['items']:
                        conn.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?)',
                                     (i['item_id'], mod_id, i['position'], i['domain'], i['prompt'],
                                      i['response_type'], json_text(i['choices']),
                                      json_text(i.get('schema', {})), i['correct']))
                    for r in module['routes']:
                        conn.execute('INSERT INTO routes VALUES (?,?,?,?,?)',
                                     (mod_id, form['form_id'], r['minimum'], r['maximum'], r['next_module_id']))
        validate(conn)
        data = conn.serialize()
        if len(data) > MAX_BYTES:
            raise ValueError('Compiled cartridge is too large')
        destination = Path(destination)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.proctor-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic publication without replacement; a reader never sees partial bytes.
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink()
    finally:
        conn.close()
