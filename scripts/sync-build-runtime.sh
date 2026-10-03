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
install -m 755 "$src/runtime/launch.sh" "$work/config/includes.chroot/usr/local/bin/argos-launch"
install -m 755 "$src/runtime/welcome.py" "$work/config/includes.chroot/usr/local/bin/argos-welcome"
install -D -m 755 "$src/scripts/argos-collect-boot" "$work/config/includes.chroot/usr/local/sbin/argos-collect-boot"
install -D -m 755 "$src/scripts/argos-export-boot" "$work/config/includes.chroot/usr/local/sbin/argos-export-boot"
cp "$src/live/config/hooks/live/020-wallpaper.hook.chroot" "$src/live/config/hooks/live/030-diagnostics.hook.chroot" "$work/config/hooks/live/"
chmod +x "$work/config/hooks/live/020-wallpaper.hook.chroot" "$work/config/hooks/live/030-diagnostics.hook.chroot"
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
  cp -a "$work/config/includes.chroot/etc/xdg" "$work/chroot/etc/"
  cp -a "$work/config/includes.chroot/etc/systemd/." "$work/chroot/etc/systemd/"
  cp -a "$work/config/includes.chroot/usr/share/." "$work/chroot/usr/share/"
  install -m 755 "$src/runtime/launch.sh" "$work/chroot/usr/local/bin/argos-launch"
  install -m 755 "$src/runtime/welcome.py" "$work/chroot/usr/local/bin/argos-welcome"
  install -D -m 755 "$src/scripts/argos-collect-boot" "$work/chroot/usr/local/sbin/argos-collect-boot"
  install -D -m 755 "$src/scripts/argos-export-boot" "$work/chroot/usr/local/sbin/argos-export-boot"
  chroot "$work/chroot" /bin/sh -c 'ln -sfn /usr/share/backgrounds/argos-live/futuristic-coastline.png /usr/share/images/desktop-base/default; systemctl enable argos-boot-log.timer'
  if [[ -e "$work/chroot/usr/share/backgrounds/xfce/xfce-blue.jpg" ]]; then
    ln -sfn /usr/share/backgrounds/argos-live/futuristic-coastline.png "$work/chroot/usr/share/backgrounds/xfce/xfce-blue.jpg"
  fi
  rm -f "$work/chroot/usr/local/share/argos-live/seed-model/.argos-storage-id"
fi
