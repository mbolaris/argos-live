"""Privacy-filtered local JSON, SVG and optional PNG Shakedown exports."""
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import secrets
import re

from .. import storage
from . import loadout


_ID = re.compile(r'^[0-9a-f]{32}$')
_FORMATS = {'json', 'svg', 'png'}
_MAX_EXPORT_BYTES = 2 * 1024 * 1024
_SAFE_MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$')
_SAFE_VERSION = re.compile(r'^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){0,4}$')
_SAFE_DATE = re.compile(r'^\d{4}-\d\d-\d\d(?:T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d))?$')
_SUSPICIOUS = re.compile(r'(?:[/\\]|\b(?:token|session|key|password|secret|fingerprint|sha256|path)\b|\b[0-9a-f]{32,}\b)', re.I)


def _safe_text(value, fallback):
    if not isinstance(value, str):
        return fallback
    value = ' '.join(value.split())
    if not value or len(value) > 120 or _SUSPICIOUS.search(value):
        return fallback
    return value


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _hardware_line(hardware):
    if not isinstance(hardware, dict):
        return 'Hardware not recorded'
    cpu = hardware.get('cpu') if isinstance(hardware.get('cpu'), dict) else {}
    ram = hardware.get('ram') if isinstance(hardware.get('ram'), dict) else {}
    gpus = hardware.get('gpus') if isinstance(hardware.get('gpus'), list) else []
    parts = []
    cpu_model = _safe_text(cpu.get('model'), '')
    if cpu_model:
        parts.append(cpu_model)
    names = [_safe_text(gpu.get('name'), '') for gpu in gpus if isinstance(gpu, dict)]
    names = [name for name in names if name]
    if names:
        parts.append(', '.join(names))
    memory = ram.get('total_bytes')
    if type(memory) is int and memory > 0:
        parts.append(f'{memory / 1024**3:.0f} GiB RAM')
    return ' · '.join(parts) if parts else 'Hardware not recorded'


def _public_cell(cell, name):
    slice_name = cell.get('slice')
    if slice_name not in ('quick', 'standard', 'full'):
        slice_name = 'full'
    suite_version = cell.get('suite_version')
    if not isinstance(suite_version, str) or not _SAFE_VERSION.fullmatch(suite_version):
        suite_version = 'version unavailable'
    slice_version = cell.get('slice_version')
    if not isinstance(slice_version, str) or not _SAFE_VERSION.fullmatch(slice_version):
        slice_version = None
    created = cell.get('date')
    if not isinstance(created, str) or not _SAFE_DATE.fullmatch(created):
        created = None
    state = cell.get('state')
    if state not in ('completed', 'cancelled', 'failed', 'running'):
        state = 'unknown'
    value = {'build': name, 'slice': slice_name,
             'suite_version': suite_version, 'slice_version': slice_version,
             'date': created, 'state': state, 'complete': bool(cell.get('complete', True)),
             'footnotes': [_safe_text(text, 'note') for text in cell.get('footnotes', [])
                           if isinstance(text, str)],
             'personal_best': bool(cell.get('personal_best'))}
    for key in ('correct', 'total', 'percent', 'value', 'count'):
        data = cell.get(key)
        if _finite_number(data):
            value[key] = data
    interval = cell.get('interval')
    if (isinstance(interval, list) and len(interval) == 2 and
            all(_finite_number(part) for part in interval)):
        value['interval'] = interval
    return value


class Exporter:
    def __init__(self, store, scorecard, *, home=None):
        self.store = store
        self.scorecard = scorecard
        self.home = Path(home) if home is not None else Path.home()
        self.root = storage.safe_local(self.home / '.local/share/argos-live/shakedown-exports')

    def payload(self):
        card = self.scorecard.scorecard()
        records = self.store.list().get('runs', [])
        candidates = []
        for item in records:
            try:
                run = self.store.load(item['id'])
                hardware = run.get('hardware')
                if isinstance(hardware, dict) and any(key in hardware for key in ('cpu', 'ram', 'gpus')):
                    candidates.append(run)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        candidates.sort(key=lambda run: (run.get('created') or '', run.get('id') or ''), reverse=True)
        latest = candidates[0] if candidates else None
        loadouts = []
        names = {}
        for item in card.get('loadouts', []):
            model = item.get('model')
            model_tag = model.removeprefix('ollama/') if isinstance(model, str) and model.startswith('ollama/') else ''
            safe_model = model_tag if _SAFE_MODEL.fullmatch(model_tag) else 'Model not recorded'
            context_fallback = item.get('recipe', {}).get('context') if isinstance(item.get('recipe'), dict) else None
            default_name = safe_model + (f' · {context_fallback}' if type(context_fallback) is int else '')
            name = _safe_text(item.get('name'), default_name)
            names[item['id']] = name
            recipe = item.get('recipe') if isinstance(item.get('recipe'), dict) else {}
            summary_parts = [safe_model]
            for key in ('quantization', 'parameter_size'):
                safe_value = _safe_text(item.get(key), '')
                if safe_value and safe_value != loadout.UNKNOWN:
                    summary_parts.append(safe_value)
            context = recipe.get('context')
            if type(context) is int and 0 <= context <= 1_000_000:
                summary_parts.append(f'{context:,} context')
            safe_recipe = {}
            for key in ('context', 'output_cap', 'seed'):
                value = recipe.get(key)
                if type(value) is int and 0 <= value <= 2**53 - 1:
                    safe_recipe[key] = value
            temperature = recipe.get('temperature')
            if _finite_number(temperature):
                safe_recipe['temperature'] = temperature
            thinking = recipe.get('thinking')
            if type(thinking) is bool or isinstance(thinking, str) and _SAFE_MODEL.fullmatch(thinking):
                safe_recipe['thinking'] = thinking
            request_format = recipe.get('request_format')
            if isinstance(request_format, str) and _SAFE_MODEL.fullmatch(request_format):
                safe_recipe['request_format'] = request_format
            loadouts.append({'name': name, 'summary': ' · '.join(summary_parts),
                             'model': safe_model, 'quantization': _safe_text(item.get('quantization'), 'not recorded'),
                             'parameter_size': _safe_text(item.get('parameter_size'), 'not recorded'),
                             'recipe': safe_recipe})
        rows = []
        for row in card.get('rows', []):
            cells = []
            for loadout_id, cell in row.get('cells', {}).items():
                name = names.get(loadout_id)
                if name is None:
                    continue
                cells.append(_public_cell(cell, name))
            footnotes = list(dict.fromkeys(note for cell in cells for note in cell['footnotes']))
            kind = row.get('kind') if row.get('kind') in ('ability', 'speed') else 'ability'
            subset = row.get('partition') or row.get('size') or 'all'
            rows.append({'label': _safe_text(row.get('label'), 'Scorecard row'), 'kind': kind,
                         'subset': _safe_text(subset, 'all'),
                         'metric': _safe_text(row.get('metric'), 'score'),
                         'unit': _safe_text(row.get('unit'), ''),
                         'higher_is_better': row.get('higher_is_better') if type(row.get('higher_is_better')) is bool else None,
                         'footnotes': footnotes, 'cells': cells})
        return {'schema': 'argos-shakedown-export/1',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'hardware_line': _hardware_line(latest.get('hardware') if latest else None),
                'loadouts': loadouts, 'rows': rows,
                'counts': {'loadouts': len(loadouts), 'rows': len(rows)}}

    @staticmethod
    def svg(payload):
        rows = payload['rows']
        loadouts = payload['loadouts']
        width = max(720, 360 + 220 * len(loadouts))
        height = 190 + 68 * len(rows)
        esc = lambda value: html.escape(str(value), quote=True)
        bits = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="#0b1117"/>',
                '<style>text{font-family:Arial,sans-serif;fill:#edf3f6}.muted{fill:#aebdc6}.accent{fill:#80dfc7}.line{stroke:#344654}</style>',
                '<text x="28" y="42" font-size="26" font-weight="700">Argos Shakedown scorecard</text>',
                f'<text x="28" y="68" font-size="13" class="muted">{esc(payload["hardware_line"])} · {esc(payload["created_at"][:10])}</text>']
        x_positions = [350 + 220 * index for index in range(len(loadouts))]
        x_by_name = {item['name']: x_positions[index] for index, item in enumerate(loadouts)}
        for index, item in enumerate(loadouts):
            bits.append(f'<text x="{x_positions[index]}" y="106" font-size="14" font-weight="700">{esc(item["name"][:30])}</text>')
            bits.append(f'<text x="{x_positions[index]}" y="126" font-size="11" class="muted">{esc(item["summary"][:44])}</text>')
        for index, row in enumerate(rows):
            y = 160 + 68 * index
            bits.append(f'<path d="M 24 {y} H {width - 24}" class="line"/>')
            bits.append(f'<text x="28" y="{y + 22}" font-size="12" font-weight="700">{esc(row["label"][:42])}</text>')
            for cell in row['cells']:
                x = x_by_name.get(cell.get('build'), 350)
                if 'correct' in cell:
                    label = f'{cell["correct"]}/{cell["total"]} · {cell.get("percent", 0):.1f}%'
                elif 'value' in cell:
                    label = f'{cell["value"]:.2f} {row.get("unit") or ""}'.strip()
                    if cell.get('count') is not None:
                        label += f' · n={cell["count"]}'
                else:
                    label = cell.get('state') or 'No result'
                if cell.get('personal_best'):
                    label += ' · Personal best'
                bits.append(f'<text x="{x}" y="{y + 22}" font-size="12" class="accent">{esc(label)}</text>')
                if cell.get('interval'):
                    low, high = cell['interval']
                    bits.append(f'<text x="{x}" y="{y + 39}" font-size="10" class="muted">95% interval {low:.1f}–{high:.1f}%</text>')
                footnotes = cell.get('footnotes') or []
                if footnotes:
                    bits.append(f'<text x="{x}" y="{y + 54}" font-size="9" class="muted">Footnotes: {esc(", ".join(footnotes))}</text>')
            bits.append(f'<text x="28" y="{y + 42}" font-size="10" class="muted">{esc(row.get("subset", "all"))}</text>')
        bits.append(f'<text x="28" y="{height - 18}" font-size="10" class="muted">Counts and intervals describe saved local runs. Subset rows are not official benchmark scores.</text>')
        bits.append('</svg>')
        return '\n'.join(bits)

    @staticmethod
    def _write(path, raw):
        if len(raw) > _MAX_EXPORT_BYTES:
            raise ValueError('Shakedown export exceeds the size limit')
        temporary = path.parent / ('.export-' + secrets.token_hex(16))
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def create(self):
        payload = self.payload()
        svg = self.svg(payload).encode('utf-8')
        json_bytes = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        ident = secrets.token_hex(16)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        base = f'shakedown-{stamp}-{ident}'
        self._write(storage.safe_local(self.root / (base + '.json')), json_bytes)
        self._write(storage.safe_local(self.root / (base + '.svg')), svg)
        png_available = False
        try:
            import cairosvg
            png = cairosvg.svg2png(bytestring=svg)
            self._write(storage.safe_local(self.root / (base + '.png')), png)
            png_available = True
        except (ImportError, OSError, ValueError, RuntimeError):
            pass
        return {'available': True, 'export_id': ident, 'files': ['json', 'svg'] + (['png'] if png_available else []),
                'png_available': png_available}

    def file(self, ident, kind):
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or kind not in _FORMATS:
            raise ValueError('Unknown Shakedown export')
        matches = list(self.root.glob(f'shakedown-*-{ident}.{kind}'))
        if len(matches) != 1:
            raise ValueError('Shakedown export not found')
        path = storage.safe_local(matches[0])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_EXPORT_BYTES:
            raise ValueError('Shakedown export not available')
        return path
