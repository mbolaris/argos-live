#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/../versions.env"
export SOURCE_DATE_EPOCH=1790812800
src=$(realpath "$(dirname "$0")/..")
builder=/var/lib/argos-live/builder
mkdir -p /var/lib/argos-live
exec 9>/var/lib/argos-live/build-run.lock
flock -n 9 || { echo 'Another build owns this workspace.' >&2; exit 1; }
[[ -f "$builder/etc/debian_version" ]] || { echo 'Run bootstrap-builder.sh first.' >&2; exit 1; }
work="$builder/work"
[[ ! -e "$work/chroot" ]] || { echo 'Existing build found. Inspect /var/lib/argos-live/builder/work before rebuilding.' >&2; exit 1; }
mkdir -p "$work"
cp -a "$src/live/." "$work/"
mkdir -p "$work/config/includes.chroot/usr/local/bin"
cp "$src/versions.env" "$work/config/includes.chroot/usr/local/share/argos-live/versions.env"
cp "$src/runtime/argos.py" "$work/config/includes.chroot/usr/local/bin/argos"
chmod +x "$work/config/includes.chroot/usr/local/bin/argos"
cp "$src/runtime/launch.sh" "$work/config/includes.chroot/usr/local/bin/argos-launch"
chmod +x "$work/config/includes.chroot/usr/local/bin/argos-launch"
cp "$src/runtime/welcome.py" "$work/config/includes.chroot/usr/local/bin/argos-welcome"
chmod +x "$work/config/includes.chroot/usr/local/bin/argos-welcome"
chmod +x "$work/config/hooks/live/010-argos.hook.chroot"
chmod +x "$work/config/hooks/live/020-wallpaper.hook.chroot"
chmod +x "$work/config/hooks/live/050-argos-menu.hook.binary"
chmod +x "$work/config/hooks/live/030-diagnostics.hook.chroot"
install -D -m 755 "$src/scripts/argos-collect-boot" "$work/config/includes.chroot/usr/local/sbin/argos-collect-boot"
install -D -m 755 "$src/scripts/argos-export-boot" "$work/config/includes.chroot/usr/local/sbin/argos-export-boot"
# Optional cached upstream archives are still hash-checked by the chroot hook.
for archive in node.tar.xz ollama.tar.zst; do
  if [[ -f /var/lib/argos-live/runtime-lock/$archive ]]; then
    install -D -m 644 "/var/lib/argos-live/runtime-lock/$archive" "$work/config/includes.chroot/opt/argos/$archive"
  fi
done
if [[ -d /var/lib/argos-live/seed-model ]]; then
  bash "$src/scripts/stage-seed-model.sh" "$work/config/includes.chroot/usr/local/share/argos-live/seed-model"
else
  echo 'Run fetch-seed-model.py /var/lib/argos-live/seed-model first.' >&2
  exit 1
fi
mount --bind /dev "$builder/dev"
mount -t proc proc "$builder/proc"
mount -t sysfs sysfs "$builder/sys"
trap 'umount "$builder/sys"; umount "$builder/proc"; umount "$builder/dev"' EXIT
chroot "$builder" /bin/bash -c "cd /work && lb config --mode debian --distribution $DEBIAN_SUITE --architectures amd64 --binary-images iso-hybrid --archive-areas 'main contrib non-free non-free-firmware' --mirror-bootstrap https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ --mirror-chroot https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ --mirror-binary https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ --security false --updates false --apt-options '--yes -o Acquire::Check-Valid-Until=false -o Acquire::https::Pipeline-Depth=0 -o Acquire::http::Pipeline-Depth=0 -o Acquire::https::Timeout=30 -o Acquire::Retries=3' --debian-installer false --bootappend-live 'boot=live components persistence persistence-encryption=luks persistence-media=removable-usb username=argos hostname=argos-live console=tty0' && lb build"
mkdir -p "$src/artifacts"
cp "$work/live-image-amd64.hybrid.iso" "$src/artifacts/argos-live-amd64.iso"
cd "$src/artifacts"
sha256sum argos-live-amd64.iso > SHA256SUMS
cp "$work/live-image-amd64.packages" packages.txt
