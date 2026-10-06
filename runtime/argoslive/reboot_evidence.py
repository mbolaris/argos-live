"""Narrow reboot-retention markers for owner-visible storage evidence.

A marker holds only a random identifier, a schema version and the boot ID at
creation. It is created exclusively inside an existing Argos directory, never
overwrites a file, and is flushed before the ledger records it. Reading it back
under a different boot ID proves only that this directory retained the marker
across a reboot. It does not prove encryption or conversation recovery.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets

from . import storage

SCHEMA = 'argos-reboot-marker/1'
LEDGER_SCHEMA = 'argos-reboot-evidence/1'
MARKER = '.argos-reboot-check.json'
BOOT_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
MARKER_ID = re.compile(r'[0-9a-f]{32}')
LIMIT = 4096


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def boot_id(proc=Path('/proc')):
    try:
        value = (Path(proc) / 'sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None
    return value if BOOT_ID.fullmatch(value) else None


def ledger_path(home):
    return storage.safe_local(Path(home) / '.config/argos-live/reboot-evidence.json')


def read_bounded(path):
    path = storage.safe_local(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Evidence file exceeds limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Evidence must be an object')
    return value


def read_marker(directory):
    value = read_bounded(Path(directory) / MARKER)
    if (set(value) != {'schema', 'id', 'boot_id'} or value['schema'] != SCHEMA
            or not isinstance(value['id'], str) or not MARKER_ID.fullmatch(value['id'])
            or not isinstance(value['boot_id'], str) or not BOOT_ID.fullmatch(value['boot_id'])):
        raise ValueError('Unrecognized reboot marker')
    return value


def read_ledger(home):
    try:
        value = read_bounded(ledger_path(home))
    except FileNotFoundError:
        return {'schema': LEDGER_SCHEMA, 'markers': {}}
    if value.get('schema') != LEDGER_SCHEMA or not isinstance(value.get('markers'), dict):
        raise ValueError('Unrecognized reboot evidence ledger')
    return value


def fsync_directory(path):
    if os.name == 'nt':
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_exclusive(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    fsync_directory(Path(path).parent)


def write_ledger(home, value):
    path = ledger_path(home)
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if len(raw) > LIMIT:
        raise ValueError('Reboot evidence ledger exceeds limit')
    temporary = path.parent / ('.reboot-evidence-' + secrets.token_hex(8))
    try:
        write_exclusive(temporary, raw)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def start(home, directories, *, current=None, clock=stamp):
    """Create missing markers in existing directories. Never overwrite."""
    current = boot_id() if current is None else current
    if not current or not BOOT_ID.fullmatch(current):
        raise ValueError('Boot identity unavailable; reboot check not started')
    ledger = read_ledger(home)
    created = []
    for key, directory in directories.items():
        directory = storage.safe_local(directory)
        if not directory.is_dir():
            continue
        marker = directory / MARKER
        if marker.exists() or marker.is_symlink():
            continue
        value = {'schema': SCHEMA, 'id': secrets.token_hex(16), 'boot_id': current}
        write_exclusive(marker, (json.dumps(value, sort_keys=True) + '\n').encode())
        ledger['markers'][key] = {'id': value['id'], 'path': str(directory), 'created_boot': current,
                                  'created_at': clock()}
        created.append(key)
    if created:
        write_ledger(home, ledger)
    return created


def assess(home, directories, *, current=None):
    """Read-only evidence for each directory. Unknown stays unknown."""
    current = boot_id() if current is None else current
    try:
        ledger = read_ledger(home)['markers']
    except (OSError, ValueError, TypeError):
        ledger = None
    result = {}
    for key, directory in directories.items():
        entry = (ledger or {}).get(key) if isinstance(ledger, dict) else None
        entry = entry if isinstance(entry, dict) and str(directory) == entry.get('path') else None
        evidence = {'state': 'unknown', 'created_at': entry.get('created_at') if entry else None,
                    'verified_at': entry.get('verified_at') if entry else None}
        try:
            marker = read_marker(storage.safe_local(directory))
        except FileNotFoundError:
            evidence['state'] = 'not-retained' if entry else 'not-started'
        except (OSError, ValueError, TypeError):
            evidence['state'] = 'needs-attention'
        else:
            if entry and entry.get('id') != marker['id']:
                evidence['state'] = 'needs-attention'
            elif not current:
                evidence['state'] = 'unknown'
            elif marker['boot_id'] == current:
                evidence['state'] = 'pending'
            else:
                evidence['state'] = 'retained'
        result[key] = evidence
    return result


def record(home, directories, *, current=None, clock=stamp):
    """Record the first boot that observed each retained marker."""
    current = boot_id() if current is None else current
    observed = assess(home, directories, current=current)
    ledger = read_ledger(home)
    changed = False
    for key, value in observed.items():
        entry = ledger['markers'].get(key)
        if value['state'] == 'retained' and isinstance(entry, dict) and not entry.get('verified_at'):
            entry.update(verified_boot=current, verified_at=clock())
            changed = True
    if changed:
        write_ledger(home, ledger)
    return changed
