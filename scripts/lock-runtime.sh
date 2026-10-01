#!/bin/bash
set -euo pipefail
src=$(realpath "$(dirname "$0")/..")
source "$src/versions.env"
cache=/var/lib/argos-live/runtime-lock
mkdir -p "$cache"
cd "$cache"
curl --fail --location --retry 5 -o node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
echo "$NODE_SHA256  node.tar.xz" | sha256sum -c -
mkdir -p node
tar -xJf node.tar.xz --strip-components=1 -C node
export PATH="$cache/node/bin:$PATH"
printf '{"name":"argos-live-runtime","version":"0.1.0","private":true,"allowScripts":{"openclaw":true},"dependencies":{"openclaw":"%s"}}\n' "$OPENCLAW_VERSION" > package.json
npm install --package-lock-only --ignore-scripts
# Bundled npm dependencies have advisories; review separately before release.
EXPECTED="$OPENCLAW_INTEGRITY" node -e 'if(require("./package-lock.json").packages["node_modules/openclaw"].integrity !== process.env.EXPECTED) process.exit(1)'
cp package-lock.json "$src/live/config/includes.chroot/usr/local/share/argos-live/package-lock.json"
