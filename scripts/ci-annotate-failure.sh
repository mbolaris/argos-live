#!/usr/bin/env bash
# Run a command; on failure publish the tail of its output as a check-run annotation so the
# reason is readable through the checks API even when job logs are not reachable.
name="$1"; shift
log="$(mktemp)"
"$@" >"$log" 2>&1
status=$?
cat "$log"
if [ "$status" -ne 0 ]; then
  message="$(tail -c 1800 "$log" | tr -d '\r' | sed -e 's/%/%25/g' -e ':a;N;$!ba;s/\n/%0A/g')"
  echo "::error title=${name} failed::${message}"
fi
rm -f "$log"
exit "$status"
