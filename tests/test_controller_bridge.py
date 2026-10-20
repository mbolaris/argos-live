import json
import os
from pathlib import Path
import sys
import socket
import threading
import time
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import controller_bridge, workload
from argoslive.results import Store
from test_bench_openclaw import configure_fake


class ControllerBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        configure_fake(self.home, workspace)

    def begin(self, bridge):
        request = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'framework-run',
                   'session_id': 'framework-session', 'session_key': 'agent:main:host-session', 'trigger': 'user'}
        value = bridge.dispatch(request)
        return request, {'auth': bridge.secret, 'run_id': request['run_id'], 'turn_token': value['turn_token']}

    def test_host_identity_and_secret_are_required_before_admission(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            base = {'auth': bridge.secret, 'op': 'begin', 'run_id': 'framework-run',
                    'session_id': 'framework-session', 'session_key': 'agent:main:host-session', 'trigger': 'user'}
            for changes in ({'auth': 'wrong'}, {'session_key': 'agent:main:unrelated'}, {'trigger': 'heartbeat'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    bridge.dispatch({**base, **changes})
            self.assertIsNone(bridge.active)
            self.assertFalse(bridge.events.exists())
            parent.complete()  # No SDK worker or inference was started in this fixture.

    def test_end_hook_and_client_completion_claim_never_release_parent(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            request, turn = self.begin(bridge)
            self.assertEqual(bridge.dispatch(request)['turn_token'], turn['turn_token'])
            bridge.dispatch({**turn, 'op': 'ended'})
            for claim in ({**turn, 'op': 'complete', 'worker_exited': True},
                          {**request, 'run_id': 'next-run'}):
                with self.assertRaises(ValueError):
                    bridge.dispatch(claim)
            with self.assertRaises(workload.Busy):
                bridge._complete()
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'proctor'):
                    self.fail('SDK end event released the controller slot')
            saved = bridge.events.read_text()
            self.assertNotIn(bridge.secret, saved)
            self.assertNotIn(turn['turn_token'], saved)

    def test_stale_turn_and_unknown_tools_cannot_dispatch(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            tool = {**turn, 'op': 'tool', 'call_id': 'call-1', 'kind': 'log', 'params': {'text': 'note'}}
            with self.assertRaises(workload.Busy):
                bridge.dispatch({**tool, 'turn_token': 'wrong'})
            with self.assertRaises(ValueError):
                bridge.dispatch({**tool, 'kind': 'exec', 'params': {'command': 'anything'}})
            self.assertFalse((self.home / '.openclaw/workspace/IMPROVEMENT-LOG.md').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_log_worker_is_one_use_and_cannot_release_controller(self):
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            _, turn = self.begin(bridge)
            tool = {**turn, 'op': 'tool', 'call_id': 'call-1', 'kind': 'log', 'params': {'text': '--literal note'}}
            value = bridge.dispatch(tool)
            self.assertEqual(value['value']['status'], 'appended')
            with self.assertRaises(ValueError):
                bridge.dispatch(tool)
            self.assertEqual(parent.record['phase'], 'running')
            with self.assertRaises(workload.Busy):
                with workload.reserve(self.home, 'proctor'):
                    self.fail('Tool completion released the parent')
            self.assertNotIn(bridge.secret, json.dumps(value))
            self.assertIsNone(bridge.pending)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_disconnected_evaluation_saves_during_aborted_host_scope_without_releasing_admission(self):
        binary = self.home / 'bin'
        binary.mkdir()
        gate = self.home / 'allow-evaluation'
        executable = binary / 'openclaw'
        executable.write_text('#!/usr/bin/env python3\nimport json,sys,time\nfrom pathlib import Path\n'
            f'gate=Path({str(gate)!r})\n'
            'deadline=time.monotonic()+10\n'
            'while not gate.exists() and time.monotonic()<deadline: time.sleep(.01)\n'
            'assert gate.exists()\n'
            'session=sys.argv[sys.argv.index("--session-id")+1]\n'
            'print(json.dumps({"payloads":[{"text":"synthetic answer"}],"meta":{"agentMeta":{'
            '"sessionId":session,"provider":"ollama","model":"qwen3:4b-instruct-2507-q4_K_M"}}}))\n')
        executable.chmod(0o700)
        failures = []
        releaser = None
        try:
            with self.assertRaisesRegex(RuntimeError, 'agent turn aborted'):
                with controller_bridge.owned(self.home, session_key='agent:main:host-session',
                                             worker_timeout=15) as (bridge, env):
                    bridge.worker_path = str(binary) + os.pathsep + bridge.worker_path
                    _, turn = self.begin(bridge)
                    tool = {**turn, 'op': 'tool', 'call_id': 'eval-disconnected',
                            'kind': 'evaluation', 'params': {'suite': 'quick'}}
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(10)
                        client.connect(env['ARGOS_CONTROLLER_SOCKET'])
                        client.sendall((json.dumps(tool) + '\n').encode())
                        with client.makefile('rb') as reader:
                            self.assertEqual(json.loads(reader.readline())['status'], 'progress')
                        client.shutdown(socket.SHUT_RDWR)
                    with self.assertRaises(workload.Busy):
                        bridge.dispatch({**tool, 'call_id': 'competing-evaluation'})

                    def release_after_teardown_begins():
                        try:
                            deadline = time.monotonic() + 5
                            while not bridge.closed and time.monotonic() < deadline:
                                time.sleep(.01)
                            self.assertTrue(bridge.closed)
                            time.sleep(.15)
                            self.assertIsNotNone(bridge.pending)
                            self.assertIsNone(bridge.pending.poll(), 'Teardown killed admitted evaluation')
                            with self.assertRaises(workload.Busy):
                                with workload.reserve(self.home, 'evaluation'):
                                    self.fail('Host released admission before saved result')
                        except BaseException as error:
                            failures.append(error)
                        finally:
                            gate.write_text('continue')
                    releaser = threading.Thread(target=release_after_teardown_begins)
                    releaser.start()
                    raise RuntimeError('agent turn aborted')
        finally:
            gate.touch()
            if releaser:
                releaser.join(timeout=10)
                self.assertFalse(releaser.is_alive())
        if failures:
            raise failures[0]
        store = Store(self.home / '.local/share/argos-live/results')
        listing = store.list()
        self.assertEqual(listing['rejected'], [])
        rows = listing['runs']
        self.assertEqual(len(rows), 1)
        saved = store.load(rows[0]['id'])
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(saved['coverage']['completed'], 20)
        self.assertEqual(bridge.outcomes[0]['result_id'], saved['id'])
        self.assertIsNone(bridge.pending)
        with self.assertRaises(workload.Busy) as caught:
            with workload.reserve(self.home, 'evaluation'):
                self.fail('Aborted controller quarantine was released')
        self.assertTrue(caught.exception.recovery)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux cross-process delegated worker')
    def test_evaluation_progress_crosses_host_bridge_before_saved_result(self):
        binary = self.home / 'bin'
        binary.mkdir()
        executable = binary / 'openclaw'
        executable.write_text('#!/usr/bin/env python3\nimport json,sys\n'
            'session=sys.argv[sys.argv.index("--session-id")+1]\n'
            'print(json.dumps({"payloads":[{"text":"synthetic answer"}],"meta":{"agentMeta":{'
            '"sessionId":session,"provider":"ollama","model":"qwen3:4b-instruct-2507-q4_K_M"}}}))\n')
        executable.chmod(0o700)
        with workload.reserve(self.home, 'controller') as parent:
            bridge = controller_bridge.Bridge(self.home, parent, session_key='agent:main:host-session')
            bridge.worker_path = str(binary) + os.pathsep + bridge.worker_path
            _, turn = self.begin(bridge)
            updates = []
            tool = {**turn, 'op': 'tool', 'call_id': 'eval-call', 'kind': 'evaluation',
                    'params': {'suite': 'quick'}}
            value = bridge.dispatch(tool, on_update=updates.append)
            self.assertEqual(value['status'], 'completed')
            self.assertEqual(value['value']['result']['state'], 'completed')
            self.assertTrue(updates)
            self.assertEqual(updates[0]['phase'], 'asking')
            self.assertEqual(updates[-1]['phase'], 'scored')
            self.assertEqual(value['value']['result']['coverage']['completed'], 20)
            self.assertEqual(parent.record['phase'], 'running')
            parent.complete()


if __name__ == '__main__':
    unittest.main()
