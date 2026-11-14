"""Fixed, nested Shakedown lap plans and conservative time estimates."""
from statistics import median
import secrets
import time

from .. import ability, bench_speed


SCHEMA = 'argos-shakedown-lap/1'
SLICE_VERSION = 'argos-shakedown-slice/1'
SIZES = ('quick', 'standard', 'full')
ITEM_LIMITS = {'quick': 10, 'standard': 20, 'full': None}
DEFAULT_FORMS = ('quick', 'standard', 'challenge', 'tool-schema', 'tool-plan', 'tool-sequence')
ESTIMATE_LOW_FACTOR = 0.75
ESTIMATE_HIGH_FACTOR = 1.35


def slice_item_ids(suite, size):
    """Return a fixed ordered subset for one built-in ability-suite version."""
    if size not in ITEM_LIMITS:
        raise ValueError('Choose quick, standard or full')
    try:
        data = ability.load(suite)
    except ValueError as exc:
        raise ValueError('Choose a shipped ability form') from exc
    ids = [item['id'] for item in data['items']]
    limit = ITEM_LIMITS[size]
    return ids if limit is None else ids[:min(limit, len(ids))]


def build(size='quick', suites=DEFAULT_FORMS, *, model_tag=None, recipe=None):
    """Build an ordered speed-first lap plan for the selected ability forms."""
    if size not in ITEM_LIMITS:
        raise ValueError('Choose quick, standard or full')
    if not isinstance(suites, (list, tuple)) or not suites:
        raise ValueError('Select at least one ability form')
    if any(not isinstance(suite, str) or suite not in DEFAULT_FORMS for suite in suites):
        raise ValueError('Choose only supported ability forms')
    if len(set(suites)) != len(suites):
        raise ValueError('Ability forms must be unique')
    if model_tag is not None and (not isinstance(model_tag, str) or not model_tag or
                                  len(model_tag) > 256 or any(char.isspace() for char in model_tag) or
                                  '/' in model_tag or '\\' in model_tag):
        raise ValueError('Choose an exact local model tag')
    if recipe is not None:
        from .. import recipe as recipe_mod
        recipe_mod.validate(recipe)
    options = {}
    if model_tag is not None:
        options['model_tag'] = model_tag
    if recipe is not None:
        options['recipe'] = recipe
    steps = [{'kind': 'speed', 'suite_version': bench_speed.SUITE, **options}]
    for suite in suites:
        data = ability.load(suite)
        steps.append({'kind': 'ability', 'suite': suite,
                      'suite_version': 'ability/' + suite + '/' + data['version'],
                      'slice_name': size, 'slice_version': SLICE_VERSION,
                      'item_ids': slice_item_ids(suite, size), **options})
    plan = {'schema': SCHEMA, 'size': size, 'steps': steps}
    validate(plan)
    return plan


def validate(plan):
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA or plan.get('size') not in SIZES:
        raise ValueError('Invalid Shakedown lap plan')
    steps = plan.get('steps')
    if not isinstance(steps, list) or not steps or not isinstance(steps[0], dict) or \
            steps[0].get('kind') != 'speed' or \
            steps[0].get('suite_version') != bench_speed.SUITE:
        raise ValueError('Lap must start with the fixed speed job')
    seen = set()
    for step in steps[1:]:
        if not isinstance(step, dict) or step.get('kind') != 'ability':
            raise ValueError('Lap contains an unsupported job')
        suite = step.get('suite')
        if suite in seen or suite not in DEFAULT_FORMS:
            raise ValueError('Lap ability forms must be supported and unique')
        seen.add(suite)
        data = ability.load(suite)
        if step.get('suite_version') != 'ability/' + suite + '/' + data['version']:
            raise ValueError('Lap form version changed; rebuild the plan')
        if step.get('slice_name') != plan['size'] or step.get('slice_version') != SLICE_VERSION:
            raise ValueError('Lap slice metadata does not match the plan')
        expected = slice_item_ids(suite, plan['size'])
        if step.get('item_ids') != expected:
            raise ValueError('Lap slice item list does not match the fixed form slice')
    for step in steps:
        if set(step) - {'kind', 'suite_version', 'suite', 'slice_name', 'slice_version',
                        'item_ids', 'model_tag', 'recipe'}:
            raise ValueError('Lap contains unsupported execution settings')
        model_tag = step.get('model_tag')
        if model_tag is not None and (not isinstance(model_tag, str) or not model_tag or
                                      len(model_tag) > 256 or any(char.isspace() for char in model_tag) or
                                      '/' in model_tag or '\\' in model_tag):
            raise ValueError('Lap contains an invalid local model tag')
        if step.get('recipe') is not None:
            from .. import recipe as recipe_mod
            recipe_mod.validate(step['recipe'])
    if len(steps) < 2:
        raise ValueError('Lap must include at least one ability form')
    return True


def _median_reply_seconds(run):
    if not isinstance(run, dict) or not isinstance(run.get('items'), list):
        return None
    values = []
    for item in run['items']:
        if not isinstance(item, dict):
            continue
        value = item.get('latency_seconds')
        if value is None and isinstance(item.get('measurement'), dict):
            value = item['measurement'].get('elapsed_seconds')
        if type(value) in (int, float) and value > 0:
            values.append(float(value))
    return median(values) if values else None


def estimate(plan, loadout):
    """Estimate lap time from the latest speed run and last matched reply median."""
    validate(plan)
    if not isinstance(loadout, dict):
        raise ValueError('Loadout measurements must be an object')
    speed = loadout.get('latest_speed')
    speed_seconds = speed.get('elapsed_seconds') if isinstance(speed, dict) else None
    reply_seconds = loadout.get('last_run_median_reply_seconds')
    if reply_seconds is None:
        reply_seconds = _median_reply_seconds(loadout.get('last_run'))
    if (type(speed_seconds) not in (int, float) or speed_seconds <= 0 or
            type(reply_seconds) not in (int, float) or reply_seconds <= 0):
        return {'known': False, 'label': 'unknown until the first lap',
                'minimum_seconds': None, 'expected_seconds': None, 'maximum_seconds': None}
    ability_items = sum(len(step['item_ids']) for step in plan['steps'] if step['kind'] == 'ability')
    expected = float(speed_seconds) + ability_items * float(reply_seconds)
    low = max(1.0, expected * ESTIMATE_LOW_FACTOR)
    high = expected * ESTIMATE_HIGH_FACTOR
    expected_minutes = max(1, round(expected / 60))
    low_minutes = max(1, round(low / 60))
    high_minutes = max(low_minutes, round(high / 60))
    return {'known': True, 'expected_seconds': round(expected),
            'minimum_seconds': round(low), 'maximum_seconds': round(high),
            'label': f'about {expected_minutes} min (roughly {low_minutes}–{high_minutes} min)'}


def execute(plan, jobs, *, lap_id=None, cancel=None, on_update=None, poll_seconds=5):
    """Run one speed-first lap through host-owned jobs, strictly one at a time."""
    validate(plan)
    if type(poll_seconds) not in (int, float) or not 0.1 <= poll_seconds <= 30:
        raise ValueError('Lap polling interval must be between 0.1 and 30 seconds')
    lap_id = lap_id or secrets.token_hex(16)
    if not isinstance(lap_id, str) or len(lap_id) != 32 or any(char not in '0123456789abcdef' for char in lap_id):
        raise ValueError('Invalid lap ID')
    steps = []
    outcome = 'completed'
    for index, step in enumerate(plan['steps']):
        if cancel is not None and cancel.is_set():
            outcome = 'cancelled'
            break
        suite = 'speed' if step['kind'] == 'speed' else step['suite']
        options = {'lap_id': lap_id}
        if step.get('model_tag') is not None:
            options['model_tag'] = step['model_tag']
        if step.get('recipe') is not None:
            options['recipe'] = step['recipe']
        if step['kind'] == 'ability':
            options.update(slice_name=step['slice_name'], slice_version=step['slice_version'])
        started = jobs.start(suite, **options)
        job_id = started['job_id']
        current = started
        while current.get('status') == 'running':
            if cancel is not None and cancel.is_set():
                jobs.cancel_owner(job_id)
            current = jobs.wait(job_id, seconds=poll_seconds, on_update=(
                (lambda value, step=step: on_update({'step': step, 'job': value}))
                if on_update else None))
            if cancel is not None and cancel.is_set() and current.get('status') == 'running':
                time.sleep(min(0.05, poll_seconds))
        result = current.get('result') if isinstance(current.get('result'), dict) else {}
        steps.append({'kind': step['kind'], 'suite': suite, 'job_id': job_id,
                      'status': current.get('status'), 'run_id': result.get('id'),
                      'run_state': result.get('state'),
                      'recovery_required': bool(current.get('recovery_required'))})
        if on_update:
            on_update({'phase': 'step-finished', 'step': step, 'result': steps[-1]})
        if (current.get('status') != 'completed' or current.get('recovery_required') or
                result.get('state') != 'completed'):
            outcome = 'incomplete'
            if cancel is not None and cancel.is_set():
                outcome = 'cancelled'
            break
    return {'schema': SCHEMA, 'lap_id': lap_id, 'size': plan['size'], 'outcome': outcome,
            'complete': outcome == 'completed' and len(steps) == len(plan['steps']), 'steps': steps}
