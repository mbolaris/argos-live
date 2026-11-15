"""Console taxonomy and failure-code registry: one versioned source of truth.

`data/shakedown/taxonomy.json` (`argos-sim-taxonomy/1`) names the consoles and their
skill-map domains, the fault families, and every failure code with a plain label.
A code belongs to exactly one console, except `miss.unclassified`, which belongs to none.
Nothing here scores or renders.
"""
import copy
import functools
import json
from pathlib import Path
import re

from .. import skill_map

SCHEMA = 'argos-sim-taxonomy/1'
PATH = Path(__file__).resolve().parents[1] / 'data' / 'shakedown' / 'taxonomy.json'
UNCLASSIFIED = 'miss.unclassified'
LIMIT = 1024**2
ID = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
CODE_ID = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
CONSOLE_KEYS = {'id', 'label', 'domain', 'summary', 'codes'}
FAMILY_KEYS = {'id', 'label', 'console', 'summary', 'scorer_kinds', 'codes'}
CODE_KEYS = {'id', 'label'}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate key in taxonomy: {key}')
        result[key] = value
    return result


def _text(value, limit=200):
    return isinstance(value, str) and 0 < len(value) <= limit and value == value.strip() and '\n' not in value


def _ids(value, pattern, what):
    if not isinstance(value, list) or any(not isinstance(v, str) or not pattern.fullmatch(v) for v in value):
        raise ValueError(f'Invalid {what} list')
    if len(set(value)) != len(value):
        raise ValueError(f'Duplicate ID in {what} list')
    return value


def validate(data):
    """Return `data` when it is a well-formed taxonomy; raise ValueError naming the fault otherwise."""
    if (not isinstance(data, dict) or data.get('schema') != SCHEMA
            or set(data) != {'schema', 'version', 'domains', 'consoles', 'families', 'codes'}
            or not isinstance(data['version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+', data['version'])):
        raise ValueError('Invalid taxonomy header')
    known_domains = {domain['id'] for domain in skill_map.DOMAINS}
    domains = _ids(data['domains'], ID, 'domain')
    for domain in domains:
        if domain not in known_domains:
            raise ValueError(f'Unknown domain: {domain}')

    if not isinstance(data['codes'], list) or not isinstance(data['consoles'], list) or not isinstance(data['families'], list):
        raise ValueError('Invalid taxonomy lists')
    codes = set()
    for entry in data['codes']:
        if (not isinstance(entry, dict) or set(entry) != CODE_KEYS or not isinstance(entry['id'], str)
                or not CODE_ID.fullmatch(entry['id']) or not _text(entry['label'])):
            raise ValueError('Invalid failure code entry')
        if entry['id'] in codes:
            raise ValueError(f"Duplicate code ID: {entry['id']}")
        codes.add(entry['id'])
    if UNCLASSIFIED not in codes:
        raise ValueError(f'Taxonomy must define {UNCLASSIFIED}')

    consoles, owners = {}, {}
    for entry in data['consoles']:
        if (not isinstance(entry, dict) or set(entry) != CONSOLE_KEYS or not isinstance(entry['id'], str)
                or not ID.fullmatch(entry['id']) or not _text(entry['label'], 32) or not _text(entry['summary'])):
            raise ValueError('Invalid console entry')
        if entry['id'] in consoles:
            raise ValueError(f"Duplicate console ID: {entry['id']}")
        if entry['domain'] not in domains:
            raise ValueError(f"Unknown domain for console {entry['id']}: {entry['domain']}")
        for code in _ids(entry['codes'], CODE_ID, f"console {entry['id']} code"):
            if code not in codes:
                raise ValueError(f"Console {entry['id']} names unknown code: {code}")
            owners.setdefault(code, []).append(entry['id'])
        consoles[entry['id']] = entry
    if len({entry['label'] for entry in consoles.values()}) != len(consoles):
        raise ValueError('Duplicate console label')
    if owners.get(UNCLASSIFIED):
        raise ValueError(f'{UNCLASSIFIED} must belong to no console')
    for code in sorted(codes - {UNCLASSIFIED}):
        if len(owners.get(code, [])) != 1:
            raise ValueError(f'Code must be owned by exactly one console: {code}')

    families = set()
    for entry in data['families']:
        if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not ID.fullmatch(entry['id'])):
            raise ValueError('Invalid fault family entry')
        if entry['id'] in families:
            raise ValueError(f"Duplicate family ID: {entry['id']}")
        if entry.get('console') not in consoles:
            raise ValueError(f"Fault family has no known console: {entry['id']}")
        if set(entry) != FAMILY_KEYS or not _text(entry['label'], 64) or not _text(entry['summary']):
            raise ValueError(f"Invalid fault family entry: {entry['id']}")
        _ids(entry['scorer_kinds'], ID, f"family {entry['id']} scorer kind")
        for code in _ids(entry['codes'], CODE_ID, f"family {entry['id']} code"):
            if owners.get(code) != [entry['console']]:
                raise ValueError(f"Family {entry['id']} names a code its console does not own: {code}")
        families.add(entry['id'])
    return data


@functools.lru_cache(maxsize=1)
def _shipped():
    with PATH.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Taxonomy exceeds metadata limit')
    data = validate(json.loads(raw, object_pairs_hook=_pairs))
    owner = {code: entry['id'] for entry in data['consoles'] for code in entry['codes']}
    return {'data': data,
            'consoles': {entry['id']: entry for entry in data['consoles']},
            'families': {entry['id']: entry for entry in data['families']},
            'codes': {entry['id']: {**entry, 'console': owner.get(entry['id'])} for entry in data['codes']}}


def load():
    """The shipped, validated taxonomy. Each call returns its own copy."""
    return copy.deepcopy(_shipped()['data'])


def version():
    return _shipped()['data']['version']


def _entry(kind, what, value):
    entry = _shipped()[kind].get(value) if isinstance(value, str) else None
    if entry is None:
        raise ValueError(f'Unknown {what}: {value!r}')
    return copy.deepcopy(entry)


def console(console_id):
    """One console: id, label, domain, summary and the codes it owns."""
    return _entry('consoles', 'console', console_id)


def family(family_id):
    """One fault family: id, label, console, summary, scorer kinds and codes."""
    return _entry('families', 'fault family', family_id)


def code(code_id):
    """One failure code: id, plain label, and its owning console (None for `miss.unclassified`)."""
    return _entry('codes', 'failure code', code_id)


def console_ids():
    return tuple(_shipped()['consoles'])


def family_ids():
    return tuple(_shipped()['families'])


def code_ids():
    return tuple(_shipped()['codes'])
