"""Fault-card sidecars: host-side meaning attached to the items of a form.

A sidecar (`argos-sim-fault/1`) is a file of fault cards for one exact form version. It adds a
console, a fault family, a tier, a partition and diagnostic matchers to each item without
changing the suite schema or the runner. Sidecars live in
`data/shakedown/sidecars/<form>-<version>.json`.

Everything in a card except what `public_card` returns stays in the host process: matcher
values, generator seeds and recovery prompts are authoring data, never a projection.
"""
import copy
import functools
import json
from pathlib import Path
import re

from .. import ability
from . import taxonomy

SCHEMA = 'argos-sim-fault/1'
SIDECARS = Path(__file__).resolve().parents[1] / 'data' / 'shakedown' / 'sidecars'
LIMIT = 1024**2
PARTITIONS = ('practice', 'sealed')
# Item ID prefixes that fix the partition, where a form uses them.
PREFIX_PARTITION = {'practice-': 'practice', 'heldout-': 'sealed'}
TIERS = (1, 2, 3)
# The closed matcher set of DESIGN 7.1. The engine that evaluates them is diagnose.py (SIM3).
MATCHERS = ('equals', 'choice-is', 'contains-token', 'numeric-delta', 'numeric-equals',
            'json-path-mismatch', 'tool-name-is', 'tool-arg-mismatch', 'sequence-violation',
            'reply-seconds-over')
FORM_SCHEMAS = ('argos-ability-suite/1',)
NAME = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
VERSION = re.compile(r'\d+\.\d+\.\d+')
SIDECAR_KEYS = {'schema', 'form', 'form_version', 'card_version', 'cards'}
CARD_REQUIRED = {'item', 'family', 'console', 'tier', 'partition', 'display', 'diagnostics'}
CARD_OPTIONAL = {'generator', 'recovery'}
PUBLIC_KEYS = ('item', 'family', 'console', 'tier', 'partition')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate key in fault-card sidecar: {key}')
        result[key] = value
    return result


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and value == value.strip()


def form_items(form):
    """Item IDs of a form, in order. Accepts an `argos-ability-suite/1` suite."""
    if (not isinstance(form, dict) or form.get('schema') not in FORM_SCHEMAS
            or not isinstance(form.get('suite'), str) or not isinstance(form.get('version'), str)
            or not isinstance(form.get('items'), list)):
        raise ValueError('Unsupported form for a fault-card sidecar')
    ids = [item.get('id') if isinstance(item, dict) else None for item in form['items']]
    if any(not isinstance(item_id, str) or not item_id for item_id in ids) or len(set(ids)) != len(ids):
        raise ValueError('Form items need distinct string IDs')
    return ids


def _validate_card(card, item, prefixed):
    """Check one card whose item is already known to belong to the form."""
    if set(card) - CARD_OPTIONAL != CARD_REQUIRED:
        raise ValueError(f'Fault card for item {item} has missing or unknown fields')
    if card['console'] not in taxonomy.console_ids():
        raise ValueError(f"Fault card for item {item} names unknown console: {card['console']!r}")
    # A retrofitted item may belong to no fault family; a named family must be a known one.
    if card['family'] is not None and card['family'] not in taxonomy.family_ids():
        raise ValueError(f"Fault card for item {item} names unknown family: {card['family']!r}")
    if type(card['tier']) is not int or card['tier'] not in TIERS:
        raise ValueError(f'Fault card for item {item} needs a tier of 1, 2 or 3')
    if card['partition'] not in PARTITIONS:
        raise ValueError(f"Fault card for item {item} needs partition 'practice' or 'sealed'")
    if prefixed:
        expected = next((part for prefix, part in PREFIX_PARTITION.items() if item.startswith(prefix)), None)
        if expected != card['partition']:
            raise ValueError(f"Partition mismatch for item {item}: card says {card['partition']}, "
                             f"the item ID says {expected or 'neither practice nor sealed'}")
    display = card['display']
    if (not isinstance(display, dict) or set(display) != {'family', 'brief'}
            or not _text(display['family'], 64) or not _text(display['brief'], 200)
            or '\n' in display['family'] or '\n' in display['brief']):
        raise ValueError(f'Fault card for item {item} needs a display family and a one-line brief')
    if not isinstance(card['diagnostics'], list):
        raise ValueError(f'Fault card for item {item} needs a diagnostics list')
    for entry in card['diagnostics']:
        if not isinstance(entry, dict) or set(entry) != {'code', 'when'}:
            raise ValueError(f'Fault card for item {item} has a malformed diagnostic')
        code = entry['code']
        if not isinstance(code, str) or code not in taxonomy.code_ids():
            raise ValueError(f'Fault card for item {item} names unknown code: {code!r}')
        if code == taxonomy.UNCLASSIFIED:
            raise ValueError(f'Fault card for item {item} may not assign {taxonomy.UNCLASSIFIED}; '
                             'the engine reports it when no matcher claims a miss')
        when = entry['when']
        if not isinstance(when, dict) or len(when) != 1:
            raise ValueError(f'Fault card for item {item} needs exactly one matcher per diagnostic')
        name = next(iter(when))
        if name not in MATCHERS:
            raise ValueError(f'Fault card for item {item} names unknown matcher: {name!r}')
    if 'generator' in card:
        generator = card['generator']
        if (not isinstance(generator, dict) or set(generator) != {'name', 'version', 'seed'}
                or not isinstance(generator['name'], str) or not NAME.fullmatch(generator['name'])
                or not isinstance(generator['version'], str) or not VERSION.fullmatch(generator['version'])
                or not _text(generator['seed'], 128)):
            raise ValueError(f'Fault card for item {item} has a malformed generator record')
    if 'recovery' in card:
        recovery = card['recovery']
        if not isinstance(recovery, dict) or set(recovery) != {'prompt'} or not _text(recovery['prompt'], 400):
            raise ValueError(f'Fault card for item {item} has a malformed recovery prompt')


def validate(sidecar, form):
    """Return `sidecar` when it covers every item of `form` exactly once with well-formed cards.

    Raises ValueError otherwise; a fault in one card names that card's item.
    """
    items = form_items(form)
    if (not isinstance(sidecar, dict) or sidecar.get('schema') != SCHEMA or set(sidecar) != SIDECAR_KEYS
            or not isinstance(sidecar['card_version'], str) or not VERSION.fullmatch(sidecar['card_version'])
            or not isinstance(sidecar['cards'], list)):
        raise ValueError('Invalid fault-card sidecar header')
    if sidecar['form'] != form['suite'] or sidecar['form_version'] != form['version']:
        raise ValueError(f"Fault-card sidecar is for {sidecar['form']} {sidecar['form_version']}, "
                         f"not {form['suite']} {form['version']}")
    known, seen = set(items), set()
    prefixed = any(item.startswith(tuple(PREFIX_PARTITION)) for item in items)
    for card in sidecar['cards']:
        item = card.get('item') if isinstance(card, dict) else None
        if not isinstance(item, str) or not item:
            raise ValueError('Fault card without an item ID')
        if item not in known:
            raise ValueError(f'Fault card for an item the form does not have: {item}')
        if item in seen:
            raise ValueError(f'More than one fault card for item {item}')
        seen.add(item)
        _validate_card(card, item, prefixed)
    for item in items:
        if item not in seen:
            raise ValueError(f'Missing fault card for item {item}')
    return sidecar


def _path(form, version, root):
    if (not isinstance(form, str) or not NAME.fullmatch(form)
            or not isinstance(version, str) or not VERSION.fullmatch(version)):
        raise ValueError('A fault-card sidecar is loaded by form name and exact version')
    return Path(root) / f'{form}-{version}.json'


@functools.lru_cache(maxsize=32)
def _shipped(form, version):
    return _read(form, version, None, SIDECARS)


def _read(form, version, suite, root):
    path = _path(form, version, root)
    try:
        with path.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
    except FileNotFoundError:
        raise ValueError(f'No fault-card sidecar for {form} {version}') from None
    if len(raw) > LIMIT:
        raise ValueError('Fault-card sidecar exceeds metadata limit')
    sidecar = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(sidecar, dict) or sidecar.get('form') != form or sidecar.get('form_version') != version:
        raise ValueError(f'Fault-card sidecar file does not describe {form} {version}')
    if suite is None:
        suite = ability.load(form, version)
    return validate(sidecar, suite)


def load(form, version, *, suite=None, root=None):
    """The validated sidecar for exactly this form version; ValueError when there is none.

    `suite` is the form it must cover; by default the shipped ability suite of that name and
    version. `root` overrides the sidecar directory (tests).
    """
    if suite is None and root is None:
        return copy.deepcopy(_shipped(form, version))
    return _read(form, version, suite, SIDECARS if root is None else root)


def card(form, version, item_id, *, suite=None, root=None):
    """The fault card of one item, with the sidecar's schema and card version attached."""
    sidecar = load(form, version, suite=suite, root=root)
    for entry in sidecar['cards']:
        if entry['item'] == item_id:
            return {'schema': SCHEMA, 'card_version': sidecar['card_version'], **entry}
    raise ValueError(f'No fault card for item {item_id!r} in {form} {version}')


def public_card(card):
    """What a spectator or the agent may see of a card: where it aims and its brief.

    Leaves out the matchers, the generator record and its seed, and the recovery prompt; says
    only whether a recovery attempt exists.
    """
    display = card.get('display') or {}
    return {**{key: card.get(key) for key in PUBLIC_KEYS},
            'display': {'family': display.get('family'), 'brief': display.get('brief')},
            'recovery': 'recovery' in card}


def public_sidecar(sidecar):
    """The public projection of a whole sidecar, cards in file order."""
    return {'schema': SCHEMA, 'form': sidecar.get('form'), 'form_version': sidecar.get('form_version'),
            'card_version': sidecar.get('card_version'),
            'cards': [public_card(entry) for entry in sidecar.get('cards') or []]}
