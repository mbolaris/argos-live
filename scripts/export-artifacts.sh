#!/bin/bash
set -euo pipefail
src=$(realpath "$(dirname "$0")/..")
work=/var/lib/argos-live/builder/work
[[ -f "$work/.build/binary_iso" ]] || { echo 'Binary image build is not complete.' >&2; exit 1; }
mkdir -p "$src/artifacts"
cp "$work/live-image-amd64.hybrid.iso" "$src/artifacts/argos-live-amd64.iso"
cp "$work/live-image-amd64.packages" "$src/artifacts/packages.txt"
cd "$src/artifacts"
sha256sum argos-live-amd64.iso > SHA256SUMS
stat -c 'Image bytes: %s' argos-live-amd64.iso
cat SHA256SUMS
