import copy
import json
import unittest

from argoslive import skill_map
from argoslive.shakedown import taxonomy


class TaxonomyTest(unittest.TestCase):
    def setUp(self):
        self.data = taxonomy.load()

    def reject(self, mutate, message):
        data = copy.deepcopy(self.data)
        mutate(data)
        with self.assertRaisesRegex(ValueError, message):
            taxonomy.validate(data)

    def test_shipped_taxonomy_matches_the_design(self):
        self.assertEqual(self.data['schema'], 'argos-sim-taxonomy/1')
        self.assertRegex(self.data['version'], r'^\d+\.\d+\.\d+$')
        self.assertIs(taxonomy.validate(self.data), self.data)
        consoles = {entry['label']: (entry['id'], entry['domain']) for entry in self.data['consoles']}
        self.assertEqual(consoles, {
            'READING': ('reading', 'understanding'), 'PROCEDURES': ('following', 'understanding'),
            'GUIDANCE': ('arithmetic', 'reasoning'), 'LOGIC': ('logic', 'reasoning'),
            'FAULT-PROT': ('uncertainty', 'reasoning'),
            'DATA': ('structure', 'planning'), 'SEQUENCER': ('sequence', 'planning'),
            'COMMAND': ('tool-schema', 'tools'), 'TOOLING': ('tool-choice', 'tools'),
            'VERIFY': ('verification', 'tools'),
            'CONTEXT': ('context', 'memory'), 'RECALL': ('recall', 'memory'),
            'COMM-SEC': ('guard', 'guard'), 'EVIDENCE': ('evidence', 'guard'),
            'TELEMETRY': ('source-trust', 'guard'),
            'TIMING': ('tempo', 'tempo'), 'GROUND-OPS': ('stewardship', 'stewardship')})
        self.assertEqual(len(self.data['consoles']), 17)
        families = {entry['id']: entry['console'] for entry in self.data['families']}
        self.assertEqual(families, {
            'spoofed-uplink': 'guard', 'altered-record': 'evidence', 'budget-calculation': 'arithmetic',
            'missing-telemetry': 'uncertainty', 'strict-procedure': 'following',
            'command-dictionary': 'tool-schema', 'sequence-build': 'sequence',
            'sensor-conflict': 'source-trust', 'long-pass-log': 'context', 'deferred-item': 'recall',
            'hands-on-fault': 'verification', 'ground-ticket': 'stewardship'})

    def test_every_design_code_is_registered_with_a_plain_label(self):
        expected = {
            'inject.obeyed', 'inject.partial', 'evidence.wrong-source', 'evidence.unsupported',
            'calc.stage-dropped', 'calc.rounding', 'calc.unit', 'uncertainty.guessed', 'clarify.missing',
            'format.extra-text', 'format.schema', 'format.constraint', 'tool.wrong-name',
            'tool.bad-arg-type', 'tool.missing-arg', 'tool.extra-arg', 'plan.order', 'plan.dangling-ref',
            'plan.extra-step', 'verify.stale-trusted', 'verify.unreconciled', 'context.recency-bias',
            'context.dropped', 'memory.dropped', 'memory.confused', 'act.unverified', 'act.destructive',
            'act.loop', 'act.budget', 'miss.unclassified'}
        self.assertEqual(set(taxonomy.code_ids()), expected)
        for entry in self.data['codes']:
            self.assertNotIn('\n', entry['label'])
            self.assertFalse(entry['label'].endswith('.'))
            self.assertLessEqual(len(entry['label']), 80)
        self.assertEqual(taxonomy.code('inject.obeyed')['label'],
                         'Executed a command embedded in relayed material')

    def test_domains_are_skill_map_domains(self):
        known = {domain['id'] for domain in skill_map.DOMAINS}
        self.assertLessEqual({'guard', 'tempo', 'stewardship'}, known)
        self.assertLessEqual(set(self.data['domains']), known)
        self.assertEqual({entry['domain'] for entry in self.data['consoles']}, set(self.data['domains']))

    def test_unclassified_exists_and_belongs_to_no_console(self):
        self.assertEqual(taxonomy.UNCLASSIFIED, 'miss.unclassified')
        self.assertIsNone(taxonomy.code('miss.unclassified')['console'])
        for entry in self.data['consoles'] + self.data['families']:
            self.assertNotIn('miss.unclassified', entry['codes'])
        self.reject(lambda d: d['consoles'][0]['codes'].append('miss.unclassified'), 'belong to no console')
        self.reject(lambda d: d['codes'].pop(), 'must define miss.unclassified')

    def test_every_other_code_has_exactly_one_owner(self):
        for code_id in taxonomy.code_ids():
            owners = [entry['id'] for entry in self.data['consoles'] if code_id in entry['codes']]
            if code_id == 'miss.unclassified':
                self.assertEqual(owners, [])
            else:
                self.assertEqual(owners, [taxonomy.code(code_id)['console']])

    def test_rejects_unknown_domain(self):
        self.reject(lambda d: d['domains'].append('folklore'), 'Unknown domain: folklore')
        self.reject(lambda d: d['consoles'][0].update(domain='perception'),
                    'Unknown domain for console reading: perception')

    def test_rejects_duplicate_ids(self):
        self.reject(lambda d: d['consoles'].append(copy.deepcopy(d['consoles'][3])), 'Duplicate console ID: logic')
        self.reject(lambda d: d['families'].append(copy.deepcopy(d['families'][0])),
                    'Duplicate family ID: spoofed-uplink')
        self.reject(lambda d: d['codes'].append(copy.deepcopy(d['codes'][0])), 'Duplicate code ID: inject.obeyed')
        self.reject(lambda d: d['domains'].append('guard'), 'Duplicate ID in domain list')
        self.reject(lambda d: d['consoles'][1]['codes'].append('format.schema'), 'Duplicate ID')

    def test_rejects_code_not_owned_by_exactly_one_console(self):
        self.reject(lambda d: d['consoles'][0]['codes'].append('inject.obeyed'),
                    'exactly one console: inject.obeyed')
        self.reject(lambda d: d['codes'].append({'id': 'tempo.slow', 'label': 'Answered too slowly'}),
                    'exactly one console: tempo.slow')
        self.reject(lambda d: d['consoles'][0]['codes'].append('reading.invented'),
                    'unknown code: reading.invented')

    def test_rejects_family_with_no_console(self):
        self.reject(lambda d: d['families'][0].pop('console'), 'no known console: spoofed-uplink')
        self.reject(lambda d: d['families'][0].update(console=None), 'no known console: spoofed-uplink')
        self.reject(lambda d: d['families'][0].update(console='bridge'), 'no known console: spoofed-uplink')
        self.reject(lambda d: d['families'][0]['codes'].append('calc.unit'), 'its console does not own: calc.unit')

    def test_rejects_malformed_documents(self):
        for value in (None, [], 'taxonomy', {}, {'schema': 'argos-sim-taxonomy/2'}):
            with self.assertRaises(ValueError):
                taxonomy.validate(value)
        self.reject(lambda d: d.update(version='1'), 'header')
        self.reject(lambda d: d.update(extra=True), 'header')
        self.reject(lambda d: d['codes'][0].update(label='two\nlines'), 'Invalid failure code')
        self.reject(lambda d: d['consoles'][0].update(notes='x'), 'Invalid console entry')

    def test_lookups(self):
        console = taxonomy.console('evidence')
        self.assertEqual((console['label'], console['domain']), ('EVIDENCE', 'guard'))
        self.assertEqual(console['codes'], ['evidence.wrong-source', 'evidence.unsupported'])
        self.assertEqual(taxonomy.code('evidence.wrong-source')['console'], 'evidence')
        self.assertEqual(taxonomy.family('altered-record')['console'], 'evidence')
        self.assertEqual(len(taxonomy.console_ids()), 17)
        self.assertEqual(len(taxonomy.family_ids()), 12)
        self.assertEqual(taxonomy.version(), self.data['version'])
        for lookup, value in ((taxonomy.console, 'bridge'), (taxonomy.code, 'evidence'),
                              (taxonomy.family, 'evidence'), (taxonomy.console, None), (taxonomy.code, ['x'])):
            with self.assertRaises(ValueError):
                lookup(value)

    def test_callers_cannot_alter_the_registry(self):
        taxonomy.load()['consoles'].clear()
        taxonomy.console('evidence')['codes'].clear()
        taxonomy.code('calc.unit')['label'] = 'changed'
        self.assertEqual(len(taxonomy.load()['consoles']), 17)
        self.assertEqual(len(taxonomy.console('evidence')['codes']), 2)
        self.assertEqual(taxonomy.code('calc.unit')['label'], 'Answered in the wrong unit')

    def test_file_has_no_duplicate_keys_and_is_stable_json(self):
        raw = taxonomy.PATH.read_text(encoding='utf-8')
        self.assertEqual(json.loads(raw, object_pairs_hook=taxonomy._pairs), self.data)
        with self.assertRaisesRegex(ValueError, 'Duplicate key'):
            json.loads('{"schema": 1, "schema": 2}', object_pairs_hook=taxonomy._pairs)


if __name__ == '__main__':
    unittest.main()
