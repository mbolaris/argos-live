"""Read-only view of the agent's self-improvement: live benchmark, run history, model and journal."""
import json
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_LINES = 60


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _runs(results_dir):
    rows = []
    for path in Path(results_dir).glob('*.json'):
        value = _read_json(path)
        if not isinstance(value, dict) or not str(value.get('suite', '')).startswith('openclaw-'):
            continue  # Raw-model runs do not measure the assistant.
        summary = value.get('summary') or {}
        coverage = value.get('coverage') or {}
        rows.append({'id': value.get('id'), 'created': value.get('created'), 'suite': value.get('suite'),
                     'model': (value.get('settings') or {}).get('assistant_model') or value.get('model'),
                     'correct': summary.get('correct'), 'total': summary.get('total'),
                     'format_errors': summary.get('format_errors'), 'state': value.get('state'),
                     'complete': coverage.get('complete') is True,
                     'elapsed_seconds': round(value.get('elapsed_seconds') or 0, 1)})
    return sorted(rows, key=lambda row: row.get('created') or '')


def snapshot(home=None):
    home = Path(home or Path.home())
    state_dir = home / '.local/state/argos-live'
    live = _read_json(state_dir / 'assistant-bench-live.json')
    if isinstance(live, dict) and live.get('phase') in ('starting', 'running'):
        try:
            updated = datetime.fromisoformat(live.get('updated') or live.get('started'))
            if (datetime.now(timezone.utc) - updated).total_seconds() > 900:
                live['phase'] = 'stale'  # The benchmark process is gone; don't show it as running.
        except (TypeError, ValueError):
            live['phase'] = 'stale'
    runs = _runs(home / '.local/share/argos-live/results')
    complete = [run for run in runs if run['complete'] and run['total']]
    best = max(complete, key=lambda run: (run['correct'] / run['total'], -(run['format_errors'] or 0)), default=None)
    state = _read_json(home / '.config/argos-live/state.json') or {}
    journal = home / '.openclaw/workspace/IMPROVEMENT-LOG.md'
    try:
        lines = journal.read_text(encoding='utf-8', errors='replace').splitlines()[-JOURNAL_LINES:]
    except OSError:
        lines = None
    return {'schema': 'argos-improve/1', 'model': state.get('model'), 'live': live, 'runs': runs,
            'best': best, 'first': complete[0] if complete else None, 'journal': lines}
