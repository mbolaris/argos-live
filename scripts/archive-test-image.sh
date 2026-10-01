#!/bin/bash
set -euo pipefail
root=/var/lib/argos-live/vm-test
dest="$root/archive-$(date +%s)"
[[ $(realpath "$root") == /var/lib/argos-live/vm-test ]] || exit 1
if pgrep -f '[q]emu-system.*TEST-DO-NOT-WRITE.raw' >/dev/null; then echo 'VM still owns the test image.' >&2; exit 1; fi
mkdir -m 700 "$dest"
for name in TEST-DO-NOT-WRITE.raw TEST-DO-NOT-WRITE.raw.sha256 test-only.key first-boot.log second-boot.log; do
  if [[ -f "$root/$name" ]]; then mv "$root/$name" "$dest/"; fi
done
