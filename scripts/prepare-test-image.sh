#!/bin/bash
set -euo pipefail
src=$(realpath "$(dirname "$0")/..")
iso=${1:-"$src/artifacts/argos-live-amd64.iso"}
directory=/var/lib/argos-live/vm-test
mkdir -p "$directory"
chmod 700 "$directory"
key="$directory/test-only.key"
[[ ! -e "$key" ]] || { echo 'Test key exists; inspect previous test first.' >&2; exit 1; }
python3 - "$key" <<'PY'
import pathlib, secrets, sys
p=pathlib.Path(sys.argv[1]); p.write_text(secrets.token_hex(16)); p.chmod(0o600)
PY
bash "$src/scripts/make-vm-image.sh" "$iso" "$directory/TEST-DO-NOT-WRITE.raw" 24G "$key"
