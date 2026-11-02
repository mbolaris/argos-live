"""Report that model selection is owner-task driven; never upgrade on fit alone."""
import json
from pathlib import Path

from . import catalog, hw, storage_view
from .pull_jobs import write_json

CONTEXT_TOKENS = 32768
HEADROOM_BYTES = 2 * 1024**3
VRAM_SHARE = 0.70
# Restrict fit previews to reviewed general-purpose dense models. This list is
# not an automatic selection policy.
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


def run(home, startup, downloads, selection, stop, *, snapshot=hw.snapshot, models=None, is_online=None):
    home = Path(home)
    marker = home / '.local/state/argos-live/first-model.json'
    if marker.exists():
        return json.loads(marker.read_text())

    def finish(**facts):
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_json(marker, {'schema': 'argos-first-model/1', **facts})
        return facts

    state = storage_view.read_state(home)
    if state.get('model_source') != 'bundled':
        return finish(outcome='skipped', reason='an owner or managed model is already selected')
    return finish(outcome='skipped', reason=(
        'automatic model selection was skipped: hardware fit alone does not show which model helps an owner task; '
        'choose a model only after defining and measuring a task need'))
