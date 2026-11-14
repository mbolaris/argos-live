"""Stable, privacy-preserving summaries of the build behind a saved run."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


UNKNOWN = 'not recorded'
_ID = re.compile(r'^[0-9a-f]{24}$')
_RECIPE_FIELDS = ('context', 'output_cap', 'temperature', 'seed', 'thinking', 'request_format')
_HARDWARE_FIELDS = ('cpu_model', 'cpu_cores', 'cpu_threads', 'memory_bytes', 'gpus',
                    'kernel', 'secure_boot')


def _recorded(value):
    return value if value is not None and value != '' else UNKNOWN


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _details(run):
    metadata = _mapping(run.get('metadata'))
    return _mapping(metadata.get('details'))


def _model_facts(run):
    details = _details(run)
    model_info = _mapping(_mapping(run.get('metadata')).get('model_info'))
    quantization = details.get('quantization_level') or details.get('quantization')
    parameter_size = details.get('parameter_size') or details.get('parameter_label')
    if quantization is None:
        for key, value in model_info.items():
            if key.endswith('.quantization_level'):
                quantization = value
                break
    if parameter_size is None:
        for key, value in model_info.items():
            if key.endswith('.parameter_size'):
                parameter_size = value
                break
    return _recorded(quantization), _recorded(parameter_size)


def _recipe(run):
    recipe = _mapping(run.get('recipe'))
    settings = _mapping(run.get('settings'))
    result = {}
    aliases = {'thinking': ('thinking', 'think'), 'request_format': ('request_format', 'format')}
    for field in _RECIPE_FIELDS:
        value = recipe.get(field)
        if value is None:
            for alias in aliases.get(field, (field,)):
                if alias in settings:
                    value = settings[alias]
                    break
        result[field] = _recorded(value)
    return result


def _cards(run):
    values = run.get('instruction_cards', run.get('enabled_instruction_cards'))
    if not isinstance(values, (list, tuple)):
        return UNKNOWN
    names = sorted({item for item in values if isinstance(item, str) and item})
    return names


def _hardware(run):
    hardware = _mapping(run.get('hardware'))
    cpu = _mapping(hardware.get('cpu'))
    ram = _mapping(hardware.get('ram'))
    gpus = hardware.get('gpus')
    if isinstance(gpus, list):
        gpus = [{key: _recorded(_mapping(gpu).get(key))
                 for key in ('name', 'vendor', 'vram_total_bytes')}
                for gpu in gpus if isinstance(gpu, dict)]
    else:
        gpus = UNKNOWN
    return {'cpu_model': _recorded(cpu.get('model')),
            'cpu_cores': _recorded(cpu.get('cores')),
            'cpu_threads': _recorded(cpu.get('threads')),
            'memory_bytes': _recorded(ram.get('total_bytes')),
            'gpus': gpus,
            'kernel': _recorded(hardware.get('kernel')),
            'secure_boot': _recorded(hardware.get('secure_boot'))}


def _canonical_facts(run):
    quantization, parameter_size = _model_facts(run)
    instruction_state = run.get('instructions_changed')
    if type(instruction_state) is not bool:
        instruction_state = UNKNOWN
    return {
        'model': _recorded(run.get('model')),
        'quantization': quantization,
        'parameter_size': parameter_size,
        'recipe': _recipe(run),
        'hardware': _hardware(run),
        'openclaw_version': _recorded(run.get('openclaw_version')),
        'ollama_version': _recorded(run.get('ollama_version')),
        'argos_version': _recorded(run.get('argos_version')),
        'instruction_cards': _cards(run),
        'instructions_changed': instruction_state,
        'tool_profile': _recorded(run.get('tool_profile')),
    }


def snapshot(run):
    """Return a deterministic public loadout without private hashes or paths.

    The manifest digest participates in the opaque ID so two manifests with the
    same model tag cannot collide, but the digest itself is never returned.
    """
    if not isinstance(run, dict):
        raise ValueError('A saved run must be an object')
    facts = _canonical_facts(run)
    identity = {'facts': facts, 'manifest_digest': run.get('manifest_digest')}
    encoded = json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return {'id': hashlib.sha256(encoded).hexdigest()[:24], **facts}


_LABELS = {
    'model': 'Model', 'quantization': 'Quantization', 'parameter_size': 'Parameter size',
    'context': 'Context', 'output_cap': 'Output cap', 'temperature': 'Temperature',
    'seed': 'Seed', 'thinking': 'Thinking mode', 'request_format': 'Request format',
    'cpu_model': 'CPU', 'cpu_cores': 'CPU cores', 'cpu_threads': 'CPU threads',
    'memory_bytes': 'Memory', 'gpus': 'GPU configuration', 'kernel': 'Kernel',
    'secure_boot': 'Secure Boot', 'openclaw_version': 'OpenClaw',
    'ollama_version': 'Ollama', 'argos_version': 'Argos',
    'instruction_cards': 'Instruction cards', 'instructions_changed': 'Instructions changed',
    'tool_profile': 'Tool profile',
}


def _display(value):
    if value == UNKNOWN:
        return UNKNOWN
    if isinstance(value, bool):
        return 'on' if value else 'off'
    if isinstance(value, list):
        return ', '.join(' '.join(str(part) for part in item.values()) if isinstance(item, dict)
                         else str(item) for item in value) if value else 'none'
    if isinstance(value, int) and value >= 1024 and value % 1024 == 0:
        return f'{value // 1024:,} KiB'
    return str(value)


def diff(a, b):
    """Describe recorded loadout changes from *a* to *b* in plain words."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        raise ValueError('Loadouts must be objects')
    changes = []
    for field in ('model', 'quantization', 'parameter_size', *_RECIPE_FIELDS,
                  *_HARDWARE_FIELDS, 'openclaw_version', 'ollama_version', 'argos_version',
                  'instruction_cards', 'instructions_changed', 'tool_profile'):
        if field in _RECIPE_FIELDS:
            before = _mapping(a.get('recipe')).get(field, UNKNOWN)
            after = _mapping(b.get('recipe')).get(field, UNKNOWN)
        elif field in _HARDWARE_FIELDS:
            before = _mapping(a.get('hardware')).get(field, UNKNOWN)
            after = _mapping(b.get('hardware')).get(field, UNKNOWN)
        else:
            before, after = a.get(field, UNKNOWN), b.get(field, UNKNOWN)
        if before != after:
            changes.append({'field': field, 'label': _LABELS[field],
                            'before': before, 'after': after,
                            'sentence': f'{_LABELS[field]} {_display(before)} to {_display(after)}.'})
    return changes


def _names_path(home=None):
    home = Path(home) if home is not None else Path.home()
    return home / '.local' / 'state' / 'argos-live' / 'shakedown-loadout-names.json'


def name(loadout_id, text, *, home=None):
    """Save an owner-given loadout name in the owner-only state directory."""
    if not isinstance(loadout_id, str) or not _ID.fullmatch(loadout_id):
        raise ValueError('Unknown loadout ID')
    if not isinstance(text, str):
        raise ValueError('Loadout name must be text')
    text = ' '.join(text.split())
    if not 1 <= len(text) <= 80:
        raise ValueError('Loadout name must contain 1 to 80 characters')
    root = Path(home).absolute() if home is not None else Path.home().absolute()
    path = _names_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise ValueError('Loadout name storage must not be a symlink')
    try:
        if path.exists() and path.stat().st_size > 128 * 1024:
            raise ValueError('Loadout name storage exceeds the size limit')
        records = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('Loadout name storage is unreadable') from exc
    if not isinstance(records, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                             for key, value in records.items()):
        raise ValueError('Loadout name storage is invalid')
    records[loadout_id] = text
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(records, stream, sort_keys=True, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    os.chmod(path.parent, 0o700)
    return text
