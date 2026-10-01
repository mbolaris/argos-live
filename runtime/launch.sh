#!/bin/bash
set -euo pipefail
if [[ ! -f "$HOME/.config/argos-live/state.json" ]]; then
  argos setup
fi
argos start
