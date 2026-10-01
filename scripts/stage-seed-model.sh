#!/bin/bash
set -euo pipefail
dest=${1:?Build seed destination required}
seed=/var/lib/argos-live/seed-model
mkdir -p "$dest"
# Strict allowlist: omit daemon metadata, test identities, and personalization.
for name in blobs manifests; do cp -a "$seed/$name" "$dest/"; done
cp "$seed/LICENSE-Qwen3.txt" "$dest/"
find "$dest/blobs" "$dest/manifests" -type d -exec chmod 755 {} +
find "$dest/blobs" "$dest/manifests" -type f -exec chmod 644 {} +
chmod 755 "$dest"
chmod 644 "$dest/LICENSE-Qwen3.txt"
