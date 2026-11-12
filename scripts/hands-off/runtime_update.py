"""Update Toronado's Argos runtime over the pinned SSH helper, without rebuilding the Live drive.

Standing orders (docs/HANDS-OFF-STANDING-ORDERS.md), order 3. A bundle is the
`runtime/argoslive` tree of a commit that is on origin/main and whose checks passed. It replaces
only /usr/local/lib/argos-live/argoslive, after a snapshot, with a health check and automatic
rollback. No reboot, no boot-area write, no change to SSH, models, the workspace or the plugin.

Commands
  build <commit> <base_commit>  make bundle-<sha>.tar and its receipt (-unverified unless checks passed)
  rehearse <bundle.json>    apply, verify, roll back and re-apply against a local copy of the image tree
  install-script            print the remote installer (it is what runs under sudo on Toronado)

The Toronado apply/rollback orchestration lives in apply_update.py and imports this module.
"""
import hashlib, io, json, pathlib, subprocess, sys, tarfile, tempfile

import os
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
# Bundles and receipts are build output, not source: they go to a git-ignored directory.
ROOT = pathlib.Path(os.environ.get('ARGOS_HANDS_OFF_DIR') or REPO / 'work' / 'hands-off')
ROOT.mkdir(parents=True, exist_ok=True)
TREE = 'usr/local/lib/argos-live/argoslive'
STATE = 'var/lib/argos-live/runtime-updates'
PREFIX = 'runtime/argoslive/'
GH_REPO = 'mbolaris/argos-live'

INSTALLER = r'''
import hashlib, json, os, pathlib, shutil, subprocess, sys, tarfile
LIMIT_FILES, LIMIT_BYTES = 2000, 64 * 1024 * 1024
args = json.loads(sys.argv[1])
root = pathlib.Path(args.get('root', '/'))
tree = root / args['tree']
state = root / args['state']
stamp = args['stamp']
assert stamp.isalnum() and len(stamp) <= 32
prev = tree.with_name(tree.name + '.prev-' + stamp)
new = tree.with_name(tree.name + '.new-' + stamp)

def manifest(base):
    out = {}
    for p in sorted(base.rglob('*')):
        if p.is_symlink():
            raise SystemExit('refused: symlink inside runtime tree: ' + p.name)
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            out[p.relative_to(base).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out

def digest(m):
    return hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()

def real_dir(p):
    return p.is_dir() and not p.is_symlink() and not any(q.is_symlink() for q in p.parents)

def emit(**value):
    print('ARGOS_RUNTIME_UPDATE ' + json.dumps(value, sort_keys=True), flush=True)

action = args['action']
if action == 'apply':
    assert real_dir(tree), 'runtime tree is not a real directory'
    assert not prev.exists() and not new.exists(), 'an earlier update with this stamp was not finished'
    bundle = state / 'staging' / ('bundle-' + args['bundle_sha256'][:16] + '.tar')
    data = bundle.read_bytes()
    assert hashlib.sha256(data).hexdigest() == args['bundle_sha256'], 'bundle hash mismatch'
    before = digest(manifest(tree))
    assert before == args['expect_before'], 'installed runtime is not the expected version; refusing'
    snaps = state / 'snapshots'
    snaps.mkdir(parents=True, exist_ok=True)
    os.chmod(snaps, 0o700)
    snap = snaps / (stamp + '.tar')
    with tarfile.open(snap, 'x') as t:
        t.add(tree, arcname='argoslive', filter=lambda m: None if ('__pycache__' in m.name or m.name.endswith('.pyc')) else m)
    os.chmod(snap, 0o600)
    new.mkdir(mode=0o755)
    files = size = 0
    import atexit, io
    done = []
    atexit.register(lambda: None if done else shutil.rmtree(new, ignore_errors=True))
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t:
            if m.isdir() and args['prefix'].startswith(m.name.rstrip('/') + '/'):
                continue  # the archive's own parent directories (runtime/, runtime/argoslive/)
            if not m.name.startswith(args['prefix']):
                raise SystemExit('refused: unexpected bundle member ' + m.name)
            rel = pathlib.PurePosixPath(m.name[len(args['prefix']):])
            if not rel.parts:
                continue
            if rel.is_absolute() or '..' in rel.parts or any(part.startswith('.') for part in rel.parts if part in ('.', '..')):
                raise SystemExit('refused: unsafe path ' + m.name)
            target = new.joinpath(*rel.parts)
            if m.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
            elif m.isfile():
                files += 1; size += m.size
                assert files <= LIMIT_FILES and size <= LIMIT_BYTES, 'bundle too large'
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                target.write_bytes(t.extractfile(m).read())
                os.chmod(target, 0o644)
            else:
                raise SystemExit('refused: bundle member is not a file or directory: ' + m.name)
    for p in new.rglob('*'):
        if p.is_dir():
            os.chmod(p, 0o755)
    after = digest(manifest(new))
    if after != args['expect_after']:
        shutil.rmtree(new)
        raise SystemExit('refused: unpacked bundle does not match its manifest')
    try:
        if getattr(os, 'geteuid', lambda: 1)() == 0:
            for p in [new, *new.rglob('*')]:
                os.chown(p, 0, 0)
            subprocess.run([sys.executable, '-m', 'compileall', '-q', str(new)], check=False)
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    os.rename(tree, prev)
    try:
        os.rename(new, tree)
    except BaseException:
        os.rename(prev, tree)
        raise
    done.append(True)
    emit(action='apply', stamp=stamp, before=before, after=after, files=files, bytes=size, snapshot=snap.name)
elif action == 'rollback':
    assert real_dir(prev), 'no previous runtime kept for this stamp'
    failed = tree.with_name(tree.name + '.failed-' + stamp)
    os.rename(tree, failed)
    try:
        os.rename(prev, tree)
    except BaseException:
        os.rename(failed, tree)
        raise
    restored = digest(manifest(tree))
    assert restored == args['expect_before'], 'restored runtime does not match the version before the update'
    shutil.rmtree(failed)
    emit(action='rollback', stamp=stamp, restored=restored)
elif action == 'finalize':
    if prev.exists():
        shutil.rmtree(prev)
    bundle = state / 'staging' / ('bundle-' + args['bundle_sha256'][:16] + '.tar')
    if bundle.exists():
        bundle.unlink()
    snaps = sorted((state / 'snapshots').glob('*.tar'))
    for old in snaps[:-5]:
        old.unlink()
    emit(action='finalize', stamp=stamp, current=digest(manifest(tree)), snapshots_kept=len(snaps[-5:]))
elif action == 'state':
    emit(action='state', current=digest(manifest(tree)), files=len(manifest(tree)))
else:
    raise SystemExit('unknown action')
'''


def git(*args, binary=False):
    p = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=True)
    return p.stdout if binary else p.stdout.decode().strip()


def tree_tar(commit):
    return git('archive', '--format=tar', commit, 'runtime/argoslive', binary=True)


def manifest_of(tar_bytes):
    out = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        for m in t:
            if m.isfile():
                out[m.name[len(PREFIX):]] = hashlib.sha256(t.extractfile(m).read()).hexdigest()
    return out


def digest(m):
    return hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()


def checks_passed(sha):
    """True only if every check run on the commit completed and none failed, and a 'test' run succeeded."""
    p = subprocess.run(['gh', 'api', f'repos/{GH_REPO}/commits/{sha}/check-runs', '--paginate',
                        '--jq', '.check_runs[] | [.name, .status, (.conclusion // "")] | @tsv'],
                       capture_output=True, text=True, check=True)
    rows = [line.split('\t') for line in p.stdout.strip().splitlines() if line.strip()]
    ok = bool(rows) and all(r[1] == 'completed' and r[2] in ('success', 'skipped', 'neutral') for r in rows)
    return ok and any(r[0] == 'test' and r[2] == 'success' for r in rows), rows


def build(commit, base_commit):
    sha = git('rev-parse', commit)
    git('fetch', 'origin', 'main', '-q')
    assert subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', sha, 'origin/main']).returncode == 0, 'commit is not on origin/main'
    passed, rows = checks_passed(sha)
    # An unverified bundle can be rehearsed locally but is never applied to Toronado.
    data = tree_tar(sha)
    after = manifest_of(data)
    before = manifest_of(tree_tar(base_commit))
    receipt = {'schema': 'argos-runtime-bundle/1', 'commit': sha, 'base_commit': git('rev-parse', base_commit),
               'bundle_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'files': len(after),
               'expect_before': digest(before), 'expect_after': digest(after),
               'changed': sorted(k for k in after if before.get(k) != after[k]), 'removed': sorted(set(before) - set(after)),
               'checks': rows}
    receipt['verified'] = passed
    stem = f'bundle-{sha[:7]}' + ('' if passed else '-unverified')
    receipt['file'] = stem + '.tar'
    (ROOT / (stem + '.tar')).write_bytes(data)
    (ROOT / (stem + '.json')).write_text(json.dumps(receipt, indent=1))
    return receipt


def run_installer(root, **args):
    payload = {'root': str(root), 'tree': TREE, 'state': STATE, 'prefix': PREFIX, **args}
    p = subprocess.run([sys.executable, '-c', INSTALLER, json.dumps(payload)], capture_output=True, text=True)
    lines = [json.loads(line.split(' ', 1)[1]) for line in p.stdout.splitlines() if line.startswith('ARGOS_RUNTIME_UPDATE ')]
    return p.returncode, (lines[-1] if lines else None), (p.stderr.strip().splitlines() or [''])[-1]


def rehearse(receipt_path):
    receipt = json.loads(pathlib.Path(receipt_path).read_text())
    data = (ROOT / receipt['file']).read_bytes()
    results = []

    def fresh(root):
        tree = root / TREE
        tree.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(tree_tar(receipt['base_commit']))) as t:
            for m in t:
                if m.isfile():
                    target = tree / m.name[len(PREFIX):]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(t.extractfile(m).read())
        staging = root / STATE / 'staging'
        staging.mkdir(parents=True)
        (staging / f"bundle-{receipt['bundle_sha256'][:16]}.tar").write_bytes(data)
        return tree

    common = dict(bundle_sha256=receipt['bundle_sha256'], expect_before=receipt['expect_before'], expect_after=receipt['expect_after'])
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        fresh(root)
        code, out, err = run_installer(root, action='apply', stamp='r1', **common)
        results.append(('apply', code == 0 and out['after'] == receipt['expect_after'], err))
        code, out, err = run_installer(root, action='state', stamp='r1', **common)
        results.append(('installed tree equals main', code == 0 and out['current'] == receipt['expect_after'], err))
        code, out, err = run_installer(root, action='rollback', stamp='r1', **common)
        results.append(('rollback restores the image version', code == 0 and out['restored'] == receipt['expect_before'], err))
        code, out, err = run_installer(root, action='apply', stamp='r2', **common)
        code2, out2, err2 = run_installer(root, action='finalize', stamp='r2', **common)
        left = [p.name for p in (root / TREE).parent.iterdir()]
        results.append(('re-apply and finalize leave one tree', code == 0 and code2 == 0 and left == ['argoslive'] and out2['current'] == receipt['expect_after'], err or err2))
    with tempfile.TemporaryDirectory() as d:  # wrong bundle hash
        root = pathlib.Path(d); fresh(root)
        code, out, err = run_installer(root, action='apply', stamp='n1', **{**common, 'bundle_sha256': receipt['bundle_sha256'][:16] + '0' * 48})
        results.append(('refuses a bundle whose hash does not match', code != 0, err))
    with tempfile.TemporaryDirectory() as d:  # unexpected installed version
        root = pathlib.Path(d); tree = fresh(root)
        (tree / 'ability.py').write_text('tampered\n')
        code, out, err = run_installer(root, action='apply', stamp='n2', **common)
        results.append(('refuses when the installed runtime is not the expected version', code != 0 and (tree / 'ability.py').read_text() == 'tampered\n', err))
    with tempfile.TemporaryDirectory() as d:  # malicious member
        root = pathlib.Path(d); fresh(root)
        evil = io.BytesIO()
        with tarfile.open(fileobj=evil, mode='w') as t:
            info = tarfile.TarInfo(PREFIX + '../../escape.py'); payload = b'x'; info.size = len(payload)
            t.addfile(info, io.BytesIO(payload))
        bad = evil.getvalue(); sha = hashlib.sha256(bad).hexdigest()
        (root / STATE / 'staging' / f'bundle-{sha[:16]}.tar').write_bytes(bad)
        code, out, err = run_installer(root, action='apply', stamp='n3', **{**common, 'bundle_sha256': sha})
        escaped = any(p.name == 'escape.py' for p in root.rglob('escape.py'))
        results.append(('refuses a path that escapes the tree', code != 0 and not escaped, err))
    with tempfile.TemporaryDirectory() as d:  # symlinked tree
        root = pathlib.Path(d); tree = fresh(root)
        real = tree.with_name('real'); tree.rename(real)
        try:
            tree.symlink_to(real, target_is_directory=True)
            code, out, err = run_installer(root, action='apply', stamp='n4', **common)
            results.append(('refuses a symlinked runtime tree', code != 0, err))
        except OSError:
            results.append(('refuses a symlinked runtime tree', None, 'symlinks unavailable on this host; not rehearsed'))
    return results


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        print(json.dumps({k: v for k, v in build(sys.argv[2], sys.argv[3]).items() if k != 'checks'}, indent=1))
    elif sys.argv[1] == 'rehearse':
        failed = False
        for name, ok, err in rehearse(sys.argv[2]):
            print(('PASS' if ok else 'SKIP' if ok is None else 'FAIL'), name, '' if ok else '| ' + err)
            failed |= ok is False
        raise SystemExit(1 if failed else 0)
    elif sys.argv[1] == 'install-script':
        print(INSTALLER)
