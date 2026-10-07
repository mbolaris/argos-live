"""Desktop-owned quick baseline: pause chat, test fixed prompts, save, resume."""
import copy
import secrets
import threading
import time

from . import bench_ability, bench_speed, doc_trial, mission_report
from .ollama import Cancelled
from .results import Store


# Each plan lists (phase, runner attribute, options). Plans are fixed so a later
# run of the same plan on another model is a matched, comparable measurement.
PLANS = {'baseline': (('speed', 'speed', {'sizes': ('short',)}), ('ability', 'ability', {'suite': 'quick'})),
         'documents': (('speed', 'speed', {'sizes': ('short', 'medium')}), ('documents', 'documents', {})),
         # The owner's own pasted document. Its text and the answer stay in memory and are never saved.
         'task': (('task', 'task', {}),)}

MAX_EVENTS = 1200


class Controller:
    budget_seconds = 900

    def __init__(self, startup, *, store=None, clock=time.monotonic,
                 speed=bench_speed.run, ability=bench_ability.run, documents=doc_trial.run):
        self.startup = startup
        self.store = store or Store(startup.home / '.local/share/argos-live/results')
        self.clock, self.speed, self.ability, self.documents = clock, speed, ability, documents
        self.plan = 'baseline'
        self.task_input = None
        self.task_result = None
        self.debrief = None
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.worker = None
        self.phase = 'idle'
        self.progress = None
        self.runs = []
        self.started = None
        self.finished = None
        self.model = None
        self.resume = False
        self.resume_requested = False
        self.closed = False
        self.run_id = None
        self.events = []
        self.first_seq = 1
        self.next_seq = 1
        self.arena = None

    def add_event(self, event_type, **data):
        with self.lock:
            seq = self.next_seq
            self.next_seq += 1
            event = {'seq': seq, 'type': event_type, **data}
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                self.events.pop(0)
                self.first_seq = self.events[0]['seq']
            return event

    def events_after(self, after_seq=0, run_id=None):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            phase = 'cancelling' if active and self.cancel_event.is_set() else self.phase
            if run_id is not None and run_id != self.run_id:
                return {
                    'run_id': self.run_id,
                    'active': active,
                    'phase': phase,
                    'reset': True,
                    'gap': False,
                    'cursor': self.next_seq - 1,
                    'events': list(self.events),
                    'arena': copy.deepcopy(self.arena),
                }
            gap = False
            if self.events and after_seq < self.first_seq - 1:
                gap = True
                events = list(self.events)
            else:
                events = [e for e in self.events if e['seq'] > after_seq]
            return {
                'run_id': self.run_id,
                'active': active,
                'phase': phase,
                'reset': False,
                'gap': gap,
                'cursor': self.next_seq - 1,
                'events': events,
                'arena': copy.deepcopy(self.arena),
            }

    def snapshot(self):
        with self.lock:
            active = self.worker is not None and self.worker.is_alive()
            return {'available': not self.closed, 'active': active,
                    'phase': 'cancelling' if active and self.cancel_event.is_set() else self.phase,
                    'model': self.model, 'plan': self.plan, 'progress': copy.deepcopy(self.progress),
                    'runs': list(self.runs), 'debrief': copy.deepcopy(self.debrief), 'task': copy.deepcopy(self.task_result), 'resume_requested': self.resume_requested,
                    'run_id': self.run_id,
                    'seq': self.next_seq - 1,
                    'arena': copy.deepcopy(self.arena),
                    'elapsed_seconds': max(0, (self.finished if self.finished is not None else self.clock()) - self.started)
                    if self.started is not None else None}

    def start(self, plan='baseline'):
        # Share startup's reservation: chat cannot restart into a benchmark.
        if plan not in PLANS:
            raise ValueError('Unknown model lab plan')
        with self.startup.lock, self.lock:
            if self.closed:
                raise ValueError('The model lab is closed')
            if self.snapshot()['active'] or self.startup.lab_active:
                raise ValueError('Another desktop workload is already active')
            status = self.startup.snapshot()
            self.resume = status['active']
            self.startup.lab_active = True
            self.startup.stop()
            self.plan = plan
            self.cancel_event.clear()
            self.phase, self.started = 'pausing', self.clock()
            self.finished = None
            self.progress, self.runs, self.model = None, [], None
            self.debrief = None
            self.resume_requested = False
            self.run_id = secrets.token_hex(16)
            self.events = []
            self.first_seq = 1
            self.next_seq = 1
            self.arena = {
                'run_id': self.run_id,
                'plan': plan,
                'model': None,
                'phase': 'pausing',
                'current_item': None,
                'receipts': [],
                'completed': 0,
                'total': 0,
                'correct': 0,
                'format_errors': 0,
                'elapsed_seconds': 0,
            }
            self.add_event('phase', phase='pausing', plan=plan, model=None, elapsed_seconds=0)
            self.worker = threading.Thread(target=self.run, daemon=True, name='argos-model-lab')
            self.worker.start()
            return self.snapshot()

    def start_documents(self):
        return self.start('documents')

    def start_task(self, document, question):
        if (not isinstance(document, str) or not document.strip() or len(document) > doc_trial.TASK_DOCUMENT_LIMIT
                or not isinstance(question, str) or not question.strip() or len(question) > doc_trial.TASK_QUESTION_LIMIT):
            raise ValueError('Paste a document and ask a question within the stated limits')
        with self.lock:
            self.task_input = (document, question)
            self.task_result = None
        try:
            return self.start('task')
        except ValueError:
            with self.lock:
                self.task_input = None
            raise

    def task(self, client, model, *, cancel=None, progress=None):
        document, question = self.task_input
        answer = doc_trial.ask(client, model, document, question, cancel=cancel)
        answer['task_id'] = secrets.token_hex(16)
        with self.lock:
            self.task_result = answer
        return answer

    def clear_task(self):
        with self.lock:
            if not self.snapshot()['active']:
                self.task_input = self.task_result = None

    def cancel(self):
        with self.lock:
            if self.snapshot()['active']:
                self.cancel_event.set()
                self.phase = 'cancelling'
                elapsed = max(0, (self.clock() - self.started)) if self.started is not None else 0
                if self.arena:
                    self.arena['phase'] = 'cancelling'
                self.add_event('phase', phase='cancelling', plan=self.plan, model=self.model, elapsed_seconds=elapsed)
            return self.snapshot()

    def report(self, phase, value=None):
        with self.lock:
            if not self.cancel_event.is_set():
                self.phase, self.progress = phase, copy.deepcopy(value)
                elapsed = max(0, (self.finished if self.finished is not None else self.clock()) - self.started) if self.started is not None else 0
                if self.arena:
                    self.arena['phase'] = phase
                    self.arena['model'] = self.model
                    self.arena['elapsed_seconds'] = elapsed

                if isinstance(value, dict):
                    vphase = value.get('phase')
                    if vphase == 'generating' and self.plan != 'task':
                        item_id = value.get('item_id')
                        prompt = value.get('prompt', '')
                        cat = value.get('category', '')
                        completed = value.get('completed', 0)
                        total = value.get('total', 0)
                        if self.arena:
                            self.arena['current_item'] = {
                                'item_id': item_id,
                                'prompt': prompt[:2048] if isinstance(prompt, str) else '',
                                'category': cat or '',
                                'answer': '',
                            }
                            self.arena['completed'] = completed
                            self.arena['total'] = total
                        self.add_event('item-start', item_id=item_id,
                                       prompt=prompt[:2048] if isinstance(prompt, str) else '',
                                       category=cat or '', completed=completed, total=total,
                                       elapsed_seconds=elapsed, eta_seconds=value.get('eta_seconds'))
                    elif vphase == 'answer-delta' and self.plan != 'task':
                        item_id = value.get('item_id')
                        delta = value.get('delta', '')
                        if isinstance(delta, str) and delta:
                            delta = delta[:1024]
                            if self.arena and self.arena.get('current_item') and self.arena['current_item'].get('item_id') == item_id:
                                if len(self.arena['current_item']['answer']) < 8192:
                                    self.arena['current_item']['answer'] += delta
                            self.add_event('answer-delta', item_id=item_id, delta=delta)
                    elif vphase == 'scored' and self.plan != 'task':
                        item_id = value.get('item_id')
                        receipt = value.get('receipt', {})
                        clean_receipt = {
                            'item_id': item_id,
                            'category': value.get('category') or receipt.get('category', ''),
                            'score': receipt.get('score'),
                            'outcome': receipt.get('outcome', 'unscored'),
                            'format_valid': receipt.get('format_valid'),
                            'latency_seconds': receipt.get('latency_seconds'),
                            'output': (receipt.get('output') or '')[:500] if isinstance(receipt.get('output'), str) else '',
                        }
                        if self.arena:
                            self.arena['receipts'].append(clean_receipt)
                            self.arena['completed'] = value.get('completed', len(self.arena['receipts']))
                            self.arena['total'] = value.get('total', self.arena['total'])
                            if clean_receipt['score'] == 1:
                                self.arena['correct'] += 1
                            if clean_receipt['outcome'] == 'format_error':
                                self.arena['format_errors'] += 1
                        self.add_event('item-scored', item_id=item_id, receipt=clean_receipt,
                                       completed=value.get('completed', 0), total=value.get('total', 0),
                                       elapsed_seconds=elapsed, eta_seconds=value.get('eta_seconds'))
                    elif vphase not in ('completed', 'cancelled', 'failed'):
                        self.add_event('phase', phase=phase, plan=self.plan, model=self.model, elapsed_seconds=elapsed)
                else:
                    self.add_event('phase', phase=phase, plan=self.plan, model=self.model, elapsed_seconds=elapsed)

    def run(self):
        timer = threading.Timer(self.budget_seconds, self.cancel)
        timer.daemon = True
        timer.start()
        outcome = 'failed'
        try:
            deadline = self.clock() + 180
            while self.startup.snapshot()['active']:
                if self.cancel_event.wait(.1):
                    raise Cancelled('Cancelled while pausing')
                if self.clock() >= deadline:
                    raise ValueError('Assistant did not release resources')
            if self.cancel_event.is_set():
                raise Cancelled('Cancelled before benchmark')
            outcome = self.execute()
        except Exception:
            # Never export private configuration paths or exception text to HTTP.
            outcome = self.failure_outcome()
            try:
                self.settle_unstarted()
            except (ValueError, OSError):
                pass
        finally:
            timer.cancel()
            with self.startup.lock, self.lock:
                self.startup.lab_active = False
                if self.resume:
                    try:
                        self.startup.start()
                        # Keep the lab visible; the owner can choose Open chat.
                        self.startup.chat_claimed = True
                        self.resume_requested = True
                    except (ValueError, OSError):
                        outcome = 'failed'
            with self.lock:
                self.phase = outcome
                self.finished = self.clock()
                elapsed = max(0, self.finished - self.started) if self.started is not None else 0
                if self.arena:
                    self.arena['phase'] = outcome
                    self.arena['elapsed_seconds'] = elapsed
                    self.add_event('final', outcome=outcome, plan=self.plan, model=self.model,
                                   completed=self.arena.get('completed', 0),
                                   total=self.arena.get('total', 0),
                                   correct=self.arena.get('correct', 0),
                                   format_errors=self.arena.get('format_errors', 0),
                                   elapsed_seconds=elapsed, runs=list(self.runs))

    def execute(self):
        target, model = self.startup.resolve_source(self.startup.home)
        with self.lock:
            self.model = model
            if self.arena:
                self.arena['model'] = model
        self.report('model-service')
        lease = self.startup.home / '.local/state/argos-live'
        with self.startup.backend(target, lease_store=lease, cancel=self.cancel_event.is_set) as client:
            client.timeout = 120
            measured = []
            for phase, name, options in PLANS[self.plan]:
                runner = getattr(self, name)
                if self.cancel_event.is_set():
                    raise Cancelled('Cancelled between tests')
                self.report(phase)
                result = runner(client, model, cancel=self.cancel_event,
                                progress=lambda value, phase=phase: self.report(phase, value), **options)
                if name != 'task':
                    self.store.save(result)
                    measured.append(result)
                    with self.lock:
                        self.runs.append(result['id'])
            if self.plan != 'task' and not self.cancel_event.is_set():
                self.report('debrief')
                opinion = mission_report.debrief(client, model, measured, cancel=self.cancel_event)
                with self.lock:
                    self.debrief = opinion
        return 'cancelled' if self.cancel_event.is_set() else 'completed'

    def settle_unstarted(self):
        """Specialized workloads may settle a receipt without backend startup."""
        pass

    def failure_outcome(self):
        return 'cancelled' if self.cancel_event.is_set() else 'failed'

    def close(self):
        with self.lock:
            self.closed = True
            self.resume = False
            self.cancel()
            worker = self.worker
        if worker:
            worker.join(timeout=200)
