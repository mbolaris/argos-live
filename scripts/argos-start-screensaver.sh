#!/bin/sh
set -eu

saver=/usr/bin/xfce4-screensaver
saver_pid=''

stop_saver() {
    if [ -n "$saver_pid" ] && kill -0 "$saver_pid" 2>/dev/null; then
        kill -TERM "$saver_pid" 2>/dev/null || true
        wait "$saver_pid" 2>/dev/null || true
    fi
    exit 0
}
trap stop_saver HUP INT TERM

screen_saver_has_dbus_owner() {
    /usr/bin/gdbus call --session --dest org.freedesktop.DBus \
        --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner \
        org.xfce.ScreenSaver 2>/dev/null | /usr/bin/grep -q '(true,)'
}

start_saver_and_wait_for_registration() {
    timeout_seconds=$1
    # Keep the daemon in the supervisor's process tree so its session-bus
    # registration can be observed before startup is declared ready.
    "$saver" --no-daemon &
    saver_pid=$!
    attempt=0
    while [ "$attempt" -lt "$timeout_seconds" ]; do
        if ! kill -0 "$saver_pid" 2>/dev/null; then
            wait "$saver_pid" || true
            return 1
        fi
        if screen_saver_has_dbus_owner; then
            wait "$saver_pid" || true
            saver_pid=''
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    return 1
}

for attempt in 1 2; do
    if start_saver_and_wait_for_registration 12; then
        exit 0
    fi
    if [ -n "$saver_pid" ] && kill -0 "$saver_pid" 2>/dev/null; then
        kill -TERM "$saver_pid" 2>/dev/null || true
        wait "$saver_pid" 2>/dev/null || true
    fi
    saver_pid=''
    if [ "$attempt" -eq 1 ]; then
        sleep 2
    fi
done

/usr/bin/logger -t argos-screensaver \
    'xfce4-screensaver failed to claim org.xfce.ScreenSaver after one restart'
exit 1
