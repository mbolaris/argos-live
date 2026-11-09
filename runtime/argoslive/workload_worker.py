"""Fixed delegated host worker. Its private capability arrives on stdin, never argv.

Only a trusted supervisor may mint the request or treat its exit as drainage.
There is no arbitrary command execution, owner-authorization inference or lease
recovery in this protocol. Same-UID shell access still defeats token isolation.
"""
import argparse
import json
from pathlib import Path
import sys

from . import bench_openclaw, campaign_log, instruction_changes, workload
from .workload import Delegation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('evaluation', 'log', 'maintenance'))
    parser.add_argument('--home', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise ValueError('Worker request exceeds limit')
        request = json.loads(raw)
        allowed = ({'delegation', 'suite'} if args.kind == 'evaluation' else
                   {'delegation', 'operation', 'params'} if args.kind == 'maintenance' else {'delegation', 'text'})
        if not isinstance(request, dict) or set(request) - allowed or 'delegation' not in request:
            raise ValueError('Unexpected worker request')
        capability = Delegation(**request['delegation'])
        if args.kind == 'maintenance':
            value = instruction_changes.perform(args.home, request.get('operation'), request.get('params'),
                                                delegation=capability)
            print(json.dumps(value))
            return 0
        if args.kind == 'evaluation':
            suite = request.get('suite', 'quick')
            if suite not in bench_openclaw.SUITES:
                raise ValueError('Unsupported suite')
            # Fixed argv and explicit output root: no owner/global result store
            # is selected through inherited environment or request data.
            return bench_openclaw.main(['--home', str(args.home), '--suite', suite,
                '--results-dir', str(args.home / '.local/share/argos-live/results'), '--json'],
                delegation=capability)
        text = request['text']
        if not isinstance(text, str):
            raise ValueError('Log note must be text')
        return campaign_log.main(['--home', str(args.home), '--text=' + text, '--json'], delegation=capability)
    except workload.Busy as error:
        # The request contains a capability. Keep recovery diagnostics bounded
        # and never dump a traceback, local paths, or raw exception details.
        stage = getattr(error, 'operation_stage', None)
        safe_stages = {'reservation', 'request-validation', 'journal-audit', 'journal-root',
                       'instruction-inspect', 'instruction-edit', 'instruction-adopt',
                       'instruction-resolve'}
        print(json.dumps({'status': 'busy', 'recovery_required': error.recovery,
                          'failure_stage': stage if stage in safe_stages else 'reservation'}))
        return 75
    except (ValueError, TypeError, KeyError, OSError):
        # The request contains a capability. Do not dump it, a traceback, parser
        # locals, or the exception payload into agent-visible output.
        print(json.dumps({'status': 'failed', 'message': 'Delegated host worker request failed'}))
        return 70


if __name__ == '__main__':
    raise SystemExit(main())
