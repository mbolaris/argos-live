#!/bin/bash
set -euo pipefail
# Physical console must remain visible; serial-only output hid the unlock prompt.
python3 - <<'PY'
from pathlib import Path
import re
p = Path('/var/lib/argos-live/builder/work/config/binary')
s = p.read_text()
s = re.sub(r'\s+console=ttyS\S*', '', s)
if 'console=tty0' not in s:
    s = s.replace('hostname=argos-live', 'hostname=argos-live console=tty0')
p.write_text(s)
PY
