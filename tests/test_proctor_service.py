import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, proctor_service
from argoslive.evaluation_context import configuration_from, receipt_from


class ProctorServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.owner_config = self.home / '.openclaw/openclaw.json'
        self.owner_config.parent.mkdir(parents=True)
        workspace = self.home / '.openclaw/workspace'
        owner = auto_setup.conversation_config('qwen3.8:27b', workspace, plugin_root='/opt/argos/plugins')
        owner['agents']['defaults']['model']['temperature'] = 0
        owner['models']['providers']['ollama']['models'][0].update(
            reasoning=True, params={'think': True, 'temperature': 0})
        self.owner_config.write_text(json.dumps(owner))

    def test_profile_is_persistent_restricted_and_preserves_model_controls(self):
        root, workspace, config_path, first_hash = proctor_service.private_profile(
            self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
            owner_config_path=self.owner_config)
        config = json.loads(config_path.read_text())
        self.assertEqual(root, self.home / '.local/state/argos-live/proctor')
        runtime_root = self.home / '.local/state/argos-live'
        if os.name != 'nt':
            self.assertEqual(runtime_root.stat().st_mode & 0o077, 0)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(config['agents']['defaults']['model']['temperature'], 0)
        model = config['models']['providers']['ollama']['models'][0]
        self.assertEqual(model['params'], {'think': True, 'temperature': 0})
        self.assertIs(model['reasoning'], True)
        self.assertEqual(config['tools']['alsoAllow'], proctor_service.PROCTOR_TOOL_NAMES)
        self.assertIn('exec', config['tools']['deny'])
        self.assertIn('process', config['tools']['deny'])
        self.assertNotIn('group:runtime', config['tools']['deny'])
        self.assertNotIn('group:fs', config['tools']['alsoAllow'])
        self.assertEqual(config['plugins']['allow'], ['argos-improve'])
        self.assertIs(config['plugins']['entries']['argos-improve']['config']['hostAdmission'], True)
        self.assertIs(config['plugins']['entries']['argos-improve']['hooks']['allowConversationAccess'], True)
        second = proctor_service.private_profile(self.home, 'qwen3.8:27b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        self.assertEqual(second[2], config_path)
        self.assertEqual(second[3], first_hash)
        self.assertEqual(json.loads(config_path.read_text()), config)

    def test_model_specific_profile_does_not_overwrite_prior_snapshot(self):
        first = proctor_service.private_profile(self.home, 'qwen3.8:27b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        other_config = json.loads(self.owner_config.read_text())
        other_config['agents']['defaults']['model']['primary'] = 'ollama/qwen3:14b'
        other_config['models']['providers']['ollama']['models'].append(
            {'id': 'qwen3:14b', 'name': 'qwen3:14b', 'input': ['text'], 'reasoning': False})
        self.owner_config.write_text(json.dumps(other_config))
        second = proctor_service.private_profile(self.home, 'qwen3:14b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        self.assertNotEqual(first[2], second[2])
        self.assertTrue(first[2].is_file())
        self.assertTrue(second[2].is_file())

    def test_practice_and_campaign_preserve_selected_per_model_generation_overrides(self):
        owner = json.loads(self.owner_config.read_text())
        defaults = owner['agents']['defaults']
        defaults['models'] = {
            'ollama/qwen3.8:27b': {'params': {'temperature': 0, 'think': True}},
            'ollama/unselected:example': {'params': {'temperature': 1}},
        }
        defaults['thinkingDefault'] = 'off'
        defaults['contextTokens'] = 32768
        owner['agents']['entries'] = {'main': {'params': {'topP': 0.7},
            'models': {'ollama/qwen3.8:27b': {'params': {'num_predict': 256}}}}}
        self.owner_config.write_text(json.dumps(owner))
        (self.home / '.openclaw/workspace').mkdir(parents=True)
        for purpose in ('practice', 'campaign'):
            with self.subTest(purpose=purpose):
                _, _, path, _ = proctor_service.private_profile(
                    self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
                    owner_config_path=self.owner_config, purpose=purpose)
                copied = json.loads(path.read_text())['agents']['defaults']
                self.assertEqual(set(copied['models']), {'ollama/qwen3.8:27b'})
                self.assertEqual(copied['models']['ollama/qwen3.8:27b']['params'],
                                 defaults['models']['ollama/qwen3.8:27b']['params'])
                self.assertEqual(copied['thinkingDefault'], 'off')
                self.assertEqual(copied['contextTokens'], 32768)
                self.assertEqual(copied['heartbeat'], {'every': '0m'})
                self.assertEqual(receipt_from(configuration_from(json.loads(path.read_text())))['configured_generation'],
                                 receipt_from(configuration_from(owner))['configured_generation'])

    def test_changed_owner_generation_settings_get_a_new_profile_without_overwriting(self):
        owner = json.loads(self.owner_config.read_text())
        owner['agents']['defaults']['models'] = {
            'ollama/qwen3.8:27b': {'params': {'temperature': 0, 'think': True}}}
        self.owner_config.write_text(json.dumps(owner))
        first = proctor_service.private_profile(self.home, 'qwen3.8:27b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        before = first[2].read_bytes()
        owner['agents']['defaults']['models']['ollama/qwen3.8:27b']['params']['temperature'] = 0.4
        self.owner_config.write_text(json.dumps(owner))
        second = proctor_service.private_profile(self.home, 'qwen3.8:27b',
            plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)
        self.assertNotEqual(first[2], second[2])
        self.assertEqual(first[2].read_bytes(), before)
        self.assertEqual(json.loads(second[2].read_text())['agents']['defaults']['models'][
            'ollama/qwen3.8:27b']['params']['temperature'], 0.4)

    def test_remote_or_unmatched_owner_model_profile_is_rejected(self):
        owner = json.loads(self.owner_config.read_text())
        owner['models']['providers']['ollama']['baseUrl'] = 'https://example.invalid'
        self.owner_config.write_text(json.dumps(owner))
        with self.assertRaisesRegex(ValueError, 'needs review'):
            proctor_service.private_profile(self.home, 'qwen3.8:27b',
                plugin_root='/opt/argos/plugins', owner_config_path=self.owner_config)

    def test_campaign_profile_uses_canonical_workspace_and_only_managed_tools(self):
        (self.home / '.openclaw/workspace').mkdir(parents=True)
        root, workspace, config_path, _digest = proctor_service.private_profile(
            self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
            owner_config_path=self.owner_config, purpose='campaign')
        config = json.loads(config_path.read_text())
        self.assertEqual(workspace, (self.home / '.openclaw/workspace').resolve())
        self.assertEqual(config['tools']['alsoAllow'], proctor_service.CAMPAIGN_TOOL_NAMES)
        self.assertIn('argos_audit_instructions', config['tools']['alsoAllow'])
        self.assertIn('group:fs', config['tools']['deny'])
        self.assertIn('exec', config['tools']['deny'])
        self.assertNotIn('argos_proctor_start', config['tools']['alsoAllow'])
        self.assertEqual(config['agents']['defaults']['model']['temperature'], 0)

    def test_improvement_campaign_starts_only_after_completed_practice(self):
        state_path = self.home / '.config/argos-live/state.json'
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({'model': 'qwen3.8:27b'}))
        feedback = {'state': 'COMPLETED', 'correct': 3, 'total': 4, 'unanswered': 0}
        campaign = {'status': 'completed', 'saved_evaluation_ids': ['run-1']}
        events = []
        with patch.object(proctor_service, 'run_practice', return_value={
                'status': 'completed', 'result': feedback, 'transcript_id': 'transcript-1'}) as practice, \
             patch.object(proctor_service.startup, 'source', return_value=(self.home / 'Models', 'qwen3.8:27b')), \
             patch.object(proctor_service, 'run_campaign', side_effect=lambda *args, **kwargs:
                          events.append(('campaign', args[3])) or campaign):
            result = proctor_service.run_improvement(self.home, executable='openclaw')
        practice.assert_called_once()
        self.assertEqual(events, [('campaign', feedback)])
        self.assertEqual(result['campaign'], campaign)
        self.assertEqual(result['status'], 'completed')
        self.assertIs(result['practice_is_improvement_evidence'], False)

    def test_campaign_assessment_requires_comparison_then_audit_for_no_change(self):
        runs = [{'kind': 'evaluation', 'state': 'completed', 'result_id': run_id}
                for run_id in ('baseline-one', 'baseline-two')]
        outcomes = [{'kind': 'inspect'}, *runs,
                    {'kind': 'compare', 'baseline_id': 'baseline-one', 'candidate_id': 'baseline-two'},
                    {'kind': 'audit', 'status': 'empty', 'passed': True}]
        assessment = proctor_service._campaign_assessment(outcomes)
        self.assertTrue(assessment['ready'])
        self.assertEqual(assessment['status'], 'completed')
        self.assertEqual(assessment['outcome'], 'no_change_audited')
        self.assertEqual(assessment['saved_evaluation_ids'], ['baseline-one', 'baseline-two'])

        outcomes = [outcomes[0], *runs, outcomes[-1], outcomes[-2]]
        assessment = proctor_service._campaign_assessment(outcomes)
        self.assertFalse(assessment['ready'])
        self.assertIn('a passed host instruction audit supporting the no-change decision',
                      assessment['missing'])

    def test_campaign_assessment_requires_host_resolution_and_audit_after_kept_change(self):
        outcomes = [{'kind': 'inspect'},
                    {'kind': 'evaluation', 'state': 'completed', 'result_id': 'base-one'},
                    {'kind': 'evaluation', 'state': 'completed', 'result_id': 'base-two'},
                    {'kind': 'evaluation', 'state': 'completed', 'result_id': 'candidate-one'},
                    {'kind': 'evaluation', 'state': 'completed', 'result_id': 'candidate-two'},
                    {'kind': 'edit', 'status': 'changed', 'change_id': 'change-1'},
                    {'kind': 'compare', 'baseline_id': 'base-one', 'candidate_id': 'candidate-one'},
                    {'kind': 'resolve', 'status': 'kept', 'change_id': 'change-1',
                     'configuration_preserved': True, 'qualified_experiment': True,
                     'baseline_ids': ['base-one', 'base-two'],
                     'candidate_ids': ['candidate-one', 'candidate-two']},
                    {'kind': 'audit', 'status': 'verified', 'passed': True}]
        assessment = proctor_service._campaign_assessment(outcomes)
        self.assertTrue(assessment['ready'])
        self.assertEqual(assessment['outcome'], 'kept')

        outcomes[-1], outcomes[-2] = outcomes[-2], outcomes[-1]
        assessment = proctor_service._campaign_assessment(outcomes)
        self.assertFalse(assessment['ready'])
        self.assertIn('a passed host instruction audit after the keep/restore decision',
                      assessment['missing'])

    def test_campaign_continues_clean_turns_until_host_evidence_is_complete(self):
        (self.home / '.openclaw/workspace').mkdir(parents=True)
        bridge = SimpleNamespace(session_key='agent:main:argos_proctor_improvement', outcomes=[],
                                 launches=[], continuations=[], completed=False)

        def launch(_executable, _prompt, **_kwargs):
            bridge.launches.append(True)

        def finish(**kwargs):
            self.assertFalse(kwargs['finalize'])
            self.assertTrue(kwargs['retain_controller'])
            if len(bridge.launches) == 1:
                bridge.outcomes.extend([
                    {'kind': 'inspect'},
                    {'kind': 'evaluation', 'state': 'completed', 'result_id': 'base-one'},
                    {'kind': 'evaluation', 'state': 'completed', 'result_id': 'base-two'},
                ])
            else:
                bridge.outcomes.extend([
                    {'kind': 'compare', 'baseline_id': 'base-one', 'candidate_id': 'base-two'},
                    {'kind': 'audit', 'status': 'empty', 'passed': True},
                ])
            return {'result': {'payloads': []}}, ''

        bridge.launch = launch
        bridge.finish = finish
        bridge.drain_campaign_evaluation = Mock()
        bridge.drain_before_backends_stop = Mock()

        def next_turn(session_key):
            bridge.continuations.append(session_key)
            bridge.session_key = session_key

        bridge.next_campaign_turn = next_turn
        bridge.complete_campaign = lambda: setattr(bridge, 'completed', True)

        @contextmanager
        def owned_bridge(*_args, **_kwargs):
            yield bridge, {}

        @contextmanager
        def owned_resource(*_args, **_kwargs):
            yield object()

        with patch.object(proctor_service, 'private_profile', return_value=(
                 self.home, self.home, self.owner_config, 'a' * 64)), \
             patch.object(proctor_service, 'refuse_live_gateway'), \
             patch.object(proctor_service, 'refuse_live_backend'), \
             patch.object(proctor_service.controller_bridge, 'owned', owned_bridge), \
             patch.object(proctor_service.owned_ollama, 'owned', owned_resource), \
             patch.object(proctor_service.owned_gateway, 'owned', owned_resource):
            result = proctor_service.run_campaign(self.home, 'qwen3.8:27b', self.home, {},
                                                  executable='openclaw')

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['controller_turns'], 2)
        self.assertEqual(result['saved_evaluation_ids'], ['base-one', 'base-two'])
        self.assertEqual(len(bridge.continuations), 1)
        self.assertTrue(bridge.completed)

    def test_run_improvement_reports_campaign_incomplete(self):
        state_path = self.home / '.config/argos-live/state.json'
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({'model': 'qwen3.8:27b'}))
        campaign = {'status': 'incomplete', 'saved_evaluation_ids': ['run-1']}
        with patch.object(proctor_service, 'run_practice', return_value={
                'status': 'completed', 'result': {'state': 'COMPLETED', 'unanswered': 0},
                'transcript_id': 'transcript-1'}), \
             patch.object(proctor_service.startup, 'source', return_value=(self.home / 'Models', 'qwen3.8:27b')), \
             patch.object(proctor_service, 'run_campaign', return_value=campaign):
            result = proctor_service.run_improvement(self.home, executable='openclaw')
        self.assertEqual(result['status'], 'incomplete')

    def test_interrupted_services_drain_evaluations_before_stopping_backends(self):
        state_path = self.home / '.config/argos-live/state.json'
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({'model': 'qwen3.8:27b'}))
        for service in ('practice', 'campaign'):
            with self.subTest(service=service), ExitStack() as mocks:
                events, live = [], set()

                @contextmanager
                def resource(name, value=None):
                    live.add(name)
                    try:
                        yield value
                    finally:
                        events.append(name + '-stop')
                        live.remove(name)

                def drain():
                    self.assertTrue({'gateway', 'backend'} <= live)
                    events.append('evaluation-saved')

                bridge = SimpleNamespace(drain_before_backends_stop=drain,
                    launch=Mock(), finish=Mock(side_effect=RuntimeError('agent deadline')))
                db = Mock()
                for target, name, value in (
                    (proctor_service.controller_bridge, 'owned', lambda *a, **k: resource('bridge', (bridge, {}))),
                    (proctor_service.owned_ollama, 'owned', lambda *a, **k: resource('backend')),
                    (proctor_service.owned_gateway, 'owned', lambda *a, **k: resource('gateway')),
                    (proctor_service, 'private_profile', Mock(return_value=(self.home, self.home, self.owner_config, 'a' * 64))),
                    (proctor_service, 'refuse_live_gateway', Mock()),
                    (proctor_service, 'refuse_live_backend', Mock()),
                    (proctor_service.startup, 'source', Mock(return_value=(self.home, 'qwen3.8:27b', {}))),
                    (proctor_service, 'make_session', Mock(return_value=(db, Mock(), Mock()))),
                    (proctor_service.session_mode, 'guest', Mock(return_value=False)),
                    (proctor_service, 'run_practice_turns', Mock(side_effect=RuntimeError('agent deadline'))),
                    (proctor_service.sys, 'platform', 'linux')):
                    mocks.enter_context(patch.object(target, name, value))
                with self.assertRaisesRegex(RuntimeError, 'agent deadline'):
                    if service == 'practice':
                        proctor_service.run_practice(self.home, self.home / 'cartridge', executable='openclaw')
                        self.fail('Practice swallowed the interruption')
                    else:
                        proctor_service.run_campaign(self.home, 'qwen3.8:27b', self.home, {}, executable='openclaw')
                        self.fail('Campaign swallowed the interruption')
                self.assertEqual(events, ['evaluation-saved', 'gateway-stop', 'backend-stop', 'bridge-stop'])
                if service == 'campaign':
                    self.assertEqual(bridge.launch.call_args.kwargs['timeout'], 7200)
                else:
                    db.close.assert_called_once()

    def test_incomplete_practice_never_starts_campaign(self):
        with patch.object(proctor_service, 'run_practice', return_value={
                'status': 'incomplete', 'result': {'state': 'ABANDONED'}}), \
             patch.object(proctor_service, 'run_campaign') as campaign:
            with self.assertRaisesRegex(ValueError, 'Practice did not complete'):
                proctor_service.run_improvement(self.home)
        campaign.assert_not_called()

    def test_timed_terminal_exam_with_unanswered_items_cannot_start_campaign(self):
        with patch.object(proctor_service, 'run_practice', return_value={
                'status': 'completed', 'result': {'state': 'COMPLETED', 'unanswered': 4}}), \
             patch.object(proctor_service, 'run_campaign') as campaign:
            with self.assertRaisesRegex(ValueError, 'Practice did not complete'):
                proctor_service.run_improvement(self.home)
        campaign.assert_not_called()

    def test_existing_gateway_is_refused_before_any_proctor_reservation(self):
        _root, _workspace, config_path, _digest = proctor_service.private_profile(
            self.home, 'qwen3.8:27b', plugin_root='/opt/argos/plugins',
            owner_config_path=self.owner_config)
        with patch('argoslive.proctor_service.socket.create_connection') as connect:
            connect.return_value.__enter__.return_value = object()
            with self.assertRaisesRegex(ValueError, 'Stop the existing OpenClaw gateway'):
                proctor_service.refuse_live_gateway(config_path)
        with patch('argoslive.proctor_service.socket.create_connection', side_effect=OSError):
            proctor_service.refuse_live_gateway(config_path)

    def test_existing_backend_is_refused_and_absent_backend_is_allowed(self):
        with patch('argoslive.proctor_service.socket.create_connection') as connect:
            connect.return_value.__enter__.return_value = object()
            with self.assertRaisesRegex(ValueError, 'Stop the existing Ollama service'):
                proctor_service.refuse_live_backend()
        with patch('argoslive.proctor_service.socket.create_connection', side_effect=OSError):
            proctor_service.refuse_live_backend()

    def test_private_service_secret_is_reused_and_never_overwritten(self):
        path = self.home / 'secret'
        first = proctor_service._secret(path)
        second = proctor_service._secret(path)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_bundled_pilot_is_content_addressed_and_explicitly_uncalibrated(self):
        first = proctor_service.default_cartridge(self.home)
        second = proctor_service.default_cartridge(self.home)
        self.assertEqual(first, second)
        cartridge = proctor_service.proctor.Cartridge(first)
        self.assertEqual(cartridge.manifest['calibration_status'], 'uncalibrated')
        self.assertEqual(cartridge.manifest['cartridge_id'], 'argos-practice-pilot')
        self.assertIn('pilot-a', cartridge.forms)
        self.assertEqual(len(cartridge.items), 5)
        self.assertEqual(cartridge.items['q5']['domain'], 'tool_call_format')
        self.assertEqual(cartridge.items['q5']['response_type'], 'json_object')

    def test_practice_turn_surfaces_tool_call_item_as_a_real_simulated_tool_call(self):
        class Exam:
            def status(self):
                return {'state': 'ACTIVE', 'item_ids': ['q5'], 'answer_revisions': {}}

        class Bridge:
            def present_proctor_item(self, item_id):
                self.item_id = item_id
                return {'item_id': item_id, 'domain': 'tool_call_format',
                    'response_type': 'json_object', 'prompt': 'Call with job_id 0123456789abcdef0123456789abcdef.'}

        bridge = Bridge()
        message = proctor_service.practice_turn_message(Exam(), bridge)
        self.assertIn('actual argos_evaluate_wait tool call', message)
        self.assertIn('0123456789abcdef0123456789abcdef', message)
        self.assertIn('Do not call argos_proctor_answer', message)
        self.assertEqual(bridge.item_id, 'q5')
        retry = proctor_service.practice_turn_message(Exam(), bridge, retry_tool_call=True)
        self.assertIn('previous turn did not make the requested tool call', retry)
        self.assertIn('argos_evaluate_wait', retry)

    def test_numeric_practice_prompt_does_not_anchor_to_a_sample_answer(self):
        class Exam:
            def status(self):
                return {'state': 'ACTIVE', 'item_ids': ['q2'], 'answer_revisions': {}}

        class Bridge:
            def present_proctor_item(self, item_id):
                self.item_id = item_id
                return {'item_id': 'q2', 'domain': 'math', 'response_type': 'numeric_grid',
                        'prompt': 'What is 2 + 2?'}

        bridge = Bridge()
        message = proctor_service.practice_turn_message(Exam(), bridge)
        self.assertIn('Solve from this question alone', message)
        self.assertIn('do not reuse another item\'s answer', message)
        self.assertNotIn('-5/4', message)
        retry = proctor_service.practice_turn_message(Exam(), bridge, retry_format=True)
        self.assertIn('Solve from this question alone', retry)
        self.assertNotIn('-5/4', retry)

    def test_session_subject_binds_verified_model_receipt_and_can_start_exam(self):
        original_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.as_posix() == '/proc/sys/kernel/random/boot_id':
                return 'synthetic-boot'
            return original_read_text(path, *args, **kwargs)

        def create_test_key(path, executable='openssl'):
            Path(path).write_bytes(b'test signing key placeholder')

        class TestSigner:
            def __init__(self, *_args, **_kwargs):
                pass

        cartridge = proctor_service.default_cartridge(self.home)
        with patch.object(Path, 'read_text', read_text), \
             patch.object(proctor_service, 'generate_key', create_test_key), \
             patch.object(proctor_service, 'Ed25519Signer', TestSigner):
            model_identity = {
                'schema': 'argos-verified-model/1', 'tag': 'fixture:latest',
                'catalog_manifest_digest': 'sha256:' + 'a' * 64,
                'local_manifest_sha256': hashlib.sha256(
                    b'synthetic fixture model manifest\n').hexdigest(),
                'artifacts': [{'digest': 'sha256:' + 'b' * 64, 'size': 7,
                               'media_type': 'application/vnd.ollama.image.model'}],
                'verified_bytes': 7,
                'verification': 'catalog manifest and every declared model blob SHA-256 verified',
            }
            model_identity['sha256'] = hashlib.sha256(json.dumps(
                model_identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            bad_identity = dict(model_identity, sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'checksum is invalid'):
                proctor_service.make_session(
                    self.home, cartridge, 'pilot-a', 'fixture:latest', 'b' * 64,
                    model_identity=bad_identity)
            incomplete_identity = dict(model_identity, verified_bytes=6)
            unsigned_identity = {key: value for key, value in incomplete_identity.items() if key != 'sha256'}
            incomplete_identity['sha256'] = hashlib.sha256(json.dumps(
                unsigned_identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            with self.assertRaisesRegex(ValueError, 'complete blob verification'):
                proctor_service.make_session(
                    self.home, cartridge, 'pilot-a', 'fixture:latest', 'b' * 64,
                    model_identity=incomplete_identity)
            self.assertFalse((self.home / '.local/state/argos-live/proctor/caller.token').exists())
            db, exam, _cart = proctor_service.make_session(
                self.home, cartridge, 'pilot-a', 'fixture:latest', 'b' * 64,
                model_identity=model_identity)
        try:
            status = exam.start('start-operation')
            self.assertEqual(status['state'], 'ACTIVE')
            row = db.execute('SELECT subject_json FROM sessions WHERE session_id=?',
                             (exam.session_id,)).fetchone()
            subject = json.loads(row['subject_json'])
            self.assertEqual(subject['model_tag'], 'fixture:latest')
            self.assertEqual(subject['model_digest'], model_identity['sha256'])
            self.assertEqual(subject['model_identity'], model_identity)
            self.assertEqual(subject['configuration']['profile_sha256'], 'b' * 64)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
