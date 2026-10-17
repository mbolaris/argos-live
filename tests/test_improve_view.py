import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.web import improve


def receipt(run_id, created, suite, model, correct, complete=True, format_errors=0):
    return {'id': run_id, 'created': created, 'suite': suite, 'model': model,
            'settings': {'assistant_model': model}, 'state': 'completed' if complete else 'failed',
            'summary': {'correct': correct, 'total': 20, 'format_errors': format_errors},
            'coverage': {'complete': complete}, 'elapsed_seconds': 30.0}


class ImproveViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.results = self.home / '.local/share/argos-live/results'
        self.results.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, value):
        (self.results / (value['id'] + '.json')).write_text(json.dumps(value))

    def test_history_best_and_gain_use_only_complete_assistant_runs(self):
        self.save(receipt('a' * 32, '2026-10-14T10:00:00+00:00', 'openclaw-quick', 'ollama/qwen3:0.6b', 7))
        self.save(receipt('b' * 32, '2026-10-14T11:00:00+00:00', 'openclaw-quick', 'ollama/qwen3:14b', 19, complete=False))
        self.save(receipt('c' * 32, '2026-10-14T12:00:00+00:00', 'openclaw-quick', 'ollama/qwen3:14b', 17))
        self.save(receipt('d' * 32, '2026-10-14T13:00:00+00:00', 'quick', 'qwen3:14b', 20))  # raw model
        value = improve.snapshot(self.home)
        self.assertEqual([run['id'][0] for run in value['runs']], ['a', 'b', 'c'])
        self.assertEqual(value['best']['id'], 'c' * 32)
        self.assertEqual(value['first']['id'], 'a' * 32)
        self.assertIsNone(value['journal'])

    def test_live_state_goes_stale_and_journal_is_tailed(self):
        state = self.home / '.local/state/argos-live'
        state.mkdir(parents=True)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        (state / 'assistant-bench-live.json').write_text(json.dumps({'phase': 'running', 'updated': old, 'items': []}))
        workspace = self.home / '.openclaw/workspace'
        workspace.mkdir(parents=True)
        (workspace / 'IMPROVEMENT-LOG.md').write_text('\n'.join(f'line {n}' for n in range(100)))
        value = improve.snapshot(self.home)
        self.assertEqual(value['live']['phase'], 'stale')
        self.assertEqual(len(value['journal']), improve.JOURNAL_LINES)
        self.assertEqual(value['journal'][-1], 'line 99')


if __name__ == '__main__':
    unittest.main()
