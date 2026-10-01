#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/../versions.env"
# Run as root within WSL2; all rootfs writes are confined to this directory.
root=/var/lib/argos-live/builder
mkdir -p /var/lib/argos-live
if [[ ! -f "$root/etc/debian_version" ]]; then
  debootstrap --arch=amd64 --include=ca-certificates "$DEBIAN_SUITE" "$root" "https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/"
fi
printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ %s main\n' "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" > "$root/etc/apt/sources.list"
chroot "$root" apt-get update
chroot "$root" apt-get install -y "live-build=$DEBIAN_LIVE_BUILD_VERSION" ca-certificates curl git xz-utils zstd python3
chroot "$root" dpkg-query -W > /var/lib/argos-live/builder-packages.txt
printf 'Builder ready: %s\n' "$root"
