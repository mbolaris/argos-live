"""Refresh distro-owned Argos entrypoints shadowed by Debian Live persistence."""
from pathlib import Path
import os
import stat
import subprocess
import tempfile


ENTRYPOINTS = ('argos', 'argos-launch', 'argos-welcome')
LIVE_LOWER = Path('/run/live/rootfs/filesystem.squashfs')


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
    return path.is_dir() and all(not parent.is_symlink() for parent in (path, *path.parents))


def _entrypoints(root, lower):
    target_bin = root / 'usr/local/bin'
    image_bin = lower / 'usr/local/bin'
    if not _real_directory(target_bin) or not _real_directory(image_bin):
        raise ValueError('Argos entrypoint directories are not safe real directories')
    rows = []
    for name in ENTRYPOINTS:
        source, target = image_bin / name, target_bin / name
        if source.is_symlink() or not source.is_file():
            raise ValueError('The live image is missing a regular Argos entrypoint')
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('A persisted Argos entrypoint is not a regular file')
        rows.append((source, target, stat.S_IMODE(source.stat().st_mode)))
    return rows


def refresh(root=Path('/'), lower=LIVE_LOWER):
    """Atomically refresh the small, distro-owned command shims only."""
    rows = _entrypoints(Path(root), Path(lower))
    changed = []
    for source, target, mode in rows:
        if target.is_file() and target.stat().st_mode & 0o777 == mode and source.read_bytes() == target.read_bytes():
            continue
        descriptor, temporary = tempfile.mkstemp(prefix='.argos-refresh-', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, target)
            changed.append(target.name)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    if changed and os.name != 'nt':
        descriptor = os.open(Path(root) / 'usr/local/bin', os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return changed


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
    try:
        changed = refresh()
    except (OSError, ValueError) as exc:
        print(f'Argos runtime refresh failed safely: {exc}')
        return 1
    if changed:
        print('Refreshed persisted Argos command entrypoints from this image: ' + ', '.join(changed))
    else:
        print('Argos command entrypoints already match this image.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
