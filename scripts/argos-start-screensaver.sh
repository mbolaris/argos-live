#!/bin/sh
set -eu

query=/usr/bin/xfconf-query
saver=/usr/bin/xfce4-screensaver
attempt=0
ready=0

# XFCE can launch this autostart entry before its session settings service and
# X11 screen-saver extension are ready. Wait for the configured channel to be
# readable several times, then give the desktop a short settling interval.
while [ "$attempt" -lt 60 ]; do
    if /usr/bin/timeout 3 "$query" -c xfce4-screensaver \
            -p /saver/idle-activation/delay >/dev/null 2>&1; then
        ready=$((ready + 1))
        if [ "$ready" -ge 3 ]; then
            /usr/bin/sleep 5
            exec "$saver"
        fi
    else
        ready=0
    fi
    attempt=$((attempt + 1))
    /usr/bin/sleep 1
done

# Keep a best-effort saver on unusually slow sessions instead of abandoning
# the user's configured desktop behavior after the bounded readiness wait.
exec "$saver"
