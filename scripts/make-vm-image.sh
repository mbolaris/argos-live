#!/bin/bash
set -euo pipefail
# Mutates only a NEW regular image file, never a block device.
iso=$(realpath "${1:?ISO path required}")
out=${2:?New raw image path required}
size=${3:-24G}
test_key=${4:-}
[[ -f "$iso" && ! -b "$iso" ]] || exit 1
[[ ! -e "$out" && ! -L "$out" ]] || { echo 'Destination must not exist.' >&2; exit 1; }
mkdir -p "$(dirname "$out")"
cp --sparse=always "$iso" "$out"
truncate -s "$size" "$out"
[[ $(stat -c %s "$out") -gt $(stat -c %s "$iso") ]] || { echo 'Image capacity must exceed ISO size.' >&2; exit 1; }
# Preserve Debian isohybrid's intentional nested ISO/EFI partition arrangement.
python3 "$(dirname "$0")/append-persistence-partition.py" "$out" "$(stat -c %s "$iso")"
bash "$(dirname "$0")/initialize-image-persistence.sh" "$out" "$test_key"
