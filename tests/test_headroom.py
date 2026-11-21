import contextlib
from datetime import datetime, timezone, timedelta
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_climb, bench_openclaw, headroom
from argoslive.bench_ability import summaries
from argoslive.results import Store
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer

MODEL = 'fixture:8b'
_counter = iter(range(1, 10 ** 6))


def stamp(day):
    return (datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat()


def saved_run(form, passes, *, day, model=MODEL, path='assistant', version=None, settings=None,
              heldout_passes=None, drop_items=0, state='completed', instructions=None):
    """A saved ability run over the real item IDs of a shipped form."""
    data, tasks, _path, omitted = bench_openclaw.suite_content(form)
    tasks = tasks[:len(tasks) - drop_items]
    remaining = {'practice': passes, 'heldout': heldout_passes if heldout_passes is not None else passes,
                 None: passes}
    items = []
    for task in tasks:
        half = task['scorer'].get('partition') if form != 'documents-short' else None
        half = half if half in ('practice', 'heldout') else None
        passed = remaining[half] > 0
        remaining[half] -= int(passed)
        item = {'item_id': task['id'], 'score': int(passed),
                'outcome': 'pass' if passed else 'wrong_answer', 'category': 'fixture'}
        if half:
            item['partition'] = half
        items.append(item)
    version = version or data['version']
    prefix = {'assistant': 'argos-openclaw-ability/' + form + '/',
              'model-only': 'ability/' + form + '/'}[path]
    run = {'schema': 'argos-bench/1', 'id': f'{next(_counter):032x}', 'created': stamp(day),
           'kind': 'ability', 'suite': ('openclaw-' if path == 'assistant' else '') + form,
           'suite_version': prefix + version, 'model': model, 'manifest_digest': 'sha256:' + 'a' * 64,
           'settings': settings or {'context': 2048}, 'hardware': {}, 'state': state, 'items': items,
           'coverage': {'completed': len(items), 'total': len(items), 'complete': state == 'completed'},
           'summary': summaries(items), 'restoration': {'succeeded': True}, 'omitted_categories': omitted}
    if instructions:
        run['prompt_fingerprint'] = {'workspace_agents_sha256': instructions * 64}
    return run


def climb_record(tier_index, passed, *, minute, model=MODEL, role='practice_baseline', status='completed'):
    tier, practice, _validation = auto_climb.CURRICULA[tier_index]
    tasks = auto_climb.load_task_file(practice)
    ids = [task['id'] for task in tasks['tasks']]
    record = {'schema': 'argos-auto-climb-suite-run/1', 'run_id': f'run-{next(_counter)}',
              'comparison_role': role, 'status': status, 'task_count': len(ids),
              'completed_task_count': len(ids), 'task_ids': ids,
              'finished_at': (datetime(2026, 11, 10, tzinfo=timezone.utc) + timedelta(minutes=minute)).isoformat(),
              'items': [{'task_id': task_id, 'passed': index < passed, 'checks': {'ok': index < passed},
                         'answer_sha256': 'c' * 64, 'assistant_session_id': 's'}
                        for index, task_id in enumerate(ids)],
              'model_identity': {'session_active_model': {'model': model, 'digest': 'd' * 64}},
              'config_fingerprint': {'config': 'e' * 64}, 'instructions_sha256': 'f' * 64,
              'suite_sha256': auto_climb._canonical_digest(tasks)}
    record['record_sha256'] = auto_climb._suite_run_digest(record)
    return record


class HeadroomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.store = Store(self.home / '.local/share/argos-live/results')

    def save(self, *runs):
        for run in runs:
            self.store.save(run)

    def report(self, **options):
        options.setdefault('model', MODEL)
        return headroom.report(self.store, home=self.home, **options)

    def row(self, result, form, partition=None, path='assistant'):
        found = [row for row in result['rows']
                 if (row['form'], row['partition'], row['path']) == (form, partition, path)]
        self.assertEqual(len(found), 1, (form, partition, path))
        return found[0]

    def climb(self, *records):
        path = self.home / auto_climb.SESSION_REL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'schema': auto_climb.SCHEMA,
                                    'suite_runs': {record['run_id']: record for record in records}}),
                        encoding='utf-8')

    def test_empty_store_lists_every_form_as_never_run(self):
        result = headroom.report(self.store, home=self.home)
        self.assertEqual(result['schema'], 'argos-headroom/1')
        self.assertEqual(result['build'], {'model': None, 'source': 'unknown'})
        self.assertTrue(result['rows'])
        self.assertEqual({row['status'] for row in result['rows']}, {'never run'})
        self.assertEqual(result['counts']['never run'], len(result['rows']))
        forms = {row['form'] for row in result['rows']}
        self.assertLessEqual({'quick', 'standard', 'challenge', 'challenge-hard', 'documents-short',
                              'documents-long', 'argos-foundation/1',
                              'argos-foundation/2', 'argos-foundation/3'}, forms)
        self.assertEqual(self.row(result, 'quick')['version'], '1.0.0')
        self.assertEqual(self.row(result, 'quick')['scores'], [])
        # Tool forms always have one row per half, never a combined one.
        self.assertEqual(self.row(result, 'tool-schema', 'practice')['items'], 20)
        self.assertEqual(self.row(result, 'tool-schema', 'heldout')['items'], 20)
        self.assertEqual(self.row(result, 'challenge-hard', 'practice')['items'], 40)
        self.assertEqual(self.row(result, 'challenge-hard', 'heldout')['items'], 40)
        self.assertEqual(self.row(result, 'documents-long', 'practice')['items'], 20)
        self.assertEqual(self.row(result, 'documents-long', 'heldout')['items'], 20)
        self.assertFalse([row for row in result['rows'] if row['form'] == 'tool-schema' and row['partition'] is None])
        self.assertFalse([row for row in result['rows'] if row['path'] == 'model-only'])

    def test_saturated_needs_three_most_recent_runs_at_ninety_percent(self):
        self.save(saved_run('quick', 10, day=1), saved_run('quick', 18, day=2),
                  saved_run('quick', 19, day=3), saved_run('quick', 20, day=4))
        row = self.row(self.report(), 'quick')
        self.assertEqual(row['status'], 'saturated')
        self.assertEqual([score['correct'] for score in row['scores']], [20, 19, 18])
        self.assertEqual(row['matched_runs'], 4)
        self.assertEqual(row['suite_version'], 'argos-openclaw-ability/quick/1.0.0')

    def test_one_recent_run_below_ninety_percent_has_room(self):
        self.save(saved_run('quick', 20, day=1), saved_run('quick', 17, day=2), saved_run('quick', 20, day=3))
        row = self.row(self.report(), 'quick')
        self.assertEqual(row['status'], 'has room')
        self.assertEqual([(score['correct'], score['total']) for score in row['scores']],
                         [(20, 20), (17, 20), (20, 20)])
        self.assertEqual(row['scores'][1]['percent'], 85.0)

    def test_fewer_than_three_matched_runs_is_too_few(self):
        self.save(saved_run('quick', 20, day=1), saved_run('quick', 20, day=2))
        row = self.row(self.report(), 'quick')
        self.assertEqual(row['status'], 'too few runs')
        self.assertEqual(len(row['scores']), 2)

    def test_suite_versions_are_never_mixed(self):
        self.save(saved_run('challenge', 40, day=1, version='1.2.0'),
                  saved_run('challenge', 40, day=2, version='1.2.0'),
                  saved_run('challenge', 40, day=3, version='1.2.0'),
                  saved_run('challenge', 22, day=4))
        row = self.row(self.report(), 'challenge')
        self.assertEqual(row['status'], 'too few runs')
        self.assertEqual([score['correct'] for score in row['scores']], [22])
        self.assertEqual(row['left_out']['other_suite_versions'], 3)

    def test_models_are_never_mixed(self):
        self.save(saved_run('quick', 20, day=1, model='other:1b'), saved_run('quick', 20, day=2, model='other:1b'),
                  saved_run('quick', 20, day=3, model='other:1b'), saved_run('quick', 12, day=4))
        row = self.row(self.report(), 'quick')
        self.assertEqual(row['status'], 'too few runs')
        self.assertEqual(row['left_out']['other_models'], 3)
        self.assertEqual(self.row(self.report(model='other:1b'), 'quick')['status'], 'saturated')

    def test_settings_are_never_mixed_and_newest_run_sets_the_row(self):
        self.save(saved_run('quick', 20, day=1), saved_run('quick', 20, day=2), saved_run('quick', 20, day=3),
                  saved_run('quick', 11, day=4, settings={'context': 4096}))
        row = self.row(self.report(), 'quick')
        self.assertEqual(row['status'], 'too few runs')
        self.assertEqual([score['correct'] for score in row['scores']], [11])
        self.assertEqual(row['left_out']['other_settings'], 3)

    def test_partial_cancelled_and_other_path_runs_are_left_out(self):
        self.save(saved_run('quick', 20, day=1), saved_run('quick', 20, day=2),
                  saved_run('quick', 15, day=3, drop_items=5),
                  saved_run('quick', 20, day=4, state='cancelled'),
                  saved_run('quick', 3, day=5, path='model-only'))
        result = self.report()
        row = self.row(result, 'quick')
        self.assertEqual(row['status'], 'too few runs')
        self.assertEqual(row['left_out']['incomplete_or_partial'], 2)
        raw = self.row(result, 'quick', path='model-only')
        self.assertEqual(raw['suite_version'], 'ability/quick/1.0.0')
        self.assertEqual([score['correct'] for score in raw['scores']], [3])

    def test_practice_and_held_out_halves_are_separate_rows(self):
        self.save(*(saved_run('tool-schema', 20, heldout_passes=9, day=day) for day in (1, 2, 3)))
        result = self.report()
        practice = self.row(result, 'tool-schema', 'practice')
        heldout = self.row(result, 'tool-schema', 'heldout')
        self.assertEqual(practice['status'], 'saturated')
        self.assertEqual(heldout['status'], 'has room')
        self.assertEqual([(score['correct'], score['total']) for score in heldout['scores']], [(9, 20)] * 3)
        self.assertNotIn(40, [score['total'] for row in result['rows'] for score in row['scores']])

    def test_instruction_changes_share_a_row_and_are_flagged(self):
        self.save(saved_run('quick', 15, day=1, instructions='1'), saved_run('quick', 15, day=2, instructions='1'),
                  saved_run('quick', 17, day=3, instructions='2'))
        row = self.row(self.report(), 'quick')
        self.assertEqual(row['status'], 'has room')
        self.assertTrue(row['instructions_varied'])
        self.assertIn('has room *', headroom.render(self.report()))

    def test_auto_climb_tiers_use_practice_baseline_runs_only(self):
        self.climb(climb_record(0, 8, minute=1), climb_record(0, 8, minute=2), climb_record(0, 8, minute=3),
                   climb_record(2, 5, minute=4), climb_record(2, 7, minute=5), climb_record(2, 8, minute=6),
                   climb_record(1, 8, minute=7), climb_record(1, 8, minute=8, role='candidate_practice'),
                   climb_record(1, 8, minute=9, status='partial'),
                   climb_record(1, 8, minute=10, model='other:1b'))
        result = self.report()
        first = self.row(result, 'argos-foundation/1', 'practice', 'auto-climb')
        self.assertEqual(first['status'], 'saturated')
        third = self.row(result, 'argos-foundation/3', 'practice', 'auto-climb')
        self.assertEqual(third['status'], 'has room')
        self.assertEqual([score['correct'] for score in third['scores']], [8, 7, 5])
        self.assertEqual(third['version'], '3.0.0')
        second = self.row(result, 'argos-foundation/2', 'practice', 'auto-climb')
        self.assertEqual(second['status'], 'too few runs')
        self.assertEqual(second['matched_runs'], 1)
        self.assertEqual(second['left_out']['incomplete_or_partial'], 1)
        self.assertEqual(second['left_out']['other_models'], 1)

    def test_tampered_auto_climb_record_is_not_counted(self):
        record = climb_record(0, 8, minute=1)
        record['items'][0]['passed'] = False
        self.climb(record)
        row = self.row(self.report(), 'argos-foundation/1', 'practice', 'auto-climb')
        self.assertEqual(row['status'], 'never run')
        self.assertEqual(row['left_out']['incomplete_or_partial'], 1)

    def test_build_comes_from_configuration_then_latest_run(self):
        self.save(saved_run('quick', 20, day=1, model='older:1b'), saved_run('quick', 20, day=2))
        self.assertEqual(headroom.report(self.store, home=self.home)['build'],
                         {'model': MODEL, 'source': 'latest saved run'})
        (self.home / '.config/argos-live').mkdir(parents=True)
        (self.home / '.config/argos-live/state.json').write_text(json.dumps({'model': 'older:1b'}))
        (self.home / '.openclaw').mkdir()
        (self.home / '.openclaw/openclaw.json').write_text(json.dumps(
            {'agents': {'defaults': {'model': {'primary': 'ollama/older:1b'}}}}))
        result = headroom.report(self.store, home=self.home)
        self.assertEqual(result['build'], {'model': 'older:1b', 'source': 'configured'})
        self.assertEqual(self.row(result, 'quick')['matched_runs'], 1)

    def test_report_does_not_write_to_the_store(self):
        self.save(saved_run('quick', 20, day=1))
        before = sorted((path.name, path.stat().st_mtime_ns) for path in self.store.root.iterdir())
        self.report()
        self.assertEqual(before, sorted((path.name, path.stat().st_mtime_ns) for path in self.store.root.iterdir()))

    def test_command_prints_table_and_json(self):
        self.save(*(saved_run('quick', 20, day=day) for day in (1, 2, 3)))
        argv = ['--results-dir', str(self.store.root), '--home', str(self.home)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(headroom.main(argv), 0)
        text = output.getvalue()
        self.assertIn(f'Deployed build: {MODEL} (latest saved run)', text)
        line = next(line for line in text.splitlines() if line.startswith('quick'))
        self.assertIn('20/20  20/20  20/20', line)
        self.assertTrue(line.endswith('saturated'))
        self.assertIn('never run', text)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(headroom.main(argv + ['--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), headroom.report(self.store, home=self.home))

    def test_argos_command_delegates_to_headroom(self):
        spec = importlib.util.spec_from_file_location('headroom_cli', ROOT / 'runtime/argos.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        args, remaining = cli.command_parser().parse_known_args(['headroom', '--json'])
        self.assertEqual(args.delegate, 'argoslive.headroom')
        self.assertEqual(remaining, ['--json'])


class HeadroomRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.store = Store(self.home / '.local/share/argos-live/results')
        self.server = DashboardServer(port=0, benchmarks=BenchmarkView(self.store))
        self.server.owner_home = self.home
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, path, *, token=None, method='GET'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, headers={'X-Argos-Token': token} if token else {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_route_requires_token_and_matches_the_module(self):
        for day in (1, 2, 3):
            self.store.save(saved_run('quick', 20, day=day))
        self.assertEqual(self.request('/api/headroom')[0], 403)
        status, body = self.request('/api/headroom', token=self.server.token)
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result, headroom.report(self.store, home=self.home))
        self.assertEqual(next(row for row in result['rows'] if row['form'] == 'quick')['status'], 'saturated')

    def test_route_rejects_unknown_parameters_and_has_no_write_method(self):
        self.assertEqual(self.request('/api/headroom?model=x', token=self.server.token)[0], 400)
        self.assertNotEqual(self.request('/api/headroom', token=self.server.token, method='POST')[0], 200)


if __name__ == '__main__':
    unittest.main()
