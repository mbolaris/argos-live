"""Owner-only native diagnostic files; never follow links or widen permissions."""
import os
from pathlib import Path
import stat
import sys

from .storage import safe_local


def private_log(path):
    if sys.platform != 'linux':
        raise ValueError('Owner-only diagnostics require Linux')
    path = safe_local(Path(path))
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077 or info.st_nlink != 1):
        os.close(fd)
        raise ValueError('Diagnostic log must be an owner-only regular file')
    return os.fdopen(fd, 'ab', buffering=0)
