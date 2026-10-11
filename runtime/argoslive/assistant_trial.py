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
CHANGE_ID, CHANGE_VERSION = 'grounded-answers', 1
START = '<!-- argos-trial:grounded-answers v1 — added with your approval; Argos Live can restore the original file -->'
END = '<!-- /argos-trial:grounded-answers -->'
INSTRUCTION = ('## Answering from text you were given\n'
               'When I give you a document, notice or passage and ask about it: answer directly first, in a short '
               'phrase or sentence. Then quote the sentence from the text that supports your answer. If the text does '
               'not contain the answer, say so plainly instead of guessing.')
BLOCK = f'{START}\n{INSTRUCTION}\n{END}\n'
PROTECTED = ('SOUL.md', 'IDENTITY.md', 'USER.md', 'MEMORY.md')
CHANGE = {'id': CHANGE_ID, 'version': CHANGE_VERSION, 'title': 'Grounded answers', 'file': 'AGENTS.md',
          'text': INSTRUCTION,
          'scope': 'Questions about text you give the assistant in chat.',
          'unchanged': ['Model and its files', 'Personality (SOUL.md, IDENTITY.md, USER.md) and memory',
                        'Tools, permissions and channels', 'Argos and OpenClaw settings']}
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
            'suggestion': suggestion, 'uncertainty': UNCERTAINTY, 'evidence': 'everyday-assistant'}


def opinion_prompt(result):
    """Ask the tested assistant to reflect on public aggregates, never raw replies."""
    totals = result['totals']
    facts = {
        'challenges': {'improved': len(result['gains']), 'worse': len(result['regressions']),
                       'unchanged': len(result['rows']) - len(result['gains']) - len(result['regressions'])},
        'checks': {kind: {'before': values['before'], 'after': values['after'], 'out_of': values['total']}
                   for kind, values in totals.items()},
    }
    return (OPINION_PREFIX +
            'You are the local assistant taking part in a small, private improvement test. In at most two short '
            'first-person sentences, say what these counts suggest and one thing you would like to investigate '
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


def staged(raw_before):
    if raw_before is not None and 'argos-trial:grounded-answers' in raw_before:
        raise ValueError('The change is already present in AGENTS.md')
    text = raw_before or ''
    if text and not text.endswith('\n'):
        text += '\n'
    return text + ('\n' if text else '') + BLOCK


def write_text(path, text):
    if text is None:
        path.unlink(missing_ok=True)
    else:
        replace_raw(path, text.encode('utf-8'))


def valid_record(value, schema):
    try:
        return (value.get('schema') == schema and value.get('change') == CHANGE_ID and
                value.get('version') == CHANGE_VERSION and
                (value.get('raw_before') is None or isinstance(value.get('raw_before'), str)) and
                value.get('raw_after') == staged(value.get('raw_before')) and
                isinstance(value.get('fingerprint'), dict))
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
        if record.exists():
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
            result = (value or {}).get('result')
            tasks = [{k: t[k] for k in ('id', 'kind', 'question', 'message', 'passage') if k in t} for t in self.tasks['tasks']]
            return {'available': True, 'active': active, 'phase': self.phase, 'progress': copy.deepcopy(self.progress),
                    'message': self.message, 'status': status, 'change': CHANGE, 'tasks': tasks,
                    'passages': self.tasks['passages'], 'result': result,
                    'can_restore': status in ('on-trial', 'kept'), 'can_keep': status == 'on-trial'}

    # ---- actions
    def start(self):
        with self.startup.lock, self.lock:
            self.require_idle()
            status, _ = self.status()
            if status != 'none':
                raise Refused('A change is already on trial or kept; restore it first')
            self.begin('starting', self.execute)
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
            write_json(record, {'schema': RECORD_SCHEMA, 'change': CHANGE_ID, 'version': CHANGE_VERSION,
                                'raw_before': value['raw_before'], 'raw_after': value['raw_after'],
                                'fingerprint': value['fingerprint'],
                                'agents_sha256': digest(path), 'kept_at': time.time(), 'result': value['result']})
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

    def run_tasks(self, side):
        outcomes, total, latest = [], len(self.tasks['tasks']), None
        for index, task in enumerate(self.tasks['tasks']):
            if self.cancel_event.is_set():
                raise ValueError('Cancelled')
            current = {'id': task['id'], 'kind': task['kind'],
                       'question': task.get('question') or task.get('message'),
                       'source': self.tasks['passages'].get(task.get('passage'))}
            self.progress = {'side': side, 'done': index, 'total': total,
                             'current': current, 'latest': latest}
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
                             'current': current, 'latest': latest}
        self.progress = {'side': side, 'done': total, 'total': total, 'current': None, 'latest': latest}
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

    def execute(self):
        try:
            _, model = self.validate_profile(self.home)
        except Exception:
            self.message = 'The reviewed local assistant profile could not be verified. No change was made.'
            raise
        if isinstance(self.runner, OpenClawRunner):
            self.runner.expected_model = model
        path = agents_path(self.home)
        raw_before = read_text(path)
        raw_after = staged(raw_before)
        config = read_json(storage.safe_local(self.home / '.openclaw/openclaw.json'))
        limit = config.get('agents', {}).get('defaults', {}).get('bootstrapMaxChars', 20000)
        if not isinstance(limit, int) or len(raw_after) > limit:
            self.message = 'AGENTS.md would exceed the assistant’s bootstrap limit. No change was made.'
            raise ValueError('Bootstrap instructions would be truncated')
        protected = fingerprint(self.home)
        self.phase = 'before'
        try:
            before = self.run_tasks('before')
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
        journal, _ = paths(self.home)
        write_json(journal, {'schema': SCHEMA, 'phase': 'staging', 'change': CHANGE_ID, 'version': CHANGE_VERSION,
                             'raw_before': raw_before, 'raw_after': raw_after, 'fingerprint': protected,
                             'started': time.time()})
        try:
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
            self.phase = 'after'
            after = self.run_tasks('after')
            if read_text(path) != raw_after or fingerprint(self.home) != protected:
                raise ValueError('Assistant files changed during the trial')
            value = read_json(journal)
            result = compare(before, after)
            result['configuration'] = {'model': model, 'tasks_version': self.tasks['version'],
                                       'tasks_sha256': hashlib.sha256(json.dumps(self.tasks, sort_keys=True).encode()).hexdigest(),
                                       'instruction_sha256': hashlib.sha256(BLOCK.encode()).hexdigest(),
                                       'profile_sha256': protected['openclaw.json']}
            result['opinion'] = self.reflect(result, model)
            value.update(phase='awaiting-decision', result=result)
            write_json(journal, value)
            self.message = 'The run is finished. Review the scorecard and your AI’s opinion, then choose what stays.'
            return 'awaiting-decision'
        except Exception:
            self.phase = 'restoring'
            self.restart()
            if read_text(path) not in (raw_after, raw_before) or fingerprint(self.home) != protected:
                self.message = 'Owner edits prevent automatic recovery. The assistant is stopped; review the retained trial record.'
                return 'recovery-blocked'
            write_text(path, raw_before)
            self.start_assistant()
            if read_text(path) != raw_before or fingerprint(self.home) != protected:
                raise ValueError('Restoration verification failed')
            finish_journal(journal)
            self.message = 'The trial stopped and the original AGENTS.md was restored.'
            return 'cancelled' if self.cancel_event.is_set() else 'rolled-back'

    def execute_restore(self, value):
        path = agents_path(self.home)
        journal, record = paths(self.home)
        if fingerprint(self.home) != value.get('fingerprint'):
            raise Refused('Protected assistant files changed; review before restoring')
        # Keep a recovery journal even when restoring a previously kept change.
        recovery = {**value, 'schema': SCHEMA, 'phase': 'restoring',
                    'change': CHANGE_ID, 'version': CHANGE_VERSION}
        write_json(journal, recovery)
        self.restart()
        if read_text(path) != value['raw_after'] or fingerprint(self.home) != value['fingerprint']:
            self.message = 'Owner edits prevent automatic restore. The assistant is stopped; review the retained trial record.'
            return 'recovery-blocked'
        write_text(path, value['raw_before'])
        self.start_assistant()
        if read_text(path) != value['raw_before'] or fingerprint(self.home) != value['fingerprint']:
            raise ValueError('Restore could not be verified')
        for file in (journal, record):
            if file.exists():
                finish_journal(file)
        self.message = 'Restored and verified: AGENTS.md is byte-for-byte the original.'
        return 'restored'
