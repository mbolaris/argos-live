#!/bin/bash
set -euo pipefail
# Start the screensaver from the same XFCE autostart path that opens Argos.
# Some live XFCE sessions skip a standalone screensaver desktop entry.
if [[ -n "${DISPLAY:-}" ]] && command -v xfce4-screensaver >/dev/null 2>&1; then
  if ! pgrep -u "$(id -u)" -x xfce4-screensaver >/dev/null 2>&1; then
    xfce4-screensaver >/dev/null 2>&1 &
  fi
fi
exec /usr/local/bin/argos desktop
