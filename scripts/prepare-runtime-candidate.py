#!/usr/bin/env python3
"""Prepare public stable runtime candidate files without changing accepted pins."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ('OPENCLAW_VERSION', 'OLLAMA_VERSION', 'NODE_VERSION')
ALLOWED = {*VERSIONS, 'OPENCLAW_INTEGRITY', 'OLLAMA_SHA256', 'NODE_SHA256'}


def pins(text):
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z][A-Z_0-9]*)=([A-Za-z0-9:._/+@=-]+)', line)
        if not match or match[1] in result:
            raise ValueError('Unexpected or duplicated pin assignment')
        result[match[1]] = match[2]
    return result


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Candidate version must be a stable release')
    return tuple(int(part) for part in value.split('.'))


def prepare(report, repo, output, *, now=None):
    current = pins((repo / 'versions.env').read_text())
    if report.get('status') != 'discovery-only' or report.get('current') != current:
        raise ValueError('Discovery report does not match current accepted pins')
    checked = datetime.fromisoformat(report['checkedAt'].replace('Z', '+00:00'))
    age = ((now or datetime.now(timezone.utc)) - checked).total_seconds()
    if not 0 <= age <= 86400:
        raise ValueError('Discovery report is stale or future dated')
    candidate = report['candidate']
    if not isinstance(candidate, dict) or candidate.keys() != current.keys():
        raise ValueError('Candidate pin set differs')
    if any(candidate[key] != current[key] for key in current if key not in ALLOWED):
        raise ValueError('Debian, security and driver changes need a separate reviewed update')
    changed = [key for key in VERSIONS if candidate[key] != current[key]]
    if not changed:
        raise ValueError('No stable runtime version changes')
    for key in VERSIONS:
        if version(candidate[key]) < version(current[key]):
            raise ValueError('Candidate downgrade refused')
    if version(candidate['NODE_VERSION'])[0] != version(current['NODE_VERSION'])[0]:
        raise ValueError('Node major transition needs compatibility review')
    for key in ('NODE_SHA256', 'OLLAMA_SHA256'):
        if not isinstance(candidate[key], str) or not re.fullmatch(r'[a-f0-9]{64}', candidate[key]):
            raise ValueError('Candidate artifact checksum missing')
    integrity = candidate['OPENCLAW_INTEGRITY']
    if not isinstance(integrity, str) or not integrity.startswith('sha512-'):
        raise ValueError('Candidate OpenClaw integrity missing')
    try:
        if len(base64.b64decode(integrity[7:], validate=True)) != 64:
            raise ValueError('Wrong digest size')
    except ValueError:
        raise ValueError('Candidate OpenClaw integrity malformed') from None
    for name, checksum in [('NODE_VERSION', 'NODE_SHA256'), ('OLLAMA_VERSION', 'OLLAMA_SHA256'),
                           ('OPENCLAW_VERSION', 'OPENCLAW_INTEGRITY')]:
        if candidate[name] == current[name] and candidate[checksum] != current[checksum]:
            raise ValueError('Unchanged version has a different artifact identity')
    sources = report.get('sources', {})
    expected = {'openclaw': 'https://github.com/openclaw/openclaw/releases/tag/v' + candidate['OPENCLAW_VERSION'],
                'ollama': 'https://github.com/ollama/ollama/releases/tag/v' + candidate['OLLAMA_VERSION'],
                'node': 'https://nodejs.org/dist/index.json'}
    if sources != expected:
        raise ValueError('Discovery sources differ from official release endpoints')
    module = (repo / 'runtime/argoslive/owned_ollama.py').read_text()
    pattern = '^PIN = ' + re.escape(repr(current['OLLAMA_VERSION'])) + '$'
    module, count = re.subn(pattern, 'PIN = ' + repr(candidate['OLLAMA_VERSION']), module, flags=re.M)
    if count != 1:
        raise ValueError('Accepted backend pin differs from versions.env')
    if output.exists() or output.is_symlink():
        raise ValueError('Candidate output must be a fresh directory')
    output.mkdir(parents=True)
    (output / 'versions.env').write_text('# STABLE CANDIDATE: not promoted; all release gates remain required.\n' +
        ''.join(key + '=' + candidate[key] + '\n' for key in current))
    (output / 'owned_ollama.py').write_text(module)
    (output / 'candidate.json').write_text(json.dumps({'schema': 'argos-runtime-candidate/1',
        'changed': changed, 'current': current, 'candidate': candidate, 'sources': expected,
        'accepted_pins_changed': False, 'promotion': 'lock, addon inventory, audit, ISO, VM and physical acceptance pending'},
        indent=2) + '\n')
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with args.report.open('rb') as stream:
        raw = stream.read(32769)
    if len(raw) > 32768:
        raise ValueError('Discovery report exceeds the size bound')
    changed = prepare(json.loads(raw), ROOT, args.output.absolute())
    print('Prepared candidate only: ' + ', '.join(changed))


if __name__ == '__main__':
    main()
