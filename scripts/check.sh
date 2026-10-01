#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
for f in scripts/*.sh runtime/*.sh live/config/hooks/live/*; do bash -n "$f"; done
