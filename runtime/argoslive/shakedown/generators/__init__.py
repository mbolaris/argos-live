"""Pure, versioned generators and deterministic form assembly for Shakedown.

Generator implementations are registered by the SIM12/SIM13 family modules. A generator is a
pure ``(seed, tier) -> (item, card)`` function. The recipe, not the generator, assigns item IDs
and practice/sealed partitions. Generator output remains authoring data; callers must use the
fault-card public projection before showing cards outside the host process.
"""
from copy import deepcopy
import hashlib
import json
import re

from ... import ability
from .. import diagnose, fault

SCHEMA = 'argos-shakedown-form-recipe/1'
VERSION = re.compile(r'\d+\.\d+\.\d+')
SLUG = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
GENERATORS = {}


def register(name, version, function):
    """Register one named generator. Duplicate registrations are an error, never overrides."""
    if (not isinstance(name, str) or not SLUG.fullmatch(name)
            or not isinstance(version, str) or not VERSION.fullmatch(version)
            or not callable(function)):
        raise ValueError('Invalid generator registration')
    if name in GENERATORS:
        raise ValueError(f'Generator is already registered: {name}')
    GENERATORS[name] = (version, function)


def names():
    """Registered generator names in stable order."""
    return tuple(sorted(GENERATORS))


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def _recipe_entries(recipe):
    if (not isinstance(recipe, dict) or set(recipe) != {'schema', 'suite', 'version', 'items'}
            or recipe.get('schema') != SCHEMA or not isinstance(recipe.get('suite'), str)
            or not SLUG.fullmatch(recipe['suite']) or not isinstance(recipe.get('version'), str)
            or not VERSION.fullmatch(recipe['version']) or not isinstance(recipe.get('items'), list)
            or not recipe['items']):
        raise ValueError('Invalid Shakedown form recipe')
    entries = []
    for index, row in enumerate(recipe['items'], 1):
        if (not isinstance(row, dict) or set(row) != {'generator', 'seed', 'tier', 'partition'}
                or not isinstance(row.get('generator'), str) or not SLUG.fullmatch(row['generator'])
                or not isinstance(row.get('seed'), str) or not row['seed'] or len(row['seed']) > 128
                or type(row.get('tier')) is not int or row['tier'] not in fault.TIERS
                or row.get('partition') not in fault.PARTITIONS):
            raise ValueError(f'Invalid recipe item at position {index}')
        item_id = f"{'practice' if row['partition'] == 'practice' else 'heldout'}-{index:02d}"
        entries.append((item_id, row))
    return entries


def generate(name, seed, tier):
    """Call one registered pure generator and return detached item/card dictionaries."""
    if not isinstance(name, str) or not SLUG.fullmatch(name):
        raise ValueError('Invalid Shakedown generator name')
    if name not in GENERATORS:
        raise ValueError(f'Unknown Shakedown generator: {name!r}')
    if (not isinstance(seed, str) or not seed or seed != seed.strip() or len(seed) > 128
            or type(tier) is not int or tier not in fault.TIERS):
        raise ValueError('A generator needs a nonempty seed and tier 1, 2 or 3')
    version, function = GENERATORS[name]
    result = function(seed, tier)
    if (not isinstance(result, tuple) or len(result) != 2
            or not isinstance(result[0], dict) or not isinstance(result[1], dict)):
        raise ValueError(f'Generator {name} must return an item and a fault card')
    first = _json_bytes({'item': result[0], 'card': result[1]})
    repeated = function(seed, tier)
    if (not isinstance(repeated, tuple) or len(repeated) != 2
            or not isinstance(repeated[0], dict) or not isinstance(repeated[1], dict)
            or _json_bytes({'item': repeated[0], 'card': repeated[1]}) != first):
        raise ValueError(f'Generator {name} is not deterministic for this seed and tier')
    item, card = deepcopy(result[0]), deepcopy(result[1])
    item.pop('id', None)
    card.pop('item', None)
    card.pop('partition', None)
    card['generator'] = {'name': name, 'version': version, 'seed': seed}
    return item, card


def build_form(recipe):
    """Build a deterministic suite/sidecar pair from a recipe and registered generators.

    The recipe fixes partition and item order. Generator code cannot assign either. The output
    uses the existing ability suite and fault-card schemas; SIM14 registers original form names
    with the evaluation runner.
    """
    entries = _recipe_entries(recipe)
    items, cards = [], []
    for item_id, row in entries:
        item, card = generate(row['generator'], row['seed'], row['tier'])
        item['id'] = item_id
        card.update(item=item_id, tier=row['tier'], partition=row['partition'])
        items.append(item)
        cards.append(card)
    form = {'schema': 'argos-ability-suite/1', 'suite': recipe['suite'],
            'version': recipe['version'], 'license': 'MIT', 'source': 'original-argos-live',
            'omitted_categories': ['code-execution'], 'items': items}
    sidecar = {'schema': fault.SCHEMA, 'form': recipe['suite'],
               'form_version': recipe['version'], 'card_version': '1.0.0', 'cards': cards}
    fault.validate(sidecar, form)
    validate_generated(form, sidecar)
    return form, sidecar


def validate_generated(form, sidecar):
    """Check scorer fixtures and prove each planted wrong answer reaches its card diagnosis."""
    fault.validate(sidecar, form)
    cards = {entry['item']: entry for entry in sidecar['cards']}
    for item in form['items']:
        for field, outcome in (('reference', 'pass'), ('wrong', 'wrong_answer'),
                               ('malformed', 'format_error')):
            scored = ability.score(item, item.get(field))
            if scored['outcome'] != outcome:
                raise ValueError(f"Generated item {item['id']} has invalid {field} fixture")
        wrong = item['wrong']
        saved = {'outcome': 'wrong_answer', 'output': wrong}
        codes = diagnose.diagnose(cards[item['id']], item, saved)
        if codes == [fault.taxonomy.UNCLASSIFIED] or len(codes) != 1:
            raise ValueError(f"Generated item {item['id']} wrong fixture does not reach one intended code")
    return form


def build_bytes(recipe):
    """Return canonical suite bytes, sidecar bytes and their SHA-256 digests."""
    form, sidecar = build_form(recipe)
    form_bytes, sidecar_bytes = _json_bytes(form), _json_bytes(sidecar)
    return {'form': form_bytes, 'sidecar': sidecar_bytes,
            'form_sha256': hashlib.sha256(form_bytes).hexdigest(),
            'sidecar_sha256': hashlib.sha256(sidecar_bytes).hexdigest()}
