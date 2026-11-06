"""Questionless fresh Live configuration; never replace an owner configuration."""
import json
import hashlib
import os
from pathlib import Path
import secrets

from . import starter, storage, session_mode
from .pull_jobs import read_json

PLUGIN_ROOT = '/usr/local/share/argos-live/plugins/argos-improve'
# Seed once in a fresh workspace; only exact, snapshot-backed migrations may
# update existing owner files, and they preserve all bytes outside the target.
WORKSPACE_FILES = (('AGENTS.md', 'SELF-IMPROVEMENT-AGENTS.md'), ('SOUL.md', 'SELF-IMPROVEMENT-SOUL.md'),
                   ('IDENTITY.md', 'SELF-IMPROVEMENT-IDENTITY.md'),
                   ('tools/argos-control.py', 'SELF-IMPROVEMENT-CONTROL.py'))
# Resumption is allowed only for an owner-started campaign. Prompt guardrails
# supplement host admission; they are not an enforcement boundary.
PREVIOUS_GUARDED_HEARTBEAT_PROMPT = (
    'Self-improvement heartbeat. First run `python3 tools/argos-control.py status` and read '
    '`tail -n 30 IMPROVEMENT-LOG.md`. If a download or evaluation is running, a workload needs '
    'recovery, or the assistant is not ready, reply exactly HEARTBEAT_OK. Never start a new '
    'campaign on a heartbeat. Only resume a campaign explicitly requested by the owner. A "## Next" '
    'entry that says it is awaiting owner direction, approval, or another owner-dependent decision is '
    'paused: reply exactly HEARTBEAT_OK without changing files, snapshots, or the log. Resume it only '
    'after the owner gives explicit direction in the campaign controller conversation. If it has a '
    'runnable "## Next" step and no "## Done" section, your campaign is active: take the last Next step now, '
    'following AGENTS.md, then append one short entry with argos_log. Call argos_evaluate and '
    'argos_compare as tools. If evaluation returns running, use argos_evaluate_wait until saved; '
    'if a turn ended before its job ID returned, call argos_evaluate_status first. Never start a '
    'second evaluation or edit during a running job. Never install software, use sudo, clone repositories or request secrets. '
    'If there is no active campaign, reply exactly HEARTBEAT_OK.')

HEARTBEAT_PROMPT = (
    'Self-improvement heartbeat. First run `python3 tools/argos-control.py status` and read '
    '`tail -n 30 IMPROVEMENT-LOG.md`. If a download or evaluation is running, a workload needs '
    'recovery, or the assistant is not ready, reply exactly HEARTBEAT_OK. Never start a new '
    'campaign on a heartbeat. Only resume a campaign explicitly requested by the owner. A "## Next" '
    'entry that says it is awaiting owner direction, approval, or another owner-dependent decision is '
    'paused: reply exactly HEARTBEAT_OK without changing files, snapshots, or the log. Resume it only '
    'after the owner gives explicit direction in the campaign controller conversation. Before taking '
    'a runnable step, reconcile it against saved results with `argos bench results` and '
    '`argos_evaluate_status`, matching suite, version, model and configuration; a missing log entry '
    'does not mean a completed run was lost. If matching saved results already satisfy the step, do '
    'not rerun it: record the verified run IDs and scores with '
    'argos_log and advance ## Next. After every new evaluation is saved, append its actual run ID, '
    'score and complete next action with argos_log before starting another evaluation. For a runnable '
    '"## Next" step and no "## Done" section, take the next unfinished step following AGENTS.md. '
    'Before diagnosing a miss, inspect the exact item prompt and scorer requirements. A tool-call miss '
    'cannot establish a general selection, refusal or formatting weakness when the item omits the '
    'available-tool inventory or required schemas; do not infer intent from hidden answer labels. '
    'Report that measurement as under-specified and use a separately versioned, fully specified form '
    'for a new baseline. Never change a fixed suite to fit a candidate. '
    'Call argos_evaluate and argos_compare as tools. If evaluation returns running, use '
    'argos_evaluate_wait until saved; if a turn ended before the job ID returned, call '
    'argos_evaluate_status first. Never start a second evaluation or edit during a running job. '
    'Never install software, use sudo, clone repositories or request secrets. If there is no active '
    'campaign, reply exactly HEARTBEAT_OK.')

# Exact heartbeat prompt observed in the deployed pre-guard Toronado profile.
# Only this generated default is eligible for the one-field migration below.
LEGACY_HEARTBEAT_PROMPT = ('Self-improvement heartbeat. First run `python3 tools/argos-control.py status` and read '
                           '`tail -n 30 IMPROVEMENT-LOG.md`. If a download or evaluation is running, a workload needs '
                           'recovery, or the assistant is not ready, reply exactly HEARTBEAT_OK. Never start a new '
                           'campaign on a heartbeat. Only resume a campaign explicitly requested by the owner. If it has a '
                           '"## Next" step and no "## Done" section, your campaign is active: take the last Next step now, '
                           'following AGENTS.md, then append one short entry with argos_log. Call argos_evaluate and '
                           'argos_compare as tools. Never install software, use sudo, clone repositories or request secrets. '
                           'If there is no active campaign, '
                           'reply exactly HEARTBEAT_OK.')

# Exact workspace guide observed on Toronado on 2026-11-01. The migration below
# replaces only its obsolete suite-first/model-first sections and preserves the
# rest of the owner's customized guide. Any other bytes require review.
LEGACY_OWNER_GUIDE_SHA256 = '318fb6341ccb28d4d6bd6a930a147ee59993a4cc6af46af0b20b5c63c2ed8c1c'
OWNER_TASK_GUIDANCE = '''## 2. Measure one change at a time

First state the recurring owner task and observable success measure. Keep system
readiness (boot, persistence, services) separate from model behavior. Use a
fixed evaluation suite only when its exact tasks directly measure the owner
task. If none fits, do not steer the owner toward generic scores or change
instructions/models from unrelated results. Report `task-not-measured` and draft
the specific task cases and checks needed from sanitized incidents; get review
before using them to qualify a change. Raw-model `argos bench ability` measures
a model, not the configured assistant or end-to-end task success.

When relevant evidence exists, compare fresh matched baselines and candidates
with the same task, model, configuration, tools and setup. Make one reversible
change, verify the saved results, and keep it only when the owner-valued outcome
improves without a safety or effort regression. Use only host-managed evaluation
and instruction tools. Every evaluation wait is bounded; continue a host-owned
job with its returned job ID and never overlap evaluations.

## 3. Improvement order and authority

**A. Owner task first.** Keep qwen3.8:27b selected unless repeated, matched
owner-task evidence shows model capability is the limiting factor. Do not
download or switch to qwen3:30b based on fit, parameter count, catalog claims,
or saturated generic suites. The current qwen3:30b candidate lacks the
configured model's thinking and vision capabilities, so it is not a matched
comparison. If no relevant task measure exists, preserve the current model and
work on the reviewed task cases instead of starting a model trial.

'''
LEGACY_MODEL_PLATEAU_GUIDANCE = '''Stop at a measured plateau when the strongest reviewed fitting model is selected
(or larger candidates measured worse), three distinct recent experiments yield
no confirmed gain, and any software upgrade found has been proposed.'''
OWNER_TASK_STOP_GUIDANCE = '''Stop when the owner-valued task outcome is measurably better, evidence is
inconclusive after a reasonable number of trials, or the next step needs an
owner decision. A synthetic-suite plateau does not prove maximum capability.'''

# Read-only Proctor tools needed to close instruction audits and perform
# signed SSH status checks without asking the owner to type terminal commands.
PROCTOR_READONLY_TOOLS = ['argos_inspect', 'argos_audit_instructions', 'argos_ssh_status']
LEGACY_IMPROVEMENT_TOOL_BASE = {
    'group:fs', 'group:runtime', 'web_fetch', 'argos_evaluate', 'argos_evaluate_wait',
    'argos_evaluate_status', 'argos_compare', 'argos_log',
}
LEGACY_IMPROVEMENT_TOOL_POLICIES = (
    frozenset(LEGACY_IMPROVEMENT_TOOL_BASE),
    frozenset(LEGACY_IMPROVEMENT_TOOL_BASE - {'argos_log'}),
    frozenset(LEGACY_IMPROVEMENT_TOOL_BASE - {'argos_evaluate_wait', 'argos_evaluate_status'}),
    frozenset(LEGACY_IMPROVEMENT_TOOL_BASE - {'argos_log', 'argos_evaluate_wait', 'argos_evaluate_status'}),
)


def workspace_file(name):
    return (Path(__file__).resolve().parent / 'data' / name).read_bytes()


def conversation_config(model, workspace, *, plugin_root=PLUGIN_ROOT):
    return {
        'gateway': {'mode': 'local', 'bind': 'loopback', 'auth': {'mode': 'token', 'token': secrets.token_hex(32)}},
        'agents': {'defaults': {'model': {'primary': 'ollama/' + model}, 'workspace': str(workspace),
                                'skipBootstrap': True,
                                # A fresh session per heartbeat: no chat history to outgrow the
                                # context, and no dependence on a chat surviving a restart.
                                'heartbeat': {'every': '3m', 'session': 'main', 'target': 'none',
                                              'isolatedSession': True,
                                              'timeoutSeconds': 1800, 'prompt': HEARTBEAT_PROMPT}}},
        'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434', 'apiKey': 'ollama-local', 'api': 'ollama',
            'models': [{'id': model, 'name': model, 'input': ['text'], 'reasoning': False,
                        'contextWindow': 32768, 'maxTokens': 4096,
                        # Explicit decoding for fresh agent configurations;
                        # existing owner profiles are never rewritten here.
                        'params': {'temperature': 0},
                        'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}},
        'tools': {'profile': 'minimal',
                  'alsoAllow': ['group:fs', 'group:runtime', 'web_fetch', 'argos_evaluate', 'argos_evaluate_wait',
                                'argos_evaluate_status', 'argos_compare', 'argos_log',
                                *PROCTOR_READONLY_TOOLS],
                  'deny': ['gateway', 'browser'],
                  'exec': {'host': 'gateway', 'security': 'full', 'ask': 'off'},
                  'elevated': {'enabled': False},
                  # Local Ollama runs otherwise hide tool schemas behind tool search, and
                  # models then call argos_evaluate by name and get an empty turn.
                  'toolSearch': False},
        'plugins': {'enabled': True, 'load': {'paths': [str(plugin_root)]},
                    'entries': {'argos-improve': {'enabled': True}}},
        'commands': {'bash': False, 'restart': False}}


def persistence():
    from .web.status import mounts_and_blocks, persistence as observed
    mounts, blocks = mounts_and_blocks()
    return observed(mounts, blocks)


def publish_new(path, value, journal):
    """Publish a private complete file without replacing a racing owner file."""
    path = storage.safe_local(path)
    raw = value if isinstance(value, bytes) else (json.dumps(value, indent=2) + '\n').encode()
    temp = path.parent / ('.setup-' + secrets.token_hex(16))
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
        journal.append((path, path.stat().st_ino, raw))
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temp.unlink(missing_ok=True)


def upgrade_legacy_heartbeat(home, config_path):
    """Update only the known generated heartbeat prompt, after a private snapshot."""
    config_path = storage.safe_local(config_path)
    raw = config_path.read_bytes()
    config = json.loads(raw)
    try:
        heartbeat = config['agents']['defaults']['heartbeat']
    except (KeyError, TypeError):
        return {'status': 'not-managed'}
    if not isinstance(heartbeat, dict) or heartbeat.get('prompt') not in {
            LEGACY_HEARTBEAT_PROMPT, PREVIOUS_GUARDED_HEARTBEAT_PROMPT}:
        return {'status': 'not-legacy-default'}

    updated = json.loads(json.dumps(config))
    updated['agents']['defaults']['heartbeat']['prompt'] = HEARTBEAT_PROMPT
    new_raw = (json.dumps(updated, indent=2) + '\n').encode()
    state_root = storage.safe_local(home / '.local/state/argos-live')
    snapshots = storage.safe_local(state_root / 'snapshots')
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshots.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        for directory in (state_root, snapshots):
            metadata = directory.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                return {'status': 'snapshot-directory-not-private'}

    snapshot = snapshots / ('openclaw-before-heartbeat-guard-' + secrets.token_hex(12) + '.json')
    descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary = config_path.parent / ('.heartbeat-config-' + secrets.token_hex(12))
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(new_raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Do not overwrite a concurrent owner edit made after the snapshot.
        if config_path.read_bytes() != raw:
            return {'status': 'config-changed-during-migration'}
        os.replace(temporary, config_path)
        if os.name != 'nt':
            descriptor = os.open(config_path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return {'status': 'updated', 'snapshot': snapshot.name,
            'before_sha256': hashlib.sha256(raw).hexdigest(),
            'after_sha256': hashlib.sha256(new_raw).hexdigest()}


def upgrade_legacy_proctor_tools(home, config_path):
    """Snapshot and add only the reviewed read-only Proctor tools to old defaults."""
    config_path = storage.safe_local(config_path)
    raw = config_path.read_bytes()
    config = json.loads(raw)
    tools = config.get('tools')
    if not isinstance(tools, dict):
        return {'status': 'not-managed'}
    allowed = tools.get('alsoAllow')
    denied = tools.get('deny')
    elevated = tools.get('elevated')
    exec_config = tools.get('exec')
    if (tools.get('profile') != 'minimal' or not isinstance(allowed, list) or
            any(not isinstance(item, str) for item in allowed) or
            not isinstance(denied, list) or set(denied) != {'gateway', 'browser'} or
            not isinstance(elevated, dict) or elevated.get('enabled') is not False or
            not isinstance(exec_config, dict) or exec_config.get('host') != 'gateway' or
            not (exec_config.get('security') == 'full' or exec_config.get('mode') == 'full') or
            (set(allowed) - set(PROCTOR_READONLY_TOOLS)) not in LEGACY_IMPROVEMENT_TOOL_POLICIES):
        return {'status': 'not-reviewed-tool-policy'}
    missing = [name for name in PROCTOR_READONLY_TOOLS if name not in allowed]
    if not missing:
        return {'status': 'already-current'}

    updated = json.loads(json.dumps(config))
    updated['tools']['alsoAllow'].extend(missing)
    new_raw = (json.dumps(updated, indent=2) + '\n').encode()
    state_root = storage.safe_local(home / '.local/state/argos-live')
    snapshots = storage.safe_local(state_root / 'snapshots')
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshots.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        for directory in (state_root, snapshots):
            metadata = directory.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                return {'status': 'snapshot-directory-not-private'}
    before = hashlib.sha256(raw).hexdigest()
    snapshot = snapshots / ('openclaw-before-proctor-tools-' + secrets.token_hex(12) + '.json')
    descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary = config_path.parent / ('.proctor-tools-config-' + secrets.token_hex(12))
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             config_path.stat().st_mode & 0o777)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(new_raw)
            stream.flush()
            os.fsync(stream.fileno())
        if config_path.read_bytes() != raw:
            return {'status': 'config-changed-during-migration', 'snapshot': snapshot.name}
        os.replace(temporary, config_path)
        if os.name != 'nt':
            descriptor = os.open(config_path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return {'status': 'updated', 'snapshot': snapshot.name,
            'before_sha256': before,
            'after_sha256': hashlib.sha256(new_raw).hexdigest(),
            'added_tools': missing}


def upgrade_legacy_owner_guide(home):
    """Migrate only Toronado's exact known guide; preserve other owner edits."""
    path = storage.safe_local(home / '.openclaw/workspace/AGENTS.md')
    if not path.is_file():
        return {'status': 'not-managed'}
    raw = path.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    if before != LEGACY_OWNER_GUIDE_SHA256:
        return {'status': 'not-targeted-guide', 'before_sha256': before}
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return {'status': 'guide-not-utf8'}
    marker = '## 2. Measure one change at a time\n'
    start = text.find(marker)
    end = text.find('**B. Configuration.**', start)
    if (start < 0 or end < 0 or text.find(marker, start + len(marker)) >= 0 or
            text.count(LEGACY_MODEL_PLATEAU_GUIDANCE) != 1):
        return {'status': 'legacy-guide-shape-mismatch', 'before_sha256': before}
    text = text[:start] + OWNER_TASK_GUIDANCE + text[end:]
    text = text.replace(LEGACY_MODEL_PLATEAU_GUIDANCE, OWNER_TASK_STOP_GUIDANCE)
    new_raw = text.encode('utf-8')
    state_root = storage.safe_local(home / '.local/state/argos-live')
    snapshots = storage.safe_local(state_root / 'snapshots')
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshots.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        for directory in (state_root, snapshots):
            metadata = directory.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                return {'status': 'snapshot-directory-not-private'}
    token = secrets.token_hex(12)
    snapshot = snapshots / ('agents-before-owner-task-guidance-' + token + '.md')
    descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary = path.parent / ('.agents-guide-' + token)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             path.stat().st_mode & 0o777)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(new_raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != raw:
            return {'status': 'guide-changed-during-migration', 'snapshot': snapshot.name}
        os.replace(temporary, path)
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return {'status': 'updated', 'snapshot': snapshot.name,
            'before_sha256': before, 'after_sha256': hashlib.sha256(new_raw).hexdigest()}


def configure(home=None, *, planner=storage.plan, verify_seed=starter.read_only,
              probe_persistence=persistence, progress=None):
    """No prompts, mounts, downloads or daemon startup; retained state is reused."""
    home = storage.safe_local(Path.home() if home is None else Path(home))
    is_guest = session_mode.guest()
    if is_guest:
        session_mode.require_ram(home)
    state_path = storage.safe_local(home / '.config/argos-live/state.json')
    config_path = storage.safe_local(home / '.openclaw/openclaw.json')
    def report(phase):
        if progress:
            progress({'phase': phase})
    if state_path.exists():
        state = read_json(state_path)
        storage.validate_configured(state)
        read_json(config_path)
        try:
            heartbeat_migration = upgrade_legacy_heartbeat(home, config_path)
        except (OSError, ValueError, json.JSONDecodeError):
            # The migration is opportunistic; a failed private snapshot or a
            # concurrent config edit must not prevent the existing assistant
            # from starting with its current owner configuration.
            heartbeat_migration = {'status': 'not-applied'}
        try:
            owner_guide_migration = upgrade_legacy_owner_guide(home)
        except (OSError, ValueError):
            # Never block startup or replace a guide if snapshotting fails.
            owner_guide_migration = {'status': 'not-applied'}
        try:
            proctor_tools_migration = upgrade_legacy_proctor_tools(home, config_path)
        except (OSError, ValueError, json.JSONDecodeError):
            # A failed private snapshot or concurrent owner edit must never
            # block startup or replace the current owner configuration.
            proctor_tools_migration = {'status': 'not-applied'}
        return {'status': 'existing', **{key: state.get(key) for key in
                ('mode', 'model', 'model_source', 'storage', 'permissions')},
                'heartbeat_prompt_migration': heartbeat_migration,
                'owner_guide_migration': owner_guide_migration,
                'proctor_tools_migration': proctor_tools_migration}
    if config_path.exists() or (config_path.parent.exists() and any(config_path.parent.iterdir())):
        raise ValueError('Existing OpenClaw state needs review; automatic setup will not replace it')
    report('verify-starter')
    identity = verify_seed()
    if identity.get('tag') != starter.TAG:
        raise ValueError('Unexpected bundled starter identity')
    report('select-storage')
    # Seed weights stay in the image. Reserve only workspace capacity here;
    # each managed pull checks its own real model budget before downloading.
    selected = planner(1)
    models = storage.safe_local(Path(selected['path']))
    if is_guest:
        session_mode.require_ram(models)
    if models.exists() and (not models.is_dir() or any(models.iterdir())):
        raise ValueError('Proposed model directory already contains data; automatic setup will not adopt it')
    observed = probe_persistence()
    if type(observed.get('active')) is not bool:
        raise ValueError('Persistence status unavailable; no automatic configuration written')
    if is_guest and observed['active']:
        raise ValueError('Guest mode cannot use live persistence; reboot using the guest entry')
    state = {'storage': str(models), 'storage_id': secrets.token_hex(24),
             'model': starter.TAG, 'model_source': 'bundled', 'permissions': 'local-tools-and-benchmarks',
             'mode': 'guest' if is_guest else ('persistent' if observed['active'] else 'try'),
             'storage_temporary': selected['kind'] == 'ram', 'storage_encrypted': selected.get('encrypted'),
             'persistence_encrypted': observed.get('encrypted'), 'starter': identity}
    if selected.get('volume_uuid'):
        state['storage_uuid'] = selected['volume_uuid']
    journal, directories = [], []
    def mkdir(path):
        storage.safe_local(path)
        if path.exists():
            if not path.is_dir():
                raise ValueError('Setup directory is not a directory')
            return
        mkdir(path.parent)
        path.mkdir(mode=0o700)
        directories.append(path)
    try:
        report('write-configuration')
        for path in (models, state_path.parent, config_path.parent / 'workspace', config_path.parent / 'workspace/tools'):
            mkdir(path)
        # Marker is metadata, not a private credential; use exclusive creation
        # on DATA filesystems that may not support hard links.
        marker = storage.safe_local(models / '.argos-storage-id')
        raw = (state['storage_id'] + '\n').encode()
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        journal.append((marker, os.fstat(descriptor).st_ino, raw))
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        workspace = config_path.parent / 'workspace'
        for target, source in WORKSPACE_FILES:
            publish_new(workspace / target, workspace_file(source), journal)
        publish_new(config_path, conversation_config(starter.TAG, workspace), journal)
        publish_new(state_path, state, journal)
    except BaseException:
        # Remove only files this transaction published, still matching its bytes
        # and inode. Changed owner files and nonempty directories are preserved.
        for path, inode, raw in reversed(journal):
            try:
                storage.safe_local(path)
                if path.stat().st_ino == inode and path.read_bytes() == raw:
                    path.unlink()
            except (OSError, ValueError):
                pass
        for path in reversed(directories):
            try:
                path.rmdir()
            except OSError:
                pass
        raise
    report('configured')
    return {'status': 'created', **state}
