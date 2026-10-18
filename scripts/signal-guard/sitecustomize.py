"""Diagnostic-only signal fence, injected into focused disposable CI fixtures.

Never imported by the product. Every destructive signal requires an exact int
PID, a matching start identity, and a child/session created by this process.
Mock PID coercion and signals to our own session/group are always refused.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback


def valid_identifier(value):
    return type(value) is int and value > 1


def install():
    directory = os.environ.get('ARGOS_SIGNAL_DIAG_DIR')
    guard = os.environ.get('ARGOS_SIGNAL_GUARD_DIR')
    if not directory or not guard or sys.platform != 'linux':
        return
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    real_kill, real_killpg, real_popen = os.kill, os.killpg, subprocess.Popen
    children, groups = {}, {}

    def identity(pid):
        raw = Path(f'/proc/{pid}/stat').read_text()
        fields = raw[raw.rfind(')') + 2:].split()
        return {'pid': pid, 'state': fields[0], 'ppid': int(fields[1]),
                'group': int(fields[2]), 'session': int(fields[3]),
                'start': int(fields[19]), 'uid': Path(f'/proc/{pid}').stat().st_uid}

    def record(kind, target, number, allowed, reason):
        value = {'actor_pid': os.getpid(), 'kind': kind,
                 'target': target if type(target) is int else type(target).__name__,
                 'signal': int(number), 'allowed': allowed, 'reason': reason,
                 'stack': [{'file': x.filename, 'line': x.lineno, 'function': x.name}
                           for x in traceback.extract_stack(limit=7)[:-1]]}
        with (directory / f'signals-{os.getpid()}.jsonl').open('a') as stream:
            stream.write(json.dumps(value) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def owned(target):
        current = identity(target)
        if current['uid'] != os.getuid():
            return False
        expected = children.get(target)
        if expected is not None and expected['start'] == current['start']:
            return True
        group = groups.get(current['group'])
        if group and current['session'] == current['group']:
            try:
                leader = identity(current['group'])
                return leader['start'] == group['start']
            except FileNotFoundError:
                return True  # Original session still has an orphan member.
        return False

    class TracedPopen(real_popen):
        def __init__(self, *args, **kwargs):
            env = dict(os.environ if kwargs.get('env') is None else kwargs['env'])
            paths = env.get('PYTHONPATH', '').split(os.pathsep)
            env['PYTHONPATH'] = os.pathsep.join([guard, *[x for x in paths if x and x != guard]])
            env['ARGOS_SIGNAL_GUARD_DIR'] = guard
            env['ARGOS_SIGNAL_DIAG_DIR'] = str(directory)
            kwargs['env'] = env
            super().__init__(*args, **kwargs)
            try:
                current = identity(self.pid)
                children[self.pid] = current
                if kwargs.get('start_new_session') is True:
                    if current['group'] != self.pid or current['session'] != self.pid:
                        raise RuntimeError('New child session identity did not match')
                    groups[self.pid] = current
            except FileNotFoundError:
                pass  # A child that already exited needs no destructive signal.

    def kill(target, number):
        if number == 0 and valid_identifier(target):
            return real_kill(target, number)
        allowed = False
        reason = 'not an exact positive child PID'
        if valid_identifier(target) and target != os.getpid():
            try:
                allowed = owned(target)
                reason = 'owned child identity' if allowed else 'not an owned child identity'
            except FileNotFoundError:
                raise ProcessLookupError(target) from None
        record('pid', target, number, allowed, reason)
        if not allowed:
            raise PermissionError('Diagnostic refused unsafe PID signal')
        return real_kill(target, number)

    def killpg(target, number):
        allowed = False
        reason = 'not an exact owned session/group ID'
        if (valid_identifier(target) and target not in (os.getpgrp(), os.getsid(0))
                and target in groups):
            try:
                current = identity(target)
                allowed = (current['start'] == groups[target]['start'] and
                           current['group'] == target and current['session'] == target)
            except FileNotFoundError:
                # Only a previously recorded owned session can reach here.
                allowed = True
            reason = 'recorded owned child session' if allowed else 'session identity changed'
        record('group', target, number, allowed, reason)
        if not allowed:
            raise PermissionError('Diagnostic refused unsafe process-group signal')
        return real_killpg(target, number)

    subprocess.Popen, os.kill, os.killpg = TracedPopen, kill, killpg


install()
