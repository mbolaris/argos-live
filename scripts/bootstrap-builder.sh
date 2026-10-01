#!/bin/bash
set -euo pipefail
# Run as root within WSL2; all rootfs writes are confined to this directory.
root=/var/lib/argos-live/builder
mkdir -p /var/lib/argos-live
if [[ ! -f "$root/etc/debian_version" ]]; then
  debootstrap --arch=amd64 trixie "$root" https://deb.debian.org/debian
fi
chroot "$root" apt-get update
chroot "$root" apt-get install -y live-build ca-certificates curl git xz-utils zstd python3
printf 'Builder ready: %s\n' "$root"
