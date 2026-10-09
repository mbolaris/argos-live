import copy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from argoslive import auto_setup, catalog, model_selection
from argoslive.pull_jobs import read_json, write_json
from test_lab import Assistant
from argoslive.web.server import DashboardServer


class Startup(Assistant):
    def __init__(self, home, fail=False, hold=False):
        super().__init__(home)
        self.phase, self.fail, self.hold = 'ready', fail, hold
        self.entered = threading.Event()
    def snapshot(self):
        return {'active': self.active, 'phase': self.phase, 'model_reply_verified': self.phase == 'ready'}
    def start(self, *, _reserved=False):
        self.calls.append('resume')
        self.entered.set()
        self.active = not self.fail
        self.phase = 'failed' if self.fail else 'gateway' if self.hold else 'ready'
    def stop(self):
        super().stop()
        self.phase = 'stopped'


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state, self.config, self.journal = model_selection.paths(self.home)
        self.state.parent.mkdir(parents=True)
        self.config.parent.mkdir(parents=True)
        self.target = self.home / 'models'; self.target.mkdir()
        (self.target / '.argos-storage-id').write_text('owner\n')
        write_json(self.state, {'storage': str(self.target), 'storage_id': 'owner',
                              'model': 'qwen3:0.6b', 'model_source': 'bundled'})
        write_json(self.config, auto_setup.conversation_config('qwen3:0.6b', self.home / 'workspace'))
        self.original = (self.state.read_bytes(), self.config.read_bytes())
        self.tag = next(e['tag'] for e in catalog.load()['models'] if e['tag'] != 'qwen3:0.6b'
                        and 'text' in e['capabilities'] and e['context_tokens'] >= 32768)
    def controller(self, **options):
        startup = Startup(self.home, **options)
        checks = []
        control = model_selection.Controller(startup, verify=lambda *args, **kw: checks.append(args))
        self.addCleanup(control.close)
        return startup, control, checks
    def finish(self, control):
        control.worker.join(5)
        self.assertFalse(control.worker.is_alive())
    def test_success_preserves_policy_token_personality_and_uses_real_selection(self):
        startup, control, checks = self.controller()
        before = read_json(self.config)
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        self.assertEqual(read_json(self.state)['model_source'], 'managed')
        self.assertEqual(read_json(self.state)['model'], self.tag)
        after = read_json(self.config)
        self.assertEqual(after['gateway'], before['gateway'])
        self.assertEqual(after['tools'], before['tools'])
        self.assertEqual(after['agents']['defaults']['workspace'], before['agents']['defaults']['workspace'])
        self.assertEqual(after['agents']['defaults']['model']['primary'], 'ollama/' + self.tag)
        self.assertEqual(after['models']['providers']['ollama']['models'][0], before['models']['providers']['ollama']['models'][0])
        self.assertEqual(len(checks), 1)
        self.assertFalse(self.journal.exists())
        self.assertTrue(startup.active)
        # Post-success rollback transaction is recorded
        snap = control.snapshot()
        self.assertTrue(snap['rollback_available'])
        self.assertEqual(snap['previous_model'], 'qwen3:0.6b')
        self.assertTrue(model_selection.rollback_path(self.home).exists())

    def test_post_success_rollback_keep_and_owner_edit_protection(self):
        startup, control, _ = self.controller()
        control.start(tag=self.tag); self.finish(control)
        self.assertTrue(control.snapshot()['rollback_available'])
        self.assertEqual(control.snapshot()['previous_model'], 'qwen3:0.6b')

        # Owner edit blocks post-success rollback
        config_data = read_json(self.config)
        config_data['owner_customization'] = 'manual-edit'
        write_json(self.config, config_data)
        can_res, _ = model_selection.can_restore_previous(self.home)
        self.assertFalse(can_res)
        with self.assertRaisesRegex(ValueError, 'not available for restoration or files were edited'):
            control.restore_previous()

        # Reverting owner edit re-enables restore
        del config_data['owner_customization']
        write_json(self.config, config_data)
        # Fix formatting to match candidate
        self.config.write_bytes(read_json(model_selection.rollback_path(self.home))['raw_current']['config'].encode())
        can_res, prev = model_selection.can_restore_previous(self.home)
        self.assertTrue(can_res)
        self.assertEqual(prev, 'qwen3:0.6b')

        # Keep current confirms selection and unlinks rollback journal
        self.assertTrue(control.keep_current())
        self.assertFalse(model_selection.rollback_path(self.home).exists())
        self.assertFalse(control.snapshot()['rollback_available'])

    def test_restore_previous_restores_exact_saved_bytes(self):
        startup, control, _ = self.controller()
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        self.assertNotEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
        self.assertTrue(model_selection.rollback_path(self.home).exists())

        # Exact restore
        control.restore_previous(); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
        self.assertFalse(model_selection.rollback_path(self.home).exists())
        self.assertFalse(self.journal.exists())
        self.assertFalse(control.snapshot()['rollback_available'])

    def test_rollback_write_failure_aborts_switch_and_restores_previous(self):
        startup, control, _ = self.controller()
        real_write = model_selection.write_json
        def fail_rollback(path, data):
            if 'model-rollback.json' in str(path):
                raise OSError('Disk quota exceeded')
            return real_write(path, data)
        with patch('argoslive.model_selection.write_json', side_effect=fail_rollback):
            control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'rolled-back')
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
        self.assertFalse(self.journal.exists())

    def test_failed_start_restores_exact_bytes(self):
        startup, control, _ = self.controller(fail=True)
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'rolled-back')
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
        self.assertFalse(self.journal.exists())
    def test_cancel_start_restores_original(self):
        startup, control, _ = self.controller(hold=True)
        control.start(tag=self.tag)
        self.assertTrue(startup.entered.wait(3))
        control.cancel(); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'cancelled')
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
    def test_owner_edit_blocks_restore_and_restart(self):
        startup, control, _ = self.controller(hold=True)
        control.start(tag=self.tag)
        self.assertTrue(startup.entered.wait(3))
        changed = read_json(self.config); changed['owner_note'] = 'retain'
        write_json(self.config, changed)
        control.cancel(); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'recovery-blocked')
        self.assertEqual(read_json(self.config)['owner_note'], 'retain')
        self.assertTrue(self.journal.exists())
        self.assertFalse(startup.active)
    def test_interrupted_pair_recovers_without_starting_model(self):
        before = {'state': read_json(self.state), 'config': read_json(self.config)}
        after = copy.deepcopy(before); after['state']['model'] = self.tag
        raw = {key: value.decode() for key, value in zip(('state', 'config'), self.original)}
        candidate = {key: json.dumps(value) + '\n' for key, value in after.items()}
        write_json(self.journal, {'schema': 'argos-model-selection/1', 'before': before,
            'after': after, 'raw': raw, 'candidate': candidate})
        self.state.write_bytes(candidate['state'].encode())
        self.assertTrue(model_selection.restore(self.home))
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
    def test_unreviewed_tag_and_competing_workload_rejected(self):
        startup, control, _ = self.controller()
        with self.assertRaises(ValueError): control.start(tag='unknown:latest')
        startup.lab_active = True
        with self.assertRaises(ValueError): control.start(tag=self.tag)
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)

    def test_http_selection_requires_header_auth_and_exact_choice(self):
        startup, control, _ = self.controller()
        with DashboardServer(port=0, selection=control) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.putrequest('POST', '/api/models/select?token=' + server.token)
                connection.putheader('Content-Length', '20'); connection.endheaders()
                response = connection.getresponse(); self.assertEqual(response.status, 403); response.read(); connection.close()
                self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
                for body in ('{"job":"x"}', '{"tag":"qwen3:0.6b","tag":"qwen3:4b"}'):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                    connection.request('POST', '/api/models/select', body, headers={
                        'X-Argos-Token': server.token, 'Content-Type': 'application/json'})
                    response = connection.getresponse(); self.assertEqual(response.status, 409); response.read(); connection.close()
                self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), self.original)
            finally:
                server.shutdown(); thread.join(3)

    def test_restore_interrupted_recovers_exact_bytes_without_starting(self):
        startup, control, _ = self.controller()
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        rb_data = read_json(model_selection.rollback_path(self.home))
        # Simulate an interrupted restore crash after journal creation and state replacement
        write_json(self.journal, {
            'schema': 'argos-model-selection/1',
            'before': {'state': read_json(self.state), 'config': read_json(self.config)},
            'after': {'state': json.loads(rb_data['raw_previous']['state']), 'config': json.loads(rb_data['raw_previous']['config'])},
            'raw': {'state': rb_data['raw_current']['state'], 'config': rb_data['raw_current']['config']},
            'candidate': {'state': rb_data['raw_previous']['state'], 'config': rb_data['raw_previous']['config']},
        })
        self.state.write_bytes(rb_data['raw_previous']['state'].encode())
        self.assertTrue(model_selection.restore(self.home))
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.state.read_bytes(), rb_data['raw_current']['state'].encode())

    def test_restore_failed_startup_rolls_back(self):
        startup, control, _ = self.controller()
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        switched_bytes = (self.state.read_bytes(), self.config.read_bytes())
        # Fail startup during restore
        startup.fail = True
        startup.entered.clear()
        control.restore_previous(); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'rolled-back')
        self.assertFalse(self.journal.exists())
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), switched_bytes)

    def test_restore_cancellation_rolls_back_cleanly(self):
        startup, control, _ = self.controller()
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        switched_bytes = (self.state.read_bytes(), self.config.read_bytes())
        # Hold startup during restore to allow cancellation
        startup.hold = True
        startup.entered.clear()
        control.restore_previous()
        self.assertTrue(startup.entered.wait(3))
        control.cancel(); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'cancelled')
        self.assertFalse(self.journal.exists())
        self.assertEqual((self.state.read_bytes(), self.config.read_bytes()), switched_bytes)

    def test_restore_concurrent_owner_edit_blocks_recovery_and_preserves_edits(self):
        startup, control, _ = self.controller()
        control.start(tag=self.tag); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'completed')
        # Hold startup during restore
        startup.hold = True
        startup.entered.clear()
        control.restore_previous()
        self.assertTrue(startup.entered.wait(3))
        # External owner modifies config during restore startup
        changed = read_json(self.config)
        changed['owner_override'] = 'concurrent edit during restore'
        write_json(self.config, changed)
        control.cancel(); self.finish(control)
        self.assertEqual(control.snapshot()['phase'], 'recovery-blocked')
        self.assertTrue(self.journal.exists())
        self.assertEqual(read_json(self.config)['owner_override'], 'concurrent edit during restore')
        self.assertFalse(startup.active)


if __name__ == '__main__':
    unittest.main()

