import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive import bench_ability, bench_speed, command_center, recipe as recipe_mod, results, skill_map
from argoslive.web.benchmarks import View
from test_bench_ability import AbilityBackend
from test_bench_speed import Backend

MOCK_HW = {
    'cpu': {'model': 'AMD Ryzen 7', 'threads': 16},
    'gpus': [{'name': 'NVIDIA RTX 4070', 'vram_used_bytes': 0, 'vram_total_bytes': 12884901888}],
    'ram': {'total_bytes': 34359738368, 'available_bytes': 25769803776},
}

VALID_DIGEST_A = 'a' * 64
VALID_DIGEST_B = 'b' * 64


def make_ability_run(model='fixture:latest', digest=VALID_DIGEST_A, recipe_spec='standard', answer='reference', run_id='a' * 32):
    run = bench_ability.run(AbilityBackend(answer), model, hardware=lambda: copy.deepcopy(MOCK_HW))
    run['id'] = run_id
    run['manifest_digest'] = 'sha256:' + digest
    run['recipe'] = recipe_mod.resolve(recipe_spec, context=2048)
    run['settings']['recipe'] = run['recipe']
    return run


def make_speed_run(model='fixture:latest', digest=VALID_DIGEST_A, recipe_spec='standard', run_id='s' * 32):
    run = bench_speed.run(Backend(), model, hardware=lambda: copy.deepcopy(MOCK_HW))
    run['id'] = run_id
    run['manifest_digest'] = 'sha256:' + digest
    run['recipe'] = recipe_mod.resolve(recipe_spec, context=2048)
    run['settings']['recipe'] = run['recipe']
    return run


class ExperimentComparisonTests(unittest.TestCase):

    def test_rejection_of_identical_runs_repeated_practice(self):
        b = make_ability_run(run_id='1' * 32)
        c = make_ability_run(run_id='2' * 32)
        with self.assertRaisesRegex(ValueError, 'repeated practice is not an independent experiment'):
            results.compare_experiment(b, c)

    def test_rejection_of_multiple_interventions(self):
        b = make_ability_run(digest=VALID_DIGEST_A, recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(digest=VALID_DIGEST_B, recipe_spec='concise', run_id='2' * 32)
        b['model'] = 'model-a:latest'
        c['model'] = 'model-b:latest'
        with self.assertRaisesRegex(ValueError, 'Controlled experiment allows exactly one declared intervention; both model and recipe differed'):
            results.compare_experiment(b, c)

    def test_rejection_of_incomplete_or_missing_manifest_digest(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        c['manifest_digest'] = None
        with self.assertRaisesRegex(ValueError, 'requires verified manifest digests'):
            results.compare_experiment(b, c)

        c['manifest_digest'] = 'invalid_not_hex'
        with self.assertRaisesRegex(ValueError, 'requires verified manifest digests'):
            results.compare_experiment(b, c)

    def test_rejection_of_multiple_recipe_variable_tampering(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        c['settings']['context'] = 4096
        c['recipe']['context'] = 4096
        with self.assertRaisesRegex(ValueError, 'allows at most one recipe variable'):
            results.compare_experiment(b, c)

    def test_rejection_of_non_recipe_settings_mismatch(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        c['settings']['custom_setting'] = 999
        with self.assertRaisesRegex(ValueError, 'requires identical non-recipe settings'):
            results.compare_experiment(b, c)

    def test_rejection_of_hardware_mismatch(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        c['hardware']['ram']['total_bytes'] = 17179869184
        with self.assertRaisesRegex(ValueError, 'requires complete, matching hardware evidence'):
            results.compare_experiment(b, c)

    def test_rejection_of_missing_cpu_evidence(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['hardware']['cpu']['model'] = None
        c['hardware']['cpu']['model'] = None
        with self.assertRaisesRegex(ValueError, 'requires complete, matching hardware evidence'):
            results.compare_experiment(b, c)

    def test_rejection_of_missing_gpu_evidence(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['hardware']['gpus'] = None
        c['hardware']['gpus'] = None
        with self.assertRaisesRegex(ValueError, 'requires complete, matching hardware evidence'):
            results.compare_experiment(b, c)

    def test_rejection_of_missing_ram_evidence(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['hardware']['ram']['total_bytes'] = 0
        c['hardware']['ram']['total_bytes'] = 0
        with self.assertRaisesRegex(ValueError, 'requires complete, matching hardware evidence'):
            results.compare_experiment(b, c)

    def test_rejection_of_missing_or_mismatched_ollama_version(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['ollama_version'] = None
        with self.assertRaisesRegex(ValueError, 'requires recorded Ollama version evidence'):
            results.compare_experiment(b, c)
        b['ollama_version'] = '0.5.1'
        c['ollama_version'] = '0.5.2'
        with self.assertRaisesRegex(ValueError, 'requires identical Ollama version'):
            results.compare_experiment(b, c)

    def test_rejection_of_missing_or_mismatched_argos_version(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['argos_version'] = None
        with self.assertRaisesRegex(ValueError, 'requires recorded Argos version evidence'):
            results.compare_experiment(b, c)
        b['argos_version'] = '0.1.0'
        c['argos_version'] = '0.2.0'
        with self.assertRaisesRegex(ValueError, 'requires identical Argos version'):
            results.compare_experiment(b, c)

    def test_rejection_of_failed_restoration(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        c['restoration']['succeeded'] = False
        with self.assertRaisesRegex(ValueError, 'requires successful cleanup/restoration'):
            results.compare_experiment(b, c)

    def test_rejection_of_incomplete_or_cancelled_coverage(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        c['state'] = 'cancelled'
        c['coverage']['complete'] = False
        with self.assertRaisesRegex(ValueError, 'Cannot compare partial or cancelled runs'):
            results.compare_experiment(b, c)

    def test_declared_intervention_filter_mismatch(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        with self.assertRaisesRegex(ValueError, "Declared intervention 'model' does not match detected change 'recipe'"):
            results.compare_experiment(b, c, allowed_intervention='model')

    def test_valid_recipe_experiment_comparison(self):
        b = make_ability_run(recipe_spec='standard', answer='reference', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', answer='wrong', run_id='2' * 32)
        exp = results.compare_experiment(b, c, allowed_intervention='recipe')
        self.assertEqual(exp['schema'], 'argos-experiment/1')
        self.assertEqual(exp['intervention'], 'recipe')
        self.assertEqual(exp['delta']['verdict'], 'regression')
        self.assertEqual(exp['delta']['correct_delta'], -len(b['items']))
        self.assertTrue(any(it['changed'] for it in exp['items']))
        self.assertIn('Observed +1 is not confirmed general improvement', exp['limitations'])

    def test_valid_model_experiment_comparison(self):
        b = make_ability_run(digest=VALID_DIGEST_A, answer='wrong', run_id='1' * 32)
        c = make_ability_run(digest=VALID_DIGEST_B, answer='reference', run_id='2' * 32)
        b['model'] = 'model-a:latest'
        c['model'] = 'model-b:latest'
        exp = results.compare_experiment(b, c, allowed_intervention='model')
        self.assertEqual(exp['schema'], 'argos-experiment/1')
        self.assertEqual(exp['intervention'], 'model')
        self.assertEqual(exp['delta']['verdict'], 'observed_gain')
        self.assertEqual(exp['delta']['correct_delta'], len(c['items']))
        self.assertIn('Observed +1 is not confirmed general improvement', exp['limitations'])

    def test_valid_speed_experiment_comparison(self):
        b = make_speed_run(digest=VALID_DIGEST_A, run_id='1' * 32)
        c = make_speed_run(digest=VALID_DIGEST_B, run_id='2' * 32)
        b['model'] = 'model-a:latest'
        c['model'] = 'model-b:latest'
        exp = results.compare_experiment(b, c, allowed_intervention='model')
        self.assertEqual(exp['schema'], 'argos-experiment/1')
        self.assertEqual(exp['intervention'], 'model')
        self.assertEqual(exp['kind'], 'speed')
        self.assertEqual(exp['delta']['verdict'], 'speed_evaluated')
        self.assertTrue(len(exp['delta']['prompts']) > 0)
        self.assertIn('inspect median token rates', exp['delta']['summary'])

    def test_skill_map_recipe_binding_rejects_mismatched_preset(self):
        std_run = make_ability_run(model='fixture:latest', digest=VALID_DIGEST_A, recipe_spec='standard', run_id='1' * 32)
        concise_run = make_ability_run(model='fixture:latest', digest=VALID_DIGEST_A, recipe_spec='concise', run_id='2' * 32)

        facts_base = {
            'runs': [std_run],
            'doc_models': [],
            'storage': {},
        }
        selected = {'model': 'fixture:latest', 'digest': VALID_DIGEST_A}

        # With standard recipe active, std_run provides evidence
        sm_std = skill_map.build_skill_map(facts_base, selected, selected_recipe='standard')
        und_std = next(n for n in sm_std['domains'][0]['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(und_std['state'], 'qualified')

        # With concise recipe active, std_run is historical and cannot qualify concise build
        sm_concise = skill_map.build_skill_map(facts_base, selected, selected_recipe='concise')
        und_concise = next(n for n in sm_concise['domains'][0]['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(und_concise['state'], 'untested')

        # With concise run present and concise recipe active, concise run qualifies
        facts_concise = {
            'runs': [concise_run],
            'doc_models': [],
            'storage': {},
        }
        sm_concise_with_run = skill_map.build_skill_map(facts_concise, selected, selected_recipe='concise')
        und_c2 = next(n for n in sm_concise_with_run['domains'][0]['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(und_c2['state'], 'qualified')
        self.assertEqual(und_c2['evidence']['recipe']['preset'], 'concise')

    def test_view_experiment_comparison_auto_orientation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(Path(temp))
            b = make_ability_run(recipe_spec='standard', answer='reference', run_id='1' * 32)
            c = make_ability_run(recipe_spec='concise', answer='wrong', run_id='2' * 32)
            store.save(b)
            store.save(c)

            view = View(store)
            # Pass in reverse order (concise as first param, standard as second param)
            # View should auto-orient standard as baseline
            exp = view.experiment_comparison(c['id'], b['id'])
            self.assertEqual(exp['baseline']['id'], b['id'])
            self.assertEqual(exp['candidate']['id'], c['id'])
            self.assertEqual(exp['delta']['verdict'], 'regression')

    def test_acceptance_when_only_transient_gpu_usage_or_temperature_differs(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['hardware']['gpus'] = [{
            'bus': '0000:01:00.0',
            'name': 'NVIDIA GeForce RTX 4090',
            'vendor': 'NVIDIA',
            'vram_total_bytes': 24 * 1024**3,
            'vram_used_bytes': 2 * 1024**3,
            'driver': '550.54.14',
            'temperature_c': 45,
        }]
        c['hardware']['gpus'] = [{
            'bus': '0000:01:00.0',
            'name': 'NVIDIA GeForce RTX 4090',
            'vendor': 'NVIDIA',
            'vram_total_bytes': 24 * 1024**3,
            'vram_used_bytes': 8 * 1024**3,
            'driver': '550.54.14',
            'temperature_c': 65,
        }]
        res = results.compare_experiment(b, c)
        self.assertEqual(res['intervention'], 'recipe')

    def test_rejection_when_gpu_capacity_or_device_differs(self):
        b = make_ability_run(recipe_spec='standard', run_id='1' * 32)
        c = make_ability_run(recipe_spec='concise', run_id='2' * 32)
        b['hardware']['gpus'] = [{
            'bus': '0000:01:00.0',
            'name': 'NVIDIA GeForce RTX 4090',
            'vendor': 'NVIDIA',
            'vram_total_bytes': 24 * 1024**3,
            'vram_used_bytes': 2 * 1024**3,
            'driver': '550.54.14',
        }]
        c['hardware']['gpus'] = [{
            'bus': '0000:01:00.0',
            'name': 'NVIDIA GeForce RTX 4090',
            'vendor': 'NVIDIA',
            'vram_total_bytes': 16 * 1024**3,
            'vram_used_bytes': 2 * 1024**3,
            'driver': '550.54.14',
        }]
        with self.assertRaisesRegex(ValueError, 'requires complete, matching hardware evidence'):
            results.compare_experiment(b, c)


if __name__ == '__main__':
    unittest.main()

