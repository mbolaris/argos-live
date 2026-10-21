import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import bench_openclaw, instruction_changes as changes, workload
from test_bench_openclaw import FakeOpenClaw, configure_fake


class InstructionChangeTests(unittest.TestCase):
    def test_challenge_requires_a_meaningful_repeatable_gain(self):
        self.assertEqual(changes.POLICY['minimum_correct_delta']['openclaw-challenge'], 3)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        configure_fake(self.home, workspace)
        self.path = workspace / 'AGENTS.md'
        self.original = b'Owner rule.\nStay concise.\n'
        self.path.write_bytes(self.original)
        self.context = workload.reserve(self.home, 'controller')
        self.parent = self.context.__enter__()
        self.addCleanup(lambda: self.context.__exit__(None, None, None))
        hardware = patch.object(bench_openclaw.hw, 'snapshot', return_value={
            'cpu': {'model': 'fixture CPU', 'cores': 2, 'threads': 2},
            'ram': {'total_bytes': 1024**3}, 'gpus': []})
        hardware.start()
        self.addCleanup(hardware.stop)

    def op(self, operation, params=None):
        cap = self.parent.delegate('maintenance')
        result = changes.perform(self.home, operation, params or {}, delegation=cap)
        self.parent.resume(cap, worker_drained=True)
        return result

    def evaluate(self, misses=0):
        class Answers(FakeOpenClaw):
            def turn(self, prompt):
                value = super().turn(prompt)
                if self.calls <= misses:
                    value['text'] = '__wrong_fixture_answer__'
                return value
        cap = self.parent.delegate('evaluation')
        result = bench_openclaw.run(home=self.home, runner=Answers(), delegation=cap)
        self.parent.resume(cap, worker_drained=True)
        return result

    def edit(self, baseline, **extra):
        return self.op('edit', {'baseline_id': baseline['id'], 'expected_sha256': changes.digest(self.path.read_bytes()),
            'find': 'Stay concise.', 'replace': 'Stay concise. Answer first.',
            'hypothesis': 'An agent-chosen directness rule may help.', **extra})

    def resolve(self, edit, action='restore', **extra):
        return self.op('resolve', {'change_id': edit['change_id'], 'action': action,
            'expected_sha256': changes.digest(self.path.read_bytes()), **extra})

    def test_inspection_excludes_credentials_and_cannot_read_an_arbitrary_path(self):
        token = json.loads((self.home / '.openclaw/openclaw.json').read_bytes())['gateway']['auth']['token']
        observed = self.op('inspect')
        self.assertEqual(observed['instructions'], self.original.decode())
        self.assertNotIn(token, json.dumps(observed))
        self.assertEqual(self.op('inspect', {'path': '/private/evaluator'})['status'], 'rejected')

    def test_empty_audit_is_explicit_and_does_not_claim_gain_or_log_verification(self):
        report = self.op('audit')
        self.assertEqual(report['schema'], 'argos-instruction-audit/1')
        self.assertEqual(report['status'], 'empty')
        self.assertTrue(report['passed'])
        self.assertEqual(report['qualified_experiments'], 0)
        self.assertFalse(report['full_log_claims_verified'])
        self.assertFalse(report['independent_gain_verified'])
        changes.root_path(self.home)  # A first inspection creates the empty journal directory.
        self.assertEqual(self.op('audit')['status'], 'empty')

    def test_patch_snapshot_restore_and_audit_match_actual_bytes(self):
        baseline = self.evaluate()
        edited = self.edit(baseline)
        self.assertEqual(edited['status'], 'changed')
        root = self.home / '.local/state/argos-live/instruction-changes'
        self.assertEqual((root / edited['change_id'] / 'before.bin').read_bytes(), self.original)
        self.assertIn(b'Answer first.', self.path.read_bytes())
        self.assertEqual(self.edit(baseline)['status'], 'rejected')
        candidate = self.evaluate()
        restored = self.resolve(edited, candidate_ids=[candidate['id']])
        self.assertEqual(restored['status'], 'restored')
        self.assertTrue(restored['qualified_experiment'])
        self.assertEqual(self.path.read_bytes(), self.original)
        audit = self.op('audit')
        self.assertTrue(audit['passed'], audit)
        self.assertEqual(audit['status'], 'verified')
        self.assertEqual(audit['qualified_experiments'], 1)
        self.assertFalse(audit['full_log_claims_verified'])

    def test_stale_hash_ambiguous_patch_and_unsupported_path_do_not_mutate(self):
        baseline = self.evaluate()
        for extra in ({'expected_sha256': '0' * 64}, {'find': 'missing'}, {'path': '../evaluator.py'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.edit(baseline, **extra)['status'], 'rejected')
                self.assertEqual(self.path.read_bytes(), self.original)
        self.path.write_text('repeat repeat')
        self.assertEqual(self.edit(baseline, find='repeat')['status'], 'rejected')

    def test_restore_preserves_concurrent_owner_edit(self):
        baseline = self.evaluate()
        edited = self.edit(baseline)
        self.path.write_bytes(b'New owner bytes\n')
        self.assertEqual(self.resolve(edited)['status'], 'rejected')
        self.assertEqual(self.path.read_bytes(), b'New owner bytes\n')
        self.assertFalse(changes.audit(self.home)['passed'])

    def test_unmeasured_restore_is_safe_but_does_not_count_as_an_experiment(self):
        baseline = self.evaluate()
        edited = self.edit(baseline)
        restored = self.resolve(edited, candidate_ids=['a' * 32])
        self.assertEqual(restored['status'], 'restored')
        self.assertFalse(restored['qualified_experiment'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(changes.audit(self.home)['passed'])

    def test_keep_requires_repeated_matched_gain_and_records_noise(self):
        baselines = [self.evaluate(misses=5), self.evaluate(misses=4)]
        edited = self.edit(baselines[0])
        candidates = [self.evaluate(misses=1), self.evaluate(misses=0)]
        kept = self.resolve(edited, 'keep', baseline_ids=[run['id'] for run in baselines],
                            candidate_ids=[run['id'] for run in candidates])
        self.assertEqual(kept['status'], 'kept', kept)
        self.assertEqual(kept['minimum_correct_gain'], 3)
        self.assertFalse(kept['independent_gain_verified'])
        audit = self.op('audit')
        self.assertTrue(audit['passed'], audit)
        self.assertEqual(audit['status'], 'verified')
        observed = audit['changes'][0]
        self.assertEqual(observed['action'], 'keep')
        self.assertEqual(observed['worst_case_correct_delta'], 3)
        self.assertEqual(observed['baseline']['scores'], [
            {'correct': 15, 'total': 20, 'format_errors': 5},
            {'correct': 16, 'total': 20, 'format_errors': 4}])
        self.assertEqual(observed['candidate']['scores'], [
            {'correct': 19, 'total': 20, 'format_errors': 1},
            {'correct': 20, 'total': 20, 'format_errors': 0}])
        self.assertEqual(len(observed['baseline']['run_ids']), 2)
        self.assertEqual(len(observed['candidate']['run_ids']), 2)
        self.assertFalse(audit['full_log_claims_verified'])
        self.assertFalse(audit['independent_gain_verified'])

    def test_single_run_or_noisy_non_gain_cannot_be_kept(self):
        baselines = [self.evaluate(), self.evaluate()]
        edited = self.edit(baselines[0])
        candidate = self.evaluate()
        one = self.resolve(edited, 'keep', baseline_ids=[run['id'] for run in baselines], candidate_ids=[candidate['id']])
        self.assertEqual(one['status'], 'rejected')
        second = self.evaluate()
        two = self.resolve(edited, 'keep', baseline_ids=[run['id'] for run in baselines],
                           candidate_ids=[candidate['id'], second['id']])
        self.assertEqual(two['code'], 'repeated-practice-gain-rule-not-met')
        self.assertEqual(self.resolve(edited, candidate_ids=[candidate['id']])['status'], 'restored')

    def test_snapshot_tampering_is_detected_by_the_audit(self):
        baseline = self.evaluate()
        edited = self.edit(baseline)
        self.resolve(edited)
        snapshot = self.home / '.local/state/argos-live/instruction-changes' / edited['change_id'] / 'after.bin'
        snapshot.write_bytes(b'tampered')
        self.assertFalse(changes.audit(self.home)['passed'])

    def test_failure_after_workspace_write_quarantines_instead_of_claiming_success(self):
        baseline = self.evaluate()
        immutable = changes.immutable
        def fail_applied(path, value):
            if path.name == 'applied.json':
                raise OSError('fixture journal publication failure')
            return immutable(path, value)
        with patch.object(changes, 'immutable', side_effect=fail_applied):
            with self.assertRaises(OSError):
                self.edit(baseline)
        self.assertIn(b'Answer first.', self.path.read_bytes())
        self.assertFalse(changes.audit(self.home)['passed'])
        with self.assertRaises(workload.Busy):
            with workload.reserve(self.home, 'proctor'):
                self.fail('Uncertain mutation reopened admission')

    def test_saved_result_without_this_controller_receipt_cannot_authorize_change(self):
        import copy
        from argoslive.results import Store
        baseline = self.evaluate()
        copied = copy.deepcopy(baseline)
        copied['id'] = 'b' * 32
        Store(self.home / '.local/share/argos-live/results').save(copied)
        self.assertEqual(self.edit(copied)['code'], 'run-is-not-from-this-host-controller')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_admission_prevents_instruction_writes_during_an_evaluation(self):
        cap = self.parent.delegate('evaluation')
        with self.assertRaises(workload.Busy):
            changes.perform(self.home, 'inspect', {}, delegation=cap)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.parent.cancel_unstarted(cap)
        self.parent.resume(cap, worker_drained=True)


if __name__ == '__main__':
    unittest.main()
