import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refresh_plugin_manifest', ROOT / 'scripts/refresh-plugin-manifest.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class ImprovementPluginBundleTests(unittest.TestCase):
    def test_package_versions_and_pinned_dependency_lock_match(self):
        package = json.loads((ROOT / 'openclaw-plugin/argos-improve/package.json').read_text())
        lock = json.loads((ROOT / 'openclaw-plugin/argos-improve/package-lock.json').read_text())
        manifest = json.loads((ROOT / 'openclaw-plugin/argos-improve/openclaw.plugin.json').read_text())
        self.assertEqual(package['version'], lock['version'])
        self.assertEqual(package['version'], lock['packages']['']['version'])
        self.assertEqual(lock['packages']['node_modules/typebox']['version'], package['dependencies']['typebox'])
        self.assertEqual(manifest['id'], 'argos-improve')
        self.assertEqual(manifest['contracts']['tools'], ['argos_evaluate', 'argos_evaluate_wait', 'argos_evaluate_status', 'argos_compare', 'argos_log',
                         'argos_inspect', 'argos_audit_instructions', 'argos_edit_instructions', 'argos_resolve_instructions',
                         'argos_proctor_start', 'argos_proctor_status', 'argos_proctor_item',
                         'argos_proctor_answer', 'argos_proctor_continue', 'argos_proctor_submit',
                         'argos_proctor_feedback'])
        self.assertTrue(all(manifest['toolMetadata'][name]['optional'] for name in
                           ('argos_evaluate_wait', 'argos_evaluate_status', 'argos_inspect', 'argos_audit_instructions', 'argos_edit_instructions', 'argos_resolve_instructions',
                            'argos_proctor_start', 'argos_proctor_status', 'argos_proctor_item',
                            'argos_proctor_answer', 'argos_proctor_continue', 'argos_proctor_submit',
                            'argos_proctor_feedback')))
        self.assertTrue((ROOT / 'runtime/argoslive/data/SELF-IMPROVEMENT-AGENTS.md').is_file())
        self.assertFalse((ROOT / 'openclaw-plugin/argos-improve/runtime').exists())

    def test_generated_manifest_covers_the_code_bundle_and_detects_drift(self):
        source = ROOT / 'openclaw-plugin/argos-improve'
        self.assertEqual(refresh.inventory(source),
                         json.loads((source / 'files.sha256.json').read_text()))
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'plugin'
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('node_modules', 'files.sha256.json'))
            actual = refresh.inventory(target)
            self.assertIn('skills/argos-improvement/SKILL.md', actual)
            self.assertFalse(any(name.startswith('node_modules/') for name in actual))
            self.assertFalse(any(name.startswith('runtime/') for name in actual))
            (target / 'index.js').write_text('changed')
            changed = refresh.inventory(target)
            self.assertNotEqual(actual['index.js'], changed['index.js'])

    def test_agent_skill_teaches_the_host_verified_experiment_path(self):
        skill = (ROOT / 'openclaw-plugin/argos-improve/skills/argos-improvement/SKILL.md').read_text()
        guide = (ROOT / 'runtime/argoslive/data/SELF-IMPROVEMENT-AGENTS.md').read_text()
        for text in (skill, guide):
            for tool in ('argos_inspect', 'argos_audit_instructions', 'argos_edit_instructions', 'argos_resolve_instructions'):
                self.assertIn(tool, text)
            self.assertIn('two distinct', text)
            self.assertIn('held-out', text)
            self.assertIn('owner edits', text)
        self.assertIn('argos_audit_instructions', guide)
        self.assertIn('argos_audit_instructions', skill)
        self.assertIn('2/20', guide)
        self.assertIn('4/70', guide)
        self.assertIn('3/40', guide)


if __name__ == '__main__':
    unittest.main()
