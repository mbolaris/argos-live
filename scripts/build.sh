#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/../versions.env"
export SOURCE_DATE_EPOCH=$(date -u -d "${DEBIAN_SNAPSHOT:0:4}-${DEBIAN_SNAPSHOT:4:2}-${DEBIAN_SNAPSHOT:6:2} ${DEBIAN_SNAPSHOT:9:2}:${DEBIAN_SNAPSHOT:11:2}:${DEBIAN_SNAPSHOT:13:2}" +%s)
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
bash "$src/scripts/install-runtime-package.sh" "$work/config/includes.chroot/usr/local/lib/argos-live"
plugin="$work/config/includes.chroot/usr/local/share/argos-live/plugins/argos-improve"
mkdir -p "$plugin"
tar -C "$src/openclaw-plugin/argos-improve" --exclude='node_modules' --exclude='runtime' \
  --exclude='__pycache__' --exclude='*.pyc' -cf - . | tar -C "$plugin" -xf -
install -D -m 644 "$src/scripts/refresh-plugin-manifest.py" \
  "$work/config/includes.chroot/usr/local/lib/argos-live/refresh-plugin-manifest.py"
install -D -m 644 "$src/scripts/patch-openclaw-liveness.mjs" \
  "$work/config/includes.chroot/usr/local/share/argos-live/patch-openclaw-liveness.mjs"
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
install -D -m 755 "$src/runtime/argos-refresh-runtime" "$work/config/includes.chroot/usr/local/sbin/argos-refresh-runtime"
install -D -m 755 "$src/runtime/argos-ssh-ready" "$work/config/includes.chroot/usr/local/sbin/argos-ssh-ready"
install -D -m 755 "$src/runtime/argos-ssh-status" "$work/config/includes.chroot/usr/local/sbin/argos-ssh-status"
install -D -m 755 "$src/runtime/argos-ssh-restart" "$work/config/includes.chroot/usr/local/sbin/argos-ssh-restart"
install -D -m 755 "$src/scripts/argos-start-screensaver.sh" "$work/config/includes.chroot/usr/local/sbin/argos-start-screensaver"
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
# Retry failed package files individually, with one active request per host, before retrying the full live-build stage.
chroot "$builder" /bin/bash -c "cd /work && lb config --mode debian --distribution $DEBIAN_SUITE --architectures amd64 --binary-images iso-hybrid --archive-areas 'main contrib non-free non-free-firmware' --mirror-bootstrap https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ --mirror-chroot https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ --mirror-binary https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ --mirror-chroot-security https://snapshot.debian.org/archive/debian-security/$DEBIAN_SECURITY_SNAPSHOT/ --mirror-binary-security https://snapshot.debian.org/archive/debian-security/$DEBIAN_SECURITY_SNAPSHOT/ --security true --updates true --apt-source-archives false --apt-options '--yes -o Acquire::Check-Valid-Until=false -o Acquire::Languages=none -o Acquire::Queue-Mode=host -o Acquire::https::Pipeline-Depth=0 -o Acquire::http::Pipeline-Depth=0 -o Acquire::https::Timeout=15 -o Acquire::http::Timeout=15 -o Acquire::Retries=3' --debian-installer false --bootappend-live 'boot=live components persistence persistence-encryption=luks persistence-media=removable-usb username=argos hostname=argos-live console=tty0'"
live_build_log=$(mktemp /var/lib/argos-live/live-build.XXXXXX)
cleanup_live_build_log() { rm -f -- "$live_build_log"; }
trap 'cleanup_live_build_log; umount "$builder/sys"; umount "$builder/proc"; umount "$builder/dev"' EXIT
max_live_build_attempts=${ARGOS_LIVE_BUILD_ATTEMPTS:-5}
for ((attempt=1; attempt<=max_live_build_attempts; attempt++)); do
  chroot "$builder" /bin/bash -c 'cd /work && lb build' >"$live_build_log" 2>&1 &
  live_build_pid=$!
  (
    while kill -0 "$live_build_pid" 2>/dev/null; do
      sleep 45
      if kill -0 "$live_build_pid" 2>/dev/null; then
        bytes=$(wc -c < "$live_build_log")
        echo "Pinned live-build attempt $attempt remains active; captured $bytes log bytes."
        if python3 "$src/scripts/report-iso-build.py" --scan-log "$live_build_log"; then
          tail -n 8 "$live_build_log"
        else
          echo 'Pinned live-build progress tail suppressed by the credential scan.'
        fi
      fi
    done
  ) &
  heartbeat_pid=$!
  if wait "$live_build_pid"; then
    status=0
  else
    status=$?
  fi
  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  python3 "$src/scripts/report-iso-build.py" --scan-log "$live_build_log"
  tail -n 80 "$live_build_log"
  if (( status == 0 )); then
    break
  fi
  if ! grep -Eqi "Couldn't download|TooManyRequests| 503 | 504 |Gateway Timeout|Connection timed out|Temporary failure resolving|Could not connect" "$live_build_log"; then
    echo 'Live-build failed for a non-transient reason; stopping without retry.' >&2
    exit "$status"
  fi
  if (( attempt == max_live_build_attempts )); then
    echo "Pinned live-build failed after $attempt transient-download attempts." >&2
    exit "$status"
  fi
  delay=$((30 * attempt))
  if (( delay > 120 )); then delay=120; fi
  echo "Pinned live-build attempt $attempt hit a transient download error; retrying in ${delay}s with the existing stage cache." >&2
  sleep "$delay"
done
mkdir -p "$src/artifacts"
cp "$work/live-image-amd64.hybrid.iso" "$src/artifacts/argos-live-amd64.iso"
cd "$src/artifacts"
sha256sum argos-live-amd64.iso > SHA256SUMS
cp "$work/live-image-amd64.packages" packages.txt
