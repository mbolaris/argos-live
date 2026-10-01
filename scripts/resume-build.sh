#!/bin/bash
set -euo pipefail
export SOURCE_DATE_EPOCH=1790812800
src=$(realpath "$(dirname "$0")/..")
builder=/var/lib/argos-live/builder
exec 9>/var/lib/argos-live/build-run.lock
flock -n 9 || { echo 'Another build owns this workspace.' >&2; exit 1; }
work="$builder/work"
[[ -f "$work/config/binary" && -d "$work/chroot" ]] || { echo 'No build to resume.' >&2; exit 1; }
bash "$src/scripts/sync-build-runtime.sh"
# Reuse locally verified upstream artifacts only when hooks are incomplete.
mkdir -p "$work/chroot/opt/argos"
if [[ ! -f "$work/.build/chroot_hooks" ]]; then
  for file in node.tar.xz ollama.tar.zst; do
    if [[ -f "/var/lib/argos-live/runtime-lock/$file" ]]; then
      cp "/var/lib/argos-live/runtime-lock/$file" "$work/chroot/opt/argos/$file"
    fi
  done
fi
mountpoint -q "$builder/dev" || mount --bind /dev "$builder/dev"
mountpoint -q "$builder/proc" || mount -t proc proc "$builder/proc"
mountpoint -q "$builder/sys" || mount -t sysfs sysfs "$builder/sys"
trap 'umount "$builder/sys"; umount "$builder/proc"; umount "$builder/dev"' EXIT
# Do not rerun bootstrap_cache restore: it replaces an existing configured rootfs.
chroot "$builder" /bin/bash -c 'cd /work && lb chroot && lb binary'
mkdir -p "$src/artifacts"
cp "$work/live-image-amd64.hybrid.iso" "$src/artifacts/argos-live-amd64.iso"
cd "$src/artifacts"
sha256sum argos-live-amd64.iso > SHA256SUMS
cp "$work/live-image-amd64.packages" packages.txt
