#!/bin/bash
set -euo pipefail
src=$(realpath "$(dirname "$0")/..")
source "$src/versions.env"
mode=${1:-}
[[ -z "$mode" || "$mode" == --check ]] || { echo 'Usage: lock-runtime.sh [--check]' >&2; exit 1; }
cache=/var/lib/argos-live/runtime-lock
mkdir -p "$cache"
cd "$cache"
curl --fail --location --retry 5 -o node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
echo "$NODE_SHA256  node.tar.xz" | sha256sum -c -
mkdir -p node
tar -xJf node.tar.xz --strip-components=1 -C node
export PATH="$cache/node/bin:$PATH"
printf '{"name":"argos-live-runtime","version":"0.1.0","private":true,"allowScripts":{"openclaw":true},"dependencies":{"openclaw":"%s"}}\n' "$OPENCLAW_VERSION" > package.json
if [[ "$mode" == --check ]]; then
  cp "$src/live/config/includes.chroot/usr/local/share/argos-live/package-lock.json" .
  EXPECTED="$OPENCLAW_INTEGRITY" PIN="$OPENCLAW_VERSION" node -e 'const l=require("./package-lock.json"); const p=l.packages["node_modules/openclaw"]; if(l.packages[""].dependencies.openclaw !== process.env.PIN || p.version !== process.env.PIN || p.integrity !== process.env.EXPECTED) process.exit(1)'
  npm ci --ignore-scripts --no-audit --fund=false
else
  npm install --package-lock-only --ignore-scripts
fi
# Bundled npm dependencies have advisories; review separately before release.
EXPECTED="$OPENCLAW_INTEGRITY" node -e 'if(require("./package-lock.json").packages["node_modules/openclaw"].integrity !== process.env.EXPECTED) process.exit(1)'
if [[ "$mode" != --check ]]; then
  cp package-lock.json "$src/live/config/includes.chroot/usr/local/share/argos-live/package-lock.json"
fi
