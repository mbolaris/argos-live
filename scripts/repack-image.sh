#!/bin/bash
set -euo pipefail
export SOURCE_DATE_EPOCH=1790812800
src=$(realpath "$(dirname "$0")/..")
builder=/var/lib/argos-live/builder
work=$(realpath "$builder/work")
exec 9>/var/lib/argos-live/build-run.lock
flock -n 9 || exit 1
[[ -f "$work/chroot/usr/local/bin/argos" && -f "$work/.build/chroot_hacks" ]] || { echo 'Configured rootfs required.' >&2; exit 1; }
excluded=/var/lib/argos-live/excluded-seed-metadata/$$
for area in config/includes.chroot chroot; do
  seed="$work/$area/usr/local/share/argos-live/seed-model"
  [[ $(realpath "$seed") == "$work/"* ]] || exit 1
  for name in metadata argos-models; do
    if [[ -e "$seed/$name" ]]; then
      mkdir -p "$excluded/$area"
      mv "$seed/$name" "$excluded/$area/"
    fi
  done
done
bash "$src/scripts/sync-build-runtime.sh"
# Do not produce a desktop that requires an absent or obsolete shutdown template.
# Repacking does not rerun the chroot hooks that construct its dependency closure.
shutdown_root="$work/chroot/usr/local/share/argos-live/shutdown-root"
[[ -f "$shutdown_root/PREPARER_SHA256" && -f "$shutdown_root/SHA256SUMS" ]] || {
  echo 'A fresh image build is required for the RAM shutdown environment.' >&2; exit 1;
}
[[ "$(cat "$shutdown_root/PREPARER_SHA256")" == "$(sha256sum "$src/live/config/includes.chroot/usr/local/share/argos-live/prepare-shutdown-root.sh" | cut -d ' ' -f1)" ]] || {
  echo 'Shutdown template differs from source; do a fresh image build.' >&2; exit 1;
}
install -m 755 "$src/live/config/hooks/live/050-argos-menu.hook.binary" "$work/config/hooks/live/050-argos-menu.hook.binary"
python3 - "$work/config/binary" <<'PY'
import pathlib, sys, re
p = pathlib.Path(sys.argv[1])
s = p.read_text()
s = re.sub(r'\s+console=ttyS\S*', '', s)
if 'console=tty0' not in s:
    s = s.replace('hostname=argos-live', 'hostname=argos-live console=tty0')
if 'persistence-media=removable-usb' not in s:
    s = s.replace('persistence-encryption=luks username',
                  'persistence-encryption=luks persistence-media=removable-usb username')
if 'persistence-media=removable-usb' not in s:
    raise SystemExit('USB-only persistence boot policy missing; refuse repack.')
p.write_text(s)
PY
find "$work/.build" -maxdepth 1 -type f -name 'binary*' -delete
mount --bind /dev "$builder/dev"
mount -t proc proc "$builder/proc"
mount -t sysfs sysfs "$builder/sys"
trap 'umount "$builder/sys"; umount "$builder/proc"; umount "$builder/dev"' EXIT
chroot "$builder" /bin/bash -c 'cd /work && lb binary'
