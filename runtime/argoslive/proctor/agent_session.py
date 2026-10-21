"""Narrow examinee adapter for a host-preauthorized Proctor session.

The caller chooses the form, exposure tier, subject snapshot, assistance policy,
cartridge, caller credentials and signing key. Examinee methods expose only the
active question and accept answers; they never return a score or transcript.
This is a cooperative API until a separate service identity protects its files.
"""
import hashlib
import json
import secrets


class AgentSession:
    """Present one fixed host-selected exam to an agent without host privileges."""

    def __init__(self, engine, *, caller_id, caller_token, form_id, tier, subject, policy):
        if tier not in {'practice', 'assessment', 'held_out'}:
            raise ValueError('Unsupported host-selected exposure tier')
        if form_id not in engine.cart.forms:
            raise ValueError('Unsupported host-selected form')
        if not isinstance(subject, dict) or not isinstance(policy, dict):
            raise ValueError('Host subject and policy snapshots are required')
        self.engine = engine
        self.caller_id, self.caller_token = caller_id, caller_token
        # Deep-copy and validate at construction so callers cannot mutate the
        # conditions after the session has been configured.
        from .cartridge import json_text
        import json
        self.form_id, self.tier = form_id, tier
        self.subject = json.loads(json_text(subject))
        self.policy = json.loads(json_text(policy))
        if (self.policy.get('enforcement_level') != 'declared' or
                self.policy.get('assistance_policy') != 'closed_book'):
            raise ValueError('Agent Proctor adapter currently supports declared closed-book exams only')
        self.session_id = None
        self._token = None
        self._answers = {}

    @staticmethod
    def _key(operation_id):
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 512:
            raise ValueError('Host operation identity is required')
        return hashlib.sha256(operation_id.encode('utf-8')).hexdigest()

    def start(self, operation_id):
        """Enroll and begin the host-selected entry module; no exam choices supplied."""
        if self.session_id is None:
            value = self.engine.enroll(self.caller_id, self.caller_token, self._key(operation_id),
                form_id=self.form_id, tier=self.tier, subject=self.subject, policy=self.policy)
            self.session_id, self._token = value['session_id'], value['examinee_token']
        status = self.engine.status(self.session_id, self._token)
        if status['state'] == 'READY':
            module = self.engine.cart.forms[self.form_id]['entry_module_id']
            self.engine.begin_module(self.session_id, self._token, module,
                                     self._key(operation_id + '-begin'))
            status = self.engine.status(self.session_id, self._token)
        return self._public_status(status)

    def status(self):
        self._require_started()
        return self._public_status(self.engine.status(self.session_id, self._token))

    def item(self, item_id):
        """Read one currently active item. Cartridge keys/routing are projected out."""
        self._require_started()
        module = self.engine.status(self.session_id, self._token).get('module_id')
        if not module:
            raise ValueError('No active exam module')
        return self.engine.get_item(self.session_id, self._token, module, item_id)

    def answer(self, item_id, answer, operation_id):
        """Record the next revision; the agent cannot forge revision counters."""
        self._require_started()
        status = self.engine.status(self.session_id, self._token)
        module = status.get('module_id')
        if not module or status.get('state') != 'ACTIVE':
            raise ValueError('No active exam module')
        prior = self._answers.get(item_id)
        if prior is not None and prior[1] == answer:
            return {'status': 'accepted', 'revision': prior[0], 'idempotent_replay': True}
        revision = status['answer_revisions'].get(item_id, 0) + 1
        self.engine.record_answer(self.session_id, self._token, module, item_id, answer,
                                  revision, self._key(operation_id))
        self._answers[item_id] = (revision, answer)
        return {'status': 'accepted', 'revision': revision}

    def submit(self, module_id, operation_id):
        """Submit the active module and return state only, never the score."""
        self._require_started()
        status = self.engine.status(self.session_id, self._token)
        module = status.get('module_id')
        if not module or module_id != module:
            raise ValueError('Submission must name the server-selected active module')
        self.engine.submit_module(self.session_id, self._token, module, self._key(operation_id))
        return self.status()

    def continue_module(self, operation_id):
        """Begin only the server-selected next module after its recorded break."""
        self._require_started()
        status = self.engine.status(self.session_id, self._token)
        module = status.get('module_id')
        if not module or status['state'] not in {'READY', 'BREAK'}:
            raise ValueError('No next exam module is ready')
        self.engine.begin_module(self.session_id, self._token, module, self._key(operation_id))
        return self.status()

    def host_transcript(self):
        """Trusted host finalization; never expose this method through agent tools."""
        self._require_started()
        status = self.engine.status(self.session_id, self._token)
        if status['state'] not in {'COMPLETED', 'ABANDONED', 'TIMED_OUT', 'INVALIDATED'}:
            raise ValueError('Exam has not reached a terminal state')
        self.engine.tick()
        return self.engine.get_transcript(self.session_id, self._token)

    def host_abandon(self):
        """Host-only close for an agent turn that ended before a terminal exam state."""
        if self.session_id is None:
            if self.tier != 'practice':
                raise ValueError('Only practice may record an unstarted host abandonment')
            value = self.engine.enroll(self.caller_id, self.caller_token,
                self._key('host-unstarted-' + secrets.token_hex(16)), form_id=self.form_id,
                tier=self.tier, subject=self.subject, policy=self.policy)
            self.session_id, self._token = value['session_id'], value['examinee_token']
        self.engine.host_abandon(self.session_id, self._token)
        return self.status()

    def practice_feedback(self):
        """Return aggregate coaching feedback only for a host-selected practice form."""
        if self.tier != 'practice':
            raise ValueError('Scores are withheld for assessment and held-out sessions')
        envelope = self.host_transcript()
        payload = json.loads(envelope['payload_json'])
        from .cartridge import correct_answer
        answers = {row['item_id']: row['answer'] for row in payload['accepted_answers']}
        delivered_modules = {row['module_id'] for row in payload['modules'] if row['started_ns'] is not None}
        items = []
        for item in self.engine.cart.items.values():
            if item['module_id'] not in delivered_modules:
                continue
            submitted = answers.get(item['item_id'])
            items.append({'item_id': item['item_id'], 'domain': item['domain'],
                          'submitted_answer': submitted,
                          'is_correct': submitted is not None and correct_answer(item, submitted),
                          'expected_answer': item['correct']})
        return {'state': payload['outcome'], 'correct': payload['accepted_correct'],
                'total': payload['total_items'], 'unanswered': payload['unanswered'],
                'domains': payload['domains'], 'items': items}

    def _require_started(self):
        if self.session_id is None or self._token is None:
            raise ValueError('Host-preauthorized exam has not started')

    @staticmethod
    def _public_status(status):
        # Deliberately omit session capability, answers, score and transcript.
        return {key: status[key] for key in
                ('state', 'reason', 'module_id', 'time_remaining_ms', 'item_ids',
                 'answer_revisions') if key in status}
