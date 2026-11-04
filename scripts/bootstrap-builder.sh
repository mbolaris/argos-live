#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/../versions.env"
phase=${1:-all}
[[ $phase == all || $phase == bootstrap || $phase == packages ]] || { echo 'Usage: bootstrap-builder.sh [bootstrap|packages|all]' >&2; exit 2; }
# Run as root within WSL2; all rootfs writes are confined to this directory.
root=/var/lib/argos-live/builder
mkdir -p /var/lib/argos-live
if [[ $phase == all || $phase == bootstrap ]]; then
if [[ ! -f "$root/etc/debian_version" ]]; then
  keyring=()
  if [[ -n ${DEBOOTSTRAP_KEYRING:-} ]]; then
    [[ -r "$DEBOOTSTRAP_KEYRING" ]] || { echo 'Bootstrap keyring is unreadable.' >&2; exit 1; }
    keyring=(--keyring="$DEBOOTSTRAP_KEYRING")
  fi
  cache=/var/cache/argos-live/debootstrap
  mkdir -p "$cache"
  attempt=1
  while :; do
    if debootstrap "${keyring[@]}" --verbose --cache-dir="$cache" --arch=amd64 --include=ca-certificates "$DEBIAN_SUITE" "$root" "https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/"; then
      break
    else
      status=$?
    fi
    if (( attempt >= 5 )); then
      echo "Debian bootstrap failed after $attempt attempts." >&2
      exit "$status"
    fi
    delay=$((30 * attempt))
    echo "Debian bootstrap attempt $attempt failed; retrying from its package cache in ${delay}s." >&2
    [[ "$root" == /var/lib/argos-live/builder ]] || { echo 'Unexpected bootstrap cleanup target.' >&2; exit 1; }
    rm -rf -- "$root"
    mkdir -p "$root"
    sleep "$delay"
    ((attempt+=1))
  done
fi
printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ %s main\n' "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" > "$root/etc/apt/sources.list"
printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ %s-updates main\n' "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" >> "$root/etc/apt/sources.list"
printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/%s/ %s-security main\n' "$DEBIAN_SECURITY_SNAPSHOT" "$DEBIAN_SUITE" >> "$root/etc/apt/sources.list"
fi
if [[ $phase == bootstrap ]]; then
  printf 'Debian bootstrap phase ready: %s\n' "$root"
  exit 0
fi
[[ -f "$root/etc/debian_version" && -f "$root/etc/apt/sources.list" ]] || { echo 'Run bootstrap phase first.' >&2; exit 1; }
if [[ $phase == all || $phase == packages ]]; then
apt_opts=(-o Acquire::Check-Valid-Until=false -o Acquire::Retries=3 -o Acquire::https::Timeout=30 \
  -o Acquire::http::Timeout=30 -o Acquire::https::Pipeline-Depth=0 -o Acquire::http::Pipeline-Depth=0 \
  -o Acquire::Languages=none -o Dpkg::Use-Pty=0)
apt_retry() {
  local label=$1; shift
  local attempt status delay
  for attempt in 1 2 3; do
    if DEBIAN_FRONTEND=noninteractive chroot "$root" apt-get -qq "${apt_opts[@]}" "$@"; then
      return 0
    else
      status=$?
    fi
    if (( attempt == 3 )); then
      echo "Pinned builder apt $label failed after $attempt attempts." >&2
      return "$status"
    fi
    delay=$((30 * attempt))
    echo "Pinned builder apt $label attempt $attempt failed; retrying in ${delay}s with cached indexes/packages." >&2
    sleep "$delay"
  done
}
apt_retry update update
apt_retry install install -y "live-build=$DEBIAN_LIVE_BUILD_VERSION" ca-certificates curl git xz-utils zstd python3
chroot "$root" dpkg-query -W > /var/lib/argos-live/builder-packages.txt
printf 'Builder ready: %s\n' "$root"
fi
