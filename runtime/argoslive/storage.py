"""Read-only Linux model-storage planning; never mount, create or adopt storage."""
import json
import os
from pathlib import Path
import re
import shutil

from .hw import command, memory_info, read
from . import session_mode

DISK_FILESYSTEMS = {'ext4', 'xfs', 'btrfs', 'ntfs', 'ntfs3', 'fuseblk', 'exfat', 'vfat'}
LIVE_MEDIA = {'/run/live/medium', '/lib/live/mount/medium'}
LSBLK = ['lsblk', '--json', '--paths', '--output', 'NAME,TYPE,FSTYPE,UUID,LABEL,TRAN,MAJ:MIN']


def safe_local(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() or
           (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
        raise ValueError('Model storage must be an absolute, unlinked local path')
    return path


def validate_configured(configured, *, mounts=None, blocks=None):
    """Keep the existing marker contract; an absent selection never falls back."""
    if session_mode.guest():
        session_mode.require_ram(configured.get('storage', ''), mounts)
    try:
        path = safe_local(configured['storage'])
        marker = safe_local(path / '.argos-storage-id')
        with marker.open('r', encoding='utf-8') as stream:
            raw = stream.read(258)
            identity = raw.strip()
        if (not path.is_dir() or not isinstance(configured['storage_id'], str)
                or not configured['storage_id'] or len(raw) > 257 or identity != configured['storage_id']):
            raise ValueError('Identity mismatch')
    except (OSError, KeyError, ValueError, UnicodeError):
        raise ValueError('Selected model storage is missing or has a different identity. '
                         'Mount the original volume; no fallback writes occur.') from None
    if configured.get('storage_uuid'):
        if mounts is None:
            mounts = mount_table(read(Path('/proc/self/mountinfo')))
            output = command(LSBLK)
            blocks = block_table(output) if output else {}
        mount = covering(path, mounts)
        block = block_for(mount, blocks or {}) if mount else None
        if not block or block['uuid'] != configured['storage_uuid']:
            raise ValueError('Configured filesystem UUID differs; no fallback writes occur')
    return path


def mount_table(text):
    """Parse proc mountinfo's separator and octal-escaped path fields."""
    def unescape(value):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    result = []
    for line in (text or '').splitlines():
        fields = line.split()
        try:
            split = fields.index('-')
            if (split < 6 or len(fields) != split + 4 or not re.fullmatch(r'\d+:\d+', fields[2])
                    or not fields[0].isdigit() or not fields[1].isdigit()):
                raise ValueError('Malformed mountinfo')
            result.append({'mount_id': int(fields[0]), 'parent_id': int(fields[1]),
                           'device': fields[2], 'root': unescape(fields[3]),
                           'target': unescape(fields[4]), 'options': fields[5].split(','),
                           'fstype': fields[split + 1], 'source': unescape(fields[split + 2]),
                           'super_options': fields[split + 3].split(',')})
        except (ValueError, IndexError):
            raise ValueError('Cannot safely parse mount table') from None
    return result


def block_table(text):
    """Retain all ancestry paths: lsblk can repeat devices in an N:M tree."""
    result = {}
    def walk(node, ancestry, encrypted):
        if not isinstance(node, dict) or not isinstance(node.get('children', []), list):
            raise ValueError('Malformed block device tree')
        key = node.get('maj:min')
        if not isinstance(key, str) or not re.fullmatch(r'\d+:\d+', key):
            raise ValueError('Missing block device identity')
        if node.get('type') == 'crypt' or node.get('fstype') == 'crypto_LUKS':
            encrypted = True
        elif not ancestry and node.get('type') != 'disk':
            # Loop files and incomplete topology do not prove at-rest encryption.
            encrypted = None
        label = node.get('label') if isinstance(node.get('label'), str) else None
        entry = result.setdefault(key, {'name': node.get('name'), 'uuid': node.get('uuid'), 'label': label,
                                       'type': node.get('type'), 'tran': node.get('tran'),
                                       'ancestors': set(), 'encrypted_paths': []})
        if (entry['name'], entry['uuid']) != (node.get('name'), node.get('uuid')):
            raise ValueError('Ambiguous repeated block identity')
        entry['ancestors'].update((*ancestry, key))
        entry['encrypted_paths'].append(encrypted)
        for child in node.get('children', []):
            walk(child, (*ancestry, key), encrypted)
    try:
        devices = json.loads(text)['blockdevices']
        if not isinstance(devices, list):
            raise ValueError('Malformed block device list')
        for device in devices:
            walk(device, (), False)
    except (TypeError, KeyError, json.JSONDecodeError):
        raise ValueError('Cannot safely parse block device inventory') from None
    return result


def block_for(mount, blocks):
    entry = blocks.get(mount['device'])
    if entry is not None:
        return entry
    matches = [v for v in blocks.values() if v['name'] == mount['source']]
    return matches[0] if len(matches) == 1 else None


def covering(path, mounts):
    candidates = [m for m in mounts if Path(path).is_relative_to(Path(m['target']))]
    if not candidates:
        return None
    longest = max(len(Path(m['target']).parts) for m in candidates)
    deepest = [m for m in candidates if len(Path(m['target']).parts) == longest]
    # systemd automounts retain an autofs trigger underneath the mounted volume.
    # Resolve only a proven direct parent/child pair, never arbitrary stacks.
    if len(deepest) == 2:
        triggers = [m for m in deepest if m['fstype'] == 'autofs']
        volumes = [m for m in deepest if m['fstype'] != 'autofs']
        if (len(triggers) == len(volumes) == 1 and triggers[0].get('mount_id') is not None
                and volumes[0].get('parent_id') == triggers[0]['mount_id']):
            return volumes[0]
    if len(deepest) != 1:
        raise ValueError('Ambiguous stacked mount identity; no storage selected')
    return deepest[0]


def capacity(path):
    """Check the nearest existing parent without a write test or mkdir."""
    path = safe_local(path)
    while not path.exists():
        if path == path.parent:
            return None
        path = path.parent
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        return None
    usage = shutil.disk_usage(path)
    return {'total_bytes': usage.total, 'free_bytes': usage.free}


def select(mounts, blocks, required_bytes, *, configured=None, ram_available=None,
           safety_bytes=1024**3, probe=capacity, uid=None):
    if (type(required_bytes) is not int or required_bytes <= 0 or
            type(safety_bytes) is not int or safety_bytes < 0):
        raise ValueError('Use a positive byte budget and nonnegative safety margin')
    budget = required_bytes + safety_bytes
    uid = os.getuid() if uid is None and hasattr(os, 'getuid') else (uid or 0)
    def result(path, mount, metrics, reason, kind, block=None):
        return select_result(path, mount, metrics, reason, kind, block, required_bytes, safety_bytes)
    if configured is not None:
        path = validate_configured(configured, mounts=mounts, blocks=blocks)
        mount = covering(path, mounts)
        block = block_for(mount, blocks) if mount else None
        if configured.get('storage_uuid') and (not block or block['uuid'] != configured['storage_uuid']):
            raise ValueError('Configured filesystem UUID differs; no fallback writes occur')
        try:
            metrics = probe(path)
        except (OSError, ValueError):
            raise ValueError('Configured storage access failed; no fallback writes occur') from None
        if (not metrics or metrics['free_bytes'] < budget or (mount and
                ('ro' in mount['options'] or 'ro' in mount['super_options']))):
            raise ValueError('Configured storage is unavailable, read-only or too small; no fallback writes occur')
        kind = 'ram' if mount and mount['fstype'] == 'tmpfs' else 'configured'
        if kind == 'ram' and (ram_available is None or ram_available < budget):
            raise ValueError('Configured RAM storage lacks the required available memory; no fallback writes occur')
        return result(path, mount, metrics, 'Owner-configured storage identity matched', kind, block)
    candidates = eligible(mounts, blocks, required_bytes, ram_available=ram_available,
                          safety_bytes=safety_bytes, probe=probe, uid=uid, _result=result)
    disks = [c for c in candidates if c['kind'] == 'disk']
    candidates = disks or candidates
    if not candidates:
        detail = '' if boot_devices(mounts, blocks) else ' Live boot device identity unavailable; automatic disk selection is blocked.'
        raise ValueError('No suitable model storage with sufficient space.' + detail)
    return candidates[0]


def boot_devices(mounts, blocks):
    boot = set()
    for mount in mounts:
        if mount['target'] in LIVE_MEDIA:
            block = block_for(mount, blocks)
            if block:
                boot.update(block['ancestors'])
    return boot


def eligible(mounts, blocks, required_bytes, *, ram_available=None, safety_bytes=1024**3,
             probe=capacity, uid=None, _result=None):
    """Every candidate the automatic selector would consider, largest first.

    Disks exclude every device sharing the live boot medium's ancestry. RAM
    candidates are temporary and listed only when RAM covers the budget.
    """
    if _result is None:
        def _result(path, mount, metrics, reason, kind, block=None):
            return select_result(path, mount, metrics, reason, kind, block, required_bytes, safety_bytes)
    budget = required_bytes + safety_bytes
    uid = os.getuid() if uid is None and hasattr(os, 'getuid') else (uid or 0)
    boot = boot_devices(mounts, blocks)
    disks, ram = [], []
    for mount in mounts:
        if 'ro' in mount['options'] or 'ro' in mount['super_options'] or mount['root'] != '/':
            continue
        block = block_for(mount, blocks)
        if (not session_mode.guest() and boot and mount['fstype'] in DISK_FILESYSTEMS and block and block['uuid'] and
                not boot.intersection(block['ancestors'])):
            path = mount['target'].rstrip('/') + '/ArgosLive/Models/catalog'
            try:
                if covering(path, mounts) is not mount:
                    continue
                metrics = probe(path)
            except (OSError, ValueError):
                continue
            if metrics and metrics['free_bytes'] >= budget:
                disks.append(_result(path, mount, metrics, 'Largest eligible writable filesystem; boot device excluded',
                                     'disk', block))
        elif mount['fstype'] == 'tmpfs' and ram_available is not None and ram_available >= budget:
            path = mount['target'].rstrip('/') + '/argos-live-' + str(uid) + '/models'
            try:
                if covering(path, mounts) is not mount:
                    continue
                metrics = probe(path)
            except (OSError, ValueError):
                continue
            if metrics and metrics['free_bytes'] >= budget:
                ram.append(_result(path, mount, metrics, 'No eligible disk; mounted tmpfs and available RAM cover budget', 'ram'))
    order = lambda c: (-c['total_bytes'], -c['free_bytes'], c['path'])
    return sorted(disks, key=order) + sorted(ram, key=order)


def select_result(path, mount, metrics, reason, kind, block, required_bytes, safety_bytes):
    encrypted = None
    if block:
        states = set(block['encrypted_paths'])
        encrypted = next(iter(states)) if len(states) == 1 else None
    return {'schema': 'argos-storage/1', 'path': str(path), 'kind': kind,
            'mountpoint': mount['target'] if mount else None,
            'filesystem': mount['fstype'] if mount else None,
            'volume_uuid': block.get('uuid') if block else None,
            'volume_label': block.get('label') if block else None,
            'device': block.get('name') if block else None,
            'encrypted': encrypted, 'encryption_evidence': 'lsblk ancestry' if block else 'unknown',
            'total_bytes': metrics['total_bytes'], 'free_bytes': metrics['free_bytes'],
            'required_bytes': required_bytes, 'safety_bytes': safety_bytes,
            'reason': reason, 'persistent': False if kind == 'ram' else (True if block else None),
            'selection_only': True,
            'write_verified': False}


def plan(required_bytes, configured=None, *, proc_root=Path('/proc'), run=command):
    mounts = mount_table(read(Path(proc_root) / 'self/mountinfo'))
    output = run(LSBLK)
    blocks = block_table(output) if output else {}
    ram = memory_info(read(Path(proc_root) / 'meminfo'))['available_bytes']
    return select(mounts, blocks, required_bytes, configured=configured, ram_available=ram)
