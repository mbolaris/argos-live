import copy
import json
from pathlib import Path
import unittest
import tempfile

from argoslive import ability, results
from argoslive.bench_ability import summaries
from argoslive.shakedown import ledger as readiness

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'shakedown' / 'runs' / 'tool-schema-1.2.0.json'
MODEL_DIGEST = 'sha256:' + 'a' * 64
INSTRUCTION_DIGEST = 'b' * 64


def prepared_run():
    run = json.loads(FIXTURE.read_text(encoding='utf-8'))
    run['manifest_digest'] = MODEL_DIGEST
    run['prompt_fingerprint'] = {'workspace_agents_sha256': INSTRUCTION_DIGEST}
    return run


def response(item, outcome='nominal', codes=None, family='alpha', sim_id='run-a', partition='practice'):
    return {'item': item, 'outcome': outcome, 'codes': list(codes or []), 'family': family,
            'sim_id': sim_id, 'partition': partition, 'tier': 1}


class ReadinessLedgerTest(unittest.TestCase):
    def test_console_state_rules_are_named_and_partition_local(self):
        self.assertEqual(readiness._state([], []), readiness.STATE_UNTESTED)
        self.assertEqual(readiness._state([response('one')], []), readiness.STATE_WATCH)
        no_go = [response('one', 'failed', ['tool.wrong-name']),
                 response('two', 'failed', ['tool.wrong-name'])]
        self.assertEqual(readiness._state(no_go, []), readiness.STATE_NO_GO)
        low_accuracy = [response('one'), response('two', 'failed', ['tool.wrong-name']),
                        response('three', 'failed', ['tool.wrong-name'])]
        self.assertEqual(readiness._state(low_accuracy, []), readiness.STATE_NO_GO)
        go = [response(f'item-{n}', family='alpha' if n < 3 else 'beta') for n in range(6)]
        self.assertEqual(readiness._state(go, []), readiness.STATE_GO)
        latest_miss = [response('recent', 'failed', ['tool.wrong-name'])]
        self.assertEqual(readiness._state(go, latest_miss), readiness.STATE_WATCH)

    def test_responses_and_public_sim_never_project_answers_or_keys(self):
        run = prepared_run()
        internal = readiness.sim(run)
        self.assertTrue(internal['comparable'])
        self.assertEqual(len(internal['responses']), 40)
        self.assertEqual(internal['responses'][0]['codes'], ['tool.wrong-name'])
        self.assertEqual(internal['responses'][0]['detector']['matcher'], 'tool-name-is')
        public = readiness.public_sim(internal)
        encoded = json.dumps(public, sort_keys=True)
        for forbidden in ('"scorer"', '"expected"', '"reference":', '"when"', '"seed"',
                          '"fingerprint"', '"not_a_provided_tool"', '"prompt"'):
            self.assertNotIn(forbidden, encoded)

    def test_ledger_keeps_partitions_separate_and_ignores_unfinished_runs(self):
        complete = prepared_run()
        partial = copy.deepcopy(complete)
        partial['id'] = 'f' * 32
        partial['state'] = 'failed'
        partial['items'] = partial['items'][:2]
        partial['coverage'] = {'completed': 2, 'total': 40, 'complete': False}
        partial['summary'] = summaries(partial['items'])
        self.assertFalse(readiness.sim(partial)['comparable'])
        with tempfile.TemporaryDirectory() as temp:
            store = results.Store(temp)
            store.save(complete)
            store.save(partial)
            first = readiness.ledger(store, readiness.fingerprint_for(complete))
            second = readiness.ledger(store, readiness.fingerprint_for(complete))
        self.assertEqual(first, second)
        public = readiness.public_ledger(first)
        command = public['consoles']['tool-schema']
        self.assertEqual(command['practice']['scored'], 20)
        self.assertEqual(command['practice']['nominal'], 0)
        self.assertEqual(command['sealed']['scored'], 20)
        self.assertEqual(command['sealed']['nominal'], 0)
        self.assertEqual(command['practice']['state'], 'no-go')
        self.assertEqual(command['sealed']['state'], 'no-go')
        self.assertEqual(command['state'], command['sealed']['state'])
        self.assertEqual(public['consoles']['arithmetic']['practice']['state'], 'untested')
        self.assertNotIn('total', command)
        self.assertNotIn('fingerprint', json.dumps(public))

    def test_model_digest_and_instruction_fingerprint_are_both_required(self):
        run = prepared_run()
        self.assertEqual(readiness.fingerprint_for(run), readiness.fingerprint_for(copy.deepcopy(run)))
        missing_model = copy.deepcopy(run)
        missing_model['manifest_digest'] = None
        self.assertIsNone(readiness.fingerprint_for(missing_model))
        missing_instructions = copy.deepcopy(run)
        missing_instructions['prompt_fingerprint']['workspace_agents_sha256'] = None
        self.assertIsNone(readiness.fingerprint_for(missing_instructions))


if __name__ == '__main__':
    unittest.main()
