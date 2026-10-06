"""Owner-private progress journal. Entries are recorded once per evidence key.

The journal holds milestone text, a tier and short evidence references (run ids,
model tags, dates). It never holds pasted documents, answers or conversations.
Recording is idempotent: a reinstall, a repeated trial or a restart never
replays a ceremony. Current readiness is computed separately from the journal.
"""
from datetime import datetime, timezone
import re

from . import storage
from .pull_jobs import read_json, write_json

SCHEMA = 'argos-journal/1'
TIERS = ('routine', 'qualified', 'commissioned')
KEY = re.compile(r'[a-z0-9][a-z0-9:._-]{0,119}')
MAX_ENTRIES = 200
MAX_TEXT = 400


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def path(home):
    return storage.safe_local(home / '.config/argos-live/journal.json')


def read(home):
    try:
        value = read_json(path(home))
    except FileNotFoundError:
        return {'schema': SCHEMA, 'entries': [], 'quiet': False}
    if (value.get('schema') != SCHEMA or not isinstance(value.get('entries'), list)
            or not isinstance(value.get('quiet', False), bool)):
        raise ValueError('Journal needs review')
    for entry in value['entries']:
        if (not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or entry.get('tier') not in TIERS):
            raise ValueError('Journal needs review')
    return value


def record(home, key, tier, title, detail, evidence=None, *, clock=stamp):
    """Add an entry once. Returns the entry if it is new, else None."""
    if not isinstance(key, str) or not KEY.fullmatch(key) or tier not in TIERS:
        raise ValueError('Invalid journal entry')
    for text in (title, detail):
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
            raise ValueError('Invalid journal text')
    value = read(home)
    if any(e['key'] == key for e in value['entries']):
        return None
    entry = {'key': key, 'tier': tier, 'title': title, 'detail': detail, 'at': clock(), 'seen': False,
             'evidence': evidence if isinstance(evidence, dict) else {}}
    value['entries'].append(entry)
    del value['entries'][:-MAX_ENTRIES]
    write_json(path(home), value)
    return entry


def mark_seen(home):
    value = read(home)
    changed = False
    for entry in value['entries']:
        if not entry.get('seen'):
            entry['seen'] = True
            changed = True
    if changed:
        write_json(path(home), value)
    return changed


def set_quiet(home, quiet):
    if not isinstance(quiet, bool):
        raise ValueError('Quiet must be true or false')
    value = read(home)
    value['quiet'] = quiet
    write_json(path(home), value)
    return quiet


def has(home, key):
    return any(e['key'] == key for e in read(home)['entries'])
