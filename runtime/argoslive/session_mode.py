"""Guest policy comes from the boot entry, never an environment preference."""
from pathlib import Path


def guest(cmdline=None):
    if cmdline is None:
        try:
            cmdline = Path('/proc/cmdline').read_text()
        except OSError:
            return False
    return 'argos.guest=1' in cmdline.split()


def require_ram(path, mounts=None):
    """Fail closed before writes if a guest path is not backed by RAM."""
    from . import storage, storage_view
    if mounts is None:
        try:
            mounts = storage.mount_table(Path('/proc/self/mountinfo').read_text())
        except OSError:
            raise ValueError('Guest mode requires RAM storage; mount evidence is unavailable') from None
    if storage_view.backing(path, mounts, {})['kind'] != 'ram':
        raise ValueError('Guest mode requires RAM storage; connected disks are not used')
