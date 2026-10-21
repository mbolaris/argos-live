"""Private host bridge for one supervised SDK controller session.

Entry and tool hooks are callers, never release authorities. The host must own
the SDK worker lifecycle and stop it before complete(); end events are evidence
only. This cooperative transport is not a boundary against same-UID shell use.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hmac
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import subprocess
import sys
import tempfile
import threading
import uuid

from . import workload, instruction_changes
from .pull_jobs import read_json, write_json
from .results import Store, compare

LIMIT = 32768
PROCTOR_TOOLS = {'proctor_start', 'proctor_status', 'proctor_item',
                 'proctor_answer', 'proctor_continue', 'proctor_submit', 'proctor_feedback'}
EVALUATION_WAIT_SECONDS = 480


def identity(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', value))


class Bridge:
    def __init__(self, home, parent, *, session_key, trigger='user', worker_timeout=1800,
                 exam_session=None):
        if not identity(session_key) or trigger not in {'user', 'heartbeat'}:
            raise ValueError('Host-selected controller identity required')
        self.home, self.parent = Path(home), parent
        self.session_key, self.trigger = session_key, trigger
        self.worker_timeout = worker_timeout
        self.exam_session = exam_session
        self.secret = secrets.token_hex(32)
        self.active = None
        self.pending = None
        self.worker = None
        self.transport_env = None
        self.worker_path = os.environ.get('PATH', '')
        self.uncertain = False
        self.closed = False
        self.verified = False
        self.outcomes = []
        self.evaluation_job = None
        self.lock = threading.RLock()
        self.tool_lock = threading.Lock()
        self.events = self.parent.path.parent / 'controller-turn.json'

    def environment(self, path):
        return {'ARGOS_CONTROLLER_SOCKET': str(path), 'ARGOS_CONTROLLER_SECRET': self.secret}

    def publish(self):
        # Never persist transport/turn secrets or model-authored prompt text.
        workload.same_owner(read_json(self.parent.path), self.parent.record)
        value = {'schema': 'argos-controller-turn/1', 'parent_id': self.parent.record['id'],
                 'generation': self.parent.record['generation'], 'uncertain': self.uncertain}
        if self.evaluation_job:
            job = self.evaluation_job
            value['evaluation_job'] = {'job_id': job['job_id'], 'suite': job['suite'],
                'state': 'running' if job['thread'].is_alive() else ('failed' if job['error'] else 'completed'),
                'completed': job['completed'], 'total': job['total']}
        if self.active:
            value.update({key: self.active[key] for key in
                          ('run_id', 'session_id', 'session_key', 'trigger', 'ended')})
            if isinstance(self.active.get('diagnostics'), dict):
                value['admission_diagnostics'] = self.active['diagnostics']
            value['host_tool_requests'] = self.active.get('host_tool_requests', 0)
            value['host_tool_failures'] = self.active.get('host_tool_failures', [])
        value['tools'] = self.outcomes
        write_json(self.events, value)

    def dispatch(self, request, on_update=None):
        if not isinstance(request, dict) or not isinstance(request.get('auth'), str) or not hmac.compare_digest(
                request['auth'], self.secret):
            raise ValueError('Bridge authentication failed')
        operation = request.get('op')
        if operation == 'begin':
            return self.begin(request)
        if operation == 'ended':
            with self.lock:
                self.check_turn(request)
                diagnostics = request.get('diagnostics')
                if isinstance(diagnostics, dict):
                    counts = ('tool_hooks', 'bound_calls', 'executions')
                    rejected = diagnostics.get('rejected')
                    rejection_kinds = ('unknown_tool', 'missing_admission', 'invalid_call_id', 'stale_binding')
                    if (set(diagnostics) != {*counts, 'rejected'} or
                            any(type(diagnostics.get(key)) is not int or diagnostics[key] < 0
                                for key in counts) or
                            not isinstance(rejected, dict) or set(rejected) != set(rejection_kinds) or
                            any(type(rejected.get(key)) is not int or rejected[key] < 0
                                for key in rejection_kinds)):
                        raise ValueError('Invalid bounded controller diagnostics')
                    self.active['diagnostics'] = diagnostics
                self.active['ended'] = True
                self.publish()
            return {'status': 'recorded'}
        if operation == 'tool':
            with self.lock:
                if self.active is not None:
                    self.active['host_tool_requests'] = self.active.get('host_tool_requests', 0) + 1
            try:
                return self.tool(request, on_update=on_update)
            except BaseException as error:
                with self.lock:
                    if self.active is not None:
                        kind = request.get('kind')
                        allowed_kinds = PROCTOR_TOOLS | {
                            'evaluation', 'evaluation_wait', 'evaluation_status', 'compare', 'log',
                            'inspect', 'edit', 'resolve'}
                        safe_kind = kind if isinstance(kind, str) and kind in allowed_kinds else 'other'
                        failures = self.active.setdefault('host_tool_failures', [])
                        if len(failures) < 32:
                            failures.append({'kind': safe_kind, 'error_class': type(error).__name__})
                        self.publish()
                raise
        raise ValueError('Unknown bridge operation')

    def begin(self, request):
        if (not identity(request.get('run_id')) or not identity(request.get('session_id')) or
                request.get('session_key') != self.session_key or request.get('trigger') != self.trigger):
            raise ValueError('Controller session was not authorized by its host')
        with self.lock:
            if self.closed or self.uncertain:
                raise workload.Busy(recovery=self.uncertain)
            if self.active:
                fields = ('run_id', 'session_id', 'session_key', 'trigger')
                if not self.active['ended'] and all(self.active[key] == request[key] for key in fields):
                    return {'status': 'admitted', 'turn_token': self.active['token']}
                raise workload.Busy()
            self.active = {key: request[key] for key in ('run_id', 'session_id', 'session_key', 'trigger')}
            self.active.update(ended=False, token=secrets.token_hex(32), calls=set())
            self.publish()
            return {'status': 'admitted', 'turn_token': self.active['token']}

    def check_turn(self, request):
        token = request.get('turn_token')
        if (self.closed or self.uncertain or not self.active or request.get('run_id') != self.active['run_id'] or
                not isinstance(token, str) or not hmac.compare_digest(token, self.active['token'])):
            raise workload.Busy(recovery=True)

    def tool(self, request, *, on_update=None):
        if not self.tool_lock.acquire(blocking=False):
            raise workload.Busy()
        try:
            with self.lock:
                self.check_turn(request)
                call = request.get('call_id')
                if not identity(call) or self.active['ended'] or call in self.active['calls']:
                    raise ValueError('Stale or replayed tool execution')
                kind, params = request.get('kind'), request.get('params')
                if not isinstance(params, dict):
                    raise ValueError('Bounded tool parameters required')
                if self.exam_session is not None and kind not in PROCTOR_TOOLS:
                    raise ValueError('Only Proctor tools are available during an exam')
                if (self.evaluation_job and not self.evaluation_job.get('consumed') and
                        kind not in {'evaluation_wait', 'evaluation_status'}):
                    raise workload.Busy()
                if kind == 'evaluation':
                    if set(params) - {'suite'} or params.get('suite', 'quick') not in {'quick', 'standard', 'challenge'}:
                        raise ValueError('Unsupported evaluation request')
                elif kind == 'evaluation_wait':
                    if set(params) != {'job_id'} or not identity(params.get('job_id')):
                        raise ValueError('Invalid evaluation job identity')
                elif kind == 'evaluation_status':
                    if params:
                        raise ValueError('Evaluation status takes no options')
                elif kind == 'log':
                    if set(params) != {'text'} or not isinstance(params['text'], str) or not 0 < len(
                            params['text'].encode('utf-8')) <= 4096:
                        raise ValueError('Invalid log note')
                elif kind == 'compare':
                    if set(params) != {'baseline_id', 'candidate_id'}:
                        raise ValueError('Invalid comparison request')
                elif kind in {'inspect', 'audit', 'edit', 'resolve'}:
                    instruction_changes.validate_request(kind, params)
                elif kind in PROCTOR_TOOLS:
                    self._validate_proctor_request(kind, params)
                    if self.exam_session is None or self.parent.record.get('kind') != 'proctor':
                        raise ValueError('No host-preauthorized exam is active')
                else:
                    raise ValueError('Unsupported controller tool')
                self.active['calls'].add(call)
            if kind in PROCTOR_TOOLS:
                value = self._proctor_tool(kind, params, call)
                outcome = {'kind': kind, 'call_id': call, 'status': value.get('state', value.get('status'))}
                with self.lock:
                    self.outcomes.append(outcome)
                    self.publish()
                return {'status': 'completed', 'value': value}
            if kind == 'evaluation':
                value = self.start_evaluation(params, on_update=on_update)
                if value.get('status') == 'running':
                    return value
                return {'status': 'completed', 'value': value}
            if kind == 'evaluation_wait':
                value = self.wait_evaluation(params['job_id'], on_update=on_update)
                if value.get('status') == 'running':
                    return value
                return {'status': 'completed', 'value': value}
            if kind == 'evaluation_status':
                value = self.evaluation_status()
                if value.get('status') == 'running':
                    return value
                return {'status': 'completed', 'value': value}
            if kind == 'compare':
                store = Store(self.home / '.local/share/argos-live/results')
                return {'status': 'completed', 'value': compare([
                    store.load(params['baseline_id']), store.load(params['candidate_id'])])}
            value = self.run_child(kind, params, on_update=on_update)
            outcome = {'kind': kind, 'call_id': call}
            if kind in {'edit', 'resolve'}:
                outcome.update(status=value['value']['status'], change_id=value['value'].get('change_id'))
            if kind == 'evaluation':
                outcome['result_id'] = value['value']['result']['id']
                outcome['state'] = value['value']['result']['state']
            with self.lock:
                self.outcomes.append(outcome)
                self.publish()
            return value
        finally:
            self.tool_lock.release()

    def start_evaluation(self, params, *, on_update=None, seconds=EVALUATION_WAIT_SECONDS):
        """Run one bounded tool wait over a host-owned evaluation worker."""
        with self.lock:
            current = self.evaluation_job
            if current and not current.get('consumed'):
                raise workload.Busy()
            job_id = secrets.token_hex(16)
            job = {'job_id': job_id, 'suite': params.get('suite', 'quick'),
                   'completed': 0, 'total': {'quick': 20, 'standard': 70, 'challenge': 40}[
                       params.get('suite', 'quick')], 'value': None, 'error': None,
                   'recorded': False, 'consumed': False, 'on_update': on_update}
            self.evaluation_job = job

            def progress(event):
                with self.lock:
                    job['completed'] = event.get('completed', job['completed'])
                    job['total'] = event.get('total', job['total'])
                callback = job.get('on_update')
                if callback is not None:
                    try:
                        callback(event)
                    except (BrokenPipeError, ConnectionError, OSError):
                        pass

            def execute():
                try:
                    job['value'] = self.run_child('evaluation', params, on_update=progress)
                except BaseException as error:
                    job['error'] = error

            job['thread'] = threading.Thread(target=execute, name='argos-controller-evaluation', daemon=False)
            job['thread'].start()
        return self.wait_evaluation(job_id, on_update=on_update, seconds=seconds)

    def wait_evaluation(self, job_id, *, on_update=None, seconds=EVALUATION_WAIT_SECONDS):
        job = self.evaluation_job
        if not job or not hmac.compare_digest(job['job_id'], job_id):
            raise ValueError('Unknown evaluation job')
        job['on_update'] = on_update
        thread = job['thread']
        thread.join(seconds)
        if thread.is_alive():
            job['on_update'] = None
            return {'status': 'running', 'job_id': job_id, 'suite': job['suite'],
                    'completed': job['completed'], 'total': job['total']}
        if job['error'] is not None:
            raise workload.Busy(recovery=True) from None
        if not job['recorded']:
            value = job['value']
            result = value['value']['result']
            with self.lock:
                self.outcomes.append({'kind': 'evaluation', 'job_id': job_id,
                                      'result_id': result['id'], 'state': result['state']})
                self.publish()
                job['recorded'] = True
                job['consumed'] = True
        return job['value']['value']

    def cancel_evaluation_owner(self, job_id):
        """Trusted-host cancellation; deliberately absent from model tool IPC."""
        job = self.evaluation_job
        if not job or not hmac.compare_digest(job['job_id'], job_id):
            raise ValueError('Unknown evaluation job')
        if not job['thread'].is_alive():
            return {'status': 'already_finished', 'job_id': job_id}
        process = self.pending
        if process is None or process.poll() is not None:
            self.uncertain = True
            self.publish()
            raise workload.Busy(recovery=True)
        process.terminate()
        return {'status': 'cancel_requested', 'job_id': job_id}

    def evaluation_status(self):
        job = self.evaluation_job
        if job is None:
            return {'status': 'idle'}
        if job['thread'].is_alive():
            return {'status': 'running', 'job_id': job['job_id'], 'suite': job['suite'],
                    'completed': job['completed'], 'total': job['total']}
        if job['error'] is not None:
            return {'status': 'busy', 'recovery_required': True}
        return {'status': 'completed', 'job_id': job['job_id'], 'suite': job['suite']}

    @staticmethod
    def _validate_proctor_request(kind, params):
        if kind in {'proctor_start', 'proctor_status', 'proctor_continue', 'proctor_feedback'}:
            if params:
                raise ValueError('This Proctor operation takes no model-selected options')
        elif kind == 'proctor_submit':
            if set(params) != {'module_id'} or not identity(params.get('module_id')):
                raise ValueError('Submission must name the server-selected module')
        elif kind == 'proctor_item':
            if set(params) != {'item_id'} or not identity(params.get('item_id')):
                raise ValueError('Invalid Proctor item request')
        elif kind == 'proctor_answer':
            if (set(params) != {'item_id', 'answer'} or not identity(params.get('item_id')) or
                    not isinstance(params.get('answer'), str) or len(params['answer'].encode('utf-8')) > 8192):
                raise ValueError('Invalid Proctor answer request')

    def _proctor_tool(self, kind, params, call_id):
        if kind == 'proctor_start':
            return self.exam_session.start(call_id)
        if kind == 'proctor_status':
            return self.exam_session.status()
        if kind == 'proctor_item':
            return self.exam_session.item(params['item_id'])
        if kind == 'proctor_answer':
            return self.exam_session.answer(params['item_id'], params['answer'], call_id)
        if kind == 'proctor_continue':
            return self.exam_session.continue_module(call_id)
        if kind == 'proctor_submit':
            return self.exam_session.submit(params['module_id'], call_id)
        if kind == 'proctor_feedback':
            return self.exam_session.practice_feedback()
        raise ValueError('Unsupported Proctor tool')

    def run_child(self, kind, params, *, on_update=None):
        maintenance = kind in {'inspect', 'edit', 'resolve'}
        worker_kind = 'maintenance' if maintenance else kind
        capability = self.parent.delegate(worker_kind)
        command = [sys.executable, '-m', 'argoslive.workload_worker', worker_kind, '--home', str(self.home)]
        # No gateway/bridge credentials or owner provider environment is passed
        # to an evaluator. Its SDK context further strips inherited authority.
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ') if key in os.environ}
        env.update(PATH=self.worker_path, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONUTF8='1')
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env,
                                       start_new_session=os.name == 'posix')
        except OSError:
            self.parent.cancel_unstarted(capability)
            self.parent.resume(capability, worker_drained=True)
            raise
        with self.lock:
            self.pending = process
        try:
            stdout_parts, stderr_parts = [], []
            output_lock = threading.Lock()
            overflow = threading.Event()
            def drain(stream, chunks, limit, progress=False):
                while True:
                    chunk = stream.readline() if progress else stream.read(4096)
                    if not chunk:
                        break
                    with output_lock:
                        size = sum(map(len, chunks))
                        if size + len(chunk) > limit:
                            if not progress:
                                overflow.set()
                                if process.poll() is None:
                                    process.kill()
                        else:
                            chunks.append(chunk)
                    if not progress or on_update is None:
                        continue
                    try:
                        event = json.loads(chunk)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(event, dict) and event.get('phase') in {'asking', 'scored'}:
                        try:
                            on_update(event)
                        except (BrokenPipeError, ConnectionError, OSError):
                            # The agent can disappear while the host-owned
                            # child still saves its result. Never cancel it.
                            pass

            out_reader = threading.Thread(target=drain, args=(process.stdout, stdout_parts, 2 * 1024**2),
                                          name='argos-child-stdout', daemon=True)
            err_reader = threading.Thread(target=drain, args=(process.stderr, stderr_parts, 32768, True),
                                          name='argos-child-stderr', daemon=True)
            out_reader.start()
            err_reader.start()
            payload = {'operation': kind, 'params': params} if maintenance else params
            process.stdin.write(json.dumps({'delegation': asdict(capability), **payload},
                                           ensure_ascii=False).encode('utf-8'))
            process.stdin.close()
            try:
                process.wait(timeout=self.worker_timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass  # Leave the parent quarantined if the exact worker survives.
                self.uncertain = True
            out_reader.join(timeout=30)
            err_reader.join(timeout=30)
            if out_reader.is_alive() or err_reader.is_alive() or overflow.is_set():
                self.uncertain = True
            stdout = b''.join(stdout_parts).decode('utf-8', errors='replace')
            _stderr = b''.join(stderr_parts).decode('utf-8', errors='replace')
            self.last_child_stdout, self.last_child_stderr = stdout, _stderr
            if process.returncode or overflow.is_set() or len(stdout.encode()) > 2 * 1024**2:
                raise workload.Busy(recovery=True)
            value = json.loads(stdout)
            if kind == 'evaluation':
                result = value['result']
                saved = Store(self.home / '.local/share/argos-live/results').load(result['id'])
                if saved != result:
                    raise workload.Busy(recovery=True)
                if self.uncertain or result['state'] != 'completed':
                    self.uncertain = True
                    self.publish()
                    # Preserve the saved partial outcome/ID for the agent while
                    # keeping admission closed. A generic busy error would hide it.
                    return {'status': 'completed', 'value': value}
            elif maintenance and value.get('status') not in {'inspected', 'changed', 'restored', 'kept', 'rejected'}:
                raise workload.Busy(recovery=True)
            elif not maintenance and value.get('status') != 'appended':
                raise workload.Busy(recovery=True)
            # communicate() confirms process exit; normal isolated evaluation
            # completed and its saved result was reloaded. Uncertain outcomes
            # never take this path. Real backend mediation remains separate.
            self.parent.resume(capability, worker_drained=True)
            return {'status': 'completed', 'value': value}
        except BaseException:
            with self.lock:
                self.uncertain = True
                self.publish()
            raise
        finally:
            if process.poll() is not None:
                with self.lock:
                    self.pending = None
                for pipe in (process.stdin, process.stdout, process.stderr):
                    pipe.close()

    def launch(self, executable, message, *, config_path=None, timeout=1800, local=True):
        """Host-only launch; no worker PID or release claim is accepted from IPC."""
        from .owned_gateway import environment
        path = Path(config_path or self.home / '.openclaw/openclaw.json')
        config = read_json(path)
        plugins = config.get('plugins', {})
        entry = plugins.get('entries', {}).get('argos-improve', {})
        if (plugins.get('enabled') is not True or 'argos-improve' not in plugins.get('allow', []) or
                entry.get('enabled') is not True or entry.get('config', {}).get('hostAdmission') is not True or
                entry.get('hooks', {}).get('allowConversationAccess') is not True or
                config.get('skills', {}).get('workshop', {}).get('autonomous', {}).get('mode') != 'off'):
            raise ValueError('Controller launch requires the reviewed admission hook policy')
        if not isinstance(message, str) or not 0 < len(message.encode()) <= 32768:
            raise ValueError('Bounded owner controller message required')
        with self.lock:
            if self.worker or self.active or self.closed or not self.transport_env:
                raise workload.Busy(recovery=True)
            Path(executable).resolve(strict=True)
            self.worker_path = str(Path(executable).absolute().parent) + os.pathsep + self.worker_path
            env = environment(self.home, path)
            env.update(self.transport_env, PATH=self.worker_path)
            self.session_id = str(uuid.uuid4())
            arguments = [str(executable), 'agent']
            if local:
                arguments.append('--local')
            arguments.extend(['--agent', 'main', '--session-id', self.session_id,
                '--session-key', self.session_key, '--message', message,
                '--timeout', str(timeout), '--json'])
            self.worker = subprocess.Popen(arguments, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                write_json(self.parent.path.parent / 'controller-worker.json', {
                    'schema': 'argos-controller-worker/1', 'parent_id': self.parent.record['id'],
                    'generation': self.parent.record['generation'], 'pid': self.worker.pid,
                    'worker_identity': workload.worker_identity(self.worker.pid),
                    'session_id': self.session_id, 'session_key': self.session_key, 'state': 'starting'})
            except BaseException:
                self.uncertain = True
                raise
            return self.worker

    def finish(self, *, timeout=1900, finalize=True):
        """Confirm our exact embedded SDK worker and its process group exited.

        agent_end is intentionally not required or sufficient: the SDK dispatches
        it asynchronously. Timeout/failed/uncertain execution stays quarantined.
        """
        if not self.worker:
            raise workload.Busy(recovery=True)
        if not finalize and (self.exam_session is None or self.exam_session.tier != 'practice'):
            raise ValueError('Only host-owned practice may retain a drained turn')
        try:
            stdout, stderr = self.worker.communicate(timeout=timeout)
            self.last_stdout, self.last_stderr = stdout, stderr
            if self.worker.returncode or len(stdout.encode()) > 2 * 1024**2:
                raise workload.Busy(recovery=True)
            value = json.loads(stdout)
            body = value.get('result', value)
            if (value.get('status', 'ok') != 'ok' or not isinstance(body.get('payloads'), list) or
                    body.get('meta', {}).get('agentMeta', {}).get('sessionId') != self.session_id):
                raise workload.Busy(recovery=True)
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
                    if int(fields[2]) == self.worker.pid and fields[0] not in ('Z', 'X'):
                        raise workload.Busy(recovery=True)
                except (FileNotFoundError, ProcessLookupError):
                    continue
            with self.lock:
                if not self.active:
                    raise workload.Busy(recovery=True)
                write_json(self.parent.path.parent / 'controller-worker.json', {
                    'schema': 'argos-controller-worker/1', 'parent_id': self.parent.record['id'],
                    'generation': self.parent.record['generation'], 'pid': self.worker.pid,
                    'session_id': self.session_id, 'session_key': self.session_key,
                    'state': 'completed', 'process_group_drained': True,
                    'sdk_end_observed': self.active['ended'], 'run_id': self.active['run_id'],
                    'stdout_sha256': hashlib.sha256(stdout.encode()).hexdigest(), 'tools': self.outcomes})
                self.verified = True
                if finalize:
                    self._complete()
            return value, stderr
        except BaseException:
            self.uncertain = True
            raise

    def next_practice_turn(self, session_key):
        """Host-only transition between verified drained practice workers.

        Keep the same exclusive reservation and exam. No agent IPC operation
        can invoke this method, release the lease, or claim worker drainage.
        """
        with self.lock:
            if (self.exam_session is None or self.exam_session.tier != 'practice' or
                    not self.verified or not self.worker or self.worker.poll() != 0 or
                    self.closed or self.uncertain or self.pending or self.tool_lock.locked() or
                    not self.active or not identity(session_key)):
                raise workload.Busy(recovery=True)
            self.worker = None
            self.active = None
            self.verified = False
            self.session_key = session_key

    def _complete(self):
        """Private host completion after finish() establishes the worker outcome."""
        with self.lock:
            if (not self.verified or not self.worker or self.worker.poll() != 0 or self.tool_lock.locked() or self.pending or
                    self.uncertain or not self.active):
                raise workload.Busy(recovery=True)
            if self.exam_session is not None:
                try:
                    # Require a terminal, privately persisted signed transcript
                    # before releasing the exclusive Proctor reservation.
                    if (self.exam_session.tier == 'practice' and
                            (self.exam_session.session_id is None or
                             self.exam_session.status()['state'] not in
                             {'COMPLETED', 'ABANDONED', 'TIMED_OUT', 'INVALIDATED'})):
                        self.exam_session.host_abandon()
                    envelope = self.exam_session.host_transcript()
                except (ValueError, OSError):
                    self.uncertain = True
                    self.publish()
                    raise workload.Busy(recovery=True) from None
                transcript_hash = hashlib.sha256(envelope['payload_json'].encode('utf-8')).hexdigest()
                session_id = self.exam_session.session_id
                transcript_id = session_id.removeprefix('sess_')
                if not re.fullmatch('[a-f0-9]{32}', transcript_id):
                    self.uncertain = True
                    self.publish()
                    raise workload.Busy(recovery=True)
                self.outcomes.append({'kind': 'proctor_finalize', 'transcript_id': transcript_id,
                                      'transcript_sha256': transcript_hash})
                # Journal the transcript receipt before release. If publication
                # fails, the parent reservation remains quarantined.
                self.publish()
                self.parent.complete(transcript_id)
            else:
                self.parent.complete()
            self.closed = True


@contextmanager
def owned(home, *, session_key, trigger='user', worker_timeout=1800, exam_session=None):
    if sys.platform != 'linux':
        raise ValueError('Native controller bridge requires Linux')
    if exam_session is not None and trigger != 'user':
        raise ValueError('Proctor exam sessions require an owner-started user turn')
    workload_kind = 'proctor' if exam_session is not None else 'controller'
    with workload.reserve(home, workload_kind) as parent:
        bridge = Bridge(home, parent, session_key=session_key, trigger=trigger,
                        worker_timeout=worker_timeout, exam_session=exam_session)
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                work_bearing = False
                write_lock = threading.Lock()
                try:
                    self.request.settimeout(5)
                    raw = self.rfile.readline(LIMIT + 1)
                    if len(raw) > LIMIT or not raw.endswith(b'\n'):
                        raise ValueError('Bridge request exceeds bound')
                    request = json.loads(raw)
                    work_bearing = isinstance(request, dict) and request.get('op') == 'tool'
                    def progress(event):
                        frame = {'status': 'progress', 'progress': {
                            'phase': event['phase'], 'completed': event.get('completed'),
                            'total': event.get('total'),
                            'passed': bool(event.get('receipt', {}).get('score'))
                            if event['phase'] == 'scored' else None}}
                        try:
                            with write_lock:
                                self.wfile.write((json.dumps(frame) + '\n').encode())
                                self.wfile.flush()
                        except OSError:
                            # A caller leaving the wait does not own child lifetime.
                            pass
                    response = bridge.dispatch(request, on_update=progress if work_bearing else None)
                except workload.Busy as error:
                    response = {'status': 'busy', 'recovery_required': error.recovery}
                except (ValueError, KeyError, TypeError, OSError):
                    response = {'status': 'failed', 'message': 'Controller bridge request failed'}
                try:
                    with write_lock:
                        self.wfile.write((json.dumps(response) + '\n').encode())
                except OSError:
                    # End notifications carry no work/release authority. A lost
                    # optional acknowledgment cannot negate proven worker exit.
                    if work_bearing and request.get('kind') not in {'evaluation', 'evaluation_wait',
                                                                      'evaluation_status'}:
                        bridge.uncertain = True
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
            block_on_close = False
        # AF_UNIX pathname bounds apply even when HOME is a long mount path.
        with tempfile.TemporaryDirectory(prefix='argos-controller-') as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / 'host.sock'
            with Server(str(path), Handler) as server:
                path.chmod(0o600)
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
                thread.start()
                bridge.transport_env = bridge.environment(path)
                try:
                    yield bridge, dict(bridge.transport_env)
                finally:
                    bridge.closed = True
                    server.shutdown()
                    thread.join(timeout=5)
                    # Startup can fail before an SDK worker or tool starts (for
                    # example, a busy local backend or gateway port). Such a
                    # reservation is safely releasable; no child inference was
                    # admitted. Any started/uncertain worker still quarantines.
                    if (not parent.drained and not bridge.uncertain and not bridge.worker and
                            not bridge.pending and not bridge.active and not bridge.tool_lock.locked()):
                        parent.complete()
                    # A caller cannot mark release before leaving a live tool
                    # worker behind. The durable parent remains quarantined.
                    if not parent.drained or bridge.pending or bridge.tool_lock.locked() or bridge.uncertain:
                        parent.drained = False
                        bridge.uncertain = True
                        # Stop the controller before draining its admitted tool.
                        # A disappearing agent/client is not an owner cancellation
                        # of an evaluation. Keep the parent lock and handler alive
                        # through saved publication, even though this controller's
                        # uncertain outcome must still leave quarantine in place.
                        if bridge.worker and bridge.worker.poll() is None:
                            bridge.worker.terminate()
                            try:
                                bridge.worker.wait(timeout=30)
                            except subprocess.TimeoutExpired:
                                pass
                        drained = bridge.tool_lock.acquire(timeout=bridge.worker_timeout + 90)
                        if drained:
                            bridge.tool_lock.release()
                        # The host's existing worker deadline still bounds failed
                        # or stuck children. This is not host-process survival or
                        # independent backend-drainage proof.
                        if bridge.pending and bridge.pending.poll() is None:
                            bridge.pending.terminate()
                            try:
                                bridge.pending.wait(timeout=30)
                            except subprocess.TimeoutExpired:
                                pass  # Quarantine persists; never infer exit from a deadline.
