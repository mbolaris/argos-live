"""Persistent owner-started queue for sequential Shakedown laps."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import threading

from .. import storage
from ..ollama import Client
from ..pull_jobs import read_json, write_json
from . import lap, loadout


MAX_ENTRIES = 12
_LOADOUT_ID = re.compile(r'^[0-9a-f]{24}$')


class QueueController:
    def __init__(self, home, store, *, jobs_factory=None, model_client_factory=Client):
        self.home = Path(home).absolute()
        self.store = store
        self.jobs_factory = jobs_factory
        self.model_client_factory = model_client_factory
        self.root = storage.safe_local(self.home / '.local/state/argos-live/shakedown-queue')
        self.path = storage.safe_local(self.root / 'current.json')
        self.lock = threading.RLock()
        self.worker = None
        self.cancel_event = None
        self.record = None
        self._load_saved()

    @staticmethod
    def _stamp():
        return datetime.now(timezone.utc).isoformat()

    def _persist(self):
        if self.record is not None:
            self.record['updated_at'] = self._stamp()
            write_json(self.path, self.record)

    def _load_saved(self):
        try:
            value = read_json(self.path)
            if not isinstance(value, dict) or value.get('schema') != 'argos-shakedown-queue/1':
                return
            self.record = value
            if value.get('state') == 'running':
                entries = value.get('entries', [])
                position = value.get('active_entry')
                if type(position) is not int:
                    position = max(0, value.get('position', 1) - 1)
                if isinstance(entries, list) and 0 <= position < len(entries):
                    entries[position].update(state='interrupted', failure='dashboard-restarted')
                    for entry in entries[position + 1:]:
                        entry.update(state='skipped', failure='queue-not-resumed')
                value.update(state='interrupted', outcome='interrupted', complete=False,
                             active_entry=None, notice='Queue stopped when Argos restarted. No entries resumed.')
                self._persist()
        except (OSError, ValueError, TypeError):
            self.record = None

    def snapshot(self):
        with self.lock:
            return deepcopy(self.record) if self.record is not None else {
                'available': True, 'schema': 'argos-shakedown-queue/1', 'state': 'idle',
                'entries': [], 'position': 0, 'estimate': None, 'notice': None}

    def choices(self):
        return [{'id': ident, 'model': value['run'].get('model'),
                 'name': value['run'].get('model', 'Saved build') + ' · ' + str(
                     loadout.snapshot(value['run'])['recipe'].get('context'))}
                for ident, value in self._source_runs().items()]

    def _source_runs(self):
        grouped = {}
        runs = []
        for row in self.store.list().get('runs', []):
            try:
                run = self.store.load(row['id'])
                ident = loadout.snapshot(run)['id']
                runs.append((ident, run))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
        runs.sort(key=lambda item: (item[1].get('created') or '', item[1].get('id') or ''), reverse=True)
        for ident, run in runs:
            grouped.setdefault(ident, []).append(run)
        result = {}
        for ident, items in grouped.items():
            complete_abilities = [run for run in items if run.get('kind') == 'ability' and
                                  run.get('state') == 'completed' and
                                  isinstance(run.get('coverage'), dict) and
                                  run['coverage'].get('complete') is True]
            if not complete_abilities:
                continue
            source = complete_abilities[0]
            speed = next((run for run in items if run.get('kind') == 'speed'), None)
            ability = complete_abilities[0]
            result[ident] = {'run': source, 'latest_speed': speed, 'last_run': ability}
        return result

    @staticmethod
    def _model_tag(model):
        if not isinstance(model, str) or not model.startswith('ollama/'):
            raise ValueError('This build does not have a supported local Ollama model identity')
        tag = model.removeprefix('ollama/')
        if (not tag or len(tag) > 256 or any(char.isspace() for char in tag) or
                '/' in tag or '\\' in tag):
            raise ValueError('This build does not have a supported local Ollama model identity')
        return tag

    def _preflight(self, entries):
        from ..evaluation_context import configuration_receipt
        sources = self._source_runs()
        plans = []
        tags = set()
        for value in entries:
            if not isinstance(value, dict) or set(value) != {'loadout_id', 'size'}:
                raise ValueError('Each queue entry needs a saved build and lap size')
            ident, size = value['loadout_id'], value['size']
            if not isinstance(ident, str) or not _LOADOUT_ID.fullmatch(ident) or ident not in sources:
                raise ValueError('Choose a build from saved Shakedown results')
            if size not in lap.SIZES:
                raise ValueError('Choose quick, standard or full for every lap')
            source_record = sources[ident]
            source = source_record['run']
            tag = self._model_tag(source.get('model'))
            recipe = source.get('settings', {}).get('recipe')
            configuration_receipt(self.home, model_tag=tag, recipe=recipe)
            if recipe is not None:
                from .. import recipe as recipe_mod
                recipe_mod.validate(recipe)
            tags.add(tag)
            plan = lap.build(size, model_tag=tag, recipe=recipe)
            estimate = lap.estimate(plan, {'latest_speed': source_record['latest_speed'],
                                           'last_run': source_record['last_run']})
            plans.append({'loadout_id': ident, 'size': size, 'model_tag': tag, 'recipe': recipe,
                          'plan': plan, 'estimate': estimate,
                          'state': 'queued', 'steps': [], 'failure': None})
        if not plans:
            raise ValueError('Add at least one lap to the queue')
        try:
            inventory = self.model_client_factory().list()
        except Exception as error:
            raise ValueError('Could not verify downloaded models before starting the queue') from error
        rows = inventory.get('models') if isinstance(inventory, dict) else None
        installed = {row.get('name') or row.get('model') for row in rows or [] if isinstance(row, dict)}
        missing = sorted(tags - installed)
        if missing:
            raise ValueError('Model is not downloaded: ' + ', '.join(missing))
        return plans

    def start(self, entries):
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError(f'Queue between 1 and {MAX_ENTRIES} laps')
        plans = self._preflight(entries)
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise ValueError('A Shakedown queue is already running')
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            estimates = [item['estimate'] for item in plans]
            total_seconds = sum(item['expected_seconds'] for item in estimates if item.get('known'))
            estimate = ({'known': True, 'expected_seconds': total_seconds,
                         'label': f'about {max(1, round(total_seconds / 60))} min total'}
                        if all(item.get('known') for item in estimates) else
                        {'known': False, 'label': 'unknown until each build has a speed and reply measurement'})
            self.record = {'available': True, 'schema': 'argos-shakedown-queue/1',
                           'queue_id': secrets.token_hex(16), 'state': 'running',
                           'outcome': None, 'complete': False, 'position': 0,
                           'entries': [{key: value for key, value in item.items()
                                        if key not in ('plan', 'model_tag', 'recipe')}
                                       for item in plans],
                           'estimate': estimate,
                           'active_entry': None, 'started_at': self._stamp(), 'notice': None}
            self.cancel_event = threading.Event()
            self._persist()
            self.worker = threading.Thread(target=self._run, args=(plans,),
                                           name='argos-shakedown-queue', daemon=False)
            self.worker.start()
            return deepcopy(self.record)

    def _run(self, plans):
        from ..evaluation_jobs import Jobs
        try:
            jobs = self.jobs_factory(self.home) if self.jobs_factory else Jobs(self.home)
        except Exception as error:
            with self.lock:
                for row in self.record['entries']:
                    row.update(state='failed', failure=type(error).__name__)
                self.record.update(state='completed-with-failures', outcome='completed-with-failures',
                                   complete=False, active_entry=None,
                                   notice='Queue could not start. Every entry was stopped before evaluation.')
                self._persist()
            return
        for index, item in enumerate(plans):
            with self.lock:
                if self.cancel_event.is_set():
                    for rest in self.record['entries'][index:]:
                        rest.update(state='cancelled', failure='queue-cancelled')
                    break
                row = self.record['entries'][index]
                row['state'] = 'running'
                self.record.update(position=index + 1, active_entry=index)
                self._persist()

            def progress(event, index=index):
                with self.lock:
                    self.record['active_progress'] = {
                        'stage': event.get('step', {}).get('kind'),
                        'suite': event.get('step', {}).get('suite'),
                        'completed': event.get('job', {}).get('completed'),
                        'total': event.get('job', {}).get('total')}
                    if event.get('phase') == 'step-finished':
                        self.record['entries'][index]['steps'].append(event['result'])
                    self._persist()

            try:
                result = lap.execute(item['plan'], jobs, lap_id=secrets.token_hex(16),
                                     cancel=self.cancel_event, on_update=progress)
            except Exception as error:
                result = {'outcome': 'failed', 'complete': False, 'steps': [],
                          'error_category': type(error).__name__}
            best_updates = None
            if result.get('complete'):
                try:
                    from .personal_best import record_complete_lap
                    from ..results import Store
                    store = getattr(jobs, 'store', None) or Store(self.home / '.local/share/argos-live/results')
                    best_updates = record_complete_lap(
                        self.home, store, [step['run_id'] for step in result['steps']])
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    best_updates = {'recorded': 0}
            with self.lock:
                row = self.record['entries'][index]
                row.update(state='completed' if result.get('complete') else result.get('outcome', 'failed'),
                           steps=result.get('steps', []), failure=result.get('error_category'),
                           personal_best_updates=best_updates)
                self.record['active_progress'] = None
                self._persist()
                if self.cancel_event.is_set():
                    for rest in self.record['entries'][index + 1:]:
                        rest.update(state='cancelled', failure='queue-cancelled')
                    break
        with self.lock:
            rows = self.record['entries']
            completed = sum(row['state'] == 'completed' for row in rows)
            failed = len(rows) - completed
            outcome = 'completed' if failed == 0 else 'completed-with-failures'
            if self.cancel_event.is_set():
                outcome = 'cancelled'
            self.record.update(state=outcome, outcome=outcome, complete=outcome == 'completed',
                               active_entry=None, active_progress=None,
                               notice=f'Queue {outcome.replace("-", " ")}: {completed} completed, {failed} not completed.')
            self._persist()

    def cancel(self):
        with self.lock:
            if self.worker is None or not self.worker.is_alive() or self.cancel_event is None:
                raise ValueError('No Shakedown queue is running')
            self.cancel_event.set()
            self.record['state'] = 'cancelling'
            self._persist()
            return deepcopy(self.record)
