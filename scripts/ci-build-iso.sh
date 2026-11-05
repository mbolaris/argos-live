#!/bin/bash
set -euo pipefail

phase=${1:-all}
case "$phase" in
  host|bootstrap|builder-packages|runtime|seed|iso|all) ;;
  *) echo "Usage: $0 [host|bootstrap|builder-packages|runtime|seed|iso|all]" >&2; exit 2 ;;
esac

# Cleanup and root-owned build inputs are confined to a disposable GitHub runner.
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && $EUID == 0 ]] || {
  echo 'This wrapper requires root in a disposable GitHub-hosted runner.' >&2; exit 1;
}
src=$(realpath "$(dirname "$0")/..")
[[ "$src" == "$(realpath "${GITHUB_WORKSPACE:?}")" ]] || { echo 'Unexpected checkout.' >&2; exit 1; }

check_space() {
  local available
  available=$(df --output=avail -B1 "$src" | tail -1)
  printf 'Available workspace space: %s bytes\n' "$available"
  df -h "$src"
  (( available >= 35 * 1024 * 1024 * 1024 )) || { echo 'At least 35 GiB free is required.' >&2; exit 1; }
}

host_setup() {
  # Fixed hosted-image tool directories only; never derive deletion targets from inputs.
  for path in \
    /usr/local/lib/android \
    /usr/share/dotnet \
    /opt/ghc \
    /opt/hostedtoolcache/CodeQL \
    /usr/local/share/boost \
    /usr/local/.ghcup \
    /usr/share/swift \
    /usr/share/miniconda; do
    if [[ -e "$path" ]]; then rm -rf -- "$path"; fi
  done
  check_space
  apt-get update
  apt-get install -y debootstrap debian-archive-keyring ca-certificates curl gnupg xz-utils zstd python3
  mkdir -p /var/lib/argos-live
  curl --fail --location --proto '=https' --retry 3 -o /var/lib/argos-live/trixie.asc https://ftp-master.debian.org/keys/archive-key-13.asc
  fingerprint=$(gpg --batch --show-keys --with-colons /var/lib/argos-live/trixie.asc | awk -F: '$1 == "fpr" { print $10; exit }')
  [[ "$fingerprint" == 04B54C3CDCA79751B16BC6B5225629DF75B188BD ]] || { echo 'Unexpected Debian archive key.' >&2; exit 1; }
  gpg --batch --yes --dearmor -o /var/lib/argos-live/bootstrap-keyring.gpg /var/lib/argos-live/trixie.asc
}

bootstrap() {
  export DEBOOTSTRAP_KEYRING=/var/lib/argos-live/bootstrap-keyring.gpg
  bash "$src/scripts/bootstrap-builder.sh" bootstrap
}

builder_packages() {
  bash "$src/scripts/bootstrap-builder.sh" packages
}

runtime() {
  bash "$src/scripts/lock-runtime.sh" --check
  git -C "$src" diff --exit-code -- live/config/includes.chroot/usr/local/share/argos-live/package-lock.json
  rm -rf /var/lib/argos-live/runtime-lock/node_modules
}

seed() {
  python3 "$src/scripts/fetch-seed-model.py" /var/lib/argos-live/seed-model
}

build_iso() {
  bash "$src/scripts/build.sh"
}

if [[ $phase == host || $phase == all ]]; then host_setup; else check_space; fi
if [[ $phase == bootstrap || $phase == all ]]; then bootstrap; fi
if [[ $phase == builder-packages || $phase == all ]]; then builder_packages; fi
if [[ $phase == runtime || $phase == all ]]; then runtime; fi
if [[ $phase == seed || $phase == all ]]; then seed; fi
if [[ $phase == iso || $phase == all ]]; then build_iso; fi
