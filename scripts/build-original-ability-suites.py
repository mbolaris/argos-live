#!/usr/bin/env python3
"""Reproduce original MIT-licensed v1 fixtures; never fetch external datasets."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.ability import validate

CHOICES = [
    ('Which number is prime?', ['15', '17', '21', '27'], 'B'),
    ('Which planet is closest to the Sun?', ['Earth', 'Mars', 'Mercury', 'Venus'], 'C'),
    ('What is binary 10 in decimal?', ['1', '2', '10', '16'], 'B'),
    ('Which is the chemical formula for water?', ['CO2', 'O2', 'H2O', 'NaCl'], 'C'),
    ('Which shape has three sides?', ['Triangle', 'Square', 'Pentagon', 'Hexagon'], 'A'),
    ('What is hexadecimal F in decimal?', ['12', '13', '14', '15'], 'D'),
    ('Which ocean is largest by area?', ['Arctic', 'Indian', 'Atlantic', 'Pacific'], 'D'),
    ('Which mammal lays eggs?', ['Cat', 'Platypus', 'Horse', 'Whale'], 'B'),
    ('Which unit measures electric current?', ['Ampere', 'Metre', 'Kelvin', 'Second'], 'A'),
    ('What is the chemical symbol for oxygen?', ['Ox', 'Og', 'O', 'On'], 'C'),
    ('Which pair contains exactly the binary digits?', ['1 and 2', '0 and 1', '0 and 2', '2 and 3'], 'B'),
    ('Which word comes first alphabetically?', ['Pear', 'Plum', 'Peach', 'Apple'], 'D'),
    ('Which number is divisible by both 2 and 3?', ['14', '15', '18', '25'], 'C'),
    ('Which data structure follows first-in first-out order?', ['Queue', 'Stack', 'Set', 'Tree'], 'A'),
]


def items():
    groups = {kind: [] for kind in ('numeric', 'choice', 'instruction', 'json', 'tool-call')}
    def add(kind, index, prompt, scorer, reference, wrong, malformed):
        prefix = {'numeric': 'math', 'choice': 'choice', 'instruction': 'instruction', 'json': 'json', 'tool-call': 'tool'}[kind]
        groups[kind].append({'id': f'{prefix}-{index:02}', 'prompt': prompt,
            'scorer': dict(kind=kind, **scorer), 'reference': reference, 'wrong': wrong, 'malformed': malformed})
    for i in range(1, 15):
        a, b = 7 * i + 3, i + 2
        value = a * b - i
        add('numeric', i, f'Calculate {a} * {b} - {i}. Answer with one number only.',
            {'expected': str(value)}, str(value), str(value + 1), 'No numeric answer.')
        question, choices, correct = CHOICES[i - 1]
        prompt = question + '\n' + '\n'.join(f'{letter}. {text}' for letter, text in zip('ABCD', choices)) + '\nAnswer with one letter only.'
        add('choice', i, prompt, {'expected': correct}, correct, 'A' if correct != 'A' else 'B', 'Unknown')
        keyword = ['ready', 'local', 'private', 'model', 'memory', 'voice', 'image',
                   'browser', 'files', 'network', 'storage', 'assistant', 'offline', 'workspace'][i - 1]
        uppercase = i % 2 == 0
        reference = f'{keyword} is ready'
        if uppercase:
            reference = reference.upper()
        prompt = f'Write one line of two to five words including the whole word "{keyword}".'
        if uppercase:
            prompt += ' Use uppercase letters only.'
        add('instruction', i, prompt, {'min_words': 2, 'max_words': 5, 'keywords': [keyword],
            'one_line': True, 'uppercase': uppercase}, reference, 'WRONG ANSWER' if uppercase else 'wrong answer', '')
        expected = {'name': f'item-{i}', 'count': i + 3, 'enabled': i % 2 == 0}
        prompt = f'Return only JSON with exactly three keys: name="item-{i}", count=the sum of {i} and 3, enabled={str(expected["enabled"]).lower()}. Use a string, integer and boolean respectively.'
        wrong = dict(expected, count=i + 4)
        add('json', i, prompt, {'expected': expected}, json.dumps(expected), json.dumps(wrong), '{invalid}')
        expected = {'name': 'add_numbers', 'arguments': {'a': i, 'b': i + 5}}
        prompt = f'Format a proposed tool call as JSON only: name "add_numbers", arguments containing integer a={i} and b={i + 5}. Do not run any tool. Use exactly name and arguments at the top level.'
        wrong = {'name': 'subtract_numbers', 'arguments': expected['arguments']}
        add('tool-call', i, prompt, {'expected': expected}, json.dumps(expected), json.dumps(wrong), 'Run add_numbers now')
    return groups


def build(suite):
    count = 4 if suite == 'quick' else 14
    return validate({'schema': 'argos-ability-suite/1', 'suite': suite, 'version': '1.0.0',
        'license': 'MIT', 'source': 'original-argos-live', 'omitted_categories': ['code-execution'],
        'items': [item for group in items().values() for item in group[:count]]})


if __name__ == '__main__':
    destination = ROOT / 'runtime/argoslive/data/ability'
    destination.mkdir(parents=True, exist_ok=True)
    for suite in ('quick', 'standard'):
        (destination / (suite + '.json')).write_text(json.dumps(build(suite), indent=2) + '\n', encoding='utf-8')
