#!/bin/bash
set -euo pipefail
# One-time repair after live-build bootstrap restore replaced the configured rootfs.
# Cached packages remain intact; only chroot stage markers are invalidated.
root=/var/lib/argos-live/builder/work
[[ -f "$root/chroot/etc/debian_version" && -d "$root/cache" ]] || exit 1
find "$root/.build" -maxdepth 1 -type f -name 'chroot*' -delete
