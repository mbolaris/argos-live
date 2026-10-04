#!/bin/bash
set -euo pipefail
# Install the same package for a fresh image and an existing repack chroot.
src=$(realpath "$(dirname "$0")/..")
destination=${1:?Usage: install-runtime-package.sh DESTINATION}
install -d -m 755 "$destination"
# Tests may leave interpreter caches in the checkout; never ship them.
tar -C "$src/runtime" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -cf - argoslive |
  tar -C "$destination" -xf -
