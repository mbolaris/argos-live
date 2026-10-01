#!/bin/bash
set -euo pipefail
src=$(realpath "$(dirname "$0")/..")
cache=/var/lib/argos-live/runtime-lock
export PATH="$cache/node/bin:$cache/node_modules/.bin:$cache/ollama/bin:$PATH"
export HOME=/var/lib/argos-live/smoke-home
mkdir -p "$HOME"
export OLLAMA_HOST=127.0.0.1:11435 OLLAMA_MODELS=/var/lib/argos-live/seed-model OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=32768 CUDA_VISIBLE_DEVICES=-1
ollama serve > "$HOME/ollama.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT
for i in {1..30}; do curl -fsS "$OLLAMA_HOST/api/version" && break || sleep 1; done
curl -fsS "$OLLAMA_HOST/api/chat" -H 'Content-Type: application/json' -d '{"model":"qwen3:0.6b","messages":[{"role":"user","content":"Say hello in one short sentence. /no_think"}],"stream":false,"think":false,"options":{"num_ctx":32768,"num_predict":64}}'
echo
python3 - "$src" <<'PY'
import importlib.util, pathlib, sys, unittest.mock, json
src = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('argos', src / 'runtime/argos.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
if not m.STATE.exists():
    with unittest.mock.patch('builtins.input', side_effect=['TEMPORARY', 'yes', '/var/lib/argos-live/seed-model', 'yes', 'qwen3:0.6b']):
        m.setup()
p = m.OC / 'openclaw.json'; c=json.loads(p.read_text()); c['models']['providers']['ollama']['baseUrl']='http://127.0.0.1:11435'; m.save(p,c)
PY
openclaw config validate
openclaw agent --local --agent main --session-id "argos-smoke-$(date +%s)" --message 'Say hello in one sentence. /no_think' --json
