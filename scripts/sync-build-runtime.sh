#!/bin/bash
set -euo pipefail
# Use only before the running build reaches the Argos hook.
src=$(realpath "$(dirname "$0")/..")
work=/var/lib/argos-live/builder/work
cp -a "$src/live/config/includes.chroot/." "$work/config/includes.chroot/"
cp "$src/live/config/hooks/live/010-argos.hook.chroot" "$work/config/hooks/live/"
cp "$src/live/config/hooks/live/050-argos-menu.hook.binary" "$work/config/hooks/live/"
chmod +x "$work/config/hooks/live/010-argos.hook.chroot"
cp "$src/live/config/includes.chroot/usr/local/share/argos-live/package-lock.json" "$work/config/includes.chroot/usr/local/share/argos-live/"
cp "$src/runtime/argos.py" "$work/config/includes.chroot/usr/local/bin/argos"
chmod +x "$work/config/includes.chroot/usr/local/bin/argos"
if [[ -d /var/lib/argos-live/seed-model ]]; then
  bash "$src/scripts/stage-seed-model.sh" "$work/config/includes.chroot/usr/local/share/argos-live/seed-model"
  rm -f "$work/config/includes.chroot/usr/local/share/argos-live/seed-model/.argos-storage-id"
fi
if [[ -d "$work/chroot/usr/local/share/argos-live" ]]; then
  mkdir -p "$work/chroot/etc/cryptsetup-initramfs"
  cp "$src/live/config/includes.chroot/etc/cryptsetup-initramfs/conf-hook" "$work/chroot/etc/cryptsetup-initramfs/conf-hook"
  cp -a "$work/config/includes.chroot/usr/local/share/argos-live/." "$work/chroot/usr/local/share/argos-live/"
  cp "$src/runtime/argos.py" "$work/chroot/usr/local/bin/argos"
  chmod +x "$work/chroot/usr/local/bin/argos"
  rm -f "$work/chroot/usr/local/share/argos-live/seed-model/.argos-storage-id"
fi
