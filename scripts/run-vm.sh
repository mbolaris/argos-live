#!/bin/bash
set -euo pipefail
image=$(realpath "${1:?Full-disk raw image required}")
[[ -f "$image" && ! -b "$image" ]] || { echo 'Regular image files only; no physical disks.' >&2; exit 1; }
# flock and QEMU's own write lock prevent concurrent writable image sessions.
exec 9>"$image.lock"
flock -n 9 || { echo 'Image already has a VM owner.' >&2; exit 1; }
exec qemu-system-x86_64 -accel kvm -cpu host -smp 8 -m 16384 \
  -drive "file=$image,format=raw,if=none,id=usbmedia" \
  -device qemu-xhci -device usb-storage,drive=usbmedia,bootindex=1 \
  -nic user,model=virtio-net-pci -display gtk \
  -monitor stdio -no-reboot
