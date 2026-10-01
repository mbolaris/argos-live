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
# Hybrid ISO GPT is expanded; new partition begins after the ISO at MiB alignment.
sgdisk -e "$out"
start=$(( ($(stat -c %s "$iso") + 1048575) / 1048576 * 2048 ))
sgdisk --new=4:${start}:0 --typecode=4:8309 --change-name=4:ArgosPersistence "$out"
loop=$(losetup --find --show --partscan "$out")
mapper="argos-vm-$$"
trap 'cryptsetup close "$mapper" 2>/dev/null || true; losetup -d "$loop"' EXIT
echo 'Enter a NEW persistence passphrase at the local prompt. It is not logged.'
if [[ -n "$test_key" ]]; then
  [[ "$out" == *TEST-DO-NOT-WRITE* && -f "$test_key" ]] || { echo 'Automated test keys are limited to clearly named disposable images.' >&2; exit 1; }
  cryptsetup luksFormat --batch-mode --type luks2 --key-file "$test_key" "${loop}p4"
  cryptsetup open --key-file "$test_key" "${loop}p4" "$mapper"
else
  cryptsetup luksFormat --type luks2 "${loop}p4"
  cryptsetup open "${loop}p4" "$mapper"
fi
mkfs.ext4 -L persistence "/dev/mapper/$mapper"
temp=$(mktemp -d)
mount "/dev/mapper/$mapper" "$temp"
printf '/ union\n' > "$temp/persistence.conf"
umount "$temp"
rmdir "$temp"
sync
sha256sum "$out" > "$out.sha256"
