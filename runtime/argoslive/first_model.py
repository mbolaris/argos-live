"""Once per install, move off the bundled starter to a model that can use tools.

The bundled qwen3:0.6b is enough to chat offline but cannot drive the agent's
tools, so "improve yourself" would stall. When the machine is online and has a
GPU, choose the largest reviewed tool-capable model that comfortably fits (at
most 70% of VRAM with a 32k-token KV cache), download it through the verified
dashboard controller, switch with the journaled selection and keep it. Climbing
further is the agent's own job. The outcome is recorded so this never repeats;
an offline boot simply tries again next time.
"""
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from . import catalog, hw, storage_view
from .pull_jobs import write_json

CONTEXT_TOKENS = 32768
HEADROOM_BYTES = 2 * 1024**3
VRAM_SHARE = 0.70
# Only official general-purpose dense models are picked automatically; coding,
# vision, MoE and community entries stay deliberate choices.
GENERAL_FAMILIES = ('qwen3', 'qwen35')


def footprint(entry):
    kv = entry.get('kv_cache') or {}
    cache = (2 * kv.get('attention_layers', 0) * kv.get('kv_heads', 0) * kv.get('head_dim', 0)
             * kv.get('bytes_per_element', 2) * CONTEXT_TOKENS)
    return entry.get('weight_bytes', 0) + cache + HEADROOM_BYTES


def choose(snapshot, models):
    vram = max((gpu.get('vram_total_bytes') or 0 for gpu in snapshot.get('gpus', [])), default=0)
    fitting = [entry for entry in models
               if entry.get('family') in GENERAL_FAMILIES and '/' not in entry['tag']
               and 'tools' in entry.get('capabilities', []) and entry.get('weight_bytes')
               and entry.get('kv_cache') and footprint(entry) <= vram * VRAM_SHARE]
    best = max(fitting, key=lambda entry: entry.get('parameter_count', 0), default=None)
    return best['tag'] if best else None


def online(timeout=10):
    try:
        with build_opener(ProxyHandler({})).open(Request('https://registry.ollama.ai/v2/'), timeout=timeout):
            return True
    except HTTPError:
        return True  # The registry answered; an auth or 404 reply still proves connectivity.
    except OSError:
        return False


def wait_until(predicate, stop, timeout, interval=2):
    deadline = time.monotonic() + timeout
    while not stop.is_set() and time.monotonic() < deadline:
        if predicate():
            return True
        stop.wait(interval)
    return False


def run(home, startup, downloads, selection, stop, *, snapshot=hw.snapshot, models=None, is_online=online):
    home = Path(home)
    marker = home / '.local/state/argos-live/first-model.json'
    if marker.exists():
        return json.loads(marker.read_text())

    def finish(**facts):
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_json(marker, {'schema': 'argos-first-model/1', **facts})
        return facts

    if not wait_until(lambda: startup.snapshot().get('phase') == 'ready', stop, 1800):
        return None
    state = storage_view.read_state(home)
    if state.get('model_source') != 'bundled':
        return finish(outcome='skipped', reason='an owner or managed model is already selected')
    tag = choose(snapshot(), models if models is not None else catalog.load()['models'])
    if tag is None:
        return finish(outcome='skipped', reason='no reviewed tool-capable model fits this GPU comfortably')
    if not is_online():
        return None  # Try again on a later boot.
    if not storage_view.confirmed(state):
        current = [row for row in storage_view.snapshot(home).get('candidates', []) if row.get('current')]
        if len(current) != 1:
            return finish(outcome='skipped', reason='model storage needs an owner choice')
        storage_view.choose(home, current[0]['id'])
    downloads.start(tag=tag)
    wait_until(lambda: not downloads.snapshot().get('active'), stop, 7200, interval=5)
    if downloads.snapshot().get('phase') != 'completed':
        return finish(outcome='failed', tag=tag, stage='download', phase=downloads.snapshot().get('phase'))
    selection.start(tag=tag)
    wait_until(lambda: not selection.snapshot().get('active'), stop, 1800, interval=5)
    if selection.snapshot().get('phase') != 'completed':
        return finish(outcome='failed', tag=tag, stage='switch', phase=selection.snapshot().get('phase'))
    selection.keep_current()
    return finish(outcome='switched', tag=tag)
