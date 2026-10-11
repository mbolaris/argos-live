"""One reviewed, reversible change to the everyday assistant, measured through the assistant itself.

The change is an Argos-managed block appended to the workspace AGENTS.md. Personality
files, OpenClaw configuration and Argos settings must stay byte-identical. Evidence comes
from independent tasks sent through the running gateway, before and after, in fresh
sessions; lab scores are never used. The owner approves the trial, then keeps or restores
it. Restores are byte-exact and refused when the owner has edited the file since.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid

from . import storage
from .model_selection import finish_journal, replace_raw
from .ollama import Client
from .pull_jobs import read_json, write_json

SCHEMA = 'argos-assistant-trial/1'
RECORD_SCHEMA = 'argos-assistant-changes/1'
DATA = Path(__file__).with_name('data') / 'assistant-trials' / 'grounded-answers.json'
LEGACY_ID = 'grounded-answers'
LEGACY_INSTRUCTION = ('## Answering from text you were given\n'
                      'When I give you a document, notice or passage and ask about it: answer directly first, in a short '
                      'phrase or sentence. Then quote the sentence from the text that supports your answer. If the text does '
                      'not contain the answer, say so plainly instead of guessing.')


def _block(change_id, version, instruction):
    start = f'<!-- argos-trial:{change_id} v{version} — added with your approval; Argos Live can restore the original file -->'
    return start, f'<!-- /argos-trial:{change_id} -->', f'{start}\n{instruction}\n<!-- /argos-trial:{change_id} -->\n'


_DEFINITIONS = (
    ('answer-first', 'Answer first',
     '## Answer first\nWhen answering a question, begin with the direct answer in one short sentence. Put explanation after it.',
     'answer_first', 'Answer questions directly before adding detail.'),
    ('quote-evidence', 'Show the source',
     '## Show the source\nWhen answering a question about text I provided, give the answer and then quote one exact sentence that supports it. Never make up or alter a quotation.',
     'exact_quote', 'Back up document answers with one exact sentence from the source.'),
    ('honest-uncertainty', 'Be honest when it is missing',
     '## Be honest when the source is silent\nIf text I provided does not contain the answer, say that it is not stated instead of guessing or filling in missing details.',
     'admits_not_stated', 'Say plainly when the provided text does not contain an answer.'),
)
CHANGES = []
for _id, _title, _text, _target, _scope in _DEFINITIONS:
    _start, _end, _candidate_block = _block(_id, 1, _text)
    CHANGES.append({'id': _id, 'version': 1, 'title': _title, 'file': 'AGENTS.md', 'text': _text,
                    'target_check': _target, 'scope': _scope,
                    'start': _start, 'end': _end, 'block': _candidate_block})
CHANGE_BY_ID = {change['id']: change for change in CHANGES}
# One GO runs the complete reviewed starter set before showing Keep/Restore.
MAX_EXPERIMENTS = len(CHANGES)
# Keep v1 journals and kept changes from the first U10 implementation recoverable.
_legacy_start, _legacy_end, _legacy_block = _block(LEGACY_ID, 1, LEGACY_INSTRUCTION)
LEGACY_CHANGE = {'id': LEGACY_ID, 'version': 1, 'title': 'Grounded answers', 'file': 'AGENTS.md',
                 'text': LEGACY_INSTRUCTION, 'scope': 'Questions about text you give the assistant in chat.',
                 'unchanged': ['Model and its files', 'Personality (SOUL.md, IDENTITY.md, USER.md) and memory',
                               'Tools, permissions and channels', 'Argos and OpenClaw settings'],
                 'start': _legacy_start, 'end': _legacy_end, 'block': _legacy_block}
CHANGE_BY_ID[LEGACY_ID] = LEGACY_CHANGE
CHANGE_ID, CHANGE_VERSION = LEGACY_ID, 1
CHANGE = LEGACY_CHANGE
START, END, INSTRUCTION, BLOCK = CHANGE['start'], CHANGE['end'], CHANGE['text'], CHANGE['block']
PROTECTED = ('SOUL.md', 'IDENTITY.md', 'USER.md', 'MEMORY.md')
UNCHANGED = ['Model and its files', 'Personality (SOUL.md, IDENTITY.md, USER.md) and memory',
             'Tools, permissions and channels', 'Argos and OpenClaw settings']
UNCERTAINTY = ('One run per task and only eight tasks; replies vary between runs, so a difference of one task '
               'is not meaningful. Automated text checks are limited evidence, not a general ability rating. '
               'These are everyday-assistant results only, separate from lab scores.')
OPINION_PREFIX = 'ARGOS_TRIAL_OPINION/1\n'
QUOTE = re.compile(r'[“"]([^”"]{15,})[”"]')
NOT_STATED = re.compile(r"\b(doesn['’]?t|does not|didn['’]?t|did not|isn['’]?t|is not|not|no)\b[^.?!]{0,60}?"
                        r"\b(say|says|said|state|states|stated|mention|mentions|mentioned|give|gives|given|include|"
                        r"includes|included|provide|provides|provided|specify|specifies|specified|contain|contains|"
                        r"information|details?)\b", re.I)
class Refused(ValueError):
    """A fixed, owner-facing reason an action cannot run now. Safe to show over HTTP."""


LEAK = re.compile(r'\b(quote|quoted|quotation|passage|not stated|supporting sentence)\b', re.I)


def load_tasks():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if data.get('schema') != 'argos-assistant-tasks/1' or data.get('change') != CHANGE_ID:
        raise ValueError('Invalid assistant task set')
    passages = data['passages']
    for task in data['tasks']:
        if task['kind'] in ('answer', 'not_stated'):
            if task['passage'] not in passages or not task.get('question'):
                raise ValueError('Invalid assistant task')
            if task['kind'] == 'answer' and not task.get('accepted'):
                raise ValueError('Answer tasks need accepted answers')
        elif task['kind'] != 'control' or not task.get('message'):
            raise ValueError('Invalid assistant task')
    return data


def message(task, passages):
    if task['kind'] == 'control':
        return task['message']
    return f"Here is a notice:\n\n{passages[task['passage']]}\n\n{task['question']}"


def tokens(text):
    return re.sub(r'[^\w$]+', ' ', text.lower()).split()


def contains(text, phrase):
    words, target = tokens(text), tokens(phrase)
    return bool(target) and any(words[i:i + len(target)] == target for i in range(len(words) - len(target) + 1))


def collapse(text):
    return ' '.join(text.split())


def score(task, passages, reply):
    """Code checks for one reply; reported separately so each behavior is visible."""
    reply = reply if isinstance(reply, str) else ''
    if task['kind'] == 'answer':
        # A correct fact only inside a citation must not rescue a wrong answer.
        answer = QUOTE.sub('', reply)
        first = ' '.join(answer.split()[:25])
        checks = {'answer_present': any(contains(answer, a) for a in task['accepted']),
                  'answer_first': any(contains(first, a) for a in task['accepted']),
                  'exact_quote': any(q in passages[task['passage']] and
                                     any(contains(q, a) for a in task['accepted']) for q in QUOTE.findall(reply))}
    elif task['kind'] == 'not_stated':
        checks = {'admits_not_stated': bool(NOT_STATED.search(reply))}
    else:
        checks = {'replied': bool(reply.strip()), 'no_instruction_leak': not LEAK.search(reply)}
    return {'passed': all(checks.values()), 'checks': checks}


def reviewed_profile(home):
    from .startup import source
    identity = source(home)
    config = read_json(storage.safe_local(home / '.openclaw/openclaw.json'))
    if config.get('agents', {}).get('defaults', {}).get('model', {}).get('fallbacks'):
        raise ValueError('Assistant trial requires the reviewed local model without fallbacks')
    for agent in config.get('agents', {}).get('list', []):
        if agent.get('id') == 'main' and set(agent) - {'id', 'name', 'workspace'}:
            raise ValueError('Agent-specific behavior overrides need a separately reviewed trial')
    return identity


def compare(before, after):
    rows, gains, regressions = [], [], []
    for b in before:
        a = next(x for x in after if x['id'] == b['id'])
        row = {'id': b['id'], 'kind': b['kind'], 'before': b, 'after': a,
               'gained': [c for c, ok in a['checks'].items() if ok and not b['checks'].get(c)],
               'regressed': [c for c, ok in b['checks'].items() if ok and not a['checks'].get(c)]}
        if row['gained'] and not row['regressed']:
            gains.append(b['id'])
        if row['regressed']:
            regressions.append(b['id'])
        rows.append(row)
    def passed(side, kind):
        return sum(1 for r in rows if r['kind'] == kind and r[side]['passed'])
    totals = {kind: {'before': passed('before', kind), 'after': passed('after', kind),
                     'total': sum(1 for r in rows if r['kind'] == kind)} for kind in ('answer', 'not_stated', 'control')}
    suggestion = 'keep' if len(gains) >= 2 and not regressions else 'restore'
    return {'rows': rows, 'totals': totals, 'gains': gains, 'regressions': regressions,
            'gained_checks': sum(len(row['gained']) for row in rows),
            'regressed_checks': sum(len(row['regressed']) for row in rows),
            'suggestion': suggestion, 'uncertainty': UNCERTAINTY, 'evidence': 'everyday-assistant'}


def tested_change_ids(record):
    """Keep already-compared ideas out of future rounds after an owner keeps a winner."""
    tested = []
    current = record
    while isinstance(current, dict):
        ids = current.get('tested_changes') or [current.get('change')]
        for change_id in ids:
            if change_id in CHANGE_BY_ID and change_id not in tested:
                tested.append(change_id)
        current = current.get('previous_record')
    return tested


def planned_changes(raw_before, previous_record=None):
    """Return the exact, fixed-order ideas disclosed before the owner presses GO."""
    text = raw_before or ''
    if f'argos-trial:{LEGACY_ID} ' in text:
        return []
    already_tested = set(tested_change_ids(previous_record))
    available = [change for change in CHANGES
                 if change['id'] not in already_tested and f"argos-trial:{change['id']} " not in text]
    return available[:MAX_EXPERIMENTS]


def session_result(experiments, selected_id=None):
    """Keep each matched comparison distinct; only one candidate can remain on trial."""
    selected = next((item for item in experiments if item['change']['id'] == selected_id), None)
    basis = selected or (experiments[0] if experiments else {})
    comparison = basis.get('comparison', {})
    return {**comparison, 'experiments': experiments, 'selected_change': selected_id,
            'suggestion': 'keep' if selected else 'restore',
            'uncertainty': ('Each idea had one pass through the same eight questions. Small differences are not meaningful on their own; '
                            'this is evidence about these checks, not proof of a smarter assistant.'),
            'evidence': 'everyday-assistant'}


def opinion_prompt(result):
    """Ask the tested assistant to reflect on public aggregates, never raw replies."""
    facts = {'ideas': []}
    for experiment in result.get('experiments', []):
        comparison = experiment['comparison']
        facts['ideas'].append({
            'idea': experiment['change']['title'],
            'improved_challenges': len(comparison['gains']),
            'worse_challenges': len(comparison['regressions']),
            'checks_gained': comparison.get('gained_checks', 0),
            'checks': {kind: {'before': values['before'], 'after': values['after'], 'out_of': values['total']}
                       for kind, values in comparison['totals'].items()},
        })
    return (OPINION_PREFIX +
            'You are the local assistant taking part in a small, private improvement game. In at most two short '
            'first-person sentences, say which idea looks most promising from these counts and one thing you would like to investigate '
            'next (or say that you need more evidence). Be candid and curious. These checks are limited text '
            'heuristics: do not claim general ability, learning, statistical significance, or proven improvement. '
            'Do not change anything, call tools, or choose Keep/Restore; the owner decides. Suggest only a future '
            'question to investigate, not an action that runs automatically. The counts below are authoritative; '
            'do not invent missing details.\nMEASURED COUNTS:\n' + json.dumps(facts, sort_keys=True))


def paths(home):
    base = home / '.config/argos-live'
    return (storage.safe_local(base / 'assistant-trial.json'), storage.safe_local(base / 'assistant-changes.json'))


def agents_path(home):
    config = read_json(storage.safe_local(home / '.openclaw/openclaw.json'))
    raw = config.get('agents', {}).get('defaults', {}).get('workspace')
    for agent in config.get('agents', {}).get('list', []):
        if agent.get('id') == 'main' and 'workspace' in agent:
            raw = agent['workspace']
    workspace = Path(raw).expanduser() if isinstance(raw, str) else home / '.openclaw/workspace'
    workspace = storage.safe_local(workspace if workspace.is_absolute() else home / workspace)
    if Path(home).resolve() not in workspace.resolve().parents:
        raise ValueError('Assistant workspace is outside the owner home')
    path = storage.safe_local(workspace / 'AGENTS.md')
    if path.exists():
        info = path.stat()
        if (not path.is_file() or info.st_nlink != 1 or info.st_size > 64 * 1024 or
                (os.name != 'nt' and info.st_uid != os.getuid())):
            raise ValueError('Assistant instructions require a single owner-controlled file')
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def fingerprint(home):
    """Everything the trial must leave untouched."""
    agents = agents_path(home)
    files = {'state.json': home / '.config/argos-live/state.json', 'openclaw.json': home / '.openclaw/openclaw.json'}
    files.update({name: agents.parent / name for name in PROTECTED})
    return {name: digest(storage.safe_local(path)) for name, path in files.items()}


def read_text(path):
    return path.read_bytes().decode('utf-8') if path.exists() else None


def change_for(change_id):
    value = CHANGE_BY_ID.get(change_id)
    if value is None:
        raise ValueError('This improvement idea is not in the reviewed list')
    return value


def staged(raw_before, change_id=CHANGE_ID):
    change = change_for(change_id)
    if raw_before is not None and f'argos-trial:{change_id} ' in raw_before:
        raise ValueError('This improvement is already present in AGENTS.md')
    text = raw_before or ''
    if text and not text.endswith('\n'):
        text += '\n'
    return text + ('\n' if text else '') + change['block']


def write_text(path, text):
    if text is None:
        path.unlink(missing_ok=True)
    else:
        replace_raw(path, text.encode('utf-8'))


def valid_record(value, schema, depth=0):
    try:
        if depth > 8 or not isinstance(value, dict) or value.get('schema') != schema:
            return False
        change = change_for(value.get('change'))
        raw_before = value.get('raw_before')
        if (value.get('version') != change['version'] or
                (raw_before is not None and not isinstance(raw_before, str)) or
                value.get('raw_after') != staged(raw_before, change['id']) or
                not isinstance(value.get('fingerprint'), dict)):
            return False
        previous = value.get('previous_record')
        if previous is not None:
            if not valid_record(previous, RECORD_SCHEMA, depth + 1) or previous.get('raw_after') != raw_before:
                return False
        planned = value.get('planned_changes')
        if planned is not None:
            if (not isinstance(planned, list) or not planned or len(planned) > MAX_EXPERIMENTS or
                    any(change_id not in CHANGE_BY_ID for change_id in planned) or len(planned) != len(set(planned)) or
                    change['id'] not in planned):
                return False
        tested = value.get('tested_changes')
        if tested is not None:
            expected = list(dict.fromkeys(tested_change_ids(previous) + (planned or [change['id']])))
            if tested != expected:
                return False
        return True
    except (ValueError, TypeError):
        return False


def recover(home):
    """An unfinished trial is reverted at desktop start; a trial awaiting a decision stays."""
    try:
        journal, _ = paths(home)
        if not journal.exists():
            return 'none'
        value = read_json(journal)
        if not valid_record(value, SCHEMA) or value.get('phase') not in ('staging', 'restoring', 'awaiting-decision'):
            return 'needs-review'
        if fingerprint(home) != value.get('fingerprint'):
            return 'needs-review'
        path = agents_path(home)
        current = read_text(path)
        if current not in (value['raw_after'], value['raw_before']):
            return 'needs-review'
        if value.get('phase') == 'awaiting-decision':
            return 'on-trial' if current == value['raw_after'] else 'needs-review'
        if current != value['raw_before']:
            write_text(path, value['raw_before'])
        finish_journal(journal)
        _, record = paths(home)
        previous = value.get('previous_record')
        if previous is not None:
            write_json(record, previous)
        elif record.exists():
            finish_journal(record)
        return 'restored'
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return 'needs-review'


class OpenClawRunner:
    """One turn through the running gateway, in a fresh session that is not the owner's chat."""

    def __init__(self, home, executable=None):
        self.home, self.executable = Path(home), executable
        self.cancel_event = None
        self.expected_model = None

    def turn(self, text):
        from .owned_gateway import environment
        executable = self.executable or shutil.which('openclaw')
        if not executable:
            raise ValueError('OpenClaw is unavailable')
        config = storage.safe_local(self.home / '.openclaw/openclaw.json')
        env = environment(self.home, config)
        env.pop('OPENCLAW_GATEWAY_STARTUP_TRACE', None)
        session = str(uuid.uuid4())
        started = time.monotonic()
        command = [str(executable), 'agent', '--agent', 'main', '--session-id', session,
                   '--session-key', 'agent:main:argos-trial-' + session,
                   '--message', text, '--timeout', '120', '--json']
        with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            deadline = time.monotonic() + 180
            while True:
                if (self.cancel_event and self.cancel_event.is_set()) or time.monotonic() >= deadline:
                    process.terminate()  # Pinned CLI forwards termination to the gateway's chat.abort.
                    try:
                        process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.communicate()
                    raise ValueError('Assistant turn stopped')
                try:
                    stdout, _ = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        if process.returncode or len(stdout) > 1024**2:
            raise ValueError('The assistant did not complete the turn')
        value = json.loads(stdout)
        body = value.get('result', value) if isinstance(value, dict) else {}
        rows = body.get('payloads') if isinstance(body, dict) else None
        if (not isinstance(value, dict) or value.get('ok') is False or
                value.get('status', 'ok') != 'ok' or not isinstance(rows, list)):
            raise ValueError('The assistant returned no reply')
        reply = '\n'.join(row['text'] for row in rows if isinstance(row, dict) and isinstance(row.get('text'), str))
        if not reply.strip():
            raise ValueError('The assistant returned no reply')
        meta = body.get('meta')
        agent_meta = meta.get('agentMeta') if isinstance(meta, dict) else None
        actual_session = agent_meta.get('sessionId') if isinstance(agent_meta, dict) else None
        if actual_session != session:
            raise ValueError('The assistant used a different session')
        if self.expected_model and (agent_meta.get('provider') != 'ollama' or
                                    agent_meta.get('model') != self.expected_model):
            raise ValueError('The assistant used a different model')
        return {'text': reply, 'elapsed_seconds': round(time.monotonic() - started, 2), 'session_id': session}


class Controller:
    def __init__(self, startup, *, home=None, runner=None, tasks=None, ready_timeout=900,
                 validate_profile=None, reflector=None):
        self.startup = startup
        self.home = Path(home or startup.home)
        self.runner = runner or OpenClawRunner(self.home)
        self.tasks = tasks or load_tasks()
        self.ready_timeout = ready_timeout
        self.validate_profile = validate_profile or reviewed_profile
        self.reflector = reflector or self.model_opinion
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        if isinstance(self.runner, OpenClawRunner):
            self.runner.cancel_event = self.cancel_event
        self.worker = None
        self.phase = 'idle'
        self.progress = None
        self.message = None
        self.session_result = None
        self.closed = False

    # ---- public state
    def status(self):
        journal, record = paths(self.home)
        try:
            if journal.exists():
                value = read_json(journal)
                if not valid_record(value, SCHEMA):
                    return 'needs-review', None
                if value.get('phase') == 'awaiting-decision':
                    if read_text(agents_path(self.home)) != value.get('raw_after'):
                        return 'edited', value
                    return 'on-trial', value
                return 'unfinished', value
            if record.exists():
                value = read_json(record)
                if not valid_record(value, RECORD_SCHEMA):
                    return 'needs-review', None
                current = read_text(agents_path(self.home))
                return ('kept' if current == value['raw_after'] else 'edited'), value
        except (OSError, ValueError, TypeError, KeyError):
            return 'needs-review', None
        return 'none', None

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            status, value = self.status()
            result = self.session_result if self.phase == 'no-improvement' else (value or {}).get('result')
            if result is None:
                result = (value or {}).get('result')
            tasks = [{k: t[k] for k in ('id', 'kind', 'question', 'message', 'passage') if k in t} for t in self.tasks['tasks']]
            try:
                raw = read_text(agents_path(self.home))
                prior_record = (value.get('previous_record') if status == 'on-trial' else value) if value else None
                plan = planned_changes(raw, prior_record)
            except (OSError, ValueError):
                plan = []
            public_plan = [self.public_change(change) for change in plan]
            return {'available': True, 'active': active, 'phase': self.phase, 'progress': copy.deepcopy(self.progress),
                    'message': self.message, 'status': status, 'change': public_plan[0] if public_plan else LEGACY_CHANGE,
                    'changes': public_plan, 'unchanged': UNCHANGED,
                    'max_experiments': len(plan), 'max_answers': len(tasks) * (1 + len(plan)), 'tasks': tasks,
                    'passages': self.tasks['passages'], 'result': result,
                    'result_state': self.phase if self.phase == 'no-improvement' else status,
                    'can_restore': status in ('on-trial', 'kept'), 'can_keep': status == 'on-trial'}

    # ---- actions
    def start(self, approved_changes=None):
        with self.startup.lock, self.lock:
            self.require_idle()
            status, prior = self.status()
            if status not in ('none', 'kept'):
                raise Refused('Finish or restore the current assistant change before starting another round')
            raw_before = read_text(agents_path(self.home))
            plan = planned_changes(raw_before, prior if status == 'kept' else None)
            plan_ids = [change['id'] for change in plan]
            if approved_changes is not None and approved_changes != plan_ids:
                raise Refused('The improvement plan changed. Review the updated ideas before starting.')
            if not plan:
                raise Refused('All reviewed starter ideas are already in the assistant; nothing new is ready to test')
            previous = prior if status == 'kept' else None
            if previous is not None and not valid_record(previous, RECORD_SCHEMA):
                raise Refused('The previous kept change needs review before another experiment')
            self.session_result = None
            self.begin('starting', lambda: self.execute(plan, previous))
            return self.snapshot()

    def keep(self):
        with self.startup.lock, self.lock:
            self.require_idle(ready=False)
            status, value = self.status()
            path = agents_path(self.home)
            if status != 'on-trial' or read_text(path) != value['raw_after']:
                raise Refused('Nothing on trial to keep, or AGENTS.md was edited during the trial')
            if fingerprint(self.home) != value['fingerprint']:
                raise Refused('Protected assistant files changed during the trial; review before keeping')
            journal, record = paths(self.home)
            write_json(record, {'schema': RECORD_SCHEMA, 'change': value['change'], 'version': value['version'],
                                'raw_before': value['raw_before'], 'raw_after': value['raw_after'],
                                'fingerprint': value['fingerprint'],
                                'agents_sha256': digest(path), 'kept_at': time.time(), 'result': value['result'],
                                'planned_changes': value.get('planned_changes', [value['change']]),
                                'tested_changes': list(dict.fromkeys(tested_change_ids(value.get('previous_record')) +
                                                                     value.get('planned_changes', [value['change']]))),
                                'previous_record': value.get('previous_record')})
            finish_journal(journal)
            self.phase, self.message = 'kept', 'Kept and verified: AGENTS.md contains the reviewed change.'
            return self.snapshot()

    def restore(self):
        with self.startup.lock, self.lock:
            self.require_idle(ready=False)
            status, value = self.status()
            if status not in ('on-trial', 'kept'):
                raise Refused('There is no change to restore')
            if read_text(agents_path(self.home)) != value['raw_after']:
                raise Refused('AGENTS.md was edited after the change; review it by hand')
            if fingerprint(self.home) != value.get('fingerprint'):
                raise Refused('Protected assistant files changed; review before restoring')
            self.begin('restoring', lambda: self.execute_restore(value))
            return self.snapshot()

    def cancel(self):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                self.cancel_event.set()
            return self.snapshot()

    def close(self):
        with self.lock:
            self.closed = True
            self.cancel_event.set()
            worker = self.worker
        if worker:
            # The desktop must not close its startup controller underneath an
            # in-flight rollback. Individual turns/restarts have bounded waits.
            worker.join()

    # ---- worker
    def require_idle(self, ready=True):
        if self.closed:
            raise Refused('The assistant trial is closed')
        if (self.worker is not None and self.worker.is_alive()) or getattr(self.startup, 'lab_active', False):
            raise Refused('Another desktop workload is active')
        if ready:
            value = self.startup.snapshot()
            if value.get('phase') != 'ready' or not value.get('model_reply_verified'):
                raise Refused('The assistant must be ready with a verified reply first')

    def begin(self, phase, target):
        self.startup.lab_active = True
        self.startup.chat_claimed = True
        self.cancel_event.clear()
        self.phase, self.message, self.progress = phase, None, None
        def run():
            try:
                self.phase = target()
            except Exception:
                # Never expose private paths or exception text over HTTP.
                try:
                    write_json(storage.safe_local(self.home / '.config/argos-live/assistant-trial-error.json'),
                               {'phase': self.phase, 'traceback': traceback.format_exc()[-16000:]})
                except (OSError, ValueError):
                    pass
                self.phase = 'failed'
                self.message = self.message or 'The trial stopped. Recovery needs review; no restoration is claimed.'
            finally:
                with self.lock:
                    self.startup.lab_active = False
        self.worker = threading.Thread(target=run, daemon=True, name='argos-assistant-trial')
        self.worker.start()

    def wait_stopped(self):
        deadline = time.monotonic() + 180
        while self.startup.snapshot()['active']:
            if time.monotonic() >= deadline:
                raise ValueError('Assistant resources were not released')
            time.sleep(.1)

    def wait_ready(self):
        deadline = time.monotonic() + self.ready_timeout
        while True:
            value = self.startup.snapshot()
            if value.get('phase') == 'ready' and value.get('model_reply_verified'):
                return
            if value.get('phase') in ('failed', 'stopped') or time.monotonic() >= deadline:
                raise ValueError('The assistant did not become ready')
            time.sleep(.1)

    def restart(self):
        self.startup.stop()
        self.wait_stopped()

    def start_assistant(self):
        with self.startup.lock:
            self.startup.start(_reserved=True)
            self.startup.chat_claimed = True
        self.wait_ready()

    def run_tasks(self, side, *, experiment=None, experiment_index=0, experiment_count=0,
                  session_offset=0, session_total=8):
        outcomes, total, latest = [], len(self.tasks['tasks']), None
        for index, task in enumerate(self.tasks['tasks']):
            if self.cancel_event.is_set():
                raise ValueError('Cancelled')
            current = {'id': task['id'], 'kind': task['kind'],
                       'question': task.get('question') or task.get('message'),
                       'source': self.tasks['passages'].get(task.get('passage'))}
            self.progress = {'side': side, 'done': index, 'total': total,
                             'current': current, 'latest': latest, 'experiment': experiment,
                             'experiment_index': experiment_index, 'experiment_count': experiment_count,
                             'session_done': session_offset + index, 'session_total': session_total}
            reply = self.runner.turn(message(task, self.tasks['passages']))
            if not isinstance(reply.get('text'), str) or len(reply['text']) > 6000:
                raise ValueError('The assistant response exceeds the trial inspection limit')
            outcome = score(task, self.tasks['passages'], reply['text'])
            record = {'id': task['id'], 'kind': task['kind'], **outcome, 'reply': reply['text'],
                      'elapsed_seconds': reply.get('elapsed_seconds'), 'session_id': reply.get('session_id')}
            outcomes.append(record)
            # Only the task, reply and visible checks are needed by the live watch;
            # gateway session identifiers remain private to the final evidence.
            latest = {**current, 'reply': reply['text'], 'checks': outcome['checks'],
                      'elapsed_seconds': reply.get('elapsed_seconds')}
            self.progress = {'side': side, 'done': index + 1, 'total': total,
                             'current': current, 'latest': latest, 'experiment': experiment,
                             'experiment_index': experiment_index, 'experiment_count': experiment_count,
                             'session_done': session_offset + index + 1, 'session_total': session_total}
        self.progress = {'side': side, 'done': total, 'total': total, 'current': None, 'latest': latest,
                         'experiment': experiment, 'experiment_index': experiment_index,
                         'experiment_count': experiment_count, 'session_done': session_offset + total,
                         'session_total': session_total}
        if self.cancel_event.is_set():
            raise ValueError('Cancelled')
        return outcomes

    def reflect(self, result, model):
        """Keep the assistant's opinion separate from code-scored evidence."""
        if self.cancel_event.is_set():
            return {'state': 'unavailable'}
        self.phase = 'reflecting'
        self.message = 'The scorecard is fixed. Your AI is writing a short opinion.'
        try:
            reply = self.reflector(model, opinion_prompt(result), self.cancel_event)
            text = reply.get('text') if isinstance(reply, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text.strip()) > 1000:
                return {'state': 'unavailable'}
            return {'state': 'completed', 'text': text.strip(), 'model': model,
                    'label': 'Local model opinion · not scored evidence'}
        except Exception:
            # Reflection is optional; failure must never discard the scored trial.
            return {'state': 'unavailable'}

    @staticmethod
    def model_opinion(model, prompt, cancel):
        """Use the selected local model directly, without workspace profile or tools."""
        client = Client(timeout=45)
        return client.generate(model, prompt, options={'num_ctx': 2048, 'num_predict': 120,
                                                       'temperature': 0.4, 'seed': 1},
                               think=False, keep_alive='5m', cancel=cancel)

    @staticmethod
    def public_change(change):
        return {key: change[key] for key in ('id', 'version', 'title', 'file', 'text', 'target_check', 'scope')}

    def execute(self, plan, previous_record=None):
        path = agents_path(self.home)
        raw_before = read_text(path)
        protected = fingerprint(self.home)
        journal, _ = paths(self.home)
        prior_record = copy.deepcopy(previous_record)
        experiments = []
        session_total = len(self.tasks['tasks']) * (1 + len(plan))
        current_change = None
        raw_after = None
        try:
            _, model = self.validate_profile(self.home)
        except Exception:
            self.message = 'The reviewed local assistant profile could not be verified. No change was made.'
            raise
        if isinstance(self.runner, OpenClawRunner):
            self.runner.expected_model = model
        if [change['id'] for change in plan] != [change['id'] for change in planned_changes(raw_before, previous_record)]:
            raise ValueError('The disclosed improvement plan changed before the run started')
        config = read_json(storage.safe_local(self.home / '.openclaw/openclaw.json'))
        limit = config.get('agents', {}).get('defaults', {}).get('bootstrapMaxChars', 20000)
        if not isinstance(limit, int) or any(len(staged(raw_before, change['id'])) > limit for change in plan):
            self.message = 'One of the reviewed ideas would exceed the assistant’s instruction limit. No change was made.'
            raise ValueError('Bootstrap instructions would be truncated')
        self.phase = 'before'
        try:
            before = self.run_tasks('before', experiment_count=len(plan),
                                    session_total=session_total)
        except Exception:
            # A lost CLI reply can leave a gateway turn running. Release it
            # before releasing the desktop workload reservation.
            self.restart()
            if read_text(path) != raw_before or fingerprint(self.home) != protected:
                self.message = 'The trial stopped before any change; owner edits need review. The assistant is stopped.'
                return 'recovery-blocked'
            self.start_assistant()
            self.message = 'The trial stopped before any change was made. The assistant is ready again.'
            return 'cancelled' if self.cancel_event.is_set() else 'failed'
        if read_text(path) != raw_before or fingerprint(self.home) != protected:
            self.message = 'Assistant files changed during the baseline. No experiment was applied; review is needed.'
            return 'recovery-blocked'
        try:
            for index, change in enumerate(plan):
                if self.cancel_event.is_set():
                    raise ValueError('Cancelled')
                current_change = change
                raw_after = staged(raw_before, change['id'])
                value = {'schema': SCHEMA, 'phase': 'staging', 'change': change['id'],
                         'version': change['version'], 'raw_before': raw_before, 'raw_after': raw_after,
                         'fingerprint': protected, 'started': time.time(), 'previous_record': prior_record,
                         'planned_changes': [item['id'] for item in plan]}
                write_json(journal, value)
                self.phase = 'staging'
                self.restart()
                if self.cancel_event.is_set():
                    raise ValueError('Cancelled')
                if read_text(path) != raw_before or fingerprint(self.home) != protected:
                    raise ValueError('Assistant files changed during the trial')
                write_text(path, raw_after)
                self.start_assistant()
                if self.cancel_event.is_set():
                    raise ValueError('Cancelled')
                self.phase = 'experiment'
                after = self.run_tasks('candidate', experiment=self.public_change(change),
                                       experiment_index=index + 1, experiment_count=len(plan),
                                       session_offset=len(self.tasks['tasks']) * (index + 1),
                                       session_total=session_total)
                if read_text(path) != raw_after or fingerprint(self.home) != protected:
                    raise ValueError('Assistant files changed during the trial')
                comparison = compare(before, after)
                comparison['configuration'] = {'model': model, 'tasks_version': self.tasks['version'],
                                               'tasks_sha256': hashlib.sha256(json.dumps(self.tasks, sort_keys=True).encode()).hexdigest(),
                                               'instruction_sha256': hashlib.sha256(change['block'].encode()).hexdigest(),
                                               'profile_sha256': protected['openclaw.json']}
                experiments.append({'change': self.public_change(change), 'comparison': comparison})
                value.update(phase='restoring', result={'experiments': experiments})
                write_json(journal, value)
                self.phase = 'restoring'
                self.restart()
                if read_text(path) not in (raw_after, raw_before) or fingerprint(self.home) != protected:
                    self.message = 'Owner edits prevent automatic recovery. The assistant is stopped; review the retained trial record.'
                    return 'recovery-blocked'
                if read_text(path) != raw_before:
                    write_text(path, raw_before)
                self.start_assistant()
                if read_text(path) != raw_before or fingerprint(self.home) != protected:
                    raise ValueError('Restoration between ideas could not be verified')
                finish_journal(journal)
                current_change = raw_after = None
                if self.cancel_event.is_set():
                    self.message = 'The run stopped safely. The original instructions are back.'
                    return 'cancelled'

            if not experiments:
                self.message = 'There are no untried reviewed ideas in this starter set. Nothing was changed.'
                return 'no-candidates'
            winners = [item for item in experiments if item['comparison']['suggestion'] == 'keep']
            winner = max(winners, key=lambda item: (item['comparison'].get('gained_checks', 0),
                                                     len(item['comparison']['gains']),
                                                     -len(item['comparison']['regressions'])), default=None)
            result = session_result(experiments, winner['change']['id'] if winner else None)
            if winner is None:
                result['opinion'] = self.reflect(result, model)
                self.session_result = result
                self.message = 'No idea earned a clean two-challenge win. Your original setup is back; nothing new was kept.'
                return 'no-improvement'

            selected = change_for(winner['change']['id'])
            raw_after = staged(raw_before, selected['id'])
            value = {'schema': SCHEMA, 'phase': 'staging', 'change': selected['id'],
                     'version': selected['version'], 'raw_before': raw_before, 'raw_after': raw_after,
                     'fingerprint': protected, 'started': time.time(), 'previous_record': prior_record,
                     'planned_changes': [item['id'] for item in plan], 'result': result}
            write_json(journal, value)
            current_change = selected
            self.phase = 'selecting'
            self.restart()
            if read_text(path) != raw_before or fingerprint(self.home) != protected:
                raise ValueError('Assistant files changed before the leading idea could be put on trial')
            write_text(path, raw_after)
            self.start_assistant()
            if read_text(path) != raw_after or fingerprint(self.home) != protected:
                raise ValueError('The leading idea could not be verified on the assistant')
            result['opinion'] = self.reflect(result, model)
            value.update(phase='awaiting-decision', result=result)
            write_json(journal, value)
            self.message = 'I tried the reviewed ideas against the same questions. Review the comparison, then choose what stays.'
            return 'awaiting-decision'
        except Exception:
            if journal.exists():
                self.phase = 'restoring'
                self.restart()
                current = read_text(path)
                if current not in (raw_after, raw_before) or fingerprint(self.home) != protected:
                    self.message = 'Owner edits prevent automatic recovery. The assistant is stopped; review the retained trial record.'
                    return 'recovery-blocked'
                if current != raw_before:
                    write_text(path, raw_before)
                self.start_assistant()
                if read_text(path) != raw_before or fingerprint(self.home) != protected:
                    raise ValueError('Restoration verification failed')
                finish_journal(journal)
            elif not self.startup.snapshot().get('active') and fingerprint(self.home) == protected:
                self.start_assistant()
            self.message = 'The run stopped. The original instructions were restored and verified.'
            return 'cancelled' if self.cancel_event.is_set() else 'rolled-back'

    def execute_restore(self, value):
        path = agents_path(self.home)
        journal, record = paths(self.home)
        if fingerprint(self.home) != value.get('fingerprint'):
            raise Refused('Protected assistant files changed; review before restoring')
        # Keep a recovery journal even when restoring a previously kept change.
        recovery = {**value, 'schema': SCHEMA, 'phase': 'restoring'}
        write_json(journal, recovery)
        self.restart()
        if read_text(path) != value['raw_after'] or fingerprint(self.home) != value['fingerprint']:
            self.message = 'Owner edits prevent automatic restore. The assistant is stopped; review the retained trial record.'
            return 'recovery-blocked'
        write_text(path, value['raw_before'])
        self.start_assistant()
        if read_text(path) != value['raw_before'] or fingerprint(self.home) != value['fingerprint']:
            raise ValueError('Restore could not be verified')
        previous = value.get('previous_record')
        if previous is not None:
            write_json(record, previous)
        elif record.exists():
            finish_journal(record)
        if journal.exists():
            finish_journal(journal)
        self.message = 'Restored and verified: AGENTS.md is byte-for-byte the original.'
        return 'restored'
