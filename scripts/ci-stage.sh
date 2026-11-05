#!/usr/bin/env bash
set -euo pipefail

label=${1:?stage label required}
shift
[[ $# -gt 0 ]] || { echo 'stage command required' >&2; exit 2; }
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
log=$(mktemp "${RUNNER_TEMP:-/tmp}/argos-ci-stage.XXXXXX")
child_pid=''
heartbeat_pid=''
cleanup() {
  if [[ -n "$heartbeat_pid" ]]; then
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true
  fi
  if [[ -n "$child_pid" ]]; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  rm -f -- "$log"
}
trap cleanup EXIT

"$@" >"$log" 2>&1 &
child_pid=$!
(
  while kill -0 "$child_pid" 2>/dev/null; do
    sleep 45
    if kill -0 "$child_pid" 2>/dev/null; then
      bytes=$(wc -c < "$log")
      echo "${label} is still running; captured $bytes log bytes."
      if python3 "$script_dir/report-iso-build.py" --scan-log "$log"; then
        tail -n 12 "$log"
      else
        echo "${label} progress tail suppressed by the credential scan."
      fi
    fi
  done
) &
heartbeat_pid=$!
if wait "$child_pid"; then
  status=0
else
  status=$?
fi
child_pid=''
kill "$heartbeat_pid" 2>/dev/null || true
wait "$heartbeat_pid" 2>/dev/null || true
heartbeat_pid=''

if ! python3 "$script_dir/report-iso-build.py" --scan-log "$log"; then
  echo "${label} log was suppressed because its credential scan failed." >&2
  exit 1
fi
tail -n 80 "$log"
exit "$status"
