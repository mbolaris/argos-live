"""Authoritative local state machine. One connection per worker; no network listener."""
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from .cartridge import DIRECTORY, correct_answer, identifier, json_text, valid_answer

MS = 1_000_000
TERMINAL = {'COMPLETED', 'ABANDONED', 'TIMED_OUT', 'INVALIDATED'}


def synchronized(method):
    """Serialize one engine's shared SQLite connection across host SDK threads."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._db_lock:
            return method(self, *args, **kwargs)
    return locked


class ProctorError(ValueError):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def clock_ns():
    # Linux suspend counts against exam time. Boot identity guards cross-reboot use.
    if hasattr(time, 'CLOCK_BOOTTIME'):
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return time.monotonic_ns()


@contextmanager
def transaction(conn):
    if conn.in_transaction:
        raise RuntimeError('Nested proctor transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield
        conn.execute('COMMIT')
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise


def open_state(path):
    """Create/open private runtime storage. The host must supply a private directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or (os.name != 'nt' and path.parent.stat().st_mode & 0o077):
        raise ValueError('State requires a private directory and an unlinked database')
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            raise ValueError('State database permissions must be private')
    else:
        os.close(fd)
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA busy_timeout=10000')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            # Single initialization transaction, also serializes first-open workers.
            with transaction(conn):
                if conn.execute('PRAGMA user_version').fetchone()[0] == 0:
                    # executescript implicitly commits; execute individual schema statements instead.
                    statement = ''
                    for line in (DIRECTORY / 'state.sql').read_text(encoding='utf-8').splitlines(True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ''
        elif version != 1:
            raise ValueError('Unsupported proctor state version')
        return conn
    except BaseException:
        conn.close()
        raise


@dataclass(frozen=True)
class Caller:
    """Host-registered credentials; identity and telemetry claims are never examinee parameters."""
    token_hash: str
    telemetry_trust: str = 'unavailable'


class Proctor:
    def __init__(self, cartridge, state, *, callers, token_secret, boot_id, signer, clock=clock_ns):
        if state.isolation_level is not None or not isinstance(token_secret, bytes) or len(token_secret) < 32:
            raise ValueError('Autocommit connection and at least 256-bit host token secret required')
        self.cart, self.db = cartridge, state
        self._db_lock = threading.RLock()
        self.callers = dict(callers)
        self.secret, self.boot_id, self.signer, self.clock = token_secret, boot_id, signer, clock
        if not isinstance(boot_id, str) or not boot_id:
            raise ValueError('Host boot identity required')
        if any(c.telemetry_trust not in ('unavailable', 'self_reported_untrusted', 'verified_harness')
               for c in self.callers.values()):
            raise ValueError('Invalid telemetry provenance')
        fingerprint = hashlib.sha256(token_secret).hexdigest()
        prior = self.db.execute("SELECT value FROM host_settings WHERE name='token_key'").fetchone()
        if prior is None:
            with transaction(self.db):
                self.db.execute("INSERT OR IGNORE INTO host_settings VALUES ('token_key',?)", (fingerprint,))
                prior = self.db.execute("SELECT value FROM host_settings WHERE name='token_key'").fetchone()
        if prior[0] != fingerprint:
            raise ValueError('Host token key changed; explicit key migration is required')

    def _caller(self, caller_id, token):
        caller = self.callers.get(caller_id)
        if not caller or not isinstance(token, str) or not hmac.compare_digest(caller.token_hash, digest(token)):
            raise ProctorError(401, 'UNAUTHORIZED_CALLER')
        return caller

    def _session(self, session_id, token):
        s = self.db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if not s or not isinstance(token, str) or not hmac.compare_digest(s['token_hash'], digest(token)):
            raise ProctorError(401, 'UNAUTHORIZED_SESSION')
        if s['cartridge_digest'] != self.cart.digest:
            raise ProctorError(409, 'CARTRIDGE_UNAVAILABLE')
        return s

    def _token(self, session_id, nonce):
        return hmac.new(self.secret, ('examinee-v1:' + session_id + ':' + nonce).encode(), hashlib.sha256).hexdigest()

    def _replay(self, caller, scope, op, key, request):
        identifier(key)
        row = self.db.execute('SELECT * FROM operations WHERE caller_id=? AND scope=? AND operation=? AND operation_key=?',
                              (caller, scope, op, key)).fetchone()
        if not row:
            return None
        if row['request_hash'] != digest(json_text(request)):
            raise ProctorError(409, 'IDEMPOTENCY_CONFLICT')
        response = json.loads(row['response_json'])
        if row['status'] < 400:
            response['idempotent_replay'] = True
        return row['status'], response

    def _save_operation(self, caller, scope, op, key, request, status, response):
        self.db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?)',
                        (caller, scope, op, key, digest(json_text(request)), 'COMPLETED', status, json_text(response)))

    @staticmethod
    def _result(status, response):
        if status >= 400:
            raise ProctorError(status, response['error'])
        return response

    @synchronized
    def enroll(self, caller_id, caller_token, key, *, form_id, tier, subject, policy):
        """Host-facing launch API. The future examinee transport must not expose subject/policy selection."""
        caller = self._caller(caller_id, caller_token)
        subject, policy = json.loads(json_text(subject)), json.loads(json_text(policy))
        for field in ('lineage_id', 'subject_type', 'model_tag', 'model_digest', 'configuration'):
            if field not in subject:
                raise ValueError('Incomplete subject snapshot')
        identifier(subject['lineage_id'])
        if subject.get('memory_id') is not None:
            identifier(subject['memory_id'])
        if subject['subject_type'] not in ('raw_model_driver', 'restricted_booth_agent', 'deployed_agent_profile'):
            raise ValueError('Unsupported subject type')
        model_digest = subject['model_digest']
        if not isinstance(model_digest, str) or len(model_digest) != 64 or any(c not in '0123456789abcdef' for c in model_digest):
            raise ValueError('Verified model digest required')
        # This core has no enforcement adapter; never certify an unimplemented booth.
        if (policy.get('enforcement_level') != 'declared' or policy.get('assistance_policy') not in
                ('closed_book', 'reference_aided')):
            raise ValueError('V1 core only records declared closed-book/reference-aided conditions')
        if len(json_text(subject).encode()) > 65536 or len(json_text(policy).encode()) > 8192:
            raise ValueError('Oversized configuration snapshot')
        if tier not in ('practice', 'assessment', 'held_out') or form_id not in self.cart.forms:
            raise ValueError('Unknown form or exposure tier')
        request = {'form_id': form_id, 'tier': tier, 'subject': subject, 'policy': policy,
                   'cartridge_digest': self.cart.digest}
        with transaction(self.db):
            replay = self._replay(caller_id, '__enroll__', 'enroll', key, request)
            if replay:
                status, response = replay
            else:
                now = self.clock()
                lineage, memory = subject['lineage_id'], subject.get('memory_id')
                exposures = self.db.execute('''SELECT e.*, s.state, s.start_deadline_ns, s.tier FROM exposures e
                    JOIN sessions s USING(session_id) WHERE e.cartridge_id=? AND e.form_id=?
                    AND (e.lineage_id=? OR (? IS NOT NULL AND e.memory_id=?))''',
                    (self.cart.manifest['cartridge_id'], form_id, lineage, memory, memory)).fetchall()
                prior_lineage = sum(e['questions_released'] and e['lineage_id'] == lineage for e in exposures)
                prior_memory = sum(e['questions_released'] and memory is not None and e['memory_id'] == memory for e in exposures)
                reservations = [e for e in exposures if e['state'] not in TERMINAL and
                                (e['state'] != 'READY' or e['start_deadline_ns'] > now)]
                blocked = ((tier == 'held_out' and (prior_lineage or prior_memory or reservations))
                           or any(e['tier'] == 'held_out' for e in reservations))
                if blocked:
                    status, response = 409, {'error': 'HELD_OUT_EXPOSURE_OR_RESERVATION'}
                else:
                    sid, nonce = 'sess_' + secrets.token_hex(16), secrets.token_hex(16)
                    token = self._token(sid, nonce)
                    entry = self.cart.forms[form_id]['entry_module_id']
                    self.db.execute('''INSERT INTO sessions (session_id,caller_id,token_hash,token_nonce,boot_id,state,
                        cartridge_digest,form_id,tier,subject_json,policy_json,lineage_id,memory_id,prior_lineage,prior_memory,
                        created_ns,start_deadline_ns,active_module) VALUES (?,?,?,?,?,'READY',?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (sid, caller_id, digest(token), nonce, self.boot_id, self.cart.digest, form_id, tier,
                         json_text(subject), json_text(dict(policy, client_telemetry_trust=caller.telemetry_trust)),
                         lineage, memory, prior_lineage, prior_memory, now,
                         now + self.cart.manifest['start_window_ms'] * MS, entry))
                    self.db.execute("INSERT INTO session_modules(session_id,module_id,state) VALUES (?,?,'PENDING')", (sid, entry))
                    self.db.execute('INSERT INTO exposures(session_id,cartridge_id,form_id,lineage_id,memory_id) VALUES (?,?,?,?,?)',
                                    (sid, self.cart.manifest['cartridge_id'], form_id, lineage, memory))
                    status, response = 200, {'session_id': sid, 'state': 'READY',
                                             'prior_lineage_exposures': prior_lineage, 'prior_memory_exposures': prior_memory}
                self._save_operation(caller_id, '__enroll__', 'enroll', key, request, status, response)
        response = self._result(status, response)
        row = self.db.execute('SELECT token_nonce FROM sessions WHERE session_id=?', (response['session_id'],)).fetchone()
        return dict(response, examinee_token=self._token(response['session_id'], row[0]))

    def _mutate(self, session_id, token, operation, key, request, action):
        with transaction(self.db):
            s = self._session(session_id, token)  # authorization before replay
            replay = self._replay(s['caller_id'], session_id, operation, key, request)
            if replay:
                status, response = replay
            else:
                now = self.clock()  # acceptance time is sampled after obtaining the write lock
                self._catch_up(session_id, now)
                s = self.db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
                try:
                    response = action(s, now)
                    status = 200
                except ProctorError as exc:
                    status, response = exc.status, {'error': exc.code}
                self._save_operation(s['caller_id'], session_id, operation, key, request, status, response)
        # Expected rejection evidence is durable before an exception reaches the caller.
        return self._result(status, response)

    def _activate(self, sid, mod_id, anchor):
        deadline = anchor + self.cart.modules[mod_id]['duration_ms'] * MS
        self.db.execute("UPDATE session_modules SET state='ACTIVE',started_ns=?,deadline_ns=? WHERE session_id=? AND module_id=?",
                        (anchor, deadline, sid, mod_id))
        self.db.execute("UPDATE sessions SET state='ACTIVE',active_module=? WHERE session_id=?", (mod_id, sid))
        self.db.execute('UPDATE exposures SET questions_released=1 WHERE session_id=?', (sid,))
        return deadline

    def _close(self, s, anchor, expired):
        sid, mod_id = s['session_id'], s['active_module']
        self.db.execute('UPDATE session_modules SET state=?,locked_ns=? WHERE session_id=? AND module_id=?',
                        ('EXPIRED' if expired else 'SUBMITTED', anchor, sid, mod_id))
        # Only bounded deterministic choice/numeric scoring runs under this lock.
        answers = {r['item_id']: r['answer'] for r in self.db.execute(
            'SELECT item_id,answer FROM answers WHERE session_id=? AND module_id=?', (sid, mod_id))}
        module = self.cart.modules[mod_id]
        correct = sum(correct_answer(i, answers.get(i['item_id'])) for i in module['items'])
        target = next(r['next_module_id'] for r in module['routes'] if r['minimum'] <= correct <= r['maximum'])
        # A late worker response must not expose an aid result after module closure.
        self.db.execute("UPDATE aids SET state='DISCARDED',completed_ns=? WHERE session_id=? AND module_id=? AND state='RUNNING'",
                        (anchor, sid, mod_id))
        if expired and self.cart.manifest['abort_on_timeout']:
            self._terminal(sid, 'TIMED_OUT', 'MODULE_TIMEOUT', anchor)
        elif target is None:
            self._terminal(sid, 'COMPLETED', 'ALL_MODULES_LOCKED', anchor)
        else:
            break_end = anchor + self.cart.modules[target]['break_ms'] * MS
            self.db.execute("INSERT INTO session_modules(session_id,module_id,state,break_deadline_ns) VALUES (?,?,'BREAK',?)",
                            (sid, target, break_end))
            self.db.execute("UPDATE sessions SET state='BREAK',active_module=? WHERE session_id=?", (target, sid))

    def _catch_up(self, sid, now):
        for _ in range(2 * len(self.cart.modules) + 2):
            s = self.db.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
            if s['state'] == 'READY' and now >= s['start_deadline_ns']:
                self._terminal(sid, 'ABANDONED', 'START_WINDOW_EXPIRED', s['start_deadline_ns'])
            elif s['state'] in ('ACTIVE', 'BREAK'):
                m = self.db.execute('SELECT * FROM session_modules WHERE session_id=? AND module_id=?',
                                    (sid, s['active_module'])).fetchone()
                if s['state'] == 'BREAK' and now >= m['break_deadline_ns']:
                    self._activate(sid, m['module_id'], m['break_deadline_ns'])
                elif s['state'] == 'ACTIVE' and now >= m['deadline_ns']:
                    self._close(s, m['deadline_ns'], True)
                else:
                    return
            else:
                return
        raise RuntimeError('Cartridge exceeded bounded transition count')

    @synchronized
    def begin_module(self, sid, token, module_id, key):
        def action(s, now):
            if s['active_module'] != module_id or s['state'] not in ('READY', 'BREAK', 'ACTIVE'):
                raise ProctorError(409, 'MODULE_NOT_STARTABLE')
            if s['state'] == 'ACTIVE':
                m = self.db.execute('SELECT deadline_ns FROM session_modules WHERE session_id=? AND module_id=?', (sid, module_id)).fetchone()
                return {'module_id': module_id, 'deadline_ns': m[0]}
            return {'module_id': module_id, 'deadline_ns': self._activate(sid, module_id, now)}
        return self._mutate(sid, token, 'begin_module', key, {'module_id': module_id}, action)

    def _active(self, s, mod_id):
        if s['state'] != 'ACTIVE' or s['active_module'] != mod_id:
            raise ProctorError(409, 'MODULE_NOT_ACTIVE')

    @synchronized
    def record_answer(self, sid, token, module_id, item_id, answer, revision, key):
        if not isinstance(answer, str) or len(answer.encode('utf-8')) > 8192 or type(revision) is not int:
            raise ProctorError(422, 'INVALID_SUBMISSION_ARGUMENTS')
        request = {'module_id': module_id, 'item_id': item_id, 'answer': answer, 'revision': revision}
        def action(s, now):
            item = self.cart.items.get(item_id)
            if item is None or item['module_id'] != module_id:
                raise ProctorError(404, 'ITEM_NOT_IN_MODULE')
            member = self.db.execute('SELECT 1 FROM session_modules WHERE session_id=? AND module_id=?', (sid, module_id)).fetchone()
            if not member:
                raise ProctorError(404, 'MODULE_NOT_RELEASED')
            row = self.db.execute('SELECT revision FROM answers WHERE session_id=? AND item_id=?', (sid, item_id)).fetchone()
            current = row[0] if row else 0
            if s['state'] != 'ACTIVE' or s['active_module'] != module_id:
                error = ProctorError(409, 'MODULE_NOT_ACTIVE')
            elif not valid_answer(item, answer):
                error = ProctorError(422, 'INVALID_ANSWER_FORMAT')
            elif revision != current + 1:
                error = ProctorError(409, 'STALE_REVISION')
            else:
                error = None
            self.db.execute('INSERT INTO attempts(session_id,module_id,item_id,operation_key,requested_revision,answer,outcome,at_ns) VALUES (?,?,?,?,?,?,?,?)',
                            (sid, module_id, item_id, key, revision, answer, error.code if error else 'ACCEPTED', now))
            if error:
                raise error
            self.db.execute('''INSERT INTO answers VALUES (?,?,?,?,?,?) ON CONFLICT(session_id,item_id) DO UPDATE
                SET revision=excluded.revision,answer=excluded.answer,accepted_ns=excluded.accepted_ns''',
                (sid, module_id, item_id, revision, answer, now))
            return {'status': 'accepted', 'revision': revision}
        return self._mutate(sid, token, 'record_answer', key, request, action)

    @synchronized
    def submit_module(self, sid, token, module_id, key):
        def action(s, now):
            self._active(s, module_id)
            self._close(s, now, False)
            self._catch_up(sid, now)  # zero-length break starts the next module immediately
            return {'state': self.db.execute('SELECT state FROM sessions WHERE session_id=?', (sid,)).fetchone()[0]}
        return self._mutate(sid, token, 'submit_module', key, {'module_id': module_id}, action)

    @synchronized
    def reserve_aid(self, sid, token, module_id, name, value, key):
        if len(json_text(value).encode()) > 8192:
            raise ValueError('Aid input exceeds limit')
        request = {'module_id': module_id, 'name': name, 'input': value}
        def action(s, now):
            self._active(s, module_id)
            if (name not in self.cart.modules[module_id]['aids'] or
                    json.loads(s['policy_json'])['assistance_policy'] != 'reference_aided'):
                raise ProctorError(403, 'AID_NOT_ALLOWED')
            aid_id = 'aid_' + secrets.token_hex(16)
            self.db.execute("INSERT INTO aids VALUES (?,?,?,?,?,?,?,'RUNNING',NULL,?,NULL)",
                            (aid_id, sid, module_id, s['caller_id'], key, name, json_text(value), now))
            return {'aid_id': aid_id, 'state': 'RUNNING'}
        response = self._mutate(sid, token, 'use_aid', key, request, action)
        # Reservation itself is the idempotent result. Worker lifecycle lives in aids.
        return response

    @synchronized
    def complete_aid(self, caller_id, caller_token, aid_id, output):
        self._caller(caller_id, caller_token)
        encoded = json_text(output)
        if len(encoded.encode()) > 8192:
            raise ValueError('Aid output exceeds limit')
        with transaction(self.db):
            a = self.db.execute('SELECT * FROM aids WHERE aid_id=? AND caller_id=?', (aid_id, caller_id)).fetchone()
            if not a:
                raise ProctorError(404, 'UNKNOWN_AID')
            session_digest = self.db.execute('SELECT cartridge_digest FROM sessions WHERE session_id=?', (a['session_id'],)).fetchone()[0]
            if session_digest != self.cart.digest:
                raise ProctorError(409, 'CARTRIDGE_UNAVAILABLE')
            if a['state'] == 'COMPLETED':
                if a['output_json'] != encoded:
                    raise ProctorError(409, 'AID_COMPLETION_CONFLICT')
                return
            now = self.clock()
            self._catch_up(a['session_id'], now)
            s = self.db.execute('SELECT * FROM sessions WHERE session_id=?', (a['session_id'],)).fetchone()
            if a['state'] != 'RUNNING' or s['state'] != 'ACTIVE' or s['active_module'] != a['module_id']:
                error = ProctorError(409, 'AID_NO_LONGER_ACTIVE')
            else:
                self.db.execute("UPDATE aids SET state='COMPLETED',output_json=?,completed_ns=? WHERE aid_id=?",
                                (encoded, now, aid_id))
                error = None
        if error:
            raise error

    @synchronized
    def aid_status(self, sid, token, aid_id):
        s = self._session(sid, token)
        a = self.db.execute('SELECT * FROM aids WHERE session_id=? AND aid_id=?', (sid, aid_id)).fetchone()
        if not a:
            raise ProctorError(404, 'UNKNOWN_AID')
        self._read_active(s, a['module_id'])
        return {'aid_id': aid_id, 'state': a['state'],
                'output': json.loads(a['output_json']) if a['state'] == 'COMPLETED' else None}

    def _read_active(self, s, mod_id):
        self._active(s, mod_id)
        deadline = self.db.execute('SELECT deadline_ns FROM session_modules WHERE session_id=? AND module_id=?',
                                   (s['session_id'], mod_id)).fetchone()[0]
        if self.clock() >= deadline:
            raise ProctorError(409, 'MODULE_DEADLINE_EXPIRED')

    @synchronized
    def get_item(self, sid, token, module_id, item_id):
        s = self._session(sid, token)
        self._read_active(s, module_id)
        item = self.cart.items.get(item_id)
        if not item or item['module_id'] != module_id:
            raise ProctorError(404, 'ITEM_NOT_IN_MODULE')
        return {k: json.loads(json_text(item[k])) for k in
                ('item_id', 'position', 'domain', 'prompt', 'response_type', 'choices')}

    @synchronized
    def status(self, sid, token):
        s = self._session(sid, token)
        mod_id = s['active_module']
        result = {'session_id': sid, 'state': s['state'], 'reason': s['reason'], 'module_id': mod_id}
        if mod_id:
            m = self.db.execute('SELECT * FROM session_modules WHERE session_id=? AND module_id=?', (sid, mod_id)).fetchone()
            result['time_remaining_ms'] = max(0, (m['deadline_ns'] - self.clock()) // MS) if m['deadline_ns'] is not None else None
            result['answer_revisions'] = {r['item_id']: r['revision'] for r in self.db.execute(
                'SELECT item_id,revision FROM answers WHERE session_id=? AND module_id=?', (sid, mod_id))}
            result['allowed_aids'] = list(self.cart.modules[mod_id]['aids']) if json.loads(s['policy_json'])['assistance_policy'] == 'reference_aided' else []
            result['item_ids'] = [i['item_id'] for i in self.cart.modules[mod_id]['items']] if s['state'] == 'ACTIVE' else []
        return result

    def _terminal(self, sid, state, reason, at):
        self.db.execute('UPDATE sessions SET state=?,reason=?,active_module=NULL WHERE session_id=?', (state, reason, sid))
        self.db.execute("UPDATE aids SET state='UNCERTAIN',completed_ns=? WHERE session_id=? AND state='RUNNING'", (at, sid))
        self._prepare_transcript(sid, at)

    def _prepare_transcript(self, sid, at):
        s = self.db.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone()
        modules = [dict(r) for r in self.db.execute('SELECT * FROM session_modules WHERE session_id=? ORDER BY started_ns,module_id', (sid,))]
        accepted = [dict(r) for r in self.db.execute('SELECT * FROM answers WHERE session_id=? ORDER BY module_id,item_id', (sid,))]
        answers = {r['item_id']: r['answer'] for r in accepted}
        delivered = [i for m in modules if m['started_ns'] is not None for i in self.cart.modules[m['module_id']]['items']]
        domains = {}
        for item in delivered:
            d = domains.setdefault(item['domain'], {'correct': 0, 'total': 0, 'answered': 0})
            d['total'] += 1
            d['answered'] += item['item_id'] in answers
            d['correct'] += correct_answer(item, answers.get(item['item_id']))
        first, corrected, rejected = {}, set(), 0
        for a in self.db.execute('SELECT * FROM attempts WHERE session_id=? ORDER BY attempt_id', (sid,)):
            first.setdefault(a['item_id'], a['outcome'])
            rejected += a['outcome'] != 'ACCEPTED'
            if a['outcome'] == 'ACCEPTED' and first[a['item_id']] != 'ACCEPTED':
                corrected.add(a['item_id'])
        payload = {'schema_version': 'argos.proctor.transcript.v1', 'session_id': sid,
                   'proctor_version': 'core/1', 'grader_version': 'choice-numeric/2',
                   'cartridge_id': self.cart.manifest['cartridge_id'], 'cartridge_digest': self.cart.digest,
                   'form_id': s['form_id'], 'content_origin': self.cart.manifest['content_origin'],
                   'calibration_status': 'uncalibrated', 'scaled_score': None, 'scale_range': None, 'scoring_basis': None,
                   'subject': json.loads(s['subject_json']), 'configuration_fingerprint': digest(s['subject_json']),
                   'conditions': json.loads(s['policy_json']), 'exposure_tier': s['tier'],
                   'prior_lineage_exposures': s['prior_lineage'], 'prior_memory_exposures': s['prior_memory'],
                   'boot_id': s['boot_id'], 'ended_boot_id': self.boot_id,
                   'outcome': s['state'], 'reason': s['reason'], 'ended_ns': at,
                   'modules': modules, 'accepted_answers': accepted, 'domains': domains, 'total_items': len(delivered),
                   'accepted_correct': sum(d['correct'] for d in domains.values()),
                   'unanswered': sum(i['item_id'] not in answers for i in delivered),
                   'discipline': {'items_attempted': len(first), 'items_accepted_on_first_submission': sum(v == 'ACCEPTED' for v in first.values()),
                                  'server_rejected_submissions': rejected, 'self_corrected_items': len(corrected),
                                  'client_rejected_tool_calls': None}}
        self.db.execute('INSERT INTO transcript_payloads VALUES (?,?)', (sid, json_text(payload)))

    @synchronized
    def issue_transcripts(self):
        """Trusted host worker: signing occurs outside every database write transaction."""
        rows = self.db.execute('''SELECT p.* FROM transcript_payloads p JOIN sessions s USING(session_id)
            LEFT JOIN transcripts t USING(session_id) WHERE t.session_id IS NULL AND s.cartridge_digest=?''', (self.cart.digest,)).fetchall()
        for row in rows:
            signature = self.signer.sign(row['payload_json'].encode('utf-8'))
            envelope = {'envelope_version': 'argos.proctor.envelope.v1',
                        'payload_json': row['payload_json'], 'signature': signature}
            with transaction(self.db):
                self.db.execute('INSERT OR IGNORE INTO transcripts VALUES (?,?)', (row['session_id'], json_text(envelope)))

    @synchronized
    def get_transcript(self, sid, token):
        self._session(sid, token)
        row = self.db.execute('SELECT envelope_json FROM transcripts WHERE session_id=?', (sid,)).fetchone()
        if not row:
            raise ProctorError(409, 'TRANSCRIPT_NOT_ISSUED')
        return json.loads(row[0])

    @synchronized
    def host_abandon(self, sid, token):
        """Finalize a host-owned practice whose agent turn ended before submission."""
        with transaction(self.db):
            session = self._session(sid, token)
            if session['state'] not in TERMINAL:
                self.db.execute("UPDATE session_modules SET state='INVALIDATED' "
                    "WHERE session_id=? AND state IN ('PENDING','ACTIVE','BREAK')", (sid,))
                self._terminal(sid, 'ABANDONED', 'HOST_TURN_ENDED', self.clock())
        self.issue_transcripts()
        return self.get_transcript(sid, token)

    @synchronized
    def tick(self):
        """Call from the daemon scheduler; also usable by an offline trusted runner."""
        rows = self.db.execute('SELECT session_id FROM sessions WHERE cartridge_digest=? AND state NOT IN (?,?,?,?)',
                              (self.cart.digest, *sorted(TERMINAL))).fetchall()
        for row in rows:
            with transaction(self.db):
                self._catch_up(row[0], self.clock())
        self.issue_transcripts()

    @synchronized
    def recover(self):
        """Host startup only, under exclusive supervisor ownership; never run per client connection."""
        with transaction(self.db):
            self.db.execute("UPDATE aids SET state='UNCERTAIN' WHERE state='RUNNING' AND session_id IN (SELECT session_id FROM sessions WHERE cartridge_digest=?)", (self.cart.digest,))
            rows = self.db.execute('SELECT * FROM sessions WHERE cartridge_digest=? AND state NOT IN (?,?,?,?)',
                                   (self.cart.digest, *sorted(TERMINAL))).fetchall()
            for s in rows:
                self.db.execute("UPDATE session_modules SET state='INVALIDATED' WHERE session_id=? AND state IN ('PENDING','ACTIVE','BREAK')", (s['session_id'],))
                reason = 'SYSTEM_REBOOT' if s['boot_id'] != self.boot_id else 'DAEMON_RESTART'
                self._terminal(s['session_id'], 'INVALIDATED', reason, self.clock())
        self.issue_transcripts()
