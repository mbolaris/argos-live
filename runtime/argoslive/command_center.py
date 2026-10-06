"""Command Center: what the robot can do, what is holding it back, what to try next.

Everything here is derived from saved evidence (storage state, trial results,
reboot markers, owner verdicts). Unknown stays unknown. Tiers follow the plan:
routine events get a plain line, qualified results name their scope, and a
commissioned moment needs demonstrated use. Each moment is journaled once.
"""
from pathlib import Path

from . import journal, results, storage_view

SCHEMA = 'argos-command-center/1'
LOOK_BACK = 40
GAIN = 1.2  # a speed change must be at least 20% to be called a gain


def stamp():
    return journal.stamp()


def load_runs(store):
    """Newest first complete runs, loaded for facts. Corrupt files are ignored."""
    listing = store.list()['runs'][:LOOK_BACK]
    runs = []
    for item in listing:
        try:
            value = store.load(item['id'])
        except (ValueError, OSError):
            continue
        if value.get('restoration', {}).get('succeeded') and value.get('state', 'completed') == 'completed':
            runs.append(value)
    return runs


def same_model(a, b):
    return a.get('model') == b.get('model') and a.get('manifest_digest') == b.get('manifest_digest')


def document_runs(runs):
    return [r for r in runs if r['kind'] == 'ability' and r.get('suite') == 'documents-short'
            and r['coverage']['complete'] and isinstance(r.get('qualification'), dict)]


def speed_for(runs, document):
    """The latest complete speed run for the same model saved before the document run."""
    for run in runs:
        if (run['kind'] == 'speed' and same_model(run, document) and run['created'] <= document['created']
                and any(p['size'] == 'short' and not p['skipped'] for p in run['prompts'])):
            return run
    return None


def generation_speed(run):
    for prompt in run['prompts']:
        if prompt['size'] == 'short' and not prompt['skipped']:
            return results.median_of(prompt, 'generation_tokens_per_second')['median']
    return None


def verdict_key(task_id):
    return 'task:' + task_id


def facts(home, store, view):
    runs = load_runs(store)
    docs = document_runs(runs)
    models = []
    for run in docs:  # newest first; keep the newest document run per distinct model
        if not any(same_model(run, kept) for kept in models):
            models.append(run)
    entries = journal.read(home)['entries']
    accepted = [e for e in entries if e['key'].startswith('task:') and e['evidence'].get('verdict') == 'accepted']
    return {'runs': runs, 'doc_models': models, 'baseline': [r for r in runs if r['kind'] in ('speed', 'ability')
                                                             and r.get('suite') != 'documents-short'],
            'accepted_tasks': accepted, 'storage': view}


def record_moments(home, f, clock=stamp):
    """Journal what the evidence supports. Each key is recorded at most once."""
    new = []
    view = f['storage'] or {}
    if view.get('confirmed') and view.get('configured'):
        new.append(journal.record(home, 'storage:confirmed', 'routine', 'Memory banks configured',
                                  'Model storage is chosen and accepted a write check. Reboot verification pending.',
                                  {'path': view['configured']['path']}, clock=clock))
    models_row = next((l for l in view.get('locations', []) if l.get('key') == 'models'), {})
    if models_row.get('reboot', {}).get('state') == 'retained':
        backing = models_row.get('backing') or {}
        encryption = {True: 'Encrypted.', False: 'Not encrypted.'}.get(backing.get('encrypted'), 'Encryption unknown.')
        new.append(journal.record(home, 'storage:reboot-retained', 'commissioned', 'Memory banks online',
                                  'Your model storage directory survived a reboot. ' + encryption +
                                  ' This does not test conversation recall.',
                                  {'verified_at': models_row['reboot'].get('verified_at')}, clock=clock))
    if f['baseline']:
        first = f['baseline'][-1]
        new.append(journal.record(home, 'baseline:saved', 'routine', 'First baseline saved',
                                  'A speed or ability baseline is saved for later comparison.',
                                  {'run': first['id'], 'model': first['model']}, clock=clock))
    models = f['doc_models']
    for run in models:
        q = run['qualification']
        new.append(journal.record(home, 'documents:trial:' + run['id'], 'routine', 'Document trial completed',
                                  f"{run['model']}: trial finished at context {run['settings'].get('context')}.",
                                  {'run': run['id'], 'model': run['model']}, clock=clock))
        if q['qualified']:
            correct = sum(c['observed'] for c in q['checks'] if c['name'] != 'format_errors')
            needed = sum(c['required'] for c in q['checks'] if c['name'] != 'format_errors')
            new.append(journal.record(home, 'documents:qualified:' + run['model'] + ':' + run['id'][:12], 'qualified',
                                      'Short documents: qualified',
                                      f"{run['model']} met the fixed criteria for short documents ({correct} correct against "
                                      f"{needed} needed) at context {run['settings'].get('context')}. "
                                      'This says nothing about longer documents or other tasks.',
                                      {'run': run['id'], 'model': run['model'], 'criteria_version': q['criteria_version']},
                                      clock=clock))
    for newer, older in zip(models, models[1:]):
        key = newer['id'][:12] + ':' + older['id'][:12]
        nq, oq = newer['qualification'], older['qualification']
        if nq['qualified'] and not oq['qualified']:
            now = sum(i['score'] for i in newer['items'])
            before = sum(i['score'] for i in older['items'])
            new.append(journal.record(home, 'improved:' + key, 'qualified', 'New brain qualified for these documents',
                                      f"{newer['model']} scored {now} of {len(newer['items'])}, up from {before} for "
                                      f"{older['model']}, under the same settings. The previous selection stays available to restore.",
                                      {'newer': newer['id'], 'older': older['id']}, clock=clock))
        elif nq['qualified'] and oq['qualified']:
            a, b = generation_speed(speed_for(f['runs'], newer) or {'prompts': []}), \
                generation_speed(speed_for(f['runs'], older) or {'prompts': []})
            if a is not None and b is not None and b > 0 and a >= b * GAIN:
                new.append(journal.record(home, 'leaner:' + key, 'qualified', 'Leaner build',
                                          f"{newer['model']} answers faster than {older['model']} ({a:.1f} against {b:.1f} "
                                          'tokens per second on the short prompt) with both meeting the same document criteria.',
                                          {'newer': newer['id'], 'older': older['id']}, clock=clock))
        elif oq['qualified'] and not nq['qualified']:
            missed = [c['label'] for c in nq['checks'] if not c['met']]
            new.append(journal.record(home, 'regression:' + key, 'routine', 'Candidate did not hold the standard',
                                      f"{newer['model']} missed: {', '.join(missed)}. {older['model']} met them. "
                                      'Results are saved for reference; restoring the previous selection is available.',
                                      {'newer': newer['id'], 'older': older['id']}, clock=clock))
    if f['accepted_tasks'] and any(m['qualification']['qualified'] for m in models):
        first = f['accepted_tasks'][0]
        model = first['evidence'].get('model')
        if any(m['model'] == model and m['qualification']['qualified'] for m in models):
            new.append(journal.record(home, 'brain:commissioned:' + model, 'commissioned', 'Brain commissioned for documents',
                                      f"{model} qualified on the short-document trial and you accepted its answer to your own "
                                      'document. Use it now for the next one.',
                                      {'model': model, 'task': first['key']}, clock=clock))
    return [e for e in new if e]


def systems(home, f, selected):
    view = f['storage'] or {}
    models_row = next((l for l in view.get('locations', []) if l.get('key') == 'models'), {})
    reboot = models_row.get('reboot', {}).get('state')
    docs = f['doc_models']
    current = next((m for m in docs if m['model'] == selected), None)
    brain = ('unknown', 'No trial results yet.')
    if current:
        qualified = current['qualification']['qualified']
        brain = ('qualified' if qualified else 'bench-test',
                 ('Qualified for short documents.' if qualified else 'Short-document criteria not met.') +
                 ' Other abilities are untested.')
    elif f['baseline']:
        brain = ('bench-test', 'Baseline saved. Documents are untested.')
    state = view.get('state')
    memory = ('unknown', 'Storage not checked.')
    if state == 'needs-attention':
        memory = ('attention', 'Selected model storage needs attention.')
    elif view.get('confirmed'):
        memory = (('commissioned', 'Storage survived a reboot.') if reboot == 'retained'
                  else ('qualified', 'Storage accepted a write check. Reboot verification pending.'))
    elif state == 'available':
        memory = ('bench-test', 'Storage found but not yet confirmed.')
    speed = next((r for r in f['runs'] if r['kind'] == 'speed'), None)
    core = ('unknown', 'No speed measurement yet. GPU use is not yet proven.')
    if speed:
        rate = generation_speed(speed)
        core = ('bench-test', 'Measured ' + (f'{rate:.1f} output tokens per second.' if rate else 'a speed run.') +
                ' GPU use is not yet proven.')
    sensors = ('unknown', 'No document read through the model yet.')
    if f['accepted_tasks']:
        sensors = ('commissioned', 'You accepted an answer from your own pasted document.')
    elif docs:
        sensors = ('bench-test', 'Short passages tested; no document of your own yet.')
    return [{'id': 'brain', 'label': 'Brain', 'state': brain[0], 'detail': brain[1]},
            {'id': 'power-core', 'label': 'Power core', 'state': core[0], 'detail': core[1]},
            {'id': 'memory-banks', 'label': 'Memory banks', 'state': memory[0], 'detail': memory[1]},
            {'id': 'sensors', 'label': 'Sensors', 'state': sensors[0], 'detail': sensors[1]},
            {'id': 'hands', 'label': 'Hands', 'state': 'unknown', 'detail': 'No tool or integration trial yet.'},
            {'id': 'cooling', 'label': 'Cooling', 'state': 'unknown', 'detail': 'Temperature readings are not yet part of trials.'},
            {'id': 'stability', 'label': 'Stability', 'state': 'qualified' if reboot == 'retained' else 'unknown',
             'detail': 'Storage retained across a reboot.' if reboot == 'retained' else 'No reboot check recorded yet.'}]


def next_action(f, selected, active):
    view = f['storage'] or {}
    docs = f['doc_models']
    current = next((m for m in docs if m['model'] == selected), None)
    if active:
        return {'id': 'wait', 'title': 'A task is running', 'reason': 'Chat resumes when it finishes.', 'action': None}
    if view.get('state') == 'needs-attention':
        return {'id': 'storage', 'title': 'Check your model storage',
                'reason': 'The chosen location cannot be used right now. Nothing falls back to another drive.',
                'action': 'storage'}
    if not view.get('confirmed'):
        return {'id': 'storage', 'title': 'Choose where your robot keeps its models',
                'reason': 'Downloads wait for a location you have confirmed. The bundled starter works without one.',
                'action': 'storage'}
    if not f['baseline']:
        return {'id': 'baseline', 'title': 'Save a baseline',
                'reason': 'A saved baseline lets you tell later whether a different model is better or just different.',
                'action': 'baseline'}
    if not current:
        return {'id': 'documents', 'title': 'Run the document trial',
                'reason': 'Eight short passages, answered with a supporting quotation. Takes a few minutes and pauses chat.',
                'action': 'documents'}
    newer, older = (docs[0], docs[1]) if len(docs) > 1 else (None, None)
    if newer and older and not newer['qualification']['qualified'] and older['qualification']['qualified'] \
            and newer['model'] == selected:
        return {'id': 'restore', 'title': 'Restore the previous model',
                'reason': f"{older['model']} met the document criteria and {newer['model']} did not.",
                'action': 'restore', 'model': older['model']}
    if not current['qualification']['qualified']:
        return {'id': 'models', 'title': 'Try a larger model',
                'reason': 'The current model missed the short-document criteria. Compare a candidate under the same trial.',
                'action': 'models'}
    if not f['accepted_tasks']:
        return {'id': 'task', 'title': 'Try a document of your own',
                'reason': 'The trial used passages we wrote. Paste something real and judge the answer yourself.',
                'action': 'task'}
    reboot = next((l for l in view.get('locations', []) if l.get('key') == 'models'), {}).get('reboot', {}).get('state')
    if reboot in ('not-started', 'pending', None) and view.get('confirmed'):
        return {'id': 'reboot', 'title': 'Verify storage across a restart',
                'reason': 'Start the reboot check, restart the robot, then reopen this page.', 'action': 'reboot'}
    return {'id': 'chat', 'title': 'Talk to Argos', 'reason': 'Everything checked so far is in order.', 'action': 'chat'}


def snapshot(home, store, *, view=None, selected=None, active=False, clock=stamp):
    home = Path(home)
    f = facts(home, store, view)
    new = record_moments(home, f, clock=clock)
    data = journal.read(home)
    entries = sorted(data['entries'], key=lambda e: e['at'], reverse=True)
    rank = {t: i for i, t in enumerate(journal.TIERS)}
    unseen = [e for e in entries if not e['seen']]
    moment = None
    if unseen and not data['quiet']:
        moment = max(unseen, key=lambda e: (rank[e['tier']], e['at']))
    return {'schema': SCHEMA, 'name': 'Argos', 'model': selected, 'quiet': data['quiet'],
            'next_action': next_action(f, selected, active), 'systems': systems(home, f, selected),
            'journal': entries[:30], 'moment': moment, 'unseen': len(unseen),
            'scope': 'Systems show only what has been demonstrated. Unknown means not yet tested.'}


class Controller:
    """Server-facing wrapper: snapshot plus the three owner actions."""

    def __init__(self, home, store, *, lab=None, storage=None, startup=None):
        self.home, self.store, self.lab, self.storage, self.startup = Path(home), store, lab, storage, startup

    def selected_model(self):
        try:
            value = storage_view.read_state(self.home).get('model')
        except (OSError, ValueError, TypeError):
            return None
        return value if isinstance(value, str) else None

    def snapshot(self):
        try:
            view = self.storage.snapshot() if self.storage else None
        except (OSError, ValueError, TypeError, KeyError):
            view = None
        active = bool(self.lab and self.lab.snapshot()['active'])
        return snapshot(self.home, self.store, view=view, selected=self.selected_model(), active=active)

    def seen(self):
        return {'changed': journal.mark_seen(self.home)}

    def quiet(self, value):
        return {'quiet': journal.set_quiet(self.home, value)}

    def verdict(self, value):
        """Record the owner's judgment of the last pasted-document answer. Text is never saved."""
        if value not in ('accepted', 'rejected'):
            raise ValueError('Choose accepted or rejected')
        task = self.lab.snapshot().get('task') if self.lab else None
        if not task or task.get('outcome') not in ('answered', 'not_stated'):
            raise ValueError('There is no answer to judge')
        entry = journal.record(self.home, verdict_key(task['task_id']), 'routine',
                               'Document answer ' + value,
                               f"You {value} {task['model']}'s answer to a document of your own. The document and answer are not saved.",
                               {'verdict': value, 'model': task['model'], 'quote_supported': task['quote_supported']})
        return {'recorded': entry is not None, 'verdict': value}
