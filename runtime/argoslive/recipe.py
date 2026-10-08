"""Versioned, canonical Lab trial recipes for bounded instruction experiments.

Standard calibration runs have no extra response instructions (preset 'standard').
Instructed Lab experiments record a canonical preset, instruction hash, actual context,
output cap, temperature, seed, thinking mode, and request format.
Experiments affect only Lab test executions, never the agent's personal profile or personality.
"""
import copy
import hashlib
import re

SCHEMA = 'argos-recipe/1'
MAX_INSTRUCTION_LENGTH = 1024

# Reviewed public instruction presets.
PRESETS = {
    'standard': {
        'id': 'standard',
        'title': 'Standard calibration',
        'description': 'Standard prompt execution without additional response instructions',
        'instructions': None,
    },
    'concise': {
        'id': 'concise',
        'title': 'Strict format instructions',
        'description': 'Instructs the model to follow requested output format and omit extra prose',
        'instructions': 'Follow the requested output format; omit extra prose.',
    },
}

# Supported aliases for presets
ALIASES = {
    'format-strict': 'concise',
    'baseline': 'standard',
}


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
    actual_instructions = preset_def['instructions'] if instructions is None else instructions

    if preset_key == 'standard' and actual_instructions is not None:
        raise ValueError('Standard calibration cannot carry custom instructions')

    if actual_instructions is not None:
        if not isinstance(actual_instructions, str):
            raise ValueError('Instructions must be a string')
        if not (1 <= len(actual_instructions) <= MAX_INSTRUCTION_LENGTH):
            raise ValueError(f'Instructions must be 1 to {MAX_INSTRUCTION_LENGTH} characters')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in actual_instructions):
            raise ValueError('Instructions contain invalid control characters')

    if type(context) is not int or not (256 <= context <= 131072):
        raise ValueError('Context must be an integer between 256 and 131072 tokens')

    if type(output_cap) is not int or not (1 <= output_cap <= 131072):
        raise ValueError('Output cap must be an integer between 1 and 131072 tokens')

    if not isinstance(temperature, (int, float)) or not (0 <= temperature <= 2.0):
        raise ValueError('Temperature must be a number between 0 and 2.0')

    if type(seed) is not int or seed < 0:
        raise ValueError('Seed must be a non-negative integer')

    if thinking not in (True, False, None):
        raise ValueError('Thinking mode must be True, False, or None')

    if request_format not in ('generate', 'chat'):
        raise ValueError("Request format must be 'generate' or 'chat'")

    return {
        'schema': SCHEMA,
        'preset': preset_key,
        'instructions': actual_instructions,
        'instruction_hash': instruction_hash(actual_instructions),
        'context': context,
        'output_cap': output_cap,
        'temperature': float(temperature) if isinstance(temperature, (int, float)) else 0.0,
        'seed': seed,
        'thinking': thinking,
        'request_format': request_format,
    }


def validate(recipe):
    """Validate a canonical recipe dictionary. Raises ValueError if invalid."""
    if not isinstance(recipe, dict):
        raise ValueError('Recipe must be a dictionary')
    if recipe.get('schema') != SCHEMA:
        raise ValueError(f'Unsupported recipe schema: {recipe.get("schema")}')

    preset = recipe.get('preset')
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError(f'Unknown recipe preset: {preset}')

    instructions = recipe.get('instructions')
    if preset == 'standard' and instructions is not None:
        raise ValueError('Standard recipe must have None for instructions')

    if instructions is not None:
        if not isinstance(instructions, str) or not (1 <= len(instructions) <= MAX_INSTRUCTION_LENGTH):
            raise ValueError('Invalid recipe instructions')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in instructions):
            raise ValueError('Recipe instructions contain control characters')

    expected_hash = instruction_hash(instructions)
    if recipe.get('instruction_hash') != expected_hash:
        raise ValueError('Mismatched recipe instruction hash')

    context = recipe.get('context')
    if type(context) is not int or not (256 <= context <= 131072):
        raise ValueError('Invalid recipe context')

    output_cap = recipe.get('output_cap')
    if type(output_cap) is not int or not (1 <= output_cap <= 131072):
        raise ValueError('Invalid recipe output cap')

    temperature = recipe.get('temperature')
    if not isinstance(temperature, (int, float)) or not (0 <= temperature <= 2.0):
        raise ValueError('Invalid recipe temperature')

    seed = recipe.get('seed')
    if type(seed) is not int or seed < 0:
        raise ValueError('Invalid recipe seed')

    if recipe.get('thinking') not in (True, False, None):
        raise ValueError('Invalid recipe thinking mode')

    if recipe.get('request_format') not in ('generate', 'chat'):
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
        return validate(copy.deepcopy(spec))
    raise ValueError('Recipe specification must be a preset name, recipe dictionary, or None')
