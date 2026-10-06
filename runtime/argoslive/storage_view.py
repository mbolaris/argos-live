"""Owner-visible storage evidence and a deliberate model-storage choice.

Locations are resolved from the live mount table and block topology, including
the upper directory behind an overlay root. Unknown evidence stays null. The
only writes are explicit owner actions: a bounded write check, a new empty
model store with its identity marker, and reboot markers.
"""
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil

from . import hw, reboot_evidence, storage
from .pull_jobs import write_json

SCHEMA = 'argos-storage-view/1'
WRITE_CHECK_BYTES = 64 * 1024
RAM_FILESYSTEMS = {'tmpfs', 'ramfs'}
PERSISTENCE_ROOTS = ('/run/live/persistence/', '/lib/live/mount/persistence/')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def state_path(home):
    return storage.safe_local(Path(home) / '.config/argos-live/state.json')


def read_state(home):
    from .web.status import read_json
    return read_json(state_path(home))


def categories(home, configured=None):
    """Directories the owner should be able to locate. Order is display order."""
    home = Path(home)
    rows = []
    if configured and isinstance(configured.get('storage'), str):
        rows.append(('models', 'Downloaded models', Path(configured['storage'])))
    else:
        rows.append(('models', 'Downloaded models', None))
    rows += [('profile', 'Assistant profile and personality', home / '.openclaw'),
             ('conversations', 'Conversations', home / '.openclaw/agents'),
             ('results', 'Trial results and history', home / '.local/share/argos-live/results'),
             ('settings', 'Argos settings', home / '.config/argos-live')]
    return rows


def marker_directories(home, configured=None):
    """Reboot markers live only in Argos-owned directories, never volume roots."""
    rows = {key: path for key, _, path in categories(home, configured)
            if key in ('models', 'profile', 'results', 'settings') and path is not None}
    return rows


def existing(path):
    path = Path(path)
    while not path.exists():
        if path == path.parent:
            return None
        path = path.parent
    return path


def option(mount, name):
    for item in mount['super_options']:
        if item.startswith(name + '='):
            return item.split('=', 1)[1]
    return None


def backing(path, mounts, blocks, boot=frozenset()):
    """Resolve the device behind a path, following one overlay upper directory."""
    result = {'path': str(path), 'resolved': None, 'kind': 'unknown', 'filesystem': None,
              'device': None, 'label': None, 'uuid': None, 'encrypted': None,
              'persistent': None, 'boot_medium': None, 'via_overlay': False, 'live_persistence': False}
    try:
        found = existing(storage.safe_local(path))
        if found is None:
            return result
        result['resolved'] = str(found)
        mount = storage.covering(found, mounts)
        if mount is None:
            return result
        if mount['fstype'] == 'overlay':
            upper = option(mount, 'upperdir')
            result['via_overlay'] = True
            if not upper:
                return result
            mount = storage.covering(upper, mounts)
            if mount is None:
                return result
            result['live_persistence'] = upper.startswith(PERSISTENCE_ROOTS)
        elif mount['target'].startswith(PERSISTENCE_ROOTS):
            result['live_persistence'] = True
        result['filesystem'] = mount['fstype']
        if mount['fstype'] in RAM_FILESYSTEMS:
            result.update(kind='ram', persistent=False)
            return result
        block = storage.block_for(mount, blocks)
        if not block:
            return result
        states = set(block['encrypted_paths'])
        result.update(kind='disk', device=block.get('name'), label=block.get('label'),
                      uuid=block.get('uuid'), encrypted=next(iter(states)) if len(states) == 1 else None,
                      persistent=True, boot_medium=bool(boot and boot.intersection(block['ancestors'])))
    except (OSError, ValueError, TypeError, KeyError):
        result['kind'] = 'unknown'
    return result


def usage(path):
    try:
        found = existing(storage.safe_local(path))
        if found is None:
            return None, None
        value = shutil.disk_usage(found)
        return value.total, value.free
    except (OSError, ValueError):
        return None, None


def candidate_id(path):
    return hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:20]


def topology(run=hw.command, proc=Path('/proc')):
    text = hw.read(Path(proc) / 'self/mountinfo')
    if text is None:
        raise ValueError('Mount information unavailable')
    mounts = storage.mount_table(text)
    raw = run(storage.LSBLK)
    blocks = storage.block_table(raw) if raw else {}
    ram = hw.memory_info(hw.read(Path(proc) / 'meminfo'))['available_bytes']
    return mounts, blocks, ram


def candidates(mounts, blocks, ram_available, *, probe=storage.capacity):
    rows = storage.eligible(mounts, blocks, 1, ram_available=ram_available, probe=probe)
    for row in rows:
        row['id'] = candidate_id(row['path'])
        row['temporary'] = row['kind'] == 'ram'
    return rows


def confirmed(configured):
    value = configured.get('storage_confirmed') if isinstance(configured, dict) else None
    return (isinstance(value, dict) and value.get('path') == configured.get('storage')
            and value.get('storage_id') == configured.get('storage_id')
            and isinstance(value.get('at'), str))


def store_has_models(path):
    path = Path(path)
    manifests = path / 'manifests'
    blobs = path / 'blobs'
    for directory in (manifests, blobs):
        if directory.is_dir() and any(directory.iterdir()):
            return True
    return False


def write_check(directory, *, size=WRITE_CHECK_BYTES):
    """Bounded write, flush, read-back and removal inside an Argos directory."""
    directory = storage.safe_local(directory)
    if not directory.is_dir():
        raise ValueError('Write check requires an existing directory')
    path = directory / ('.argos-write-check-' + secrets.token_hex(8))
    data = secrets.token_bytes(size)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        with path.open('rb') as stream:
            back = stream.read(size + 1)
        if back != data:
            raise ValueError('Write check read back different data')
    finally:
        path.unlink(missing_ok=True)
    reboot_evidence.fsync_directory(directory)
    return {'verified': True, 'bytes': size, 'at': stamp()}


def require_ready_for_download(home, *, check=write_check):
    """Downloads need a deliberately confirmed store that accepts a write now.

    Every failure is a ValueError with a message the owner can act on, so a
    missing state file, a swapped volume, a full or read-only drive all stop the
    download before any job is created.
    """
    try:
        configured = read_state(home)
    except FileNotFoundError:
        raise ValueError('Choose where models are stored before downloading') from None
    except (OSError, TypeError):
        raise ValueError('Model storage settings could not be read; refresh and choose a location') from None
    path = storage.validate_configured(configured)
    if not confirmed(configured):
        raise ValueError('Choose where models are stored before downloading')
    try:
        check(path)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise ValueError('The model drive is full. Free space or choose another location.') from None
        raise ValueError('The model drive did not accept a test write. It may be read-only or unplugged.') from None
    return path


def snapshot(home=None, *, topology=topology, probe=storage.capacity, boot=None):
    home = Path.home() if home is None else Path(home)
    result = {'schema': SCHEMA, 'configured': None, 'confirmed': False, 'locations': [],
              'candidates': [], 'unused_volumes': [], 'boot_id_available': None,
              'can_change': False, 'change_blocked_reason': None, 'state': 'unknown'}
    try:
        configured = read_state(home)
    except FileNotFoundError:
        configured = None
        result['state'] = 'not-configured'
    except (OSError, ValueError, TypeError):
        configured = None
        result['state'] = 'needs-attention'
    try:
        mounts, blocks, ram = topology()
    except (OSError, ValueError, TypeError, KeyError):
        mounts, blocks, ram = None, {}, None
    boot_set = storage.boot_devices(mounts, blocks) if mounts else set()
    if configured is not None:
        try:
            path = storage.validate_configured(configured, mounts=mounts, blocks=blocks) if mounts else \
                storage.validate_configured(configured)
            result['configured'] = {'path': str(path), 'temporary': configured.get('storage_temporary') is True}
            result['confirmed'] = confirmed(configured)
            result['state'] = 'available'
            if store_has_models(path):
                result['change_blocked_reason'] = ('This store already holds downloaded models. '
                    'Moving a store is a manual migration; see the storage guide.')
        except (OSError, ValueError, TypeError, KeyError):
            result['state'] = 'needs-attention'
    current = reboot_evidence.boot_id() if boot is None else boot
    result['boot_id_available'] = bool(current)
    directories = marker_directories(home, configured)
    reboot = reboot_evidence.assess(home, directories, current=current)
    for key, label, path in categories(home, configured):
        row = {'key': key, 'label': label, 'path': str(path) if path else None,
               'backing': None, 'total_bytes': None, 'free_bytes': None,
               'reboot': reboot.get('profile' if key == 'conversations' else key,
                                    {'state': 'not-started', 'created_at': None, 'verified_at': None})}
        if key == 'conversations':
            row['note'] = 'Shares the profile folder. Conversation recall is a separate test.'
        if path is not None and mounts is not None:
            row['backing'] = backing(path, mounts, blocks, boot_set)
            row['total_bytes'], row['free_bytes'] = usage(path)
        result['locations'].append(row)
    if mounts is not None:
        try:
            rows = candidates(mounts, blocks, ram, probe=probe)
        except (OSError, ValueError, TypeError, KeyError):
            rows = []
        current_path = result['configured']['path'] if result['configured'] else None
        for row in rows:
            row['current'] = row['path'] == current_path
            row['contains_data'] = bool(existing(row['path']) == Path(row['path'])
                                        and any(Path(row['path']).iterdir())) and not row['current']
        result['candidates'] = rows
        result['unused_volumes'] = [{'label': r['volume_label'], 'mountpoint': r['mountpoint'],
                                     'free_bytes': r['free_bytes'], 'encrypted': r['encrypted']}
                                    for r in rows if r['kind'] == 'disk' and not (
                                        current_path and Path(current_path).is_relative_to(r['mountpoint']))]
    result['can_change'] = (result['state'] == 'available' and result['change_blocked_reason'] is None
                            and bool(result['candidates']))
    return result


def choose(home, candidate, *, topology=topology, probe=storage.capacity, check=write_check, clock=stamp):
    """Confirm or switch the model store to an eligible, empty, writable location."""
    home = Path(home)
    configured = read_state(home)
    if not isinstance(candidate, str) or len(candidate) != 20:
        raise ValueError('Choose a listed storage location')
    mounts, blocks, ram = topology()
    rows = candidates(mounts, blocks, ram, probe=probe)
    row = next((r for r in rows if r['id'] == candidate), None)
    current = storage.validate_configured(configured, mounts=mounts, blocks=blocks)
    if row is None:
        raise ValueError('That location is no longer eligible; refresh and choose again')
    target = storage.safe_local(Path(row['path']))
    if target == current:
        receipt = check(current)
        configured['storage_confirmed'] = {'path': str(current), 'storage_id': configured['storage_id'],
                                           'at': clock(), 'write_check': receipt}
        write_json(state_path(home), configured)
        return {'path': str(current), 'changed': False, 'write_check': receipt}
    if store_has_models(current):
        raise ValueError('The current store holds downloaded models; moving it is a manual migration')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('That location already contains data; Argos will not adopt it')
    created = []
    missing = []
    probe_path = target
    while not probe_path.exists():
        missing.append(probe_path)
        probe_path = probe_path.parent
    try:
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
            created.append(directory)
        target.mkdir(mode=0o700, exist_ok=True)
        receipt = check(target)
        identity = secrets.token_hex(24)
        reboot_evidence.write_exclusive(target / '.argos-storage-id', (identity + '\n').encode())
    except BaseException:
        (target / '.argos-storage-id').unlink(missing_ok=True)
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    updated = dict(configured)
    updated.update(storage=str(target), storage_id=identity, storage_temporary=row['kind'] == 'ram',
                   storage_encrypted=row['encrypted'])
    if row.get('volume_uuid'):
        updated['storage_uuid'] = row['volume_uuid']
    else:
        updated.pop('storage_uuid', None)
    updated['storage_confirmed'] = {'path': str(target), 'storage_id': identity, 'at': clock(),
                                    'write_check': receipt}
    write_json(state_path(home), updated)
    return {'path': str(target), 'changed': True, 'write_check': receipt,
            'previous': str(current)}


def start_reboot_check(home, *, current=None):
    configured = read_state(home)
    storage.validate_configured(configured)
    return reboot_evidence.start(home, marker_directories(home, configured), current=current)


def record_reboot_evidence(home):
    try:
        configured = read_state(home)
    except (OSError, ValueError, TypeError):
        configured = None
    return reboot_evidence.record(home, marker_directories(home, configured))


class Controller:
    """Dashboard storage actions share the desktop workload reservation."""

    def __init__(self, startup, *, home=None, view=snapshot, chooser=choose, reboot=start_reboot_check):
        self.startup = startup
        self.home = Path(home) if home is not None else startup.home
        self.view, self.chooser, self.reboot = view, chooser, reboot

    def snapshot(self):
        return self.view(self.home)

    def choose(self, candidate):
        with self.startup.lock:
            if self.startup.lab_active:
                raise ValueError('Another desktop workload is active')
            return self.chooser(self.home, candidate)

    def reboot_check(self):
        with self.startup.lock:
            return {'created': self.reboot(self.home)}
