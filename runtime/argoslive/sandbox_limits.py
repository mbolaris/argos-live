"""Trusted Linux launcher; applies hard limits before exec, without preexec_fn."""
import os
import resource
import sys

if __name__ == '__main__':
    for name, limit in [(resource.RLIMIT_CPU, 2), (resource.RLIMIT_AS, 256 * 1024**2),
                        (resource.RLIMIT_FSIZE, 1024**2), (resource.RLIMIT_NOFILE, 32),
                        (resource.RLIMIT_CORE, 0)]:
        resource.setrlimit(name, (limit, limit))
    os.execv(sys.argv[1], sys.argv[1:])
