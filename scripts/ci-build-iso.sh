#!/bin/bash
set -euo pipefail
# Cleanup is deliberately unavailable on owner machines and self-hosted runners.
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && $EUID == 0 ]] || {
  echo 'This wrapper requires root in a disposable GitHub-hosted runner.' >&2; exit 1;
}
src=$(realpath "$(dirname "$0")/..")
[[ "$src" == "$(realpath "${GITHUB_WORKSPACE:?}")" ]] || { echo 'Unexpected checkout.' >&2; exit 1; }
# Fixed hosted-image tool directories only; never derive deletion targets from inputs.
rm -rf /usr/local/lib/android /usr/share/dotnet /opt/ghc
available=$(df --output=avail -B1 "$src" | tail -1)
(( available >= 35 * 1024 * 1024 * 1024 )) || { echo 'At least 35 GiB free is required.' >&2; exit 1; }
apt-get update
apt-get install -y debootstrap debian-archive-keyring ca-certificates curl gnupg xz-utils zstd python3
mkdir -p /var/lib/argos-live
# Older Ubuntu keyrings can predate trixie. Import only the reviewed public key
# into this build's isolated keyring; never disable Release signature checking.
curl --fail --location --proto '=https' --retry 3 -o /var/lib/argos-live/trixie.asc https://ftp-master.debian.org/keys/archive-key-13.asc
fingerprint=$(gpg --batch --show-keys --with-colons /var/lib/argos-live/trixie.asc | awk -F: '$1 == "fpr" { print $10; exit }')
[[ "$fingerprint" == 04B54C3CDCA79751B16BC6B5225629DF75B188BD ]] || { echo 'Unexpected Debian archive key.' >&2; exit 1; }
gpg --batch --yes --dearmor -o /var/lib/argos-live/bootstrap-keyring.gpg /var/lib/argos-live/trixie.asc
export DEBOOTSTRAP_KEYRING=/var/lib/argos-live/bootstrap-keyring.gpg
bash "$src/scripts/bootstrap-builder.sh"
bash "$src/scripts/lock-runtime.sh" --check
git -C "$src" diff --exit-code -- live/config/includes.chroot/usr/local/share/argos-live/package-lock.json
# npm-ci check files are disposable build overhead, not installed image state.
rm -rf /var/lib/argos-live/runtime-lock/node_modules
python3 "$src/scripts/fetch-seed-model.py" /var/lib/argos-live/seed-model
bash "$src/scripts/build.sh"
df -h "$src"
