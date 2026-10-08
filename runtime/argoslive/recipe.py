"""Versioned, canonical Lab trial recipes for bounded instruction experiments.

Standard calibration runs have no extra response instructions (preset 'standard').
Instructed Lab experiments record a canonical preset, instruction hash, actual context,
output cap, temperature, seed, thinking mode, and request format.
Experiments affect only Lab test executions, never the agent's personal profile or personality.
"""
import copy
import hashlib

SCHEMA = 'argos-recipe/1'
MAX_INSTRUCTION_LENGTH = 1024

CANONICAL_KEYS = {
    'schema',
    'preset',
    'instructions',
    'instruction_hash',
    'context',
    'output_cap',
    'temperature',
    'seed',
    'thinking',
    'request_format',
}

PRESET_CONCISE_INSTRUCTIONS = 'Follow the requested output format; omit extra prose.'
PRESET_CONCISE_HASH = hashlib.sha256(PRESET_CONCISE_INSTRUCTIONS.encode('utf-8')).hexdigest()

# Reviewed public instruction presets with exact canonical text and hashes.
PRESETS = {
    'standard': {
        'id': 'standard',
        'title': 'Standard calibration',
        'description': 'Standard prompt execution without additional response instructions',
        'instructions': None,
        'instruction_hash': None,
    },
    'concise': {
        'id': 'concise',
        'title': 'Strict format instructions',
        'description': 'Instructs the model to follow requested output format and omit extra prose',
        'instructions': PRESET_CONCISE_INSTRUCTIONS,
        'instruction_hash': PRESET_CONCISE_HASH,
    },
}

# Supported aliases for presets
ALIASES = {
    'format-strict': 'concise',
    'baseline': 'standard',
}

SUPPORTED_CONTEXTS = (2048, 4096)
SUPPORTED_OUTPUT_CAP = 128
SUPPORTED_TEMPERATURE = 0.0
SUPPORTED_SEED = 1
SUPPORTED_THINKING = False
SUPPORTED_REQUEST_FORMAT = 'generate'


def instruction_hash(text):
    """Return the SHA-256 hex digest of canonical instruction text, or None."""
    if text is None:
        return None
    if not isinstance(text, str):
        raise ValueError('Instruction text must be a string or None')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def canonical(preset='standard', *, instructions=None, context=2048, output_cap=128,
              temperature=0, seed=1, thinking=False, request_format='generate'):
    """Create a validated, canonical recipe dictionary."""
    preset_key = ALIASES.get(preset, preset)
    if not isinstance(preset_key, str) or preset_key not in PRESETS:
        raise ValueError(f'Unknown recipe preset: {preset}')

    preset_def = PRESETS[preset_key]

    # Enforce reviewed preset allowlist: no custom instructions in this slice
    if instructions is not None and instructions != preset_def['instructions']:
        raise ValueError('Custom instructions are not supported; choose a reviewed preset')

    actual_instructions = preset_def['instructions']
    expected_hash = preset_def['instruction_hash']

    # Recorded recipes must match execution in this slice
    if context not in SUPPORTED_CONTEXTS:
        raise ValueError(f'Unsupported recipe deviation: context must be in {SUPPORTED_CONTEXTS} in this slice')

    if output_cap != SUPPORTED_OUTPUT_CAP:
        raise ValueError(f'Unsupported recipe deviation: output cap must be {SUPPORTED_OUTPUT_CAP} in this slice')

    if not isinstance(temperature, (int, float)) or float(temperature) != SUPPORTED_TEMPERATURE:
        raise ValueError(f'Unsupported recipe deviation: temperature must be {SUPPORTED_TEMPERATURE} in this slice')

    if seed != SUPPORTED_SEED:
        raise ValueError(f'Unsupported recipe deviation: seed must be {SUPPORTED_SEED} in this slice')

    if thinking is not SUPPORTED_THINKING:
        raise ValueError('Unsupported recipe deviation: thinking experiments are deferred to J6c')

    if request_format != SUPPORTED_REQUEST_FORMAT:
        raise ValueError(f"Unsupported recipe deviation: request format must be '{SUPPORTED_REQUEST_FORMAT}' in this slice")

    return {
        'schema': SCHEMA,
        'preset': preset_key,
        'instructions': actual_instructions,
        'instruction_hash': expected_hash,
        'context': context,
        'output_cap': output_cap,
        'temperature': float(temperature),
        'seed': seed,
        'thinking': thinking,
        'request_format': request_format,
    }


def validate(recipe):
    """Validate a canonical recipe dictionary. Raises ValueError if invalid."""
    if not isinstance(recipe, dict):
        raise ValueError('Recipe must be a dictionary')

    if set(recipe.keys()) != CANONICAL_KEYS:
        raise ValueError(f'Recipe contains unexpected or missing fields: {set(recipe.keys()) ^ CANONICAL_KEYS}')

    if recipe.get('schema') != SCHEMA:
        raise ValueError(f'Unsupported recipe schema: {recipe.get("schema")}')

    preset = recipe.get('preset')
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError(f'Unknown recipe preset: {preset}')

    preset_def = PRESETS[preset]

    # Exact preset text and hash required
    if recipe.get('instructions') != preset_def['instructions']:
        raise ValueError('Recipe instructions must match the reviewed preset exactly')

    if recipe.get('instruction_hash') != preset_def['instruction_hash']:
        raise ValueError('Mismatched recipe instruction hash')

    context = recipe.get('context')
    if context not in SUPPORTED_CONTEXTS:
        raise ValueError('Invalid recipe context')

    if recipe.get('output_cap') != SUPPORTED_OUTPUT_CAP:
        raise ValueError('Invalid recipe output cap')

    temp = recipe.get('temperature')
    if not isinstance(temp, (int, float)) or float(temp) != SUPPORTED_TEMPERATURE:
        raise ValueError('Invalid recipe temperature')

    if recipe.get('seed') != SUPPORTED_SEED:
        raise ValueError('Invalid recipe seed')

    if recipe.get('thinking') is not SUPPORTED_THINKING:
        raise ValueError('Invalid recipe thinking mode')

    if recipe.get('request_format') != SUPPORTED_REQUEST_FORMAT:
        raise ValueError('Invalid recipe request format')

    return recipe


def resolve(spec, *, context=2048, output_cap=128, thinking=False):
    """Resolve a recipe specification (None, preset name, or dict) to a canonical recipe."""
    if spec is None:
        return canonical('standard', context=context, output_cap=output_cap, thinking=thinking)
    if isinstance(spec, str):
        preset_key = ALIASES.get(spec, spec)
        if preset_key not in PRESETS:
            raise ValueError(f'Unknown recipe preset: {spec}')
        return canonical(preset_key, context=context, output_cap=output_cap, thinking=thinking)
    if isinstance(spec, dict):
        validated = validate(copy.deepcopy(spec))
        if context is not None and validated['context'] != context:
            raise ValueError(f'Recipe context ({validated["context"]}) does not match runner context ({context})')
        return validated
    raise ValueError('Recipe specification must be a preset name, recipe dictionary, or None')


def is_standard(value):
    """Return True if value (recipe dict, benchmark run, or None) represents standard calibration."""
    if value is None:
        return True
    if isinstance(value, dict) and 'recipe' in value:
        rec = value['recipe']
    elif isinstance(value, dict) and value.get('schema') == SCHEMA:
        rec = value
    else:
        return True
    if rec is None:
        return True
    return rec.get('preset') == 'standard' and rec.get('instructions') is None


def list_presets():
    """Return a list of public reviewed instruction presets."""
    return [
        {
            'id': p['id'],
            'title': p['title'],
            'description': p['description'],
            'instructions': p['instructions'],
            'instruction_hash': p['instruction_hash'],
        }
        for p in PRESETS.values()
    ]
