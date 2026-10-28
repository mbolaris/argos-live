import copy
from collections import Counter
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability


class AbilityTests(unittest.TestCase):
    def test_every_reference_wrong_and_malformed_answer(self):
        for suite, count in [('quick', 20), ('standard', 70), ('challenge', 40),
                             ('tool-schema', 40), ('tool-plan', 40)]:
            data = ability.load(suite)
            self.assertEqual(len(data['items']), count)
            self.assertEqual(data['omitted_categories'], ['code-execution'])
            for item in data['items']:
                with self.subTest(suite=suite, item=item['id']):
                    for field, outcome in [('reference', 'pass'), ('wrong', 'wrong_answer'), ('malformed', 'format_error')]:
                        result = ability.score(item, item[field])
                        self.assertEqual(result['outcome'], outcome)
                        self.assertEqual(result['score'], int(outcome == 'pass'))
                        self.assertFalse(result['tool_execution_verified'])

    def test_generation_is_reproducible_and_quick_is_exact_subset(self):
        spec = importlib.util.spec_from_file_location('original_suites', ROOT / 'scripts/build-original-ability-suites.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        standard = {item['id']: item for item in ability.load('standard')['items']}
        for suite in ('quick', 'standard', 'challenge', 'tool-schema', 'tool-plan'):
            self.assertEqual(ability.load(suite), generator.build(suite))
        for item in ability.load()['items']:
            self.assertEqual(item, standard[item['id']])
        self.assertFalse({item['id'] for item in ability.load('challenge')['items']} & set(standard))
        categories = Counter(item['scorer']['kind'] for item in ability.load('challenge')['items'])
        self.assertEqual(categories, {'numeric': 8, 'choice': 8, 'instruction': 8, 'json': 8, 'tool-call': 8})

    def test_tool_schema_has_disjoint_vocabulary_and_explicit_schemas(self):
        data = ability.load('tool-schema')
        partitions = {name: [item for item in data['items'] if item['scorer']['partition'] == name]
                      for name in ('practice', 'heldout')}
        names = {name: {schema['name'] for item in items for schema in item['scorer']['available_tools']}
                 for name, items in partitions.items()}
        keys = {name: {key for item in items for schema in item['scorer']['available_tools']
                       for key in schema['arguments']} for name, items in partitions.items()}
        self.assertEqual([len(partitions[name]) for name in ('practice', 'heldout')], [20, 20])
        self.assertFalse(names['practice'] & names['heldout'])
        self.assertFalse(keys['practice'] & keys['heldout'])
        for item in data['items']:
            self.assertIn('Available tool schemas:', item['prompt'])
            self.assertIn(item['scorer']['expected']['name'], item['prompt'])
            self.assertIn('exactly two top-level keys: "name" and "arguments"', item['prompt'])
            self.assertIn('Do not use "tool" as a key', item['prompt'])
        for items in partitions.values():
            positions = Counter(next(index for index, schema in enumerate(item['scorer']['available_tools'])
                                     if schema['name'] == item['scorer']['expected']['name'])
                                for item in items)
            self.assertEqual(sorted(positions.values()), [6, 7, 7])
            first_position_hits = sum(item['scorer']['available_tools'][0]['name'] ==
                                      item['scorer']['expected']['name'] for item in items)
            self.assertEqual(first_position_hits, 7)

    def test_tool_schema_rejects_a_first_tool_position_shortcut(self):
        data = copy.deepcopy(ability.load('tool-schema'))
        for item in data['items']:
            schemas = item['scorer']['available_tools']
            old = json.dumps({'tools': schemas}, separators=(',', ':'), ensure_ascii=False)
            target = next(schema for schema in schemas
                          if schema['name'] == item['scorer']['expected']['name'])
            reordered = [target] + [schema for schema in schemas if schema is not target]
            item['scorer']['available_tools'] = reordered
            new = json.dumps({'tools': reordered}, separators=(',', ':'), ensure_ascii=False)
            item['prompt'] = item['prompt'].replace(old, new, 1)
        with self.assertRaisesRegex(ValueError, 'target position must be balanced'):
            ability.validate(data)

    def test_tool_plan_is_balanced_and_uses_multiconstraint_requests(self):
        data = ability.load('tool-plan')
        partitions = {name: [item for item in data['items'] if item['scorer']['partition'] == name]
                      for name in ('practice', 'heldout')}
        self.assertEqual([len(partitions[name]) for name in ('practice', 'heldout')], [20, 20])
        names = {name: {schema['name'] for item in items for schema in item['scorer']['available_tools']}
                 for name, items in partitions.items()}
        keys = {name: {key for item in items for schema in item['scorer']['available_tools']
                       for key in schema['arguments']} for name, items in partitions.items()}
        self.assertFalse(names['practice'] & names['heldout'])
        self.assertFalse(keys['practice'] & keys['heldout'])
        for items in partitions.values():
            positions = Counter(next(index for index, schema in enumerate(item['scorer']['available_tools'])
                                     if schema['name'] == item['scorer']['expected']['name'])
                                for item in items)
            self.assertEqual(positions, Counter({0: 5, 1: 5, 2: 5, 3: 5}))
            self.assertEqual({len(item['scorer']['available_tools']) for item in items}, {4})
            self.assertTrue(all(len(item['scorer']['expected']['arguments']) >= 4 for item in items))
            self.assertTrue(all('Available tool schemas:' in item['prompt'] for item in items))

    def test_numeric_format_tolerance_and_ambiguous_rejection(self):
        item = {'id': 'math-01', 'scorer': {'kind': 'numeric', 'expected': '1234.5'}}
        for response in ('Answer: 1,234.5', 'Result: 1234.5.', '1.2345e3', '```text\n1234.5\n```'):
            self.assertEqual(ability.score(item, response)['outcome'], 'pass')
        for response in ('12 and 1234.5', '1,23', 'NaN', 'Infinity', '1234.5..'):
            self.assertEqual(ability.score(item, response)['outcome'], 'format_error')

    def test_json_duplicate_keys_extra_fields_and_boolean_integer_confusion(self):
        item = {'id': 'json-01', 'scorer': {'kind': 'json', 'expected': {'count': 1}}}
        for response in ('{"count":0,"count":1}', '{"count":true}', '{"count":1,"extra":2}', '{"count":NaN}'):
            self.assertEqual(ability.score(item, response)['outcome'], 'format_error')
        self.assertEqual(ability.score(item, '{"count":2}')['outcome'], 'wrong_answer')

    def test_instruction_whole_words_multiline_and_case(self):
        item = next(i for i in ability.load()['items'] if i['scorer']['kind'] == 'instruction')
        self.assertEqual(ability.score(item, 'already here now')['outcome'], 'wrong_answer')
        self.assertEqual(ability.score(item, 'ready\nnow')['outcome'], 'wrong_answer')
        upper = next(i for i in ability.load()['items'] if i['scorer'].get('uppercase'))
        self.assertEqual(ability.score(upper, upper['reference'].lower())['outcome'], 'wrong_answer')

    def test_output_bounds_unicode_and_non_string_response(self):
        item = ability.load()['items'][0]
        for response in (None, {}, 'x' * (ability.LIMIT + 1), '\ud800'):
            self.assertEqual(ability.score(item, response)['outcome'], 'format_error')

    def test_inert_tool_call_rejects_shape_but_does_not_execute(self):
        item = next(i for i in ability.load()['items'] if i['scorer']['kind'] == 'tool-call')
        self.assertEqual(ability.score(item, item['reference'])['outcome'], 'pass')
        self.assertEqual(ability.score(item, '{"name":"add_numbers","arguments":"run shell"}')['outcome'], 'format_error')

    def test_suite_drift_and_invalid_constraints_rejected(self):
        data = copy.deepcopy(ability.load())
        data['items'][1]['id'] = data['items'][0]['id']
        with self.assertRaises(ValueError):
            ability.validate(data)
        data = copy.deepcopy(ability.load())
        next(i for i in data['items'] if i['scorer']['kind'] == 'instruction')['scorer']['min_words'] = -1
        with self.assertRaises(ValueError):
            ability.validate(data)
        with self.assertRaises(ValueError):
            ability.load('../private')
        with self.assertRaises(ValueError):
            ability.load([])
