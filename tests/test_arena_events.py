import contextlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))

from argoslive import lab, bench_ability, bench_speed
from argoslive.results import Store
from argoslive.ollama import Cancelled
from argoslive.web.server import DashboardServer
from test_bench_speed import Backend
from test_results import ability_result


class StreamingBackend(Backend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stream_chunks = ['Answer ', 'is ', '42']

    def generate(self, model, prompt, **kwargs):
        callback = kwargs.get('callback')
        if prompt and callback:
            for chunk in self.stream_chunks:
                callback({'response': chunk})
        res = super().generate(model, prompt, **kwargs)
        if prompt:
            res['text'] = ''.join(self.stream_chunks)
        return res


class Assistant:
    def __init__(self, home, active=True):
        self.home, self.active = home, active
        self.lock = threading.RLock()
        self.lab_active = False
        self.calls = []
        self.chat_claimed = False

    def snapshot(self):
        return {'active': self.active}

    def stop(self):
        self.calls.append('pause')
        self.active = False

    def start(self):
        assert not self.lab_active
        self.calls.append('resume')
        self.active = True

    def resolve_source(self, home):
        self.calls.append('resolve')
        return home / 'models', 'fixture:latest'

    @contextlib.contextmanager
    def backend(self, target, **options):
        self.calls.append('backend-start')
        try:
            yield StreamingBackend()
        finally:
            self.calls.append('backend-stop')


class ArenaEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.assistant = Assistant(Path(self.temp.name))
        self.store = Store(Path(self.temp.name) / 'results')
        self.lab = lab.Controller(self.assistant, store=self.store,
            speed=lambda client, model, **kw: bench_speed.run(client, model, hardware=lambda: {}, **kw),
            ability=lambda client, model, **kw: bench_ability.run(client, model, hardware=lambda: {}, **kw))
        self.addCleanup(self.lab.close)

    def finish(self, timeout=8):
        if self.lab.worker:
            self.lab.worker.join(timeout=timeout)
            self.assertFalse(self.lab.worker.is_alive())

    def test_events_emission_sequencing_and_schema(self):
        with patch.object(lab.mission_report, 'debrief', return_value={'state': 'unavailable'}):
            self.lab.start('baseline')
            self.finish()

        val = self.lab.snapshot()
        self.assertEqual(val['phase'], 'completed')
        self.assertIsNotNone(val['run_id'])
        self.assertGreater(val['seq'], 0)
        self.assertIsNotNone(val['arena'])

        events_res = self.lab.events_after(0)
        self.assertFalse(events_res['reset'])
        self.assertFalse(events_res['gap'])
        self.assertEqual(events_res['run_id'], val['run_id'])
        events = events_res['events']
        self.assertTrue(len(events) > 10)

        # Check strictly increasing sequences starting at 1
        seqs = [e['seq'] for e in events]
        self.assertEqual(seqs, list(range(1, len(events) + 1)))

        event_types = {e['type'] for e in events}
        self.assertIn('phase', event_types)
        self.assertIn('item-start', event_types)
        self.assertIn('answer-delta', event_types)
        self.assertIn('item-scored', event_types)
        self.assertIn('final', event_types)

        # Validate item-start schema
        item_starts = [e for e in events if e['type'] == 'item-start']
        self.assertEqual(len(item_starts), 20)
        for s in item_starts:
            self.assertIn('item_id', s)
            self.assertIn('prompt', s)
            self.assertIn('category', s)
            self.assertIn('completed', s)
            self.assertIn('total', s)
            self.assertIn('elapsed_seconds', s)

        # Validate answer-delta schema
        deltas = [e for e in events if e['type'] == 'answer-delta']
        self.assertTrue(len(deltas) > 0)
        for d in deltas:
            self.assertIn('item_id', d)
            self.assertIn('delta', d)
            self.assertIsInstance(d['delta'], str)
            self.assertTrue(len(d['delta']) > 0)

        # Validate item-scored schema
        scored = [e for e in events if e['type'] == 'item-scored']
        self.assertEqual(len(scored), 20)
        for sc in scored:
            self.assertIn('item_id', sc)
            self.assertIn('receipt', sc)
            r = sc['receipt']
            self.assertIn('score', r)
            self.assertIn('outcome', r)
            self.assertIn('format_valid', r)
            self.assertIn('output', r)
            self.assertIn('latency_seconds', r)

        # Validate final event
        finals = [e for e in events if e['type'] == 'final']
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]['outcome'], 'completed')
        self.assertEqual(finals[0]['completed'], 20)
        self.assertEqual(finals[0]['total'], 20)

    def test_buffer_bounds_and_gap_detection(self):
        self.lab.start('baseline')
        # Inject more events than MAX_EVENTS
        for i in range(1300):
            self.lab.add_event('answer-delta', item_id='item-01', delta='token')

        self.assertEqual(len(self.lab.events), lab.MAX_EVENTS)
        self.assertGreater(self.lab.first_seq, 100)

        # If client asks for after_seq=1, it missed events before first_seq -> gap detected
        res = self.lab.events_after(after_seq=1)
        self.assertTrue(res['gap'])
        self.assertEqual(len(res['events']), lab.MAX_EVENTS)

        # If client asks for after_seq >= first_seq - 1 -> no gap
        res_recent = self.lab.events_after(after_seq=self.lab.first_seq + 10)
        self.assertFalse(res_recent['gap'])
        self.assertEqual(res_recent['events'][0]['seq'], self.lab.first_seq + 11)
        self.lab.cancel()
        self.finish()

    def test_stale_run_isolation_returns_reset(self):
        self.lab.start('baseline')
        current_run_id = self.lab.run_id

        # Query with wrong / stale run_id
        res = self.lab.events_after(after_seq=5, run_id='stale-run-id-999')
        self.assertTrue(res['reset'])
        self.assertEqual(res['run_id'], current_run_id)
        self.assertIsNotNone(res['arena'])

        # Query with matching run_id
        res_ok = self.lab.events_after(after_seq=0, run_id=current_run_id)
        self.assertFalse(res_ok['reset'])
        self.lab.cancel()
        self.finish()

    def test_safe_reconnect_without_restarting(self):
        running_event = threading.Event()
        def paused_ability(client, model, cancel=None, progress=None, **kw):
            if progress:
                progress({'phase': 'generating', 'item_id': 'num-01', 'prompt': 'Calculate 2+2',
                          'category': 'numeric', 'completed': 0, 'total': 20, 'elapsed_seconds': 0.5})
                progress({'phase': 'answer-delta', 'item_id': 'num-01', 'delta': '4', 'elapsed_seconds': 0.6})
                progress({'phase': 'scored', 'item_id': 'num-01', 'category': 'numeric',
                          'receipt': {'item_id': 'num-01', 'score': 1, 'outcome': 'pass', 'format_valid': True,
                                      'output': '4', 'latency_seconds': 0.2},
                          'completed': 1, 'total': 20, 'elapsed_seconds': 0.7})
            running_event.set()
            # simulate running until cancelled
            while not cancel.is_set():
                time.sleep(0.02)
            raise Cancelled('Finished waiting')

        self.lab.ability = paused_ability
        self.lab.start('baseline')

        self.assertTrue(running_event.wait(5))

        # First connection: get snapshot
        snap1 = self.lab.snapshot()
        self.assertTrue(snap1['active'])
        self.assertEqual(snap1['arena']['completed'], 1)
        self.assertEqual(len(snap1['arena']['receipts']), 1)
        cursor1 = snap1['seq']

        # Reconnect (e.g. page refresh): fetch snapshot again
        snap2 = self.lab.snapshot()
        self.assertTrue(snap2['active'])
        self.assertEqual(snap2['run_id'], snap1['run_id'])
        self.assertEqual(snap2['arena']['receipts'][0]['item_id'], 'num-01')

        # Incremental events after cursor
        events_inc = self.lab.events_after(after_seq=cursor1, run_id=snap1['run_id'])
        self.assertFalse(events_inc['reset'])
        self.assertFalse(events_inc['gap'])

        # Cancel cleanly
        self.lab.cancel()
        self.finish()

    def test_cancellation_marks_partial_results_incomplete(self):
        entered = threading.Event()
        def running_ability(client, model, cancel=None, progress=None, **kw):
            if progress:
                progress({'phase': 'generating', 'item_id': 'item-01', 'prompt': 'Q1',
                          'category': 'numeric', 'completed': 0, 'total': 20, 'elapsed_seconds': 0.1})
                progress({'phase': 'scored', 'item_id': 'item-01', 'category': 'numeric',
                          'receipt': {'item_id': 'item-01', 'score': 1, 'outcome': 'pass', 'format_valid': True,
                                      'output': 'Ans', 'latency_seconds': 0.1},
                          'completed': 1, 'total': 20, 'elapsed_seconds': 0.2})
            entered.set()
            while not cancel.is_set():
                time.sleep(0.01)
            raise Cancelled('Stopped by owner')

        self.lab.ability = running_ability
        self.lab.start('baseline')
        self.assertTrue(entered.wait(5))

        self.lab.cancel()
        self.finish()

        snap = self.lab.snapshot()
        self.assertEqual(snap['phase'], 'cancelled')
        self.assertFalse(snap['active'])
        self.assertEqual(snap['arena']['phase'], 'cancelled')
        self.assertEqual(len(snap['arena']['receipts']), 1)
        self.assertEqual(snap['arena']['completed'], 1)
        self.assertEqual(snap['arena']['total'], 20)

        events = self.lab.events_after(0)['events']
        final_events = [e for e in events if e['type'] == 'final']
        self.assertEqual(len(final_events), 1)
        self.assertEqual(final_events[0]['outcome'], 'cancelled')
        self.assertEqual(final_events[0]['completed'], 1)

    def test_task_plan_privacy_exclusion(self):
        doc = "Secret owner internal document with sensitive credentials"
        question = "What are the credentials?"
        with patch.object(lab.doc_trial, 'ask', return_value={'status': 'answered', 'answer': '42', 'quote': ''}):
            self.lab.task_input = (doc, question)
            self.lab.start('task')
            self.finish()

        snap = self.lab.snapshot()
        self.assertEqual(snap['phase'], 'completed')
        # Ensure private doc text is not in events or arena
        events_str = str(self.lab.events)
        self.assertNotIn("Secret owner internal document", events_str)
        self.assertNotIn("What are the credentials?", events_str)
        arena_str = str(self.lab.arena)
        self.assertNotIn("Secret owner internal document", arena_str)
        self.assertNotIn("What are the credentials?", arena_str)

    def test_events_http_route(self):
        import http.client
        with DashboardServer(port=0, lab=self.lab) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            def get(path, headers=None):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                try:
                    conn.request('GET', path, headers=headers or {})
                    res = conn.getresponse()
                    body = res.read()
                    return res.status, json.loads(body.decode('utf-8'))
                finally: conn.close()
            try:
                auth = {'X-Argos-Token': server.token}
                # Unauthenticated returns 403
                status, _ = get('/api/lab/events')
                self.assertEqual(status, 403)

                # Authenticated returns event response
                status, data = get('/api/lab/events', headers=auth)
                self.assertEqual(status, 200)
                self.assertIn('events', data)
                self.assertIn('cursor', data)

                # Query with params
                status, data2 = get('/api/lab/events?after=0', headers=auth)
                self.assertEqual(status, 200)
                self.assertIn('events', data2)
            finally:
                server.shutdown()
                worker.join(3)

    def test_documents_plan_streams_and_records_receipts(self):
        from test_doc_trial import DocBackend
        from argoslive import doc_trial
        backend = DocBackend()
        @contextlib.contextmanager
        def provide(target, **options):
            self.assistant.calls.append('backend-start')
            try:
                yield backend
            finally:
                self.assistant.calls.append('backend-stop')
        self.assistant.backend = provide
        self.lab.documents = lambda client, model, **kw: doc_trial.run(client, 'fixture:latest', hardware=lambda: {}, **kw)
        self.lab.speed = lambda client, model, **kw: bench_speed.run(client, 'fixture:latest', hardware=lambda: {}, **kw)
        self.lab.start_documents()
        self.finish()

        snap = self.lab.snapshot()
        self.assertEqual(snap['phase'], 'completed')
        self.assertEqual(snap['plan'], 'documents')
        self.assertIsNotNone(snap['arena'])
        self.assertTrue(len(snap['arena']['receipts']) > 0)
        events = self.lab.events_after(0)['events']
        item_starts = [e for e in events if e['type'] == 'item-start']
        self.assertTrue(len(item_starts) > 0)

    def test_adversarial_output_bounded_and_cleaned(self):
        huge_text = "<script>alert('xss')</script>" * 200
        def ability_adversarial(client, model, cancel=None, progress=None, **kw):
            if progress:
                progress({'phase': 'generating', 'item_id': 'adv-01', 'prompt': 'Q',
                          'category': 'instruction', 'completed': 0, 'total': 1, 'elapsed_seconds': 0.1})
                progress({'phase': 'answer-delta', 'item_id': 'adv-01', 'delta': huge_text, 'elapsed_seconds': 0.2})
                progress({'phase': 'scored', 'item_id': 'adv-01', 'category': 'instruction',
                          'receipt': {'item_id': 'adv-01', 'score': 0, 'outcome': 'wrong_answer',
                                      'format_valid': True, 'output': huge_text, 'latency_seconds': 0.2},
                          'completed': 1, 'total': 1, 'elapsed_seconds': 0.3})
            return ability_result()

        self.lab.ability = ability_adversarial
        self.lab.start('baseline')
        self.finish()

        events = self.lab.events_after(0)['events']
        deltas = [e for e in events if e['type'] == 'answer-delta']
        self.assertTrue(len(deltas) > 0)
        # Delta bounded to 1024 and explicitly marked truncated
        self.assertLessEqual(len(deltas[0]['delta']), 1024)
        self.assertTrue(deltas[0].get('truncated'))

        scored = [e for e in events if e['type'] == 'item-scored']
        self.assertTrue(len(scored) > 0)
        # Receipt output bounded to 500 and explicitly marked truncated
        self.assertLessEqual(len(scored[0]['receipt']['output']), 500)
        self.assertTrue(scored[0]['receipt'].get('output_truncated'))
        self.assertTrue(scored[0]['receipt']['output'].endswith('[truncated]'))


if __name__ == '__main__':
    unittest.main()
