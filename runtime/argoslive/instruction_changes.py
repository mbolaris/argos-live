"""Bounded agent-chosen instruction experiments and an auditable host journal.

Only canonical AGENTS.md can change. No path, command, evaluator, permission or
provider credential is a tool argument. Same-UID unmediated writes remain outside
this cooperative boundary until protected service deployment.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import statistics
import copy

from . import storage, workload
from .assistant_trial import agents_path
from .bench_ability import summaries
from .evaluation_context import configuration_receipt, configuration_from, receipt_from, EXECUTION_PATH
from .model_selection import replace_raw
from .pull_jobs import read_json, write_json
from .results import Store, compare, identifier, same_hardware

SCHEMA = 'argos-instruction-change/1'
POLICY = {'id': 'argos-practice-keep/1', 'repeats_each': 2,
          'minimum_correct_delta': {'openclaw-quick': 2, 'openclaw-standard': 4},
          'reliability_max_latency_ratio': 1.5}


class Refused(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit, *, empty=False):
    try:
        valid = (isinstance(value, str) and (empty or bool(value.strip())) and
                 len(value.encode('utf-8')) <= limit and not any(ord(c) < 32 and c not in '\n\t' for c in value))
    except UnicodeError:
        valid = False
    if not valid:
        raise Refused('invalid-text')


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise Refused('invalid-instruction-hash')


def run_id(value):
    try:
        return identifier(value)
    except ValueError:
        raise Refused('invalid-saved-id') from None


def validate_request(operation, params):
    if not isinstance(params, dict):
        raise Refused('invalid-request')
    if operation == 'inspect':
        if params:
            raise Refused('inspection-takes-no-path-or-arguments')
    elif operation == 'edit':
        if set(params) != {'baseline_id', 'expected_sha256', 'find', 'replace', 'hypothesis'}:
            raise Refused('invalid-edit-fields')
        run_id(params['baseline_id'])
        sha(params['expected_sha256'])
        text(params['find'], 4096)
        text(params['replace'], 4096, empty=True)
        text(params['hypothesis'], 1024)
        if params['find'] == params['replace']:
            raise Refused('edit-does-not-change-bytes')
    elif operation == 'resolve':
        if set(params) - {'change_id', 'expected_sha256', 'action', 'baseline_ids', 'candidate_ids'}:
            raise Refused('invalid-resolution-fields')
        run_id(params.get('change_id'))
        sha(params.get('expected_sha256'))
        if params.get('action') not in {'keep', 'restore'}:
            raise Refused('invalid-resolution-action')
        for field in ('baseline_ids', 'candidate_ids'):
            values = params.get(field, [])
            if (not isinstance(values, list) or len(values) > 8 or
                    any(not isinstance(value, str) for value in values) or len(set(values)) != len(values)):
                raise Refused('invalid-evidence-ids')
            for value in values:
                run_id(value)
        if params['action'] == 'keep' and any(len(params.get(field, [])) < 2 for field in ('baseline_ids', 'candidate_ids')):
            raise Refused('keep-needs-two-baseline-and-two-candidate-runs')
    else:
        raise Refused('unsupported-instruction-operation')


def root_path(home):
    root = storage.safe_local(Path(home) / '.local/state/argos-live/instruction-changes')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def read_owned(path, limit):
    path = storage.safe_local(path)
    info = path.stat()
    if (not path.is_file() or info.st_nlink != 1 or info.st_size > limit or
            os.name != 'nt' and info.st_uid != os.getuid()):
        raise Refused('input-is-not-a-bounded-owner-file')
    raw = path.read_bytes()
    if len(raw) > limit:
        raise Refused('input-exceeds-limit')
    return raw


def inputs(home):
    expected = storage.safe_local(Path(home) / '.openclaw/workspace/AGENTS.md')
    if agents_path(home) != expected:
        raise Refused('managed-instructions-require-canonical-workspace')
    raw = read_owned(expected, 65536)
    raw.decode('utf-8')
    config = read_owned(Path(home) / '.openclaw/openclaw.json', 1024**2)
    return expected, raw, config, configuration_receipt(home)


def state(root):
    path = root / 'state.json'
    value = read_json(path) if path.exists() else {'schema': SCHEMA, 'sequence': 0, 'active': None, 'last_id': None}
    if value.get('schema') != SCHEMA or type(value.get('sequence')) is not int:
        raise workload.Busy(recovery=True)
    if value.get('active') and value['active'].get('phase') != 'applied':
        raise workload.Busy(recovery=True)
    return value


def new_file(path, raw):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def immutable(path, value):
    new_file(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())


def load_run(home, run_id, expected_hash, config_hash, parent, generation):
    try:
        run = Store(Path(home) / '.local/share/argos-live/results').load(run_id)
    except ValueError:
        raise Refused('saved-run-is-missing-or-invalid') from None
    if (run.get('state') != 'completed' or not run.get('coverage', {}).get('complete') or
            run.get('settings', {}).get('execution_path') != EXECUTION_PATH or
            run.get('prompt_fingerprint', {}).get('workspace_agents_sha256') != expected_hash or
            run.get('prompt_fingerprint', {}).get('evaluation_config_sha256') != config_hash or
            run.get('summary') != summaries(run.get('items', []))):
        raise Refused('run-does-not-match-this-instruction-experiment')
    # A model cannot borrow an old result from another controller reservation.
    matches = []
    for path in (Path(home) / '.local/state/argos-live/workload/child').glob('*.json'):
        child = read_json(path)
        if (child.get('parent_id'), child.get('generation'), child.get('kind'),
                child.get('state'), child.get('result_id')) == (parent, generation, 'evaluation', 'released', run_id):
            matches.append(child)
    if len(matches) != 1:
        raise Refused('run-is-not-from-this-host-controller')
    return run, matches[0]


def inspect(home, root):
    _path, raw, _config, receipt = inputs(home)
    current = state(root)
    return {'status': 'inspected', 'instructions': raw.decode('utf-8'), 'sha256': digest(raw),
            'configuration': receipt, 'active_change': current.get('active'), 'keep_policy': copy.deepcopy(POLICY),
            'scope': 'configured instruction/practice evidence; not independent verification'}


def edit(home, root, params, slot):
    path, before, config, receipt = inputs(home)
    current = state(root)
    if current['active']:
        raise Refused('resolve-current-change-before-editing-again')
    if digest(before) != params['expected_sha256']:
        raise Refused('instructions-changed-since-inspection')
    if current['last_id']:
        resolved = read_json(root / current['last_id'] / 'resolved.json')
        if resolved['result_sha256'] != digest(before):
            raise Refused('untracked-owner-edit-needs-review')
    source = before.decode('utf-8')
    if source.count(params['find']) != 1:
        raise Refused('find-must-match-exactly-once')
    after = source.replace(params['find'], params['replace'], 1).encode('utf-8')
    if len(after) > 65536:
        raise Refused('resulting-instructions-exceed-limit')
    parent = slot.record.get('parent_id')
    if not parent:
        raise Refused('instruction-changes-require-host-controller-delegation')
    baseline, admission = load_run(home, params['baseline_id'], digest(before), receipt['sha256'],
                                   parent, slot.record['generation'])
    observed = stamp()
    if datetime.fromisoformat(baseline['created']) > datetime.fromisoformat(observed):
        raise Refused('baseline-clock-is-ahead-of-this-change')
    change_id = secrets.token_hex(16)
    directory = root / change_id
    directory.mkdir(mode=0o700)
    new_file(directory / 'before.bin', before)
    new_file(directory / 'after.bin', after)
    new_file(directory / 'openclaw.json', config)
    immutable(directory / 'baseline.json', baseline)
    immutable(directory / 'baseline-admission.json', admission)
    intent = {'schema': SCHEMA, 'id': change_id, 'sequence': current['sequence'] + 1,
              'previous_id': current['last_id'], 'parent_id': parent, 'generation': slot.record['generation'],
              'observed': observed, 'hypothesis': params['hypothesis'], 'baseline_id': baseline['id'],
              'find': params['find'], 'replacement': params['replace'],
              'before_sha256': digest(before), 'after_sha256': digest(after),
              'config_sha256': digest(config), 'evaluation_config_sha256': receipt['sha256'],
              'baseline_sha256': digest((json.dumps(baseline, sort_keys=True, indent=2) + '\n').encode())}
    immutable(directory / 'intent.json', intent)
    current.update(sequence=intent['sequence'], active={'id': change_id, 'phase': 'prepared'})
    write_json(root / 'state.json', current)
    # Admission serializes cooperating writers. Protected ownership is still
    # required to exclude an arbitrary same-UID editor's rename race.
    if path.read_bytes() != before or (Path(home) / '.openclaw/openclaw.json').read_bytes() != config:
        raise workload.Busy(recovery=True)
    replace_raw(path, after)
    if path.read_bytes() != after:
        raise workload.Busy(recovery=True)
    immutable(directory / 'applied.json', {'observed': stamp(), 'sha256': digest(path.read_bytes())})
    current['active'] = {'id': change_id, 'phase': 'applied', 'before_sha256': digest(before),
                         'after_sha256': digest(after), 'baseline_id': baseline['id']}
    write_json(root / 'state.json', current)
    return {'status': 'changed', 'change_id': change_id, 'before_sha256': digest(before),
            'after_sha256': digest(after), 'observed': intent['observed'], 'snapshot_saved': True}


def evidence(home, intent, directory, params):
    baseline_ids = params.get('baseline_ids', [intent['baseline_id']])
    if intent['baseline_id'] not in baseline_ids:
        raise Refused('include-the-original-baseline')
    candidate_ids = params.get('candidate_ids', [])
    if len(set(baseline_ids + candidate_ids)) != len(baseline_ids + candidate_ids):
        raise Refused('evidence-runs-must-be-distinct')
    groups = []
    for ids, expected in ((baseline_ids, intent['before_sha256']), (candidate_ids, intent['after_sha256'])):
        group = []
        for run_id in ids:
            run, admission = load_run(home, run_id, expected, intent['evaluation_config_sha256'],
                                      intent['parent_id'], intent['generation'])
            created = datetime.fromisoformat(run['created'])
            if (expected == intent['before_sha256'] and created > datetime.fromisoformat(intent['observed']) or
                    expected == intent['after_sha256'] and created < datetime.fromisoformat(
                        read_json(directory / 'applied.json')['observed'])):
                raise Refused('evidence-is-not-from-the-measured-change-window')
            group.append((run, admission))
        groups.append(group)
    runs = [pair[0] for group in groups for pair in group]
    if len(runs) > 1:
        try:
            compare(runs)
        except ValueError:
            raise Refused('evidence-runs-are-not-comparable') from None
        if any(run['model'] != runs[0]['model'] or not same_hardware(runs[0], run) for run in runs):
            raise Refused('evidence-needs-the-same-model-tag-and-hardware')
    result = {'baseline_ids': baseline_ids, 'candidate_ids': candidate_ids,
              'qualified_experiment': bool(candidate_ids), 'independent_gain_verified': False}
    if params['action'] == 'keep':
        bases, candidates = [[pair[0] for pair in group] for group in groups]
        minimum = POLICY['minimum_correct_delta'].get(bases[0]['suite'])
        if minimum is None:
            raise Refused('unsupported-keep-suite')
        base_score = max(run['summary']['correct'] for run in bases)
        candidate_score = min(run['summary']['correct'] for run in candidates)
        base_errors = min(run['summary']['format_errors'] for run in bases)
        candidate_errors = max(run['summary']['format_errors'] for run in candidates)
        ratio = statistics.median(run['elapsed_seconds'] for run in candidates) / max(
            .000001, statistics.median(run['elapsed_seconds'] for run in bases))
        accuracy = candidate_score - base_score >= minimum and candidate_errors <= base_errors
        reliability = (candidate_score >= base_score and candidate_errors < base_errors and
                       ratio <= POLICY['reliability_max_latency_ratio'])
        if not (accuracy or reliability):
            raise Refused('repeated-practice-gain-rule-not-met')
        result.update(policy=copy.deepcopy(POLICY), minimum_correct_gain=candidate_score - base_score,
                      maximum_candidate_format_errors=candidate_errors, latency_ratio=ratio,
                      gain_kind='accuracy' if accuracy else 'reliability',
                      limitation='Configured model tag matched; installed weight identity/generalization need independent verification')
    return result, groups


def resolve(home, root, params):
    path, raw, _config, receipt = inputs(home)
    current = state(root)
    if not current['active'] or current['active']['id'] != params['change_id']:
        raise Refused('change-is-not-active')
    directory = root / identifier(params['change_id'])
    intent = read_json(directory / 'intent.json')
    before = read_owned(directory / 'before.bin', 65536)
    after = read_owned(directory / 'after.bin', 65536)
    if digest(before) != intent['before_sha256'] or digest(after) != intent['after_sha256']:
        raise workload.Busy(recovery=True)
    if digest(raw) != params['expected_sha256'] or raw != after:
        raise Refused('candidate-instructions-were-edited-preserving-owner-bytes')
    if params['action'] == 'keep' and receipt['sha256'] != intent['evaluation_config_sha256']:
        raise Refused('configuration-changed-during-instruction-experiment')
    try:
        measured, groups = evidence(home, intent, directory, params)
    except Refused as error:
        if params['action'] != 'restore':
            raise
        # Restoring known bytes must not require a successful/comparable exam.
        # Unverified supplied IDs are not promoted into measurement claims.
        baseline_raw = read_owned(directory / 'baseline.json', 1024**2)
        if digest(baseline_raw) != intent['baseline_sha256']:
            raise workload.Busy(recovery=True)
        measured = {'baseline_ids': [intent['baseline_id']], 'candidate_ids': [],
                    'qualified_experiment': False, 'independent_gain_verified': False,
                    'rejected_evidence_code': str(error)}
        groups = [[(json.loads(baseline_raw), read_json(directory / 'baseline-admission.json'))], []]
    files = directory / 'evidence'
    files.mkdir(mode=0o700)
    for group in groups:
        for run, admission in group:
            immutable(files / (run['id'] + '.json'), run)
            immutable(files / (run['id'] + '-admission.json'), admission)
    action = params['action']
    immutable(directory / 'resolution-intent.json', {'observed': stamp(), 'action': action, **measured})
    current['active']['phase'] = 'resolving'
    write_json(root / 'state.json', current)
    if path.read_bytes() != after:
        raise workload.Busy(recovery=True)
    if action == 'restore':
        replace_raw(path, before)
    expected = before if action == 'restore' else after
    if path.read_bytes() != expected:
        raise workload.Busy(recovery=True)
    observed = stamp()
    immutable(directory / 'resolved.json', {'observed': observed, 'action': action,
              'result_sha256': digest(expected), **measured})
    current.update(active=None, last_id=intent['id'])
    write_json(root / 'state.json', current)
    return {'status': 'restored' if action == 'restore' else 'kept', 'change_id': intent['id'],
            'sha256': digest(expected), 'observed': observed, 'configuration_preserved': True, **measured}


def perform(home, operation, params, *, delegation=None):
    with workload.reserve(home, 'maintenance', delegation=delegation) as slot:
        try:
            validate_request(operation, params)
            root = root_path(home)
            if operation == 'inspect':
                result = inspect(home, root)
            elif operation == 'edit':
                result = edit(home, root, params, slot)
            else:
                result = resolve(home, root, params)
        except Refused as error:
            result = {'status': 'rejected', 'code': str(error), 'workspace_mutated': False}
        slot.complete()
        return result


def audit(home):
    """Verify host instruction events, snapshots and evidence; no prose inference.

    This does not certify the free-form IMPROVEMENT-LOG or independent model gain.
    It is read-only and never repairs/reclaims an uncertain journal.
    """
    report = {'scope': 'host instruction journal only', 'passed': False, 'changes': [],
              'full_log_claims_verified': False, 'independent_gain_verified': False}
    try:
        root = storage.safe_local(Path(home) / '.local/state/argos-live/instruction-changes')
        current = read_json(root / 'state.json')
        if current['schema'] != SCHEMA or current['active'] is not None:
            raise ValueError('unfinished-change')
        entries = []
        for directory in root.iterdir():
            if re.fullmatch('[a-f0-9]{32}', directory.name):
                entries.append((read_json(directory / 'intent.json'), directory))
        entries.sort(key=lambda item: item[0]['sequence'])
        previous, previous_sha = None, None
        for index, (intent, directory) in enumerate(entries, 1):
            before = read_owned(directory / 'before.bin', 65536)
            after = read_owned(directory / 'after.bin', 65536)
            config = read_owned(directory / 'openclaw.json', 1024**2)
            baseline = read_owned(directory / 'baseline.json', 1024**2)
            applied = read_json(directory / 'applied.json')
            resolved = read_json(directory / 'resolved.json')
            resolution = read_json(directory / 'resolution-intent.json')
            if (intent['id'] != directory.name or intent['schema'] != SCHEMA or
                    intent['sequence'] != index or intent['previous_id'] != previous or
                    digest(before) != intent['before_sha256'] or digest(after) != intent['after_sha256'] or
                    digest(config) != intent['config_sha256'] or digest(baseline) != intent['baseline_sha256'] or
                    receipt_from(configuration_from(json.loads(config)))['sha256'] != intent['evaluation_config_sha256'] or
                    applied['sha256'] != digest(after) or previous_sha is not None and digest(before) != previous_sha):
                raise ValueError('snapshot-or-chain-mismatch')
            source = before.decode('utf-8')
            if source.count(intent['find']) != 1 or source.replace(intent['find'], intent['replacement'], 1).encode() != after:
                raise ValueError('patch-replay-mismatch')
            timestamps = [datetime.fromisoformat(item['observed']) for item in (intent, applied, resolution, resolved)]
            if timestamps != sorted(timestamps) or any(item.tzinfo is None for item in timestamps):
                raise ValueError('event-time-mismatch')
            if resolution['action'] != resolved['action']:
                raise ValueError('resolution-mismatch')
            resulting = digest(before if resolved['action'] == 'restore' else after)
            if resolved['action'] not in {'keep', 'restore'} or resolved['result_sha256'] != resulting:
                raise ValueError('resolution-byte-mismatch')
            if not resolved.get('rejected_evidence_code'):
                measured, groups = evidence(home, intent, directory, {
                    'action': resolved['action'], 'baseline_ids': resolved['baseline_ids'],
                    'candidate_ids': resolved['candidate_ids']})
                if any(resolved.get(key) != value or resolution.get(key) != value for key, value in measured.items()):
                    raise ValueError('measured-evidence-mismatch')
                for group in groups:
                    for run, admission in group:
                        if (read_json(directory / 'evidence' / (run['id'] + '.json')) != run or
                                read_json(directory / 'evidence' / (run['id'] + '-admission.json')) != admission):
                            raise ValueError('saved-evidence-mismatch')
            elif resolved['action'] != 'restore' or resolved.get('qualified_experiment') is not False:
                raise ValueError('unverified-evidence-claimed-as-gain')
            report['changes'].append({'change_id': intent['id'], 'action': resolved['action'],
                'before_sha256': digest(before), 'after_sha256': digest(after),
                'qualified_experiment': resolved['qualified_experiment'], 'observed': resolved['observed']})
            previous, previous_sha = intent['id'], resulting
        _path, live, _config, _receipt = inputs(home)
        if (not entries or current['sequence'] != len(entries) or current['last_id'] != previous or
                digest(live) != previous_sha):
            raise ValueError('current-instructions-or-index-mismatch')
        report.update(passed=True, qualified_experiments=sum(item['qualified_experiment'] for item in report['changes']))
    except (ValueError, KeyError, OSError, TypeError) as error:
        report['error'] = type(error).__name__  # Never echo private inputs/paths.
    return report
