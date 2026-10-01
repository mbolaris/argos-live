#!/bin/bash
set -euo pipefail
# Add serial diagnostics before binary boot menus are generated.
sed -i 's/hostname=argos-live"/hostname=argos-live console=tty0 console=ttyS0,115200"/' /var/lib/argos-live/builder/work/config/binary
