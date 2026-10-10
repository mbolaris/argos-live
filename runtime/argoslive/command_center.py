"""Command Center: what the robot can do, what is holding it back, what to try next.

Everything here is derived from saved evidence (storage state, trial results,
reboot markers, owner verdicts). Unknown stays unknown. Tiers follow the plan:
routine events get a plain line, qualified results name their scope, and a
commissioned moment needs demonstrated use. Each moment is journaled once.
"""
import hashlib
from pathlib import Path

from . import journal, model_verify, results, starter, storage_view, mission_report, skill_map

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


def digest_of(value):
    """Bare hex digest, or None when the identity is unknown."""
    if not isinstance(value, str):
        return None
    value = value[7:] if value.startswith('sha256:') else value
    return value if len(value) == 64 and all(c in '0123456789abcdef' for c in value) else None


def same_model(a, b):
    """Same tag AND same manifest digest. A tag alone is never an identity."""
    da, db = digest_of(a.get('manifest_digest')), digest_of(b.get('manifest_digest'))
    return a.get('model') == b.get('model') and da is not None and da == db


def is_selected(run, selected):
    """Does this run describe the weights currently selected? Unknown identity never matches."""
    digest = digest_of((selected or {}).get('digest'))
    return (digest is not None and run.get('model') == (selected or {}).get('model')
            and digest_of(run.get('manifest_digest')) == digest)


def selected_identity(home):
    """Tag plus the manifest digest of the selected model, read cheaply from its store."""
    try:
        state = storage_view.read_state(Path(home))
        tag = state.get('model')
        if not isinstance(tag, str):
            return {'model': None, 'digest': None}
    except (OSError, ValueError, TypeError):
        return {'model': None, 'digest': None}
    try:
        root = starter.ROOT if state.get('model_source') == 'bundled' else Path(state['storage'])
        digest = hashlib.sha256(model_verify.read_manifest(root, tag)).hexdigest()
    except (OSError, ValueError, TypeError, KeyError):
        digest = None
    return {'model': tag, 'digest': digest}


def same_hardware(a, b):
    """Hardware must match for a speed or accuracy comparison to be a claim about the model."""
    def key(run):
        h = run.get('hardware')
        if not isinstance(h, dict) or not h:
            return None
        cpu = h.get('cpu')
        cpu_key = (cpu.get('model'), cpu.get('cores'), cpu.get('threads')) if isinstance(cpu, dict) else repr(cpu)
        gpus = h.get('gpus')
        if isinstance(gpus, list):
            gpu_key = tuple(
                (g.get('vendor'), g.get('name'), g.get('bus'), g.get('vram_total_bytes'), g.get('driver'))
                if isinstance(g, dict) else repr(g)
                for g in gpus
            )
        else:
            gpu_key = repr(gpus)
        ram_key = (h.get('ram') or {}).get('total_bytes')
        return (cpu_key, gpu_key, ram_key)
    return key(a) is not None and key(a) == key(b)


def supported_pair(newer, older):
    """The existing comparison validator plus matching hardware. Anything less is not a comparison."""
    try:
        results.compare([newer, older])
    except ValueError:
        return False
    return same_hardware(newer, older)


def document_runs(runs, selected_recipe=None):
    from . import recipe as recipe_mod

    def matches_rec(r):
        if selected_recipe is None or recipe_mod.is_standard(selected_recipe):
            return recipe_mod.is_standard(r)
        sel_preset = selected_recipe.get('preset') if isinstance(selected_recipe, dict) else selected_recipe
        r_rec = r.get('recipe')
        return isinstance(r_rec, dict) and r_rec.get('preset') == sel_preset

    return [r for r in runs if r['kind'] == 'ability' and r.get('suite') == 'documents-short'
            and r['coverage']['complete'] and isinstance(r.get('qualification'), dict)
            and matches_rec(r)]


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


def facts(home, store, view, selected_recipe=None):
    runs = load_runs(store)
    docs = document_runs(runs, selected_recipe=selected_recipe)
    models = []
    for run in docs:  # newest first; keep the newest document run per distinct model
        if not any(same_model(run, kept) for kept in models):
            models.append(run)
    entries = journal.read(home)['entries']
    accepted = [e for e in entries if e['key'].startswith('task:') and e['evidence'].get('verdict') == 'accepted'
                and digest_of(e['evidence'].get('manifest_digest')) is not None]
    from . import recipe as recipe_mod

    def matches_rec(r):
        if selected_recipe is None or recipe_mod.is_standard(selected_recipe):
            return recipe_mod.is_standard(r)
        sel_preset = selected_recipe.get('preset') if isinstance(selected_recipe, dict) else selected_recipe
        r_rec = r.get('recipe')
        return isinstance(r_rec, dict) and r_rec.get('preset') == sel_preset

    return {'runs': runs, 'doc_models': models, 'baseline': [r for r in runs if r['kind'] in ('speed', 'ability')
                                                             and r.get('suite') != 'documents-short'
                                                             and matches_rec(r)],
            'accepted_tasks': accepted, 'storage': view, 'selected_recipe': selected_recipe}


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
                                  {'run': run['id'], 'model': run['model'], 'manifest_digest': run.get('manifest_digest')},
                                  clock=clock))
        if q['qualified']:
            correct = sum(c['observed'] for c in q['checks'] if c['name'] != 'format_errors')
            needed = sum(c['required'] for c in q['checks'] if c['name'] != 'format_errors')
            new.append(journal.record(home, 'documents:qualified:' + run['model'] + ':' + run['id'][:12], 'qualified',
                                      'Short documents: qualified',
                                      f"{run['model']} met the fixed criteria for short documents ({correct} correct against "
                                      f"{needed} needed) at context {run['settings'].get('context')}. "
                                      'This says nothing about longer documents or other tasks.',
                                      {'run': run['id'], 'model': run['model'], 'manifest_digest': run.get('manifest_digest'),
                                       'criteria_version': q['criteria_version']},
                                      clock=clock))
    for newer, older in zip(models, models[1:]):
        if not supported_pair(newer, older):
            continue  # different suite, context, settings or hardware: no comparative claim
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
            fast, slow = speed_for(f['runs'], newer), speed_for(f['runs'], older)
            a = generation_speed(fast) if fast else None
            b = generation_speed(slow) if slow else None
            # The speed claim needs its own matched pair of speed runs, not just matched document runs.
            if (a is not None and b is not None and b > 0 and a >= b * GAIN
                    and supported_pair(fast, slow)):
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
    for task in f['accepted_tasks']:
        match = next((m for m in models if m['qualification']['qualified'] and m['model'] == task['evidence'].get('model')
                      and digest_of(m.get('manifest_digest')) == digest_of(task['evidence'].get('manifest_digest'))), None)
        if match:
            model, digest = match['model'], digest_of(match['manifest_digest'])
            new.append(journal.record(home, 'brain:commissioned:' + model + ':' + digest[:12], 'commissioned',
                                      'Brain commissioned for documents',
                                      f"{model} qualified on the short-document trial and you accepted its answer to your own "
                                      'document, both with the same model files. Use it now for the next one.',
                                      {'model': model, 'manifest_digest': match['manifest_digest'], 'task': task['key']},
                                      clock=clock))
            break
    return [e for e in new if e]


def systems(home, f, selected):
    view = f['storage'] or {}
    models_row = next((l for l in view.get('locations', []) if l.get('key') == 'models'), {})
    reboot = models_row.get('reboot', {}).get('state')
    docs = f['doc_models']
    current = next((m for m in docs if is_selected(m, selected)), None)
    accepted = [e for e in f['accepted_tasks'] if digest_of(e['evidence'].get('manifest_digest')) == digest_of((selected or {}).get('digest'))
                and e['evidence'].get('model') == (selected or {}).get('model')]
    brain = ('unknown', 'No trial results yet.')
    if not current and docs and digest_of((selected or {}).get('digest')) is None:
        brain = ('unknown', 'The selected model files could not be identified, so earlier results are not applied.')
    elif not current and docs:
        brain = ('unknown', 'These model files have no trial result yet. Results for a different version do not carry over.')
    if current:
        qualified = current['qualification']['qualified']
        brain = ('qualified' if qualified else 'bench-test',
                 ('Qualified for short documents.' if qualified else 'Short-document criteria not met.') +
                 ' Other abilities are untested.')
    elif any(is_selected(run, selected) for run in f['baseline']) and not docs:
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
    speed = next((r for r in f['runs'] if r['kind'] == 'speed' and is_selected(r, selected)), None)
    core = ('unknown', 'No speed measurement yet. GPU use is not yet proven.')
    if speed:
        rate = generation_speed(speed)
        core = ('bench-test', 'Measured ' + (f'{rate:.1f} output tokens per second.' if rate else 'a speed run.') +
                ' GPU use is not yet proven.')
    sensors = ('unknown', 'No document read through the model yet.')
    if accepted:
        sensors = ('commissioned', 'You accepted an answer from your chosen pasted document.')
    elif f['accepted_tasks']:
        sensors = ('bench-test', 'An earlier model version was accepted on your own document. These model files need a new check.')
    elif docs:
        sensors = ('bench-test', 'Short passages tested; no document you chose yet.')
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
    current = next((m for m in docs if is_selected(m, selected)), None)
    accepted = [e for e in f['accepted_tasks'] if digest_of(e['evidence'].get('manifest_digest')) == digest_of((selected or {}).get('digest'))
                and e['evidence'].get('model') == (selected or {}).get('model')]
    if active:
        return {'id': 'wait', 'title': 'A task is running', 'reason': 'Chat resumes when it finishes.', 'action': None}
    if view.get('state') == 'needs-attention':
        return {'id': 'storage', 'title': 'Restore the model bay',
                'reason': 'The chosen location needs attention before Argos can save or test downloaded models. Nothing falls back to another drive.',
                'action': 'storage'}
    if not current:
        return {'id': 'documents', 'title': 'Read this brief',
                'reason': 'Eight short passages test answers, supporting quotes, and “not stated” responses. This qualifies short-document reading. Chat pauses for the test and resumes afterward.',
                'action': 'documents'}
    newer, older = (docs[0], docs[1]) if len(docs) > 1 else (None, None)
    if newer and older and not newer['qualification']['qualified'] and older['qualification']['qualified'] \
            and is_selected(newer, selected) and supported_pair(newer, older):
        return {'id': 'restore', 'title': 'Restore the model that met the standard',
                'reason': f"{older['model']} passed the document criteria; {newer['model']} missed them. The previous model remains available.",
                'action': 'restore', 'model': older['model']}
    if not current['qualification']['qualified']:
        from . import replay
        groups = replay.miss_groups(current)
        if replay.kept_meaning_only(groups):
            # Diagnostic, not a score: these misses don't point to a larger model.
            wording, requirement = groups.get('wording', 0), groups.get('requirement', 0)
            return {'id': 'review', 'title': 'See why the answers missed',
                    'reason': ('A diagnostic review (not a score) found every miss kept an accepted answer: '
                               f'{wording} worded differently and {requirement} not given as a short answer. '
                               'That does not point to a larger model. Step through the misses before choosing a change.'),
                    'action': 'review'}
        if not view.get('confirmed'):
            return storage_action()
        return {'id': 'models', 'title': 'Find a candidate for the missed checks',
                'reason': 'The current model missed the short-document criteria. Compare a verified candidate under the same trial; a larger model is not automatically better.',
                'action': 'models'}
    if not accepted:
        return {'id': 'task', 'title': 'Test a document that matters to you',
                'reason': 'The short trial passed. Now check an answer on text you chose and decide whether it is useful. Your text and answer are not saved.',
                'action': 'task'}
    if not view.get('confirmed'):
        return storage_action()
    reboot = next((l for l in view.get('locations', []) if l.get('key') == 'models'), {}).get('reboot', {}).get('state')
    if (not (view.get('configured') or {}).get('temporary') and
            reboot in ('not-started', 'pending', None) and view.get('confirmed')):
        return {'id': 'reboot', 'title': 'Check model storage after a restart',
                'reason': 'Write a small test marker, restart Argos, then return here to see whether the chosen folder retained it.', 'action': 'reboot'}
    return {'id': 'capabilities', 'title': 'Choose the next capability you care about',
            'reason': 'The current checks are complete. Pick a capability, review what it needs, and test it before calling it ready.',
            'action': 'capabilities'}


def storage_action():
    return {'id': 'storage', 'title': 'Choose a home for future models',
            'reason': 'You have tested the current build. Choose where future model downloads will live; the bundled starter stays available.',
            'action': 'storage'}


def build_path(f, selected, next_step):
    """Task-specific progress, never a global intelligence rank or hardware score."""
    baseline = any(is_selected(run, selected) for run in f['baseline'])
    current = next((run for run in f['doc_models'] if is_selected(run, selected)), None)
    qualified = bool(current and current['qualification']['qualified'])
    accepted = any(is_selected(entry['evidence'], selected) for entry in f['accepted_tasks'])
    compared = bool(current and any(not same_model(current, other) and supported_pair(current, other)
                                   for other in f['doc_models']))
    steps = []
    for key, title, complete, detail in (
        ('documents', 'Read this brief', qualified, 'Meet fixed answer, quotation and missing-information criteria.'),
        ('task', 'Try something useful', accepted, 'Judge an answer on a document you care about.'),
        ('baseline', 'Measure this build', baseline, 'Save generation speed, first-token wait and quick ability results.'),
        ('models', 'Compare a candidate', compared, 'Compare matching document trials on the same hardware and settings.'),
    ):
        state = 'complete' if complete else 'current' if next_step == key else 'untested'
        if key == 'documents' and current and not qualified:
            state = 'attention'
            detail = 'The current model missed the fixed criteria. Inspect the misses before choosing a candidate.'
        steps.append({'id': key, 'title': title, 'state': state, 'detail': detail})
    return {'steps': steps, 'completed': sum(step['state'] == 'complete' for step in steps),
            'scope': 'Short-document build path. Evidence applies to the selected model files; comparison is not proof of improvement.'}


def snapshot(home, store, *, view=None, selected=None, active=False, clock=stamp, selected_recipe=None):
    home = Path(home)
    f = facts(home, store, view, selected_recipe=selected_recipe)
    new = record_moments(home, f, clock=clock)
    data = journal.read(home)
    entries = sorted(data['entries'], key=lambda e: e['at'], reverse=True)
    rank = {t: i for i, t in enumerate(journal.TIERS)}
    unseen = [e for e in entries if not e['seen']]
    moment = None
    if unseen and not data['quiet']:
        moment = max(unseen, key=lambda e: (rank[e['tier']], e['at']))
    for entry in entries:
        digest = digest_of(entry['evidence'].get('manifest_digest')) if isinstance(entry.get('evidence'), dict) else None
        entry['applies_to_selected'] = None if digest is None else is_selected(
            {'model': entry['evidence'].get('model'), 'manifest_digest': digest}, selected)
    action = next_action(f, selected, active)
    sm = skill_map.build_skill_map(f, selected, selected_recipe=selected_recipe)
    return {'schema': SCHEMA, 'name': 'Argos', 'model': (selected or {}).get('model'), 'quiet': data['quiet'],
            'report': mission_report.summarize([r for r in f['runs'] if is_selected(r, selected)]),
            'next_action': action, 'build_path': build_path(f, selected, action['id']), 'systems': systems(home, f, selected),
            'skill_map': sm,
            'selected_recipe': selected_recipe,
            'journal': entries[:30], 'moment': moment, 'unseen': len(unseen),
            'scope': 'Systems show only what has been demonstrated. Unknown means not yet tested.'}


class Controller:
    """Server-facing wrapper: snapshot plus the three owner actions."""

    def __init__(self, home, store, *, lab=None, storage=None, startup=None, identity=selected_identity):
        self.home, self.store, self.lab, self.storage, self.startup = Path(home), store, lab, storage, startup
        self.identity = identity

    def selected_model(self):
        return self.identity(self.home)

    def snapshot(self):
        try:
            view = self.storage.snapshot() if self.storage else None
        except (OSError, ValueError, TypeError, KeyError):
            view = None
        lab_snap = self.lab.snapshot() if self.lab else {}
        active = bool(lab_snap.get('active'))
        selected_recipe = lab_snap.get('selected_recipe')
        return snapshot(self.home, self.store, view=view, selected=self.selected_model(), active=active, selected_recipe=selected_recipe)

    def skill_map(self):
        return self.snapshot().get('skill_map')

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
        if value == 'accepted' and digest_of(task.get('manifest_digest')) is None:
            raise ValueError('The model files could not be identified, so this answer cannot count as evidence')
        entry = journal.record(self.home, verdict_key(task['task_id']), 'routine',
                               'Document answer ' + value,
                               f"You {value} {task['model']}'s answer to a document you chose. The document and answer are not saved.",
                               {'verdict': value, 'model': task['model'], 'manifest_digest': task.get('manifest_digest'),
                                'quote_supported': task['quote_supported']})
        return {'recorded': entry is not None, 'verdict': value}
