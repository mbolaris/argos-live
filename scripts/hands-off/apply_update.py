"""Apply, health-check or roll back a runtime bundle on Toronado over the pinned SSH helper.

Standing orders order 3. Usage:  apply_update.py apply|health|rollback <receipt.json> <stamp>
Each step builds a stdlib-only script and runs it through the helper named by ARGOS_REMOTE_HELPER
(strict host-key pin; no passphrase involved). Nothing here reboots or touches the boot area.
"""
import base64, json, os, pathlib, subprocess, sys
import runtime_update as ru

ROOT = ru.ROOT
REMOTE = pathlib.Path(os.environ['ARGOS_REMOTE_HELPER'])  # the strict-pinned SSH helper; never a plain ssh call

COMMON = r'''
import json, os, pathlib, signal, subprocess, sys, time
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
HOME = pathlib.Path.home()
SESSION = HOME / '.local/state/argos-live/desktop-session.json'
INSTALLER = ARGS['installer']

def say(**v):
    print('STEP ' + json.dumps(v, sort_keys=True), flush=True)

def api(path, payload=None, timeout=20):
    s = json.loads(SESSION.read_text()); u = urlsplit(s['url'])
    headers = {'X-Argos-Token': parse_qs(u.query)['token'][0]}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode(); headers['Content-Type'] = 'application/json'
    with build_opener(ProxyHandler({})).open(Request(f'http://127.0.0.1:{u.port}{path}', data=data, headers=headers), timeout=timeout) as r:
        body = r.read()
    return r.status, body

def campaign():
    return json.loads(api('/api/proctor-campaign')[1])

def installer(action, **extra):
    payload = dict(tree=ARGS['tree'], state=ARGS['state'], prefix=ARGS['prefix'], stamp=ARGS['stamp'], action=action,
                   bundle_sha256=ARGS['bundle_sha256'], expect_before=ARGS['expect_before'], expect_after=ARGS['expect_after'], **extra)
    p = subprocess.run(['sudo', '-n', 'python3', '-c', INSTALLER, json.dumps(payload)], capture_output=True, text=True)
    rows = [json.loads(l.split(' ', 1)[1]) for l in p.stdout.splitlines() if l.startswith('ARGOS_RUNTIME_UPDATE ')]
    return p.returncode, (rows[-1] if rows else None), p.stderr.strip()[-400:]

def desktop_pids():
    p = subprocess.run(['pgrep', '-f', '^python3 /usr/local/bin/argos desktop$'], capture_output=True, text=True)
    return [int(x) for x in p.stdout.split()]

def restart_desktop():
    pids = desktop_pids()
    assert len(pids) == 1, f'expected one desktop process, found {pids}'
    pid = pids[0]
    env = dict(e.split(b'=', 1) for e in open(f'/proc/{pid}/environ', 'rb').read().split(b'\x00') if b'=' in e)
    env = {k.decode(): v.decode() for k, v in env.items()}
    old_mtime = SESSION.stat().st_mtime if SESSION.exists() else 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(120):
        if not pathlib.Path(f'/proc/{pid}').exists():
            break
        time.sleep(1)
    else:
        raise SystemExit('desktop did not stop within 120 s; left running (no kill)')
    time.sleep(3)
    subprocess.Popen(['/usr/local/bin/argos', 'desktop'], env=env, cwd=str(HOME), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        time.sleep(2)
        try:
            if SESSION.exists() and SESSION.stat().st_mtime > old_mtime and campaign() is not None:
                return True
        except Exception:
            pass
    raise SystemExit('desktop did not come back within 240 s')
'''

APPLY = r'''
import base64
c = campaign()
if c.get('active'):
    raise SystemExit('refused: an evaluation is active')
say(stage='idle', phase=c.get('phase'))
staging = pathlib.Path(ARGS['state']) / 'staging'
data = base64.b64decode(ARGS['bundle_b64'])
tmp = pathlib.Path('/tmp/argos-bundle-' + ARGS['stamp'])
tmp.write_bytes(data)
subprocess.run(['sudo', '-n', 'install', '-d', '-m', '0700', '-o', 'root', '-g', 'root', '/' + ARGS['state'], '/' + ARGS['state'] + '/staging'], check=True)
subprocess.run(['sudo', '-n', 'install', '-m', '0600', '-o', 'root', '-g', 'root', str(tmp), '/' + ARGS['state'] + '/staging/bundle-' + ARGS['bundle_sha256'][:16] + '.tar'], check=True)
tmp.unlink()
ARGS['tree'] = '/' + ARGS['tree'] if not ARGS['tree'].startswith('/') else ARGS['tree']
ARGS['state'] = '/' + ARGS['state'] if not ARGS['state'].startswith('/') else ARGS['state']
code, out, err = installer('apply')
say(stage='installed', code=code, out=out, err=err)
if code != 0:
    raise SystemExit('apply failed; the old runtime is untouched')
restart_desktop()
say(stage='desktop-restarted', phase=campaign().get('phase'))
'''

ROLLBACK = r'''
ARGS['tree'] = '/' + ARGS['tree'] if not ARGS['tree'].startswith('/') else ARGS['tree']
ARGS['state'] = '/' + ARGS['state'] if not ARGS['state'].startswith('/') else ARGS['state']
code, out, err = installer('rollback')
say(stage='rolled-back', code=code, out=out, err=err)
if code == 0:
    restart_desktop()
    say(stage='desktop-restarted-on-old-runtime', phase=campaign().get('phase'))
'''

HEALTH = r'''
ARGS['tree'] = '/' + ARGS['tree'] if not ARGS['tree'].startswith('/') else ARGS['tree']
ARGS['state'] = '/' + ARGS['state'] if not ARGS['state'].startswith('/') else ARGS['state']
code, out, err = installer('state')
say(stage='tree', matches_bundle=bool(out and out.get('current') == ARGS['expect_after']), files=out and out.get('files'))
assert out and out.get('current') == ARGS['expect_after'], 'installed tree is not the bundle'
for path in ('/match.js', '/match.css', '/api/proctor-match/recent'):
    status, body = api(path)
    say(stage='route', path=path, status=status, bytes=len(body))
deadline = time.time() + 1200
while time.time() < deadline:
    c = campaign()
    if c.get('assistant_ready') and c.get('can_start') and not c.get('active'):
        break
    time.sleep(10)
else:
    raise SystemExit('assistant did not become ready in 20 minutes: ' + json.dumps({k: c.get(k) for k in ('phase', 'assistant_phase', 'failure_code', 'message')}))
say(stage='assistant-ready', model=c.get('model'))
payload = {'owner_task': 'Runtime update health check: run one bundled practice round and save a signed practice result. Do not change the model, prompt, configuration, memory or production.',
           'success_criteria': 'A signed practice result is saved. Do not claim improvement from the practice score.', 'measurement_suite': 'quick'}
status, body = api('/api/proctor-campaign/start', payload, timeout=30)
say(stage='evaluation-started', status=status)
deadline = time.time() + 2400
while time.time() < deadline:
    time.sleep(15)
    c = campaign()
    if not c.get('active'):
        break
else:
    raise SystemExit('evaluation still active after 40 minutes')
result = c.get('result') or {}
say(stage='evaluation-finished', phase=c.get('phase'), failure_code=c.get('failure_code'), result_keys=sorted(result)[:12])
ids = (result.get('campaign') or {}).get('saved_evaluation_ids') or []
ok = bool(result) and not c.get('failure_code') and c.get('phase') != 'incomplete' and result.get('status') != 'incomplete' and bool(ids)
say(stage='health', ok=bool(ok), saved_evaluations=len(ids), status=result.get('status'))
if not ok:
    raise SystemExit('health check failed')
code, out, err = installer('finalize')
say(stage='finalized', code=code, out=out)
'''


def run(step, receipt_path, stamp):
    receipt = json.loads(pathlib.Path(receipt_path).read_text())
    assert receipt.get('verified') is True, 'receipt is not verified; refusing'
    data = (ROOT / receipt['file']).read_bytes()
    args = dict(installer=ru.INSTALLER, tree=ru.TREE, state=ru.STATE, prefix=ru.PREFIX, stamp=stamp,
                bundle_sha256=receipt['bundle_sha256'], expect_before=receipt['expect_before'], expect_after=receipt['expect_after'])
    if step == 'apply':
        args['bundle_b64'] = base64.b64encode(data).decode()
    body = {'apply': APPLY, 'health': HEALTH, 'rollback': ROLLBACK}[step]
    script = 'ARGS = ' + json.dumps(args) + '\n' + COMMON + body
    (ROOT / 'probes').mkdir(exist_ok=True)
    path = ROOT / 'probes' / f'{step}-{stamp}.py'
    path.write_text(script)
    p = subprocess.run([sys.executable, '-I', str(REMOTE), str(path)], capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    if p.returncode:
        sys.stdout.write(p.stderr[-1500:])
    return p.returncode


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1], sys.argv[2], sys.argv[3]))
