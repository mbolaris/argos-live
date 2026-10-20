"""Small append-only campaign tool. Agent notes are not verified experiment claims.

The host supplies the timestamp and receipts for every referenced saved run.
This does not yet prove arbitrary natural-language claims about instruction edits.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil

from .assistant_trial import agents_path
from . import storage
from .results import Store
from .workload import Busy, reserve


def append(home, text, *, delegation=None):
    if (not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 4096
            or any(ord(c) < 32 and c not in '\n\t' for c in text)):
        raise ValueError('Log text must contain 1–4096 UTF-8 bytes without control characters')
    home = Path(home)
    with reserve(home, 'log', delegation=delegation) as slot:
        # This operation never starts a child or inference request. Even a bad
        # run ID can release admission safely; it must not strand the campaign.
        slot.complete()
        workspace = agents_path(home).parent
        path = storage.safe_local(workspace / 'IMPROVEMENT-LOG.md')
        # A typo must not become an invented result. Receipts come from the
        # validated result store, independently of the agent's score prose.
        ids = sorted(set(re.findall(r'\b[a-f0-9]{32}\b', text)))
        store = Store(home / '.local/share/argos-live/results')
        receipts = []
        for run_id in ids:
            run = store.load(run_id)
            receipts.append({k: run.get(k) for k in ('id', 'created', 'model', 'suite', 'state', 'summary')})
        timestamp = datetime.now(timezone.utc).isoformat()
        snapshot = storage.safe_local(home / '.local/state/argos-live/snapshots' /
                                      ('log-' + secrets.token_hex(16)))
        snapshot.mkdir(mode=0o700, parents=True)
        checksums = []
        for source in (path, workspace / 'AGENTS.md'):
            source = storage.safe_local(source)
            if source.exists():
                shutil.copy2(source, snapshot / source.name)
                checksums.append(hashlib.sha256(source.read_bytes()).hexdigest() + '  ' + source.name)
        (snapshot / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n', encoding='utf-8')
        entry = ('\n## Step observed by host at ' + timestamp + '\n\n' + text.strip() + '\n\n'
                 'Host-verified saved-run receipts: ' + json.dumps(receipts, sort_keys=True) + '\n'
                 'Pre-append snapshot: ' + str(snapshot) + '\n')
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, 'ab') as stream:
            stream.write(entry.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        slot.complete()
        return {'status': 'appended', 'observed': timestamp, 'snapshot': str(snapshot),
                'receipts': receipts, 'note_claims_verified': False}


def main(argv=None, *, delegation=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--text', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        value = append(args.home, args.text, delegation=delegation)
    except Busy as error:
        print(json.dumps({'status': 'busy', 'recovery_required': error.recovery, 'message': str(error)}))
        return 75
    print(json.dumps(value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
