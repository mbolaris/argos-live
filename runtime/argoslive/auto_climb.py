"""Durable Auto Climb coordinator for bounded, validated assistant self-improvement.

Owner-approved product contract:
- One button starts a bounded session after boot.
- Discloses the approved envelope (time, experiment count, download budget).
- Shows real observable work across shared foundation challenges.
- Proposes structured, reversible interventions with a 30-second server countdown.
- Supports Try now, Skip, Pause, and Stop overrides; opening details pauses countdown.
- Practice identifies candidate gains; independent held-out validation confirms generalization.
- Fresh validation exposure and confirmation policy: disjoint partitions, consumed on exposure.
- Rebased comparisons on verified current kept build; later regression cannot inherit earlier gains.
- Guarded mutations: journal before write, owner-edit protection, verified Undo.
- Single worker ownership, cancellable child execution, cumulative budgets across Resume/reboot.
- Stops honestly at measured plateau (>= 3 non-improving AND all options evaluated), options exhausted, or budget exhaustion.
- Reuses OpenClaw runner, transactions, scoring, hardware probing, and recovery.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import traceback
import uuid

from . import assistant_trial, catalog, hw, model_selection, model_verify, starter, storage
from .assistant_trial import (
    agents_path,
    changed_trial_files,
    fingerprint,
    fingerprint_matches,
    message,
    read_text,
    score,
    staged,
    write_text,
    CHANGE_BY_ID,
    CHANGES,
    Refused,
    TrialTurnError,
)
from .pull_jobs import read_json, write_json

SCHEMA = 'argos-auto-climb/1'
SESSION_REL_PATH = Path('.local/share/argos-live/auto-climb/session.json')
INVENTORY_REL_PATH = Path('.local/share/argos-live/auto-climb/exposure-inventory.json')
INVENTORY_SCHEMA = 'argos-auto-climb-inventory/1'


def get_model_catalog_entry(tag):
    if not tag:
        return None
    try:
        data = catalog.load()
        for m in data.get('models', []):
            if m.get('tag') == tag:
                return m
    except Exception:
        pass
    return None


def get_model_digest(tag):
    entry = get_model_catalog_entry(tag)
    return entry.get('manifest_digest') if entry else None


def configured_model(home):
    """Return the model only when both Argos and OpenClaw configuration agree."""
    state_path = storage.safe_local(Path(home) / '.config/argos-live/state.json')
    config_path = storage.safe_local(Path(home) / '.openclaw/openclaw.json')
    state = read_json(state_path)
    config = read_json(config_path)
    tag = state.get('model')
    primary = config.get('agents', {}).get('defaults', {}).get('model', {}).get('primary')
    return tag if isinstance(tag, str) and primary == 'ollama/' + tag else None

PRACTICE_TASKS_PATH = Path(__file__).with_name('data') / 'assistant-trials' / 'grounded-answers.json'
VALIDATION_TASKS_PATH = Path(__file__).with_name('data') / 'assistant-trials' / 'held-out-validation.json'

DEFAULT_ENVELOPE = {
    'max_duration_seconds': 3600,   # 60 minutes
    'max_experiments': 6,          # 6 completed experiments
    'max_model_downloads': 1,      # At most 1 model download
    'max_download_bytes': 8 * 1024 * 1024 * 1024,  # 8 GiB
    'permissions': 'none',         # No permission expansion
}

# Candidate instruction interventions
INSTRUCTION_CANDIDATES = [
    {
        'id': 'answer-first',
        'kind': 'instruction',
        'title': 'Answer first',
        'change': 'Add rule in AGENTS.md: Answer questions directly before adding detail.',
        'rationale': 'Improves answer directness on factual queries.',
        'cost': '0 MB download · ~2 min test',
        'verification': '8 practice challenges + 8 independent validation challenges',
        'change_id': 'answer-first',
    },
    {
        'id': 'quote-evidence',
        'kind': 'instruction',
        'title': 'Show the source',
        'change': 'Add rule in AGENTS.md: Back up document answers with one exact sentence from the source.',
        'rationale': 'Grounds factual answers in explicit cited source sentences.',
        'cost': '0 MB download · ~2 min test',
        'verification': '8 practice challenges + 8 independent validation challenges',
        'change_id': 'quote-evidence',
    },
    {
        'id': 'honest-uncertainty',
        'kind': 'instruction',
        'title': 'Be honest when missing',
        'change': 'Add rule in AGENTS.md: Say plainly when the provided text does not contain an answer.',
        'rationale': 'Prevents hallucination and guessing when documents are silent.',
        'cost': '0 MB download · ~2 min test',
        'verification': '8 practice challenges + 8 independent validation challenges',
        'change_id': 'honest-uncertainty',
    },
]


def validate_envelope(envelope):
    """Strictly validate approved session limits against specification rules."""
    if envelope is None:
        return dict(DEFAULT_ENVELOPE)
    if not isinstance(envelope, dict):
        raise Refused('Approved envelope must be a dictionary')
    merged = dict(DEFAULT_ENVELOPE)
    for k, v in envelope.items():
        if k not in merged:
            raise Refused(f'Unknown envelope limit: {k}')
        merged[k] = v
    if not isinstance(merged['max_duration_seconds'], int) or not (60 <= merged['max_duration_seconds'] <= 86400):
        raise Refused('max_duration_seconds must be an integer between 60 and 86400')
    if not isinstance(merged['max_experiments'], int) or not (1 <= merged['max_experiments'] <= 50):
        raise Refused('max_experiments must be an integer between 1 and 50')
    if not isinstance(merged['max_model_downloads'], int) or not (0 <= merged['max_model_downloads'] <= 5):
        raise Refused('max_model_downloads must be an integer between 0 and 5')
    if not isinstance(merged['max_download_bytes'], int) or not (0 <= merged['max_download_bytes'] <= 100 * 1024 * 1024 * 1024):
        raise Refused('max_download_bytes must be an integer between 0 and 100 GiB')
    if merged.get('permissions') != 'none':
        raise Refused('permissions must be "none"')
    return merged


def load_task_file(path):
    with path.open('rb') as f:
        return json.loads(f.read().decode('utf-8'))


def load_validation_tasks(path=VALIDATION_TASKS_PATH):
    return load_task_file(path)


def load_validation_partitions(path=VALIDATION_TASKS_PATH):
    data = load_task_file(path)
    if 'partitions' in data and isinstance(data['partitions'], list):
        return data['partitions']
    # Fallback to single partition
    return [{
        'id': 'val-p1',
        'passages': data.get('passages', {}),
        'tasks': data.get('tasks', []),
    }]


def recommend_hardware_model(home, *, envelope=None, budgets=None,
                             hardware_fn=hw.snapshot, catalog_data=None, excluded_candidates=()):
    """Find the best eligible candidate model for this machine within approved budget."""
    envelope = envelope or DEFAULT_ENVELOPE
    budgets = budgets or {}
    data = catalog_data if catalog_data is not None else catalog.load()

    state_file = storage.safe_local(Path(home) / '.config/argos-live/state.json')
    current_model = starter.TAG
    configured = None
    if state_file.exists():
        try:
            configured = read_json(state_file)
            current_model = configured.get('model') or starter.TAG
        except (OSError, ValueError):
            pass

    current_entry = next((e for e in data['models'] if e['tag'] == current_model), None)
    if not current_entry:
        return None
    current_weight = current_entry['weight_bytes']

    measured = hardware_fn() if hardware_fn else {}
    ram = measured.get('ram', {}).get('available_bytes')
    gpus = measured.get('gpus') or []
    capacities = [g['vram_total_bytes'] - g['vram_used_bytes'] for g in gpus
                  if type(g.get('vram_total_bytes')) is int and type(g.get('vram_used_bytes')) is int
                  and g['vram_total_bytes'] >= g['vram_used_bytes']]
    vram = max(capacities) if capacities else None

    # The reviewed selection/startup path runs the conversation at 32k context.
    # A fit recommendation at the smaller benchmark context would be misleading.
    execution_context = 32768

    eligible_candidates = []
    for entry in data['models']:
        tag = entry['tag']
        if tag == current_model or '/' in tag or f'model-{tag}' in excluded_candidates:
            continue
        if not catalog.is_curated(tag):
            continue
        if 'text' not in entry.get('capabilities', []):
            continue
        if entry.get('context_tokens', 0) < execution_context:
            continue
        if entry['weight_bytes'] <= current_weight:
            continue

        cur_info = catalog.curated_info(tag)
        if cur_info and not cur_info.get('downloadable', True):
            continue

        gpu_fit = catalog.fit(entry, vram, device='gpu', context_tokens=execution_context) if vram is not None else {'status': 'unknown'}
        cpu_fit = catalog.fit(entry, ram, device='cpu', context_tokens=execution_context) if ram is not None else {'status': 'unknown'}
        if gpu_fit['status'] != 'fits' and cpu_fit['status'] != 'fits':
            continue

        # Check full artifact identity/readiness if configured with model_verify.verify
        installed = False
        if configured:
            try:
                root = storage.validate_configured(configured)
                model_verify.verify(root, entry)
                installed = True
            except Exception:
                installed = False

        needs_download = not installed
        download_bytes = entry['total_download_bytes'] if needs_download else 0

        # If download is needed, check against envelope budget
        if needs_download:
            max_downloads = envelope.get('max_model_downloads', 1)
            max_bytes = envelope.get('max_download_bytes', 8 * 1024 * 1024 * 1024)
            if budgets.get('model_downloads', 0) >= max_downloads:
                continue
            if budgets.get('download_bytes', 0) + download_bytes > max_bytes:
                continue

        eligible_candidates.append((entry, installed, download_bytes))

    if not eligible_candidates:
        return None

    # Pick smallest viable weight upgrade among curated candidates
    selected_entry, installed, download_bytes = min(eligible_candidates, key=lambda item: item[0]['weight_bytes'])

    needs_download = not installed
    storage_needed = False
    if needs_download:
        try:
            from . import storage_view
            storage_view.require_ready_for_download(Path(home))
        except Exception:
            storage_needed = True

    curated_info = catalog.curated_info(selected_entry['tag']) or {}
    rationale = curated_info.get('rationale', 'Curated upgrade with confirmed hardware memory headroom.')
    cost_str = (f"{download_bytes // (1024 * 1024):,} MB download · ~5 min test"
                if needs_download else "0 MB download · ~2 min test")

    return {
        'id': f'model-{selected_entry["tag"]}',
        'kind': 'model',
        'tag': selected_entry['tag'],
        'title': f'Upgrade model to {selected_entry["tag"]}',
        'change': f'Switch assistant primary model from {current_model} to {selected_entry["tag"]}.',
        'rationale': rationale,
        'cost': cost_str,
        'verification': '8 practice challenges + 8 independent validation challenges',
        'needs_download': needs_download,
        'download_bytes': download_bytes,
        'storage_needed': storage_needed,
        'manifest_digest': selected_entry.get('manifest_digest'),
        'entry': selected_entry,
    }


class Controller:
    """Server-side Auto Climb coordinator owning session durability, countdown, and execution."""

    def __init__(self, startup, *, home=None, runner=None, clock=time.monotonic,
                 time_fn=time.time, sleep_fn=time.sleep, practice_path=PRACTICE_TASKS_PATH,
                 validation_path=VALIDATION_TASKS_PATH, candidates=None,
                 model_recommender=recommend_hardware_model, model_switcher=None,
                 model_restorer=None, download_runner=None, selection=None, downloads=None):
        self.startup = startup
        self.home = Path(home or getattr(startup, 'home', Path.home()))
        self.clock = clock
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn
        self.practice_tasks = load_task_file(practice_path)
        self.validation_tasks = load_task_file(validation_path)
        self.validation_partitions = load_validation_partitions(validation_path)
        if candidates is not None:
            self.candidate_pool = list(candidates)
            self.model_recommender = None if model_recommender is recommend_hardware_model else model_recommender
        else:
            self.candidate_pool = list(INSTRUCTION_CANDIDATES)
            self.model_recommender = model_recommender
        self.model_switcher = model_switcher
        self.model_restorer = model_restorer
        self.download_runner = download_runner
        self.selection = selection
        self.downloads = downloads

        # Wire OpenClaw runner by default if not passed or not in startup
        self.runner = runner or getattr(startup, 'runner', None)
        if self.runner is None and self.home:
            self.runner = assistant_trial.OpenClawRunner(self.home)

        self.cancel_event = threading.Event()
        if hasattr(self.runner, 'cancel_event'):
            self.runner.cancel_event = self.cancel_event

        # Track and set expected model on runner
        active_model_tag = None
        if hasattr(self.startup, 'snapshot'):
            active_model_tag = self.startup.snapshot().get('model')
        if active_model_tag and hasattr(self.runner, 'expected_model'):
            self.runner.expected_model = active_model_tag

        self.lock = threading.RLock()
        self.worker = None
        self.child_worker = None
        self._active_slice_start = None
        self.closed = False

        self.session_path = storage.safe_local(self.home / SESSION_REL_PATH)
        self.inventory_path = storage.safe_local(self.home / INVENTORY_REL_PATH)
        self.session = self._load_or_recover_session()

        # Ephemeral runtime flags
        self.current_action_id = None
        self.countdown_deadline = 0.0
        self.pause_event = threading.Event()
        self.skip_event = threading.Event()
        self.try_now_event = threading.Event()
        self.stop_event = threading.Event()

        # Ephemeral watch streaming data
        self.current_progress = None
        self.current_receipts = []

    def _load_inventory(self):
        if not self.inventory_path.exists():
            return {'schema': INVENTORY_SCHEMA, 'consumed_partitions': [], 'history': []}
        try:
            data = read_json(self.inventory_path)
            if not isinstance(data, dict):
                raise ValueError('Corrupt exposure inventory: content must be a JSON object')
            if data.get('schema') != INVENTORY_SCHEMA:
                raise ValueError(f'Corrupt exposure inventory schema: {data.get("schema")}')
            if not isinstance(data.get('consumed_partitions'), list):
                raise ValueError('Corrupt exposure inventory: consumed_partitions must be a list')
            if any(not isinstance(pid, str) or not pid for pid in data['consumed_partitions']):
                raise ValueError('Corrupt exposure inventory: partition IDs must be non-empty strings')
            history = data.get('history')
            if not isinstance(history, list):
                raise ValueError('Corrupt exposure inventory: history must be a list')
            history_ids = []
            for row in history:
                if not isinstance(row, dict) or not isinstance(row.get('partition_id'), str) or not row['partition_id']:
                    raise ValueError('Corrupt exposure inventory: invalid history entry')
                history_ids.append(row['partition_id'])
            # Treat history as an additional consumed ledger. This protects against
            # an incomplete consumed_partitions array after an interrupted write.
            data['consumed_partitions'] = sorted(set(data['consumed_partitions']).union(history_ids))
            return data
        except Exception as exc:
            raise ValueError(f'Corrupt exposure inventory: {exc}') from exc

    def _consume_partitions(self, partition_ids, *, session_id, candidate_id, reason):
        with self.lock:
            try:
                inv = self._load_inventory()
            except Exception as exc:
                if self.session is not None:
                    self.session['phase'] = 'blocked'
                    self.session['failure_code'] = 'corrupt-inventory'
                    self.session['stopping_reason'] = f'Corrupt exposure inventory: {exc}. Automatic validation blocked.'
                    self.session['message'] = self.session['stopping_reason']
                    self._save_session()
                raise Refused(f'Corrupt exposure inventory: {exc}. Automatic validation blocked.')

            consumed = set(inv.get('consumed_partitions', []))
            history = list(inv.get('history', []))
            now_iso = datetime.now(timezone.utc).isoformat()
            for pid in partition_ids:
                if pid not in consumed:
                    consumed.add(pid)
                    history.append({
                        'partition_id': pid,
                        'session_id': session_id,
                        'candidate_id': candidate_id,
                        'consumed_at': now_iso,
                        'reason': reason,
                    })
            inv['schema'] = INVENTORY_SCHEMA
            inv['consumed_partitions'] = sorted(consumed)
            inv['history'] = history
            inv['updated_at'] = now_iso
            self.inventory_path.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(5):
                try:
                    write_json(self.inventory_path, inv)
                    break
                except (PermissionError, OSError):
                    if attempt == 4:
                        raise
                    time.sleep(0.05)

            # Mirror in session exposure ledger
            if self.session is not None:
                ledger = self.session.setdefault('exposure_ledger', {})
                sess_consumed = set(ledger.get('consumed_partitions', []))
                sess_consumed.update(partition_ids)
                ledger['consumed_partitions'] = sorted(sess_consumed)
                self._save_session()

    def _get_fresh_partitions(self, count=2):
        with self.lock:
            try:
                inv = self._load_inventory()
            except Exception as exc:
                if self.session is not None:
                    self.session['phase'] = 'blocked'
                    self.session['failure_code'] = 'corrupt-inventory'
                    self.session['stopping_reason'] = f'Corrupt exposure inventory: {exc}. Automatic validation blocked.'
                    self.session['message'] = self.session['stopping_reason']
                    self._save_session()
                raise Refused(f'Corrupt exposure inventory: {exc}. Automatic validation blocked.')

            globally_consumed = set(inv.get('consumed_partitions', []))
            sess_consumed = set(self.session.get('exposure_ledger', {}).get('consumed_partitions', [])) if self.session else set()
            all_consumed = globally_consumed.union(sess_consumed)

            available = [p for p in self.validation_partitions if p['id'] not in all_consumed]
            if len(available) < count:
                return None
            return available[:count]

    def _load_or_recover_session(self):
        """Recover pending session from disk, resolving pending mutations if any."""
        if not self.session_path.exists():
            return None
        try:
            data = read_json(self.session_path)
            if data.get('schema') != SCHEMA:
                return None
            phase = data.get('phase')
            mutation = data.get('mutation')

            if phase in ('staging', 'stage', 'retest', 'validate', 'countdown', 'acquire', 'undoing') or mutation:
                if mutation and mutation.get('kind') == 'model':
                    expected_model = data.get('active_model', {}).get('model')
                    try:
                        restored = model_selection.restore(self.home)
                        current_model = configured_model(self.home)
                        if not current_model or current_model != expected_model:
                            raise RuntimeError('Configured model does not match the pre-experiment model')
                        if restored is False and current_model != expected_model:
                            raise RuntimeError('No model rollback transaction was available')
                    except Exception:
                        data['phase'] = 'blocked'
                        data['failure_code'] = 'model-restore-failed'
                        data['message'] = 'Interrupted model change could not be verified or restored. Automatic recovery is blocked.'
                        self.startup.lab_active = True
                        # Preserve the mutation record so recovery remains reviewable.
                        write_json(self.session_path, data)
                        return data
                    data['active_model'] = dict(data.get('active_model') or {})
                    data.pop('mutation', None)
                    data['phase'] = 'paused'
                    data['message'] = 'Recovered from restart. Previous model verified; session paused.'
                elif mutation and mutation.get('kind') != 'instruction':
                    data['phase'] = 'blocked'
                    data['failure_code'] = 'unknown-mutation-kind'
                    data['message'] = 'Interrupted change type is unknown; automatic recovery is blocked.'
                    self.startup.lab_active = True
                    write_json(self.session_path, data)
                    return data

                if not mutation or mutation.get('kind') == 'instruction':
                    agents = agents_path(self.home)
                    raw_before = mutation.get('raw_before') if mutation else data.get('raw_before')
                    expected_after = mutation.get('expected_after') if mutation else None

                    if agents.exists() and raw_before is not None:
                        current = read_text(agents)
                        clean_current = current.replace('\r\n', '\n') if isinstance(current, str) else ''
                        clean_expected = expected_after.replace('\r\n', '\n') if isinstance(expected_after, str) else None
                        clean_raw = raw_before.replace('\r\n', '\n') if isinstance(raw_before, str) else ''

                        if clean_expected is not None and clean_current == clean_expected:
                            # Staged change is present without owner edits: restore safely
                            write_text(agents, raw_before)
                            data['phase'] = 'paused'
                            data['message'] = 'Recovered from restart. Pending mutation restored; session paused.'
                            data.pop('mutation', None)
                        elif clean_current == clean_raw:
                            # Already at baseline
                            data['phase'] = 'paused'
                            data['message'] = 'Recovered from restart. Workspace matches baseline; session paused.'
                            data.pop('mutation', None)
                        else:
                            # Owner modified AGENTS.md while offline: DO NOT overwrite!
                            data['phase'] = 'blocked'
                            data['failure_code'] = 'owner-edit-conflict'
                            data['message'] = 'Owner edit detected in AGENTS.md; preserved without overwriting. Session blocked.'
                    else:
                        data['phase'] = 'paused'
                        data['message'] = 'Recovered from restart. Workspace reset; session paused.'
                write_json(self.session_path, data)
            return data
        except (OSError, ValueError):
            return None

    def _save_session(self):
        """Durably persist current session state using atomic write."""
        with self.lock:
            if self.session is not None:
                self.session_path.parent.mkdir(parents=True, exist_ok=True)
                for attempt in range(5):
                    try:
                        write_json(self.session_path, self.session)
                        break
                    except (PermissionError, OSError):
                        if attempt == 4:
                            raise
                        time.sleep(0.05)

    def _restart_assistant(self, timeout=30, expected_model=None):
        """Restart local assistant via startup controller and wait until verified ready."""
        if not self.startup:
            return
        try:
            self.startup.stop()
        except Exception:
            pass
        try:
            self.startup.start(_reserved=True)
        except TypeError:
            self.startup.start()
        start_t = self.clock()
        while self.clock() - start_t < timeout:
            snap = self.startup.snapshot()
            if snap.get('phase') == 'failed':
                raise RuntimeError(f'Assistant startup failed: {snap.get("failure")}')
            phase_ready = snap.get('phase') == 'ready'
            verified = snap.get('model_reply_verified') is True
            gateway_ready = snap.get('gateway_ready', phase_ready) is True
            if phase_ready and verified and gateway_ready:
                if expected_model and snap.get('model') != expected_model:
                    raise RuntimeError('Assistant became ready on a different model than the selected model')
                return
            self.sleep_fn(0.2)
        raise TimeoutError('Assistant restart timed out waiting to become verified ready')

    def _ensure_assistant_ready(self, expected_model=None):
        """Reuse a child controller's verified restart, or perform one if still needed."""
        status = self.startup.snapshot() if self.startup and hasattr(self.startup, 'snapshot') else {}
        if (status.get('phase') == 'ready' and status.get('model_reply_verified') is True and
                status.get('gateway_ready') is True and
                (not expected_model or status.get('model') == expected_model)):
            return
        self._restart_assistant(expected_model=expected_model)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def snapshot(self):
        with self.lock:
            sess = self.session or {}
            phase = sess.get('phase', 'idle')
            active = bool(self.worker is not None and self.worker.is_alive() and
                          phase not in ('options-exhausted', 'plateau', 'budget-exhausted', 'stopped', 'blocked'))
            active = active or phase == 'undoing'

            countdown_info = None
            if phase == 'countdown' and self.current_action_id:
                remaining = max(0, int(self.countdown_deadline - self.clock()))
                countdown_info = {
                    'action_id': self.current_action_id,
                    'seconds_remaining': remaining,
                    'total_seconds': sess.get('countdown_seconds', 30),
                    'proposal': sess.get('proposal'),
                }

            clean_initial = (sess.get('initial_raw_before') or '').replace('\r\n', '\n')
            clean_kept = (sess.get('current_kept_raw') or '').replace('\r\n', '\n')
            initial_model_tag = sess.get('initial_model', {}).get('model')
            active_model_tag = sess.get('active_model', {}).get('model')
            can_undo = bool((sess.get('initial_raw_before') is not None and clean_kept != clean_initial) or
                            (initial_model_tag and active_model_tag and initial_model_tag != active_model_tag))

            return {
                'available': True,
                'active': active,
                'phase': phase,
                'session_id': sess.get('session_id'),
                'approved_envelope': sess.get('approved_envelope', DEFAULT_ENVELOPE),
                'budgets_used': sess.get('budgets_used', {
                    'duration_seconds': 0,
                    'completed_experiments': 0,
                    'model_downloads': 0,
                    'download_bytes': 0,
                }),
                'active_model': sess.get('active_model'),
                'curriculum_version': sess.get('curriculum_version', 'argos-foundation/1'),
                'starting_level': sess.get('starting_level'),
                'current_level': sess.get('current_level'),
                'proposal': sess.get('proposal'),
                'countdown': countdown_info,
                'progress': self.current_progress,
                'receipts': list(self.current_receipts),
                'history': sess.get('history', []),
                'message': sess.get('message', ''),
                'stopping_reason': sess.get('stopping_reason'),
                'failure_code': sess.get('failure_code'),
                'can_start': phase in ('idle', 'plateau', 'options-exhausted', 'budget-exhausted', 'stopped', 'blocked'),
                'can_pause': active and phase not in ('paused', 'stopped', 'plateau', 'options-exhausted', 'budget-exhausted', 'blocked', 'undoing'),
                'can_resume': phase == 'paused',
                'can_stop': (active and phase != 'undoing') or phase in ('countdown', 'paused'),
                'can_override': phase == 'countdown',
                'can_undo': can_undo and not active,
            }

    def start(self, envelope=None):
        """Start a new Auto Climb session within the approved envelope."""
        with self.startup.lock, self.lock:
            if self.closed:
                raise Refused('Auto Climb coordinator is closed')
            if (self.worker is not None and self.worker.is_alive()) or getattr(self.startup, 'lab_active', False):
                raise Refused('Another desktop workload is active')

            merged_envelope = validate_envelope(envelope)

            status_val = self.startup.snapshot() if hasattr(self.startup, 'snapshot') else {}
            active_tag = status_val.get('model', 'starter')
            active_digest = status_val.get('digest') or get_model_digest(active_tag)
            model_info = {'model': active_tag, 'digest': active_digest}

            if hasattr(self.runner, 'expected_model') and active_tag:
                self.runner.expected_model = active_tag

            session_id = str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

            raw_before = read_text(agents_path(self.home)) or ''
            fp = fingerprint(self.home)

            self.session = {
                'schema': SCHEMA,
                'session_id': session_id,
                'created_at': now_iso,
                'approved_envelope': merged_envelope,
                'budgets_used': {
                    'duration_seconds': 0,
                    'completed_experiments': 0,
                    'model_downloads': 0,
                    'download_bytes': 0,
                },
                'initial_model': dict(model_info),
                'active_model': model_info,
                'curriculum_version': 'argos-foundation/1',
                'phase': 'preflight',
                'message': 'Starting Auto Climb session…',
                'initial_raw_before': raw_before,
                'current_kept_raw': raw_before,
                'fingerprint': fp,
                'exposure_ledger': {
                    'consumed_partitions': [],
                },
                'history': [],
                'completed_candidates': [],
                'experiments_since_last_gain': 0,
                'starting_level': None,
                'current_level': None,
                'proposal': None,
                'countdown_seconds': 30,
                'stopping_reason': None,
                'failure_code': None,
            }
            self._save_session()

            self.pause_event.clear()
            self.cancel_event.clear()
            self.skip_event.clear()
            self.try_now_event.clear()
            self.stop_event.clear()
            self.current_progress = None
            self.current_receipts = []

            self.startup.lab_active = True
            self.worker = threading.Thread(target=self._run_session, daemon=True, name='auto-climb-coordinator')
            self.worker.start()
            return self.snapshot()

    def try_now(self, action_id):
        """Override countdown: proceed to the proposed action immediately."""
        with self.lock:
            if not self.session or self.session.get('phase') != 'countdown' or self.current_action_id != action_id:
                raise Refused('That proposal is no longer active')
            self.try_now_event.set()
            self.session['phase'] = 'stage'
            self._save_session()
            return self.snapshot()

    def skip(self, action_id):
        """Override countdown: skip the proposed candidate and propose another."""
        with self.lock:
            if not self.session or self.session.get('phase') != 'countdown' or self.current_action_id != action_id:
                raise Refused('That proposal is no longer active')
            self.current_action_id = None
            self.skip_event.set()
            return self.snapshot()

    def pause(self):
        """Pause Auto Climb (including during countdown or between steps)."""
        worker = None
        with self.lock:
            if self.session and self.session.get('phase') == 'undoing':
                raise Refused('Undo is finishing its model transaction; wait for it to complete')
            if not self.session or self.session.get('phase') in ('idle', 'stopped', 'plateau', 'options-exhausted', 'budget-exhausted', 'blocked'):
                raise Refused('No active Auto Climb session to pause')
            self.pause_event.set()
            self.cancel_event.set()
            self.current_action_id = None
            worker = self.worker

        # Join outside coordinator locks so worker can acquire self.lock to finalize
        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)

        with self.lock:
            if worker is not None and worker.is_alive():
                raise Refused('Previous Auto Climb worker is still terminating')
            self.worker = None
            self.session['phase'] = 'paused'
            self.session['message'] = 'Auto Climb paused. Resume whenever you are ready.'
            self._save_session()
            return self.snapshot()

    def resume(self):
        """Resume a paused Auto Climb session."""
        worker = None
        with self.lock:
            if not self.session or self.session.get('phase') != 'paused':
                raise Refused('Session is not paused')
            worker = self.worker

        # Wait outside coordinator locks if worker is still terminating
        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)

        with self.startup.lock, self.lock:
            if not self.session or self.session.get('phase') != 'paused':
                raise Refused('Session is not paused')
            if (self.worker is not None and self.worker.is_alive()) or (worker is not None and worker.is_alive()) or getattr(self.startup, 'lab_active', False):
                raise Refused('Previous Auto Climb worker is still terminating')

            self.worker = None
            self.pause_event.clear()
            self.cancel_event.clear()
            self.skip_event.clear()
            self.try_now_event.clear()
            self.stop_event.clear()

            self.session['phase'] = 'assess'
            self.session['message'] = 'Resuming Auto Climb…'
            self._save_session()

            self.startup.lab_active = True
            self.worker = threading.Thread(target=self._run_session, daemon=True, name='auto-climb-coordinator')
            self.worker.start()
            return self.snapshot()

    def stop(self):
        """Stop Auto Climb cleanly, restoring any in-flight mutation."""
        worker = None
        with self.lock:
            if self.session and self.session.get('phase') == 'undoing':
                raise Refused('Undo is finishing its model transaction; wait for it to complete')
            if not self.session or self.session.get('phase') in ('idle', 'stopped'):
                return self.snapshot()
            self.stop_event.set()
            self.cancel_event.set()
            self.current_action_id = None
            worker = self.worker

        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)

        with self.lock:
            if worker is not None and worker.is_alive():
                raise Refused('Previous Auto Climb worker is still terminating')
            self.worker = None

            # If mutation in flight, safely restore and propagate failure
            mutation = self.session.get('mutation')
            if mutation:
                try:
                    if mutation.get('kind') == 'model':
                        self._run_model_restore()
                    else:
                        self._restore_instruction(mutation.get('raw_before', ''), mutation.get('expected_after', ''))
                except Exception as exc:
                    self.session['phase'] = 'blocked'
                    self.session['failure_code'] = 'restore-failed'
                    self.session['message'] = f'Restoration failed during stop: {exc}'
                    self._save_session()
                    return self.snapshot()

            self.session['phase'] = 'stopped'
            self.session['stopping_reason'] = 'Stopped by owner'
            self.session['message'] = 'Auto Climb stopped.'
            self.startup.lab_active = False
            self._save_session()
            return self.snapshot()

    def undo(self):
        """Revert all kept changes from this session back to the initial baseline, protecting owner edits."""
        worker = None
        with self.lock:
            if not self.session:
                raise Refused('No Auto Climb session to undo')
            phase = self.session.get('phase')
            worker = self.worker
            if worker is not None and worker.is_alive() and phase not in (
                    'options-exhausted', 'plateau', 'budget-exhausted', 'stopped', 'paused', 'blocked'):
                raise Refused('Cannot undo while Auto Climb is actively running')
        if worker is not None and worker.is_alive():
            worker.join(timeout=2)

        with self.startup.lock, self.lock:
            if not self.session:
                raise Refused('No Auto Climb session to undo')
            if ((self.worker is not None and self.worker.is_alive()) or
                    getattr(self.startup, 'lab_active', False)):
                raise Refused('Cannot undo while Auto Climb is actively running')
            initial_raw = self.session.get('initial_raw_before')
            current_kept = self.session.get('current_kept_raw', initial_raw)
            clean_initial = initial_raw.replace('\r\n', '\n') if isinstance(initial_raw, str) else ''
            clean_kept = current_kept.replace('\r\n', '\n') if isinstance(current_kept, str) else ''
            instruction_changed = bool(initial_raw is not None and clean_kept != clean_initial)

            initial_model = self.session.get('initial_model')
            active_model = self.session.get('active_model')
            initial_tag = initial_model.get('model') if isinstance(initial_model, dict) else None
            active_tag = active_model.get('model') if isinstance(active_model, dict) else None
            model_changed = bool(initial_tag and active_tag and initial_tag != active_tag)

            if not instruction_changed and not model_changed:
                raise Refused('No kept changes to undo')

            if instruction_changed:
                agents = agents_path(self.home)
                current = read_text(agents)
                clean_current = current.replace('\r\n', '\n') if isinstance(current, str) else ''
                if clean_current != clean_kept:
                    raise Refused('Workspace was modified since Auto Climb; Undo blocked to preserve owner edits.')
            # Keep the workload reserved, then release locks before a child
            # selector runs; that worker must acquire startup.lock to complete.
            self.startup.lab_active = True
            self.session['phase'] = 'undoing'
            self.session['message'] = 'Restoring the session starting point…'
            self.session['mutation'] = ({
                'kind': 'model', 'candidate_id': f'undo-model-{initial_tag}',
            } if model_changed else {
                'kind': 'instruction', 'raw_before': current_kept,
                'expected_after': initial_raw,
            })
            self._save_session()

        try:
            if instruction_changed:
                write_text(agents, initial_raw)
                restored = read_text(agents)
                if (restored.replace('\r\n', '\n') if isinstance(restored, str) else '') != clean_initial:
                    raise ValueError('Undo could not be verified byte-for-byte')
                with self.lock:
                    self.session['current_kept_raw'] = initial_raw
                    self._save_session()
                if not model_changed:
                    self._restart_assistant()

            if model_changed:
                self._restore_kept_model(initial_tag)

            with self.startup.lock, self.lock:
                if model_changed:
                    self.session['active_model'] = dict(initial_model)
                self.session.pop('mutation', None)
                self.session['phase'] = 'stopped'
                self.session['stopping_reason'] = 'Undone to initial baseline by owner.'
                self.session['message'] = self.session['stopping_reason']
                self.startup.lab_active = False
                self._save_session()
                return self.snapshot()
        except Exception as exc:
            with self.lock:
                self.session['phase'] = 'blocked'
                self.session['failure_code'] = 'restore-failed'
                self.session['message'] = f'Undo could not be verified; recovery is blocked: {exc}'
                self._save_session()
            raise Refused('Undo could not be verified; recovery is blocked.') from exc

    def close(self):
        """Shutdown coordinator and wait for worker thread."""
        with self.lock:
            self.closed = True
            self.stop_event.set()
            self.cancel_event.set()
            worker = self.worker
        if worker and worker.is_alive():
            worker.join(timeout=5.0)
        with self.lock:
            self.worker = None

    # -------------------------------------------------------------------------
    # Execution Engine
    # -------------------------------------------------------------------------

    def _run_session(self):
        slice_start_time = self.clock()
        self._active_slice_start = slice_start_time
        try:
            # 1. Assessment / Baseline check
            if not self.session.get('starting_level'):
                self.session['phase'] = 'assess'
                self.session['message'] = 'Assessing your AI’s current baseline on foundation challenges…'
                self._save_session()

                practice_baseline = self._run_task_suite('baseline', self.practice_tasks, 'practice', slice_start_time=slice_start_time)
                if self._should_stop() or self.session.get('phase') == 'budget-exhausted':
                    return

                passed_practice = sum(1 for r in practice_baseline if r['passed'])

                baseline_level = {
                    'practice_passed': passed_practice,
                    'practice_total': len(practice_baseline),
                    'validation_passed': 0,
                    'validation_total': 0,
                    'label': f'{passed_practice}/{len(practice_baseline)} practice',
                }
                self.session['starting_level'] = baseline_level
                self.session['current_level'] = baseline_level
                self.session['practice_baseline'] = practice_baseline
                self._save_session()

            # Main experiment loop
            while not self._should_stop() and self.session.get('phase') not in ('budget-exhausted', 'blocked'):
                # Check budgets before selecting candidate
                if self._check_budget_exhaustion(slice_start_time, before_candidate=True):
                    break

                # 2. Select next candidate
                candidate = self._select_next_candidate()
                if candidate is None:
                    # Differentiate plateau vs options exhausted
                    if self.session.get('experiments_since_last_gain', 0) >= 3:
                        self.session['phase'] = 'plateau'
                        self.session['stopping_reason'] = 'Plateau within this session’s tested options: 3 consecutive experiments showed no validated gain and all options evaluated.'
                    else:
                        self.session['phase'] = 'options-exhausted'
                        self.session['stopping_reason'] = 'Options exhausted within approved session.'
                    self.session['message'] = self.session['stopping_reason']
                    self._save_session()
                    break

                # 3. Propose candidate and Countdown
                action_id = str(uuid.uuid4())
                with self.lock:
                    self.current_action_id = action_id
                    self.countdown_deadline = self.clock() + 30.0
                    self.session['phase'] = 'countdown'
                    self.session['proposal'] = candidate
                    self.session['message'] = f'Suggested next improvement: {candidate["title"]}'
                    self._save_session()

                countdown_result = self._await_countdown(action_id)

                if countdown_result == 'stopped':
                    break
                if countdown_result == 'paused':
                    break
                if countdown_result == 'skipped':
                    self.session.setdefault('completed_candidates', []).append(candidate['id'])
                    self.session['history'].append({
                        'candidate': candidate,
                        'verdict': 'skipped',
                        'reason': 'Skipped by owner during 30-second preview.',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    })
                    self._save_session()
                    continue

                # 4. Countdown passed or Try Now clicked -> Reserve experiment slot durably!
                budgets = self.session.setdefault('budgets_used', {})
                budgets['completed_experiments'] = budgets.get('completed_experiments', 0) + 1
                self._save_session()

                # Execute experiment!
                self._execute_experiment(candidate, slice_start_time)

                # Check plateau policy after experiment
                if self.session.get('experiments_since_last_gain', 0) >= 3:
                    remaining = self._select_next_candidate()
                    if remaining is None:
                        self.session['phase'] = 'plateau'
                        self.session['stopping_reason'] = 'Plateau within this session’s tested options: 3 consecutive experiments showed no validated gain and all options evaluated.'
                        self.session['message'] = self.session['stopping_reason']
                        self._save_session()
                        break

        except Exception as error:
            # Preserve the cause privately without putting paths/configuration
            # into the public coordinator message.
            from .private_files import private_log
            try:
                root = storage.safe_local(self.home / '.local/state/argos-live')
                root.mkdir(mode=0o700, parents=True, exist_ok=True)
                with private_log(root / 'auto-climb-failure.log') as log:
                    log.write(traceback.format_exc().encode()[-65536:])
            except (OSError, ValueError):
                pass
            with self.lock:
                if self.session.get('failure_code') in ('restore-failed', 'owner-edit-conflict', 'corrupt-inventory'):
                    return
                mutation = self.session.get('mutation')
                if mutation:
                    try:
                        if mutation.get('kind') == 'model':
                            self._run_model_restore()
                        else:
                            self._restore_instruction(mutation.get('raw_before', ''), mutation.get('expected_after', ''))
                    except Exception as cleanup_err:
                        self.session['phase'] = 'blocked'
                        self.session['failure_code'] = 'restore-failed'
                        self.session['message'] = f'Restoration failed after error: {cleanup_err}'
                        self._save_session()
                        return
                self.session['phase'] = 'blocked'
                self.session['failure_code'] = error.code if isinstance(error, TrialTurnError) else 'coordinator-error'
                self.session['message'] = ('The assistant could not finish a test answer. No gain was accepted. '
                                           'The previous kept build was restored.' if mutation else
                                           'The climb could not finish its checks. No gain was accepted.')
                if self.session.get('proposal'):
                    self.session.setdefault('history', []).append({
                        'candidate': self.session['proposal'], 'verdict': 'failed',
                        'reason': self.session['message'],
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    })
                self._save_session()
        finally:
            with self.lock:
                # Accumulate elapsed slice duration
                elapsed = max(0, int(self.clock() - slice_start_time))
                budgets = self.session.setdefault('budgets_used', {})
                budgets['duration_seconds'] = budgets.get('duration_seconds', 0) + elapsed
                self._save_session()
                if self.child_worker is not None and self.child_worker.is_alive():
                    self.session['phase'] = 'blocked'
                    self.session['failure_code'] = 'child-worker-stuck'
                    self.session['message'] = 'A delegated model operation did not stop safely. The workload remains reserved for recovery.'
                    self._save_session()
                else:
                    self.startup.lab_active = False
                self._active_slice_start = None

    def _should_stop(self):
        return self.closed or self.stop_event.is_set() or self.pause_event.is_set()

    def _await_countdown(self, action_id):
        """Run countdown loop on server. Returns 'proceed', 'try-now', 'skipped', 'paused', or 'stopped'."""
        self.try_now_event.clear()
        self.skip_event.clear()

        while self.clock() < self.countdown_deadline:
            if self._should_stop():
                return 'stopped' if self.stop_event.is_set() else 'paused'
            if self.skip_event.is_set():
                return 'skipped'
            if self.try_now_event.is_set():
                return 'try-now'
            self.sleep_fn(0.1)

        if self._should_stop():
            return 'stopped' if self.stop_event.is_set() else 'paused'
        return 'proceed'

    def _check_budget_exhaustion(self, slice_start_time, *, before_candidate=False):
        envelope = self.session.get('approved_envelope', DEFAULT_ENVELOPE)
        budgets = self.session.get('budgets_used', {})
        current_slice = int(self.clock() - slice_start_time)
        total_duration = budgets.get('duration_seconds', 0) + current_slice

        # Slots are reserved before execution. Permit the final reserved attempt
        # to finish; enforce the attempt cap before choosing the next candidate.
        if before_candidate and budgets.get('completed_experiments', 0) >= envelope.get('max_experiments', 6):
            self.session['phase'] = 'budget-exhausted'
            self.session['stopping_reason'] = f'Session limit reached: {envelope.get("max_experiments")} attempts used.'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return True

        if total_duration >= envelope.get('max_duration_seconds', 3600):
            self.session['phase'] = 'budget-exhausted'
            self.session['stopping_reason'] = f'Session time budget reached ({envelope.get("max_duration_seconds") // 60} minutes).'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return True

        return False

    def _remaining_duration(self, slice_start_time):
        envelope = self.session.get('approved_envelope', DEFAULT_ENVELOPE)
        budgets = self.session.get('budgets_used', {})
        elapsed = max(0, self.clock() - slice_start_time)
        return max(0.0, envelope.get('max_duration_seconds', 3600) -
                   budgets.get('duration_seconds', 0) - elapsed)

    def _select_next_candidate(self):
        completed = set(self.session.get('completed_candidates', []))
        # A kept/owner-existing instruction is part of the starting build, not
        # a new candidate. Never append its managed block a second time.
        existing = read_text(agents_path(self.home)) or ''
        completed.update(c['id'] for c in self.candidate_pool
                         if c.get('kind') == 'instruction' and
                         'argos-trial:' + c.get('change_id', c['id']) + ' ' in existing)

        # Prefer the cheapest reviewed intervention when all observed misses
        # have the same precise cause. Validation and promotion remain unchanged.
        misses = [r for r in self.session.get('practice_baseline', []) if not r.get('passed')]
        quote_only = len(misses) >= 2 and all(
            r.get('kind') == 'answer' and r.get('checks', {}).get('exact_quote') is False and
            r.get('checks', {}).get('answer_present') is True and
            r.get('checks', {}).get('answer_first') is True for r in misses)
        if quote_only:
            for candidate in self.candidate_pool:
                if candidate['id'] == 'quote-evidence' and candidate['id'] not in completed:
                    return dict(candidate, rationale='The answers were correct, but supporting quotes were missing. '
                                'Try the reviewed source-quote instruction before changing models.')

        # Check model recommendation candidate first if available (AC3)
        if self.model_recommender:
            envelope = self.session.get('approved_envelope', DEFAULT_ENVELOPE)
            budgets = self.session.get('budgets_used', {})
            options = {'envelope': envelope, 'budgets': budgets}
            if self.model_recommender is recommend_hardware_model:
                options['excluded_candidates'] = completed
            rec = self.model_recommender(self.home, **options)
            if rec and rec['id'] not in completed:
                return rec

        for cand in self.candidate_pool:
            if cand['id'] not in completed:
                return cand
        return None

    def _execute_experiment(self, candidate, slice_start_time):
        """Reversibly stage candidate, retest, validate on fresh partitions, and Keep or Restore."""
        kind = candidate.get('kind', 'instruction')
        raw_before = read_text(agents_path(self.home)) or ''
        prev_model = self.session.get('active_model', {}).get('model', starter.TAG)

        # 0. If model requires download, perform acquisition first
        if kind == 'model' and candidate.get('needs_download'):
            if candidate.get('storage_needed'):
                self.session.setdefault('completed_candidates', []).append(candidate['id'])
                self.session.setdefault('history', []).append({
                    'experiment_index': self.session.get('budgets_used', {}).get('completed_experiments', 0),
                    'candidate': candidate,
                    'verdict': 'skipped',
                    'reason': 'Choose model storage before downloading a model.',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })
                self._save_session()
                return

            self.session['phase'] = 'acquire'
            self.session['message'] = f'Downloading {candidate["title"]} ({candidate["cost"]})…'
            self._save_session()

            dl_ok = self._run_model_download(candidate)
            if not dl_ok:
                self.session.setdefault('completed_candidates', []).append(candidate['id'])
                self.session.setdefault('history', []).append({
                    'experiment_index': self.session.get('budgets_used', {}).get('completed_experiments', 0),
                    'candidate': candidate,
                    'verdict': 'failed',
                    'reason': f'Download failed for {candidate["tag"]}. ' + self.session.get('download_failure', 'No model change was made.'),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })
                self._save_session()
                return

        fp_before = fingerprint(self.home)
        change_id = candidate.get('change_id')
        raw_after = staged(raw_before, change_id) if change_id else raw_before

        fresh = self._get_fresh_partitions(2)
        if fresh is None or len(fresh) < 2:
            self.session['phase'] = 'options-exhausted'
            self.session['stopping_reason'] = 'Fresh validation inventory exhausted; automatic promotion paused.'
            self.session['message'] = self.session['stopping_reason']
            self._save_session()
            return

        p1, p2 = fresh[0], fresh[1]

        # Reserve and record both partitions as consumed globally BEFORE running any turns
        self._consume_partitions([p1['id'], p2['id']],
                                 session_id=self.session['session_id'],
                                 candidate_id=candidate['id'],
                                 reason='reserved-before-baseline')

        self.session['phase'] = 'assess'
        self.session['message'] = 'Checking the current kept build before trying this change...'
        self._save_session()
        p_baselines = self.session.setdefault('partition_baselines', {})
        p1_baseline = self._run_task_suite('baseline', p1, f'kept-{p1["id"]}', slice_start_time=slice_start_time)
        if self._should_stop() or self.session.get('phase') == 'budget-exhausted':
            return
        p2_baseline = self._run_task_suite('baseline', p2, f'kept-{p2["id"]}', slice_start_time=slice_start_time)
        if self._should_stop() or self.session.get('phase') == 'budget-exhausted':
            return
        p_baselines[p1['id']] = p1_baseline
        p_baselines[p2['id']] = p2_baseline
        self._save_session()

        # 1. Journal mutation before write
        self.session['phase'] = 'stage'
        self.session['message'] = f'Staging: {candidate["title"]}…'
        self.session['mutation'] = {
            'kind': kind,
            'raw_before': raw_before,
            'expected_after': raw_after,
            'fingerprint': fp_before,
            'candidate_id': candidate['id'],
            'staged_at': datetime.now(timezone.utc).isoformat(),
        }
        self._save_session()

        if kind == 'instruction':
            write_text(agents_path(self.home), raw_after)
            self._restart_assistant()
        elif kind == 'model':
            switch_ok = self._run_model_switch(candidate['tag'])
            if not switch_ok:
                self._run_model_restore()
                self.session.setdefault('completed_candidates', []).append(candidate['id'])
                self.session.setdefault('history', []).append({
                    'experiment_index': self.session.get('budgets_used', {}).get('completed_experiments', 0),
                    'candidate': candidate,
                    'verdict': 'failed',
                    'reason': f'Assistant model switch to {candidate["tag"]} failed; restored previous model {prev_model}.',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })
                self._save_session()
                return

        # 2. Retest practice challenges
        self.session['phase'] = 'retest'
        self.session['message'] = f'Evaluating {candidate["title"]} on practice challenges…'
        self._save_session()

        practice_retest = self._run_task_suite('practice', self.practice_tasks, candidate['title'], slice_start_time=slice_start_time)
        if self._should_stop() or self.session.get('phase') == 'budget-exhausted':
            try:
                if kind == 'instruction':
                    self._restore_instruction(raw_before, raw_after)
                elif kind == 'model':
                    self._run_model_restore()
            except Exception as exc:
                self.session['phase'] = 'blocked'
                self.session['failure_code'] = 'restore-failed'
                self.session['message'] = f'Restoration failed: {exc}'
                self._save_session()
                raise
            return

        # Compare against REBASED practice baseline (current kept build)
        practice_comp = assistant_trial.compare(self.session['practice_baseline'], practice_retest)
        practice_improved = len(practice_comp['gains']) >= 2 and not practice_comp['regressions']

        validation_comp = None
        verdict = 'restored'
        decision_reason = ''

        if practice_improved:
            # 3. Independent Fresh Held-Out Validation!
            self.session['phase'] = 'validate'
            self.session['message'] = 'Practice showed gains. Verifying on fresh independent validation partition…'
            self._save_session()

            val1_retest = self._run_task_suite('validation', p1, candidate['title'], slice_start_time=slice_start_time)
            if self._should_stop() or self.session.get('phase') == 'budget-exhausted':
                try:
                    if kind == 'instruction':
                        self._restore_instruction(raw_before, raw_after)
                    elif kind == 'model':
                        self._run_model_restore()
                except Exception as exc:
                    self.session['phase'] = 'blocked'
                    self.session['failure_code'] = 'restore-failed'
                    self.session['message'] = f'Restoration failed: {exc}'
                    self._save_session()
                    raise
                return

            comp1 = assistant_trial.compare(p1_baseline, val1_retest)
            val1_improved = len(comp1['gains']) >= 1 and not comp1['regressions']

            if not val1_improved:
                verdict = 'restored'
                decision_reason = 'Practice showed potential gains, but fresh validation partition 1 did not confirm generalization.'
                validation_comp = comp1
            else:
                # 4. Confirmation on a SECOND disjoint fresh partition!
                val2_retest = self._run_task_suite('validation', p2, candidate['title'], slice_start_time=slice_start_time)
                if self._should_stop() or self.session.get('phase') == 'budget-exhausted':
                    try:
                        if kind == 'instruction':
                            self._restore_instruction(raw_before, raw_after)
                        elif kind == 'model':
                            self._run_model_restore()
                    except Exception as exc:
                        self.session['phase'] = 'blocked'
                        self.session['failure_code'] = 'restore-failed'
                        self.session['message'] = f'Restoration failed: {exc}'
                        self._save_session()
                        raise
                    return

                comp2 = assistant_trial.compare(p2_baseline, val2_retest)
                val2_improved = len(comp2['gains']) >= 1 and not comp2['regressions']

                if val2_improved:
                    verdict = 'kept'
                    decision_reason = 'Confirmed gain on both disjoint fresh validation partitions.'
                    validation_comp = comp2
                else:
                    verdict = 'restored'
                    decision_reason = 'Validation partition 1 showed gains, but disjoint confirmation partition did not confirm.'
                    validation_comp = comp2
        else:
            verdict = 'restored'
            decision_reason = (f'Practice challenges did not meet win threshold ({len(practice_comp["gains"])} gains, '
                               f'{len(practice_comp["regressions"])} regressions; needs ≥2 gains, 0 regressions).')

        # 5. Keep or Restore
        self.session['phase'] = 'keep-or-restore'
        self.session['message'] = f'Decision: {verdict.upper()} ({decision_reason})'
        self._save_session()

        if verdict == 'kept':
            # Rebase practice baseline onto the newly verified kept build!
            self.session['practice_baseline'] = practice_retest
            p_baselines[p1['id']] = val1_retest
            p_baselines[p2['id']] = val2_retest
            if kind == 'instruction':
                self.session['current_kept_raw'] = read_text(agents_path(self.home))
                self.session['raw_before'] = self.session['current_kept_raw']
            elif kind == 'model':
                self._run_model_keep()
                model_tag = candidate.get('tag')
                model_digest = candidate.get('manifest_digest') or get_model_digest(model_tag)
                self.session['active_model'] = {'model': model_tag, 'digest': model_digest}
                if hasattr(self.runner, 'expected_model') and model_tag:
                    self.runner.expected_model = model_tag
            self.session['experiments_since_last_gain'] = 0
            self.session.pop('mutation', None)

            # Update current level metrics
            passed_practice = sum(1 for r in practice_retest if r['passed'])
            passed_val = sum(1 for r in val2_retest if r['passed']) if 'val2_retest' in locals() else 0
            self.session['current_level'] = {
                'practice_passed': passed_practice,
                'practice_total': len(practice_retest),
                'validation_passed': passed_val,
                'validation_total': len(val2_retest) if 'val2_retest' in locals() else 8,
                'label': f'{passed_practice}/{len(practice_retest)} practice · {passed_val}/8 validation',
            }
        else:
            try:
                if kind == 'instruction':
                    self._restore_instruction(raw_before, raw_after)
                elif kind == 'model':
                    self._run_model_restore()
            except Exception as exc:
                self.session['phase'] = 'blocked'
                self.session['failure_code'] = 'restore-failed'
                self.session['message'] = f'Restoration failed: {exc}'
                self._save_session()
                raise
            self.session['experiments_since_last_gain'] = self.session.get('experiments_since_last_gain', 0) + 1

        # Record experiment record in session history
        budgets = self.session.setdefault('budgets_used', {})
        self.session.setdefault('completed_candidates', []).append(candidate['id'])
        self.session.setdefault('history', []).append({
            'experiment_index': budgets.get('completed_experiments', 0),
            'candidate': candidate,
            'verdict': verdict,
            'reason': decision_reason,
            'practice_comparison': {
                'gains': practice_comp.get('gains', []),
                'regressions': practice_comp.get('regressions', []),
                'totals': practice_comp.get('totals', {}),
            },
            'validation_comparison': {
                'gains': validation_comp.get('gains', []) if validation_comp else [],
                'regressions': validation_comp.get('regressions', []) if validation_comp else [],
                'totals': validation_comp.get('totals', {}) if validation_comp else {},
            } if validation_comp else None,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        self._save_session()

    def _restore_instruction(self, raw_before, raw_after):
        """Guarded restoration checking for owner edits."""
        agents = agents_path(self.home)
        if not agents.exists():
            return
        current = read_text(agents)
        clean_current = current.replace('\r\n', '\n') if isinstance(current, str) else ''
        clean_after = raw_after.replace('\r\n', '\n') if isinstance(raw_after, str) else ''
        clean_before = raw_before.replace('\r\n', '\n') if isinstance(raw_before, str) else ''

        if clean_current == clean_after:
            write_text(agents, raw_before)
            restored = read_text(agents)
            if (restored.replace('\r\n', '\n') if isinstance(restored, str) else '') != clean_before:
                raise ValueError('Restoration could not be verified byte-for-byte')
            self.session.pop('mutation', None)
            self._restart_assistant()
        elif clean_current == clean_before:
            self.session.pop('mutation', None)
        else:
            # Owner edit detected! DO NOT overwrite!
            self.session['phase'] = 'blocked'
            self.session['failure_code'] = 'owner-edit-conflict'
            self.session['message'] = 'Owner edit detected during experiment; preserved without overwriting. Session blocked.'
            self._save_session()
            raise Refused('Owner edit detected during experiment; preserved without overwriting.')

    def _settle_child(self, worker, cancel_fn=None, timeout=300.0):
        """Wait for child worker thread within timeout; cancel and join if overdue."""
        if worker is None:
            return True
        self.child_worker = worker
        deadline = time.monotonic() + max(0, timeout)
        interrupted = False
        while worker.is_alive():
            if self._should_stop():
                interrupted = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=min(.1, remaining))
        if worker.is_alive():
            if cancel_fn:
                try:
                    cancel_fn()
                except Exception:
                    pass
            worker.join(timeout=5.0)
            if worker.is_alive():
                raise RuntimeError('Child worker thread timed out and could not be terminated')
            self.child_worker = None
            if interrupted:
                return False
            raise RuntimeError('Child worker thread timed out and was cancelled')
        self.child_worker = None
        return not interrupted

    def _run_model_download(self, candidate):
        self.session.pop('download_failure', None)
        tag = candidate['tag']
        download_bytes = candidate.get('download_bytes', 0)
        budgets = self.session.setdefault('budgets_used', {})

        # Always charge download attempts and bytes even on failure
        budgets['model_downloads'] = budgets.get('model_downloads', 0) + 1
        budgets['download_bytes'] = budgets.get('download_bytes', 0) + download_bytes
        self._save_session()

        if self.download_runner:
            try:
                ok = self.download_runner(tag)
                return bool(ok)
            except Exception:
                return False

        if self.downloads:
            try:
                # Retain lab_active throughout child delegation
                self.downloads.start(tag=tag, _delegated=True)
                if hasattr(self.downloads, 'worker') and self.downloads.worker:
                    cancel_fn = getattr(self.downloads, 'cancel', None)
                    remaining = self._remaining_duration(self._active_slice_start)
                    if remaining <= 0:
                        self._check_budget_exhaustion(self._active_slice_start)
                        cancel_fn() if cancel_fn else None
                        return False
                    settled = self._settle_child(self.downloads.worker, cancel_fn=cancel_fn,
                                                 timeout=min(300.0, remaining))
                    if not settled:
                        self.session['download_failure'] = 'Download stopped at the operation time limit; partial download retained. No model change was made.'
                        return False
                snap = self.downloads.snapshot()
                return snap.get('phase') == 'completed'
            except Exception:
                return False

        # Fail closed if downloader unavailable (never synthetic success)
        return False

    def _run_model_switch(self, tag):
        if self.model_switcher:
            ok = self.model_switcher(tag)
            if ok is not False:
                self._restart_assistant()
                if hasattr(self.runner, 'expected_model'):
                    self.runner.expected_model = tag
                return True
            return False

        if self.selection:
            try:
                self.selection.start(tag=tag, _delegated=True)
            except TypeError:
                self.selection.start(tag=tag)
            if hasattr(self.selection, 'worker') and self.selection.worker:
                cancel_fn = getattr(self.selection, 'cancel', None)
                remaining = self._remaining_duration(self._active_slice_start)
                if remaining <= 0:
                    self._check_budget_exhaustion(self._active_slice_start)
                    cancel_fn() if cancel_fn else None
                    return False
                if not self._settle_child(self.selection.worker, cancel_fn=cancel_fn,
                                          timeout=min(300.0, remaining)):
                    return False
            snap = self.selection.snapshot()
            if snap.get('phase') == 'completed':
                self._ensure_assistant_ready(expected_model=tag)
                if hasattr(self.runner, 'expected_model'):
                    self.runner.expected_model = tag
                return True
            return False

        # Use reviewed model_selection controller with journaled transactions
        sel = model_selection.Controller(self.startup)
        self.selection = sel
        sel.start(tag=tag, _delegated=True)
        if hasattr(sel, 'worker') and sel.worker:
            cancel_fn = getattr(sel, 'cancel', None)
            remaining = self._remaining_duration(self._active_slice_start)
            if remaining <= 0:
                self._check_budget_exhaustion(self._active_slice_start)
                cancel_fn() if cancel_fn else None
                return False
            if not self._settle_child(sel.worker, cancel_fn=cancel_fn,
                                      timeout=min(300.0, remaining)):
                return False
        snap = sel.snapshot()
        if snap.get('phase') == 'completed':
            self._ensure_assistant_ready(expected_model=tag)
            if hasattr(self.runner, 'expected_model'):
                self.runner.expected_model = tag
            return True
        return False

    def _run_model_restore(self):
        """Restore previous model; propagate errors and never swallow exceptions."""
        prev_model = self.session.get('active_model', {}).get('model', 'starter')
        if self.model_restorer:
            if self.model_restorer() is False:
                raise RuntimeError('Model restoration was rejected')
            self._ensure_assistant_ready(expected_model=prev_model)
            if hasattr(self.runner, 'expected_model') and prev_model:
                self.runner.expected_model = prev_model
            self.session.pop('mutation', None)
            return

        if self.selection:
            try:
                self.selection.start_restore(_delegated=True)
            except TypeError:
                self.selection.start_restore()
            if hasattr(self.selection, 'worker') and self.selection.worker:
                cancel_fn = getattr(self.selection, 'cancel', None)
                self._settle_child(self.selection.worker, cancel_fn=cancel_fn, timeout=300.0)
            snap = self.selection.snapshot()
            if snap.get('phase') != 'completed':
                if configured_model(self.home) != prev_model:
                    raise RuntimeError(f'Model restoration did not complete: {snap.get("phase")}')
            self._ensure_assistant_ready(expected_model=prev_model)
            if hasattr(self.runner, 'expected_model') and prev_model:
                self.runner.expected_model = prev_model
            self.session.pop('mutation', None)
            return

        ok = model_selection.restore(self.home)
        if not ok:
            if configured_model(self.home) != prev_model:
                raise RuntimeError('Model restoration failed to restore previous state')
        self._ensure_assistant_ready(expected_model=prev_model)
        if hasattr(self.runner, 'expected_model') and prev_model:
            self.runner.expected_model = prev_model
        self.session.pop('mutation', None)

    def _run_model_keep(self):
        """Finalize model keep transaction; propagate errors."""
        if self.selection:
            if self.selection.keep_current() is False:
                raise RuntimeError('Model Keep could not finalize its rollback transaction')
            return
        if self.model_switcher is None and model_selection.keep_current(self.home) is False:
            raise RuntimeError('Model Keep could not finalize its rollback transaction')

    def _restore_kept_model(self, target_tag):
        """Select a previously kept model through the normal journaled model-selection path."""
        if self.model_restorer:
            if self.model_restorer() is False:
                raise RuntimeError('Model Undo was rejected')
            self._restart_assistant()
            if hasattr(self.runner, 'expected_model'):
                self.runner.expected_model = target_tag
            return
        selection = self.selection or model_selection.Controller(self.startup)
        self.selection = selection
        selection.start(tag=target_tag, _delegated=True)
        if hasattr(selection, 'worker') and selection.worker:
            self._settle_child(selection.worker, cancel_fn=getattr(selection, 'cancel', None), timeout=300.0)
        snap = selection.snapshot()
        if snap.get('phase') != 'completed':
            raise RuntimeError(f'Model Undo selection did not complete: {snap.get("phase")}')
        self._ensure_assistant_ready(expected_model=target_tag)
        if configured_model(self.home) != target_tag:
            raise RuntimeError('Model Undo did not restore the initial configured model')
        if selection.keep_current() is False:
            raise RuntimeError('Model Undo could not finalize its transaction')
        if hasattr(self.runner, 'expected_model'):
            self.runner.expected_model = target_tag

    def _run_task_suite(self, side, suite, label, slice_start_time=None):
        """Run tasks through OpenClaw runner turn-by-turn with live streaming progress."""
        if self.runner is None or not hasattr(self.runner, 'turn'):
            raise TrialTurnError('missing-runner')

        results = []
        passages = suite.get('passages', {})
        tasks = suite.get('tasks', [])
        total = len(tasks)

        self.current_receipts = []

        for idx, task in enumerate(tasks):
            if self._should_stop():
                break
            if slice_start_time is not None and self._check_budget_exhaustion(slice_start_time):
                break
            remaining = self._remaining_duration(slice_start_time) if slice_start_time is not None else None
            if remaining is not None and remaining <= 0:
                self._check_budget_exhaustion(slice_start_time)
                break

            prompt_msg = message(task, passages)
            current_item = {
                'id': task['id'],
                'kind': task['kind'],
                'question': task.get('question') or task.get('message'),
                'passage': passages.get(task.get('passage')),
            }

            self.current_progress = {
                'side': side,
                'label': label,
                'done': idx,
                'total': total,
                'current': current_item,
            }

            start_t = self.clock()
            try:
                if remaining is not None and isinstance(self.runner, assistant_trial.OpenClawRunner):
                    turn_res = self.runner.turn(prompt_msg, timeout=remaining)
                else:
                    turn_res = self.runner.turn(prompt_msg)
            except TrialTurnError as exc:
                if self._should_stop() or (hasattr(exc, 'code') and exc.code == 'cancelled'):
                    break
                if (slice_start_time is not None and
                        hasattr(exc, 'code') and exc.code == 'turn-timeout' and
                        self._check_budget_exhaustion(slice_start_time)):
                    break
                raise
            if isinstance(turn_res, dict):
                reply_text = turn_res.get('text', '')
                elapsed = turn_res.get('elapsed_seconds', round(self.clock() - start_t, 2))
            elif isinstance(turn_res, str):
                reply_text = turn_res
                elapsed = round(self.clock() - start_t, 2)
            else:
                raise TrialTurnError('invalid-reply')

            if not reply_text or not reply_text.strip():
                raise TrialTurnError('empty-reply')

            score_res = score(task, passages, reply_text)
            receipt = {
                'id': task['id'],
                'kind': task['kind'],
                'passed': score_res['passed'],
                'checks': score_res['checks'],
                'reply': {
                    'text': reply_text,
                    'elapsed_seconds': elapsed,
                    'session_id': getattr(self.runner, 'session_id', None) or f'turn-{idx}',
                },
                'elapsed_seconds': elapsed,
            }

            results.append(receipt)
            self.current_receipts.append(receipt)
            self.current_progress['latest'] = receipt
            self.current_progress['done'] = idx + 1

        return results
