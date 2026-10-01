#!/bin/bash
set -euo pipefail
out=$(realpath "${1:?Regular raw image required}")
test_key=${2:-}
reset=${3:-}
[[ -f "$out" && ! -b "$out" && ! -L "$out" ]] || exit 1
loop=$(losetup --find --show --partscan "$out")
mapper="argos-image-$$"
trap 'cryptsetup close "$mapper" 2>/dev/null || true; losetup -d "$loop"' EXIT
[[ $(losetup -n -O BACK-FILE "$loop") == "$out" ]] || { echo 'Loop backing file identity differs.' >&2; exit 1; }
[[ -b "${loop}p4" ]] || { echo 'Persistence partition 4 not detected.' >&2; exit 1; }
if cryptsetup isLuks "${loop}p4"; then
  [[ "$reset" == --reset-image-encryption && -z "$test_key" ]] || { echo 'Persistence is already encrypted; inspect rather than overwrite.' >&2; exit 1; }
  echo 'Resetting encryption on this regular image file only; its previous persistence data becomes inaccessible.'
fi
if [[ -n "$test_key" ]]; then
  [[ "$out" == *TEST-DO-NOT-WRITE* && -f "$test_key" ]] || exit 1
  cryptsetup luksFormat --batch-mode --type luks2 --key-file "$test_key" "${loop}p4"
  cryptsetup open --key-file "$test_key" "${loop}p4" "$mapper"
else
  echo 'Enter a NEW persistence passphrase at this local prompt.'
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
