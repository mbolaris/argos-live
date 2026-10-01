#!/bin/bash
set -euo pipefail
src=$(realpath "$(dirname "$0")/..")
source "$src/versions.env"
cache=/var/lib/argos-live/runtime-lock
cd "$cache"
export PATH="$cache/node/bin:$PATH"
npm ci
curl --fail --location --retry 5 -o ollama.tar.zst "https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst"
echo "$OLLAMA_SHA256  ollama.tar.zst" | sha256sum -c -
mkdir -p ollama
tar --zstd -xf ollama.tar.zst -C ollama
./node_modules/.bin/openclaw --version
./ollama/bin/ollama --version
