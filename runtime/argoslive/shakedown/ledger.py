"""Responses, per-run sim records and a rebuildable readiness ledger.

Scorer rules and matcher values remain host-side. Practice and sealed evidence is summarized
independently at every step; a sealed result never borrows practice counts to qualify a console.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re

from .. import ability, results
from . import diagnose, fault, taxonomy

RESPONSE_SCHEMA = 'argos-sim-response/1'
SIM_SCHEMA = 'argos-sim-record/1'
LEDGER_SCHEMA = 'argos-sim-ledger/1'
SUITE_VERSION = re.compile(r'argos-openclaw-ability/([a-z][a-z0-9-]*)/(\d+\.\d+\.\d+)')
SUPPORTED = {'challenge', 'tool-schema', 'tool-plan', 'tool-sequence'}
SHA256 = re.compile(r'(?:sha256:)?[0-9a-f]{64}')

STATE_UNTESTED = 'untested'
STATE_GO = 'go'
STATE_WATCH = 'watch'
STATE_NO_GO = 'no-go'
MIN_GO_RESPONSES = 6
MIN_GO_FAMILIES = 2
GO_ACCURACY = 0.85
MIN_NO_GO_RESPONSES = 3
NO_GO_ACCURACY = 0.50


def fingerprint_for(run):
    """Opaque grouping key for a model manifest and workspace instruction digest.

    Older records that lack either digest are deliberately not grouped: a model tag is not a
    substitute for the model weights digest.
    """
    model_digest = run.get('manifest_digest') if isinstance(run, dict) else None
    prompt = run.get('prompt_fingerprint') if isinstance(run, dict) else None
    instructions = prompt.get('workspace_agents_sha256') if isinstance(prompt, dict) else None
    if (not isinstance(model_digest, str) or not SHA256.fullmatch(model_digest)
            or not isinstance(instructions, str) or not re.fullmatch(r'[0-9a-f]{64}', instructions)):
        return None
    raw = json.dumps([model_digest, instructions], separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _form(run):
    match = SUITE_VERSION.fullmatch(run.get('suite_version', ''))
    if run.get('kind') != 'ability' or match is None or match.group(1) not in SUPPORTED:
        raise ValueError('The saved run is not one of the shipped sidecar ability suites')
    name, version = match.groups()
    form = ability.load(name, version)
    return name, version, form, fault.load(name, version, suite=form)


def _reply_seconds(saved):
    value = saved.get('latency_seconds', saved.get('reply_seconds'))
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def responses(run):
    """Build host-only, answer-free response records for the items saved in `run`."""
    results.validate(run)
    _, _, form, sidecar = _form(run)
    tasks = {item['id']: item for item in form['items']}
    cards = {card['item']: card for card in sidecar['cards']}
    records = []
    for saved in run['items']:
        item_id = saved['item_id']
        item, card = tasks.get(item_id), cards.get(item_id)
        if item is None or card is None:
            raise ValueError('Saved run contains an item outside its exact suite version')
        codes = diagnose.diagnose(card, item, saved)
        detector = None
        for entry in card['diagnostics']:
            if entry['code'] in codes and diagnose.matches(entry['when'], item, saved):
                detector = {'matcher': next(iter(entry['when'])), 'card_version': sidecar['card_version']}
                break
        raw_outcome = saved.get('outcome')
        if raw_outcome == 'pass':
            outcome = 'nominal'
        elif raw_outcome in diagnose.MISSES:
            outcome = 'recovered' if saved.get('recovered') is True else 'failed'
        else:
            outcome, codes, detector = 'unscored', [], None
        records.append({
            'schema': RESPONSE_SCHEMA,
            'run_id': run['id'],
            'item': item_id,
            'console': card['console'],
            'family': card['family'],
            'tier': card['tier'],
            'partition': card['partition'],
            'outcome': outcome,
            'codes': codes,
            'detector': detector,
            'reply_seconds': _reply_seconds(saved),
            'tool_calls': (saved.get('tool_calls') if type(saved.get('tool_calls')) is int
                           and saved['tool_calls'] >= 0 else 0),
            'recovery': {'offered': saved.get('recovery_offered') is True,
                         'recovered': outcome == 'recovered'},
        })
    return records


def _run_id(value):
    if isinstance(value, dict):
        return value.get('id')
    return value if isinstance(value, str) else None


def sim(run, baseline=None):
    """Derive one sim record. Partial and exploratory runs are retained but never comparable."""
    results.validate(run)
    form_name, version, _, _ = _form(run)
    records = responses(run)
    created = run['created']
    try:
        created_order = datetime.fromisoformat(created).timestamp()
    except (ValueError, OverflowError):
        created_order = 0
    coverage = run.get('coverage', {})
    complete = (run.get('state') == 'completed' and coverage.get('complete') is True
                and coverage.get('completed') == coverage.get('total'))
    kind = run.get('sim_kind', 'reference')
    if kind not in ('reference', 'stress'):
        raise ValueError('Sim kind must be reference or stress')
    comparable = complete and kind == 'reference'
    timings = [row['reply_seconds'] for row in records if row['reply_seconds'] is not None]
    slowest = max((row for row in records if row['reply_seconds'] is not None),
                  key=lambda row: (row['reply_seconds'], row['item']), default=None)
    return {
        'schema': SIM_SCHEMA,
        'run_id': run['id'],
        'created': created,
        'created_order': created_order,
        'sim_kind': kind,
        'form': form_name,
        'version': version,
        'comparable': comparable,
        'responses': records,
        'timing': {
            'median_reply_seconds': _median(timings),
            'slowest_item': slowest['item'] if slowest else None,
            'slowest_reply_seconds': slowest['reply_seconds'] if slowest else None,
            'tool_calls': sum(row['tool_calls'] for row in records),
        },
        'watch_id': run.get('watch_id'),
        'baseline_run_id': _run_id(baseline),
        'fingerprint': fingerprint_for(run),
    }


def _median(values):
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def _state(scored, latest_reference):
    """Readiness state for one console and one partition; never receives mixed partitions."""
    if not scored:
        return STATE_UNTESTED
    correct = sum(row['outcome'] in ('nominal', 'recovered') for row in scored)
    accuracy = correct / len(scored)
    repeated = defaultdict(lambda: defaultdict(set))
    for row in scored:
        if row.get('outcome') != 'failed':
            continue
        for code in row.get('codes', []):
            repeated[row.get('sim_id')][code].add(row['item'])
    repeated_fault = any(len(items) >= 2 for by_code in repeated.values() for items in by_code.values())
    if repeated_fault or (len(scored) >= MIN_NO_GO_RESPONSES and accuracy < NO_GO_ACCURACY):
        return STATE_NO_GO
    no_latest_miss = not any(row.get('outcome') == 'failed' for row in latest_reference)
    families = {row.get('family') for row in scored if row.get('family') is not None}
    if (len(scored) >= MIN_GO_RESPONSES and len(families) >= MIN_GO_FAMILIES
            and accuracy >= GO_ACCURACY and no_latest_miss):
        return STATE_GO
    return STATE_WATCH


def _partition_ledger(console_id, partition, responses_for_partition, latest_reference, run_ids):
    scored = [row for row in responses_for_partition if row['outcome'] != 'unscored']
    nominal = sum(row['outcome'] in ('nominal', 'recovered') for row in scored)
    tier_counts = {str(tier): [0, 0] for tier in fault.TIERS}
    codes, families = Counter(), defaultdict(lambda: [0, 0])
    for row in scored:
        tier = str(row['tier'])
        tier_counts[tier][1] += 1
        if row['outcome'] in ('nominal', 'recovered'):
            tier_counts[tier][0] += 1
        if row['outcome'] == 'failed':
            codes.update(row['codes'])
        if row['family'] is not None:
            families[row['family']][1] += 1
            families[row['family']][0] += int(row['outcome'] in ('nominal', 'recovered'))
    worst = min(families, key=lambda family: (families[family][0] / families[family][1], family)) if families else None
    latest = latest_reference.get((console_id, partition), [])
    state = _state([{**row, 'sim_id': row.get('sim_id')} for row in scored], latest)
    return {
        'state': state,
        'scored': len(scored),
        'nominal': nominal,
        'by_tier': tier_counts,
        'codes': dict(sorted(codes.items())),
        'worst_family': worst,
        'last_reference_run': run_ids.get((console_id, partition)),
        'fixes': [],
    }


def ledger(store, fingerprint):
    """Rebuild a ledger from a `results.Store` for one verified identity fingerprint."""
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('A model and instruction fingerprint is required')
    summaries = store.list()
    if summaries.get('rejected'):
        # Bad files cannot silently disappear from longitudinal evidence.
        raise ValueError('Saved result store contains invalid records')
    sims = []
    for summary in summaries.get('runs', []):
        if summary.get('kind') != 'ability':
            continue
        run = store.load(summary['id'])
        if fingerprint_for(run) != fingerprint:
            continue
        try:
            record = sim(run)
        except ValueError as exc:
            if 'not one of the shipped sidecar ability suites' in str(exc):
                continue
            raise
        sims.append(record)
    sims.sort(key=lambda record: (record['created_order'], record['run_id']))
    comparable = [record for record in sims if record['comparable']]
    all_responses = [row for record in comparable for row in record['responses']]
    latest_reference, latest_ids = {}, {}
    for record in comparable:
        if record['sim_kind'] != 'reference':
            continue
        per_key = defaultdict(list)
        for row in record['responses']:
            if row['outcome'] != 'unscored':
                per_key[(row['console'], row['partition'])].append({**row, 'sim_id': record['run_id']})
        for key, values in per_key.items():
            latest_reference[key] = values
            latest_ids[key] = record['run_id']
    consoles = {}
    for console in taxonomy.console_ids():
        partitions = {}
        for partition in fault.PARTITIONS:
            rows = [{**row, 'sim_id': record['run_id']}
                    for record in comparable for row in record['responses']
                    if row['console'] == console and row['partition'] == partition]
            partitions[partition] = _partition_ledger(
                console, partition, rows, latest_reference, latest_ids)
        # The top-level state is the sealed state; practice evidence never raises readiness.
        consoles[console] = {'state': partitions['sealed']['state'], **partitions}
    return {'schema': LEDGER_SCHEMA, 'consoles': consoles}


def public_sim(record):
    """Allowlisted public projection of a sim; excludes fingerprints and host-only values."""
    if not isinstance(record, dict) or record.get('schema') != SIM_SCHEMA:
        raise ValueError('Invalid sim record')
    public_responses = []
    for row in record.get('responses', []):
        public_responses.append({key: deepcopy(row.get(key)) for key in (
            'schema', 'run_id', 'item', 'console', 'family', 'tier', 'partition', 'outcome', 'codes',
            'detector', 'reply_seconds', 'tool_calls', 'recovery')})
    timing = record.get('timing', {})
    return {
        'schema': SIM_SCHEMA,
        'run_id': record.get('run_id'),
        'kind': record.get('sim_kind'),
        'form': record.get('form'),
        'version': record.get('version'),
        'comparable': record.get('comparable') is True,
        'responses': public_responses,
        'timing': {key: deepcopy(timing.get(key)) for key in (
            'median_reply_seconds', 'slowest_item', 'slowest_reply_seconds', 'tool_calls')},
        'watch_id': record.get('watch_id'),
        'baseline_run_id': record.get('baseline_run_id'),
    }


def public_ledger(value):
    """Allowlisted public ledger projection with practice and sealed values kept separate."""
    if not isinstance(value, dict) or value.get('schema') != LEDGER_SCHEMA:
        raise ValueError('Invalid readiness ledger')
    consoles = {}
    partition_keys = ('state', 'scored', 'nominal', 'by_tier', 'codes', 'worst_family',
                      'last_reference_run', 'fixes')
    for console, entry in value.get('consoles', {}).items():
        if console not in taxonomy.console_ids() or not isinstance(entry, dict):
            raise ValueError('Invalid readiness console')
        projected = {'state': entry.get('state')}
        for partition in fault.PARTITIONS:
            raw = entry.get(partition)
            if not isinstance(raw, dict):
                raise ValueError('Readiness ledger is missing a partition')
            projected[partition] = {key: deepcopy(raw.get(key)) for key in partition_keys}
        consoles[console] = projected
    return {'schema': LEDGER_SCHEMA, 'consoles': consoles}
