"""Refresh Argos-owned runtime files shadowed by Debian Live persistence."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile


ENTRYPOINTS = ('argos', 'argos-launch', 'argos-welcome')
LIVE_LOWER = Path('/run/live/rootfs/filesystem.squashfs')
OWNED_TREES = (
    Path('usr/local/lib/argos-live/argoslive'),
    Path('usr/local/share/argos-live/plugins/argos-improve'),
)
MAX_FILES = 10000
MAX_BYTES = 128 * 1024 * 1024


def supports_live_lower(mount_report, lower=LIVE_LOWER):
    """Accept only an overlay root whose lowerdir includes this live image."""
    fields = mount_report.strip().split(None, 1)
    if len(fields) != 2 or fields[0] != 'overlay':
        return False
    for option in fields[1].split(','):
        if not option.startswith('lowerdir='):
            continue
        lowers = option.removeprefix('lowerdir=').split(':')
        return any(os.path.normpath(item) == os.path.normpath(str(lower)) for item in lowers)
    return False


def _real_directory(path):
    path = Path(path)
    return path.is_dir() and all(not parent.is_symlink() for parent in (path, *path.parents))


def _relative_path(path):
    value = Path(path).as_posix()
    if value.startswith('/') or any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('Unsafe Argos runtime path')
    return value


def _walk_regular_files(base, relative, *, optional=False):
    """Return image/overlay files below one fixed Argos-owned directory."""
    directory = Path(base) / relative
    if not directory.exists() and optional:
        return {}
    if not _real_directory(directory):
        raise ValueError('An Argos runtime tree is missing or is not a safe real directory')
    found = {}

    def fail(error):
        raise error

    for current, dirs, files in os.walk(directory, topdown=True, followlinks=False, onerror=fail):
        current = Path(current)
        for name in dirs:
            path = current / name
            if path.is_symlink() or not path.is_dir():
                raise ValueError('An Argos runtime tree contains an unsafe directory')
        for name in files:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('An Argos runtime tree contains a non-regular file')
            relative_path = path.relative_to(base).as_posix()
            _relative_path(relative_path)
            data = path.read_bytes()
            found[relative_path] = {
                'data': data,
                'mode': stat.S_IMODE(path.stat().st_mode),
            }
            if len(found) > MAX_FILES or sum(len(item['data']) for item in found.values()) > MAX_BYTES:
                raise ValueError('Argos runtime tree exceeds the refresh size limit')
    return found


def _image_files(lower):
    lower = Path(lower)
    files = {}
    for name in ENTRYPOINTS:
        relative = Path('usr/local/bin') / name
        source = lower / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError('The live image is missing a regular Argos entrypoint')
        files[relative.as_posix()] = {
            'data': source.read_bytes(),
            'mode': stat.S_IMODE(source.stat().st_mode),
        }
    for relative in OWNED_TREES:
        files.update(_walk_regular_files(lower, relative))
    total = sum(len(item['data']) for item in files.values())
    if len(files) > MAX_FILES or total > MAX_BYTES:
        raise ValueError('Argos runtime exceeds the refresh size limit')
    return files


def _fsync_directory(path):
    if os.name == 'nt':
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(target, data, mode):
    descriptor, temporary = tempfile.mkstemp(prefix='.argos-refresh-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _ensure_parent(root, relative, created_directories):
    target = Path(root)
    for part in Path(relative).parts[:-1]:
        target = target / part
        if target.is_symlink():
            raise ValueError('An Argos runtime destination traverses a symlink')
        if target.exists():
            if not target.is_dir():
                raise ValueError('An Argos runtime destination parent is not a directory')
            continue
        target.mkdir(mode=0o755)
        created_directories.append(target)


def _validate_target_parent(root, relative):
    target = Path(root)
    for part in Path(relative).parts[:-1]:
        target = target / part
        if target.is_symlink():
            raise ValueError('An Argos runtime destination traverses a symlink')
        if target.exists() and not target.is_dir():
            raise ValueError('An Argos runtime destination parent is not a directory')


def _snapshot(changes, snapshot_root, image_sha256):
    snapshot_root = Path(snapshot_root)
    if snapshot_root.is_symlink():
        raise ValueError('Argos runtime snapshot directory must not be a symlink')
    snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not _real_directory(snapshot_root):
        raise ValueError('Argos runtime snapshot directory is unsafe')
    os.chmod(snapshot_root, 0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base_name = f'runtime-refresh-{stamp}-{image_sha256[:12]}'
    snapshot = snapshot_root / base_name
    suffix = 0
    while snapshot.exists():
        suffix += 1
        snapshot = snapshot_root / f'{base_name}-{suffix}'
    snapshot.mkdir(mode=0o700)
    manifest = {
        'schema': 'argos-runtime-refresh-snapshot/1',
        'image_sha256': image_sha256,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'changes': [],
    }
    archive_path = snapshot / 'before.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        for item in changes:
            entry = {
                'path': item['path'],
                'action': item['action'],
                'existed': item['old_data'] is not None,
                'old_mode': item['old_mode'],
                'old_sha256': hashlib.sha256(item['old_data']).hexdigest()
                    if item['old_data'] is not None else None,
            }
            manifest['changes'].append(entry)
            if item['old_data'] is not None:
                member = tarfile.TarInfo('before/' + item['path'])
                member.size = len(item['old_data'])
                member.mode = item['old_mode']
                member.mtime = 0
                archive.addfile(member, io.BytesIO(item['old_data']))
    with archive_path.open('r+b') as stream:
        os.fsync(stream.fileno())
    manifest_path = snapshot / 'manifest.json'
    with manifest_path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(manifest, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(archive_path, 0o600)
    os.chmod(manifest_path, 0o600)
    _fsync_directory(snapshot)
    _fsync_directory(snapshot_root)
    return snapshot


def _restore(changes, root, created_directories):
    for item in reversed(changes):
        target = Path(root) / item['path']
        if item['old_data'] is None:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        else:
            _ensure_parent(root, item['path'], [])
            _atomic_write(target, item['old_data'], item['old_mode'])
    for directory in reversed(created_directories):
        try:
            directory.rmdir()
        except OSError:
            pass


def refresh(root=Path('/'), lower=LIVE_LOWER, snapshot_root=None):
    """Refresh image-owned runtime trees and entrypoints, preserving a snapshot.

    Only the packaged Python runtime, bundled Argos Improvement plugin, and
    three command shims are managed. User workspaces, settings, records, and
    model storage are outside these roots and are never copied or removed.
    """
    root, lower = Path(root), Path(lower)
    image_files = _image_files(lower)
    image_hash = hashlib.sha256()
    for name, item in sorted(image_files.items()):
        image_hash.update(name.encode('utf-8') + b'\0')
        image_hash.update(str(item['mode']).encode('ascii') + b'\0')
        image_hash.update(hashlib.sha256(item['data']).digest())
    image_sha256 = image_hash.hexdigest()

    old_files = {}
    for relative in OWNED_TREES:
        old_files.update(_walk_regular_files(root, relative, optional=True))
    for name in ENTRYPOINTS:
        relative = (Path('usr/local/bin') / name).as_posix()
        _validate_target_parent(root, relative)
        target = root / relative
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('A persisted Argos entrypoint is not a regular file')
        if target.is_file():
            old_files[relative] = {
                'data': target.read_bytes(),
                'mode': stat.S_IMODE(target.stat().st_mode),
            }

    changes = []
    for name, image_item in image_files.items():
        old = old_files.get(name)
        if old is None or old['data'] != image_item['data'] or old['mode'] != image_item['mode']:
            changes.append({
                'path': name, 'action': 'write', 'new_data': image_item['data'],
                'new_mode': image_item['mode'],
                'old_data': old['data'] if old else None,
                'old_mode': old['mode'] if old else None,
            })
    for name, old in old_files.items():
        if name not in image_files:
            changes.append({
                'path': name, 'action': 'delete', 'new_data': None,
                'new_mode': None, 'old_data': old['data'], 'old_mode': old['mode'],
            })
    if not changes:
        return []

    if snapshot_root is None:
        snapshot_root = root / 'var/lib/argos-live/runtime-refresh'
    snapshot = _snapshot(changes, snapshot_root, image_sha256)
    created_directories = []
    try:
        for item in changes:
            if item['action'] == 'write':
                _ensure_parent(root, item['path'], created_directories)
                _atomic_write(root / item['path'], item['new_data'], item['new_mode'])
            else:
                target = root / item['path']
                if target.is_symlink() or not target.is_file():
                    raise ValueError('A stale Argos runtime file changed during refresh')
                target.unlink()
                _fsync_directory(target.parent)
        return [item['path'] for item in changes]
    except Exception:
        _restore(changes, root, created_directories)
        raise


def main():
    try:
        report = subprocess.run(['findmnt', '-n', '-o', 'FSTYPE,OPTIONS', '/'],
                                check=True, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        print('Argos runtime refresh skipped: root filesystem could not be verified.')
        return 0
    if not supports_live_lower(report):
        print('Argos runtime refresh skipped: root is not the expected Debian Live overlay.')
        return 0
    snapshot_root = Path('/var/lib/argos-live/runtime-refresh')
    before = set(snapshot_root.iterdir()) if snapshot_root.is_dir() else set()
    try:
        changed = refresh(snapshot_root=snapshot_root)
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(f'Argos runtime refresh failed safely: {exc}')
        return 1
    if changed:
        created = sorted(set(snapshot_root.iterdir()) - before)
        print(f'Refreshed {len(changed)} Argos runtime files from this image; '
              f'pre-change snapshot: {created[0] if created else "available"}.')
    else:
        print('Argos runtime and entrypoints already match this image.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
