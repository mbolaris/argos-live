"""Reviewed personality activation and scoped rollback while the gateway is stopped.

The caller verifies encrypted storage and stops OpenClaw. Imported documents are
data; providers, credentials, model downloads and privileges are never imported.
"""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import zipfile

from . import packs
from .pack_export import bounded, private_directory, unlinked
from .pack_import import active_roster, preview

CHAT = {'profile': 'minimal',
        'deny': ['gateway', 'group:runtime', 'group:fs', 'group:web', 'browser'],
        'elevated': {'enabled': False}}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with unlinked(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
            value.update(chunk)
    return value.hexdigest()


def atomic(path, data, mode=0o600):
    path = unlinked(path)
    fd, temporary = tempfile.mkstemp(prefix='.argos-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def save(path, data):
    atomic(path, (json.dumps(data, indent=2) + '\n').encode())


@contextmanager
def lock(home, stopped):
    if not stopped:
        raise ValueError('Stop the gateway first and explicitly acknowledge --gateway-stopped')
    path = unlinked(home) / '.argos-pack.lock'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('Another pack operation or interrupted transaction holds the lock') from None
    os.close(fd)
    try:
        yield
    finally:
        path.unlink()


class OpenClaw:
    def __init__(self, cli, version, home):
        self.cli, self.home = cli, unlinked(home)
        self.env = dict(os.environ, OPENCLAW_STATE_DIR=str(self.home),
                        OPENCLAW_CONFIG_PATH=str(self.home / 'openclaw.json'), NO_COLOR='1')
        output = subprocess.check_output([cli, '--version'], env=self.env, text=True, timeout=30)
        if version not in re.findall(r'\d{4}\.\d+\.\d+', output):
            raise ValueError('OpenClaw must match the reviewed distro version')

    def run(self, *args, config=None):
        env = dict(self.env)
        if config:
            env['OPENCLAW_CONFIG_PATH'] = str(config)
        result = subprocess.run([self.cli, *map(str, args)], env=env,
                                capture_output=True, timeout=120)
        if result.returncode:
            # CLI output can include private config; keep it out of public logs.
            raise ValueError('OpenClaw command failed: ' + ' '.join(map(str, args[:2])))

    def validate(self, config):
        self.run('config', 'validate', config=config)

    def backup(self, target):
        self.run('backup', 'create', '--output', target, '--verify')
        self.run('backup', 'verify', target)


def external(root, home, roster):
    root = unlinked(root)
    if not root.is_dir():
        raise ValueError('Use an existing private root on verified encrypted storage')
    protected = [home] + [unlinked(e['workspace']) for e in roster.values()
                          if isinstance(e.get('workspace'), str)]
    if any(root.is_relative_to(p) or p.is_relative_to(root) for p in protected):
        raise ValueError('Snapshots and staging must be separate from active state')
    return root


def restore_files(snapshot, transaction, partial=False):
    """Preflight every hash before restoring anything; never clobber later edits."""
    originals = []
    for item in transaction['files']:
        path = unlinked(item['path'])
        current = bounded(path) if path.exists() else None
        current_hash = digest(current) if current is not None else None
        acceptable = {item['after_sha256']}
        if partial:
            acceptable.add(item['before_sha256'])
        if current_hash not in acceptable:
            raise ValueError('Target changed since activation; rollback requires a fresh review')
        data = None
        if item['before_sha256'] is not None:
            data = bounded(snapshot / item['backup'])
            if digest(data) != item['before_sha256']:
                raise ValueError('Snapshot file checksum mismatch')
        originals.append((path, data, item['mode']))
    # Config is recorded last, so documents restore before the roster.
    for path, data, mode in originals:
        if data is None:
            if path.exists():
                path.unlink()
        else:
            atomic(path, data, mode)
    for directory in reversed(transaction['created_directories']):
        path = unlinked(directory)
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def apply(stage, home, snapshots, reviewed_sha256, runtime, *, installed=None,
          reviewed_skills=False, gateway_stopped=False):
    home, stage = unlinked(home), unlinked(stage)
    with lock(home, gateway_stopped):
        roster = active_roster(home)
        external(stage.parent, home, roster)
        snapshots = external(snapshots, home, roster)
        if stage.is_relative_to(snapshots) or snapshots.is_relative_to(stage):
            raise ValueError('Snapshot root must be separate from the reviewed stage')
        archive = stage / 'reference.zip'
        inspection = packs.inspect(archive, reviewed_sha256)
        receipt = packs.decode(bounded(stage / 'preview.json'))
        if inspection['archive_sha256'] != receipt.get('archive_sha256'):
            raise ValueError('Stage receipt differs from reviewed archive')
        with archive.open('rb') as stream:
            raw = stream.read(packs.MAX_ARCHIVE + 1)
        if len(raw) > packs.MAX_ARCHIVE or digest(raw) != inspection['archive_sha256']:
            raise ValueError('Pack changed after inspection')
        manifest = inspection['manifest']
        if any(a['skill_files'] for a in manifest['agents']) and not reviewed_skills:
            raise ValueError('Selected skill definitions require --reviewed-skills')
        report = preview(manifest, roster, installed=installed)
        if any(a['conflicts'] for a in report['agents']):
            raise ValueError('Resolve current preview conflicts before activation')
        config_path = home / 'openclaw.json'
        config_bytes = bounded(config_path)
        if ('active_config_sha256' not in receipt or
                digest(config_bytes) != receipt['active_config_sha256'] or
                [a['files'] for a in report['agents']] != [a['files'] for a in receipt['agents']]):
            raise ValueError('Active state changed since staging; import and review a fresh stage')
        config = packs.decode(config_bytes)
        runtime.validate(config_path)
        # Native pinned schema uses entries; refuse lossy conversion of legacy list.
        if 'list' in config.get('agents', {}):
            raise ValueError('Normalize the Live roster to the pinned entries schema first')
        entries = config.setdefault('agents', {}).setdefault('entries', {})
        writes, activated, pending, agent_directories = [], [], [], []
        expected_before = {}
        provider = config.get('models', {}).get('providers', {}).get('ollama', {})
        local_provider = (provider.get('api') == 'ollama' and
                          re.fullmatch(r'http://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?/?',
                                       provider.get('baseUrl', '')) is not None)
        available = {m.get('id') for m in provider.get('models', []) if isinstance(m, dict)}
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            for agent, change in zip(manifest['agents'], report['agents']):
                model = change['model']
                if (model['status'] != 'installed' or not local_provider
                        or model.get('model') not in available
                        or model.get('model', '').split(':')[-1].endswith('cloud')):
                    pending.append({'id': agent['id'], 'reason': 'Exact installed local model/provider required'})
                    continue
                ident = agent['id']
                active = roster.get(ident.casefold())
                workspace = unlinked(active['workspace'] if active else home / ('workspace-' + ident))
                agent_dir = unlinked(active.get('agentDir', home / 'agents' / ident / 'agent')
                                     if active else home / 'agents' / ident / 'agent')
                # Keep isolation and prevent persona writes overlapping unrelated agents/state.
                for other_id, other in roster.items():
                    if other_id != ident.casefold() and other.get('workspace'):
                        other_path = unlinked(other['workspace'])
                        if workspace.is_relative_to(other_path) or other_path.is_relative_to(workspace):
                            raise ValueError('Agent workspaces must be separate')
                    if other_id != ident.casefold() and other.get('agentDir'):
                        other_dir = unlinked(other['agentDir'])
                        if agent_dir.is_relative_to(other_dir) or other_dir.is_relative_to(agent_dir):
                            raise ValueError('Agent state directories must be separate')
                if workspace == home or home.is_relative_to(workspace):
                    raise ValueError('Workspace cannot contain active state')
                if agent_dir == home or home.is_relative_to(agent_dir):
                    raise ValueError('Agent directory cannot contain active state')
                agent_directories.append(agent_dir)
                entry = dict(entries.get(ident, {}))
                entry.update(identity=dict(entry.get('identity', {}), name=agent['name']),
                             workspace=str(workspace), agentDir=str(agent_dir),
                             model='ollama/' + model['model'], tools=json.loads(json.dumps(CHAT)))
                if active and active.get('default') is True:
                    entry['default'] = True
                # Source grants/fallbacks/helpers are not copied. Live credentials stay in agentDir.
                entries[ident] = entry
                for name in agent['persona_files'] + agent['skill_files']:
                    parts = name.split('/')
                    relative = Path(parts[3]) if parts[2] == 'persona' else Path('skills', *parts[3:])
                    target = unlinked(workspace / relative)
                    writes.append((target, bundle.read(name)))
                    expected_before[str(target)] = next(f['current_sha256'] for f in change['files']
                                                        if f['path'] == name)
                activated.append(ident)
        if not activated:
            return {'activation': False, 'activated': [], 'pending': pending, 'snapshot_id': None}
        writes.append((config_path, (json.dumps(config, indent=2) + '\n').encode()))
        expected_before[str(config_path)] = digest(config_bytes)
        if len({str(p).casefold() for p, _ in writes}) != len(writes):
            raise ValueError('Overlapping target files')
        snapshot = snapshots / ('snapshot-' + uuid.uuid4().hex)
        private_directory(snapshot)
        # Verified native backup includes existing agent state/workspaces; scoped originals
        # support exact rollback without overwriting unrelated sessions or credentials.
        runtime.backup(snapshot / 'native-backup.tar.gz')
        native_hash = file_digest(snapshot / 'native-backup.tar.gz')
        transaction = {'schema': 'argos-pack-transaction/1', 'home': str(home),
                       'archive_sha256': reviewed_sha256, 'native_backup_sha256': native_hash,
                       'status': 'prepared', 'files': [], 'created_directories': [],
                       'activated': activated, 'pending': pending}
        for index, (path, data) in enumerate(writes):
            before = bounded(path) if path.exists() else None
            if (digest(before) if before is not None else None) != expected_before[str(path)]:
                raise ValueError('Target changed while taking backup; import and review a fresh stage')
            name = 'before-' + str(index)
            if before is not None:
                atomic(snapshot / name, before)
            transaction['files'].append({'path': str(path), 'backup': name,
                                         'before_sha256': digest(before) if before is not None else None,
                                         'after_sha256': digest(data),
                                         'mode': path.stat().st_mode & 0o777 if before is not None else 0o600})
        candidate = snapshot / 'candidate.json'
        atomic(candidate, writes[-1][1])
        runtime.validate(candidate)
        # Record every intended new directory before the first mutation for crash recovery.
        directories = set()
        for parent in [p.parent for p, _ in writes] + agent_directories:
            while not parent.exists():
                directories.add(parent)
                parent = parent.parent
        transaction['created_directories'] = [str(p) for p in sorted(directories, key=lambda p: (len(p.parts), str(p)))]
        save(snapshot / 'transaction.json', transaction)
        try:
            for directory in transaction['created_directories']:
                private_directory(Path(directory))
            for (path, data), item in zip(writes, transaction['files']):
                before = bounded(path) if path.exists() else None
                if (digest(before) if before is not None else None) != item['before_sha256']:
                    raise ValueError('Target changed during activation')
                atomic(path, data, item['mode'])
            runtime.validate(config_path)
            transaction['status'] = 'applied'
            save(snapshot / 'transaction.json', transaction)
        except Exception:
            try:
                restore_files(snapshot, transaction, partial=True)
                transaction['status'] = 'automatically-restored'
            except Exception:
                transaction['status'] = 'recovery-required'
                save(snapshot / 'transaction.json', transaction)
                raise ValueError('Rollback could not safely finish; retain snapshot ' + snapshot.name) from None
            save(snapshot / 'transaction.json', transaction)
            raise ValueError('Activation failed; original files restored. Snapshot ' + snapshot.name) from None
        return {'activation': True, 'activated': activated, 'pending': pending,
                'snapshot_id': snapshot.name, 'model_capability_verified': False}


def rollback(snapshot, home, runtime, *, gateway_stopped=False):
    snapshot, home = unlinked(snapshot), unlinked(home)
    with lock(home, gateway_stopped):
        external(snapshot.parent, home, active_roster(home))
        transaction = packs.decode(bounded(snapshot / 'transaction.json'))
        if (transaction.get('schema') != 'argos-pack-transaction/1' or transaction.get('home') != str(home)
                or transaction.get('status') not in {'applied', 'prepared', 'recovery-required'}):
            raise ValueError('Snapshot is not eligible for this active home')
        if file_digest(snapshot / 'native-backup.tar.gz') != transaction['native_backup_sha256']:
            raise ValueError('Native backup checksum mismatch')
        restore_files(snapshot, transaction, partial=transaction['status'] != 'applied')
        runtime.validate(home / 'openclaw.json')
        transaction['status'] = 'rolled-back'
        save(snapshot / 'transaction.json', transaction)
        return {'rollback': True, 'snapshot_id': snapshot.name}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['apply', 'rollback'])
    parser.add_argument('id')
    parser.add_argument('--active-home', required=True)
    parser.add_argument('--snapshots-root', required=True)
    parser.add_argument('--staging-root')
    parser.add_argument('--reviewed-sha256')
    parser.add_argument('--installed-inventory', help='Private exact verified Ollama inventory JSON; capability not inferred')
    parser.add_argument('--reviewed-skills', action='store_true')
    parser.add_argument('--gateway-stopped', action='store_true')
    parser.add_argument('--openclaw', default='openclaw')
    parser.add_argument('--openclaw-version', required=True)
    args = parser.parse_args(argv)
    packs.identifier(args.id)
    if not args.gateway_stopped:
        parser.error('Stop the gateway first; --gateway-stopped is required')
    runtime = OpenClaw(args.openclaw, args.openclaw_version, args.active_home)
    if args.operation == 'apply':
        if not args.staging_root or not args.reviewed_sha256:
            parser.error('Apply needs --staging-root and --reviewed-sha256')
        inventory = packs.decode(bounded(args.installed_inventory)) if args.installed_inventory else None
        report = apply(Path(args.staging_root) / args.id, args.active_home, args.snapshots_root,
                       args.reviewed_sha256, runtime, installed=inventory,
                       reviewed_skills=args.reviewed_skills, gateway_stopped=True)
    else:
        report = rollback(Path(args.snapshots_root) / args.id, args.active_home, runtime, gateway_stopped=True)
    print(json.dumps(report, indent=2))
