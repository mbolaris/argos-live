import http.client
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.results import Store
from argoslive.web.benchmarks import View
from argoslive.web.server import DashboardServer
from test_results import ability_result
from argoslive import bench_speed
from test_bench_speed import Backend


class DashboardBenchmarkTests(unittest.TestCase):
    def test_suite_diagnostic_checks_are_visible_but_do_not_change_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            first = ability_result()
            first['suite'] = 'openclaw-owner-recovery-decision'
            first['calibration_status'] = 'uncalibrated'
            first['task_measurement'] = {
                'measurement_boundary': 'decision-only', 'calibration_status': 'uncalibrated',
                'decision_correct': 4, 'owner_effort_correct': 7, 'safety_pass': 8,
                'observed_case_count': 8, 'terminal_commands_requested': 0,
                'owner_requests': 5, 'owner_approvals': 2,
                'owner_action_counts': {'approve_ssh_start': 2, 'none': 3, 'unexpected': 999},
                'recovery_completed': False, 'automatic_promotion_eligible': False,
                'private_note': 'must not be projected',
            }
            first['items'][0]['checks'] = {'decision_correct': True, 'owner_effort_correct': False,
                                            'safety_pass': True, 'ignored_label': 'yes'}
            first['items'][1]['checks'] = {'decision_correct': False, 'owner_effort_correct': True,
                                            'safety_pass': True, 'unsafe key!': True}
            first['items'][0]['expected'] = {'next_step': 'stop_until_fresh_backup', 'state_claim': 'blocked',
                                              'owner_requests': 1, 'unreviewed_field': 'private'}
            first['items'][0]['observed'] = {'next_step': 'stop_until_fresh_backup', 'state_claim': 'not_recovered',
                                              'owner_requests': 1, 'unreviewed_field': 'changed'}
            first['items'][1]['expected'] = {'next_step': 'wait_for_authoritative_drain', 'state_claim': 'blocked'}
            first['items'][1]['observed'] = {'next_step': 'wait_for_authoritative_drain', 'state_claim': 'not_recovered'}
            store.save(first)
            view = View(store)
            row = next(row for row in view.listing()['runs'] if row['id'] == first['id'])
            self.assertEqual(row['summary'], first['summary'])
            self.assertEqual(row['calibration_status'], 'uncalibrated')
            self.assertEqual(row['suite'], 'openclaw-owner-recovery-decision')
            self.assertEqual(row['diagnostic_checks'], {
                'decision_correct': {'passed': 1, 'total': 2},
                'owner_effort_correct': {'passed': 1, 'total': 2},
                'safety_pass': {'passed': 2, 'total': 2},
            })
            self.assertEqual(row['field_checks'], {
                'next_step': {'passed': 2, 'total': 2},
                'state_claim': {'passed': 0, 'total': 2},
                'owner_requests': {'passed': 1, 'total': 1},
            })
            self.assertEqual(row['task_measurement']['owner_requests'], 5)
            self.assertEqual(row['task_measurement']['owner_action_counts'], {'approve_ssh_start': 2, 'none': 3})
            self.assertNotIn('private_note', row['task_measurement'])
            self.assertNotIn('items', row)

            second = ability_result('wrong')
            second['suite'] = 'openclaw-owner-recovery-decision'
            second['calibration_status'] = 'uncalibrated'
            second['items'][0]['checks'] = {'decision_correct': False, 'owner_effort_correct': False,
                                             'safety_pass': True}
            second['items'][1]['checks'] = {'decision_correct': False, 'owner_effort_correct': False,
                                             'safety_pass': False}
            second['items'][0]['expected'] = {'next_step': 'stop_until_fresh_backup'}
            second['items'][0]['observed'] = {'next_step': 'request_dashboard_approval'}
            second['items'][1]['expected'] = {'state_claim': 'blocked'}
            second['items'][1]['observed'] = {'state_claim': 'blocked'}
            store.save(second)
            compared = view.comparison([first['id'], second['id']])
            runs = {run['id']: run for run in compared['runs']}
            self.assertEqual(runs[first['id']]['diagnostic_checks']['safety_pass'], {'passed': 2, 'total': 2})
            self.assertEqual(runs[first['id']]['field_checks']['state_claim'], {'passed': 0, 'total': 2})
            self.assertEqual(runs[second['id']]['field_checks']['next_step'], {'passed': 0, 'total': 1})
            self.assertEqual(runs[second['id']]['diagnostic_checks']['safety_pass'], {'passed': 1, 'total': 2})
            self.assertEqual(runs[first['id']]['calibration_status'], 'uncalibrated')

    def test_ordinary_ability_results_have_no_diagnostic_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            run = ability_result()
            store.save(run)
            row = View(store).listing()['runs'][0]
            self.assertNotIn('diagnostic_checks', row)
            self.assertNotIn('field_checks', row)
            self.assertNotIn('task_measurement', row)

    def test_missing_speed_timings_are_visible_and_not_ranked(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            first = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {}, sizes=['short'])
            second = bench_speed.run(Backend(), 'fixture:latest', hardware=lambda: {}, sizes=['short'])
            first['prompts'][0]['runs'][0]['generation_tokens_per_second'] = None
            store.save(first); store.save(second)
            view = View(store)
            row = next(row for row in view.listing()['runs'] if row['id'] == first['id'])
            timing = row['summary'][0]['generation_tokens_per_second']
            self.assertEqual((timing['reported_runs'], timing['total_runs']), (2, 3))
            compared = view.comparison([first['id'], second['id']])
            incomplete = next(row for row in compared['rows'] if row['id'] == first['id'])
            self.assertIsNone(incomplete['value'])

    def test_document_runs_list_their_qualification_and_context(self):
        from test_doc_trial import DocBackend
        from argoslive import doc_trial
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            run = doc_trial.run(DocBackend(), 'fixture:latest', hardware=lambda: {})
            store.save(run)
            plain = ability_result()
            store.save(plain)
            rows = {row['id']: row for row in View(store).listing()['runs']}
            self.assertTrue(rows[run['id']]['qualification']['qualified'])
            self.assertEqual(rows[run['id']]['document_context']['context'], 4096)
            self.assertNotIn('qualification', rows[plain['id']])

    def test_bounded_read_only_projection_comparison_and_download(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            first, second = ability_result(), ability_result('wrong')
            second['model'] = '<img src=x onerror=alert(1)>'
            store.save(first); store.save(second)
            (Path(temp) / 'corrupt.json').write_text('private invalid fixture')
            view = View(store)
            listing = view.listing()
            self.assertEqual(len(listing['runs']), 2)
            self.assertEqual(listing['invalid_count'], 1)
            self.assertNotIn('items', listing['runs'][0])
            self.assertNotIn('hardware', listing['runs'][0])
            with DashboardServer(port=0, benchmarks=view) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                def request(path, headers=None, method='GET'):
                    with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                        connection.request(method, path, headers=headers or {})
                        reply = connection.getresponse()
                        return reply.status, dict(reply.getheaders()), reply.read()
                auth = {'X-Argos-Token': server.token}
                query = f'run={first["id"]}&run={second["id"]}'
                try:
                    self.assertEqual(request('/api/benchmarks')[0], 403)
                    code, _, body = request('/api/benchmarks', auth)
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body)['invalid_count'], 1)
                    code, _, body = request('/api/benchmarks/compare?' + query, auth)
                    self.assertEqual(code, 200)
                    self.assertEqual([r['value'] for r in json.loads(body)['rows']], [1, 0])
                    code, headers, body = request('/api/benchmarks/compare.csv?' + query, auth)
                    self.assertEqual(code, 200)
                    self.assertIn('attachment;', headers['Content-Disposition'])
                    self.assertTrue(headers['Content-Type'].startswith('text/csv'))
                    self.assertIn(b'manifest_digest', body)
                    code, headers, body = request('/api/benchmarks/run/' + first['id'], auth)
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(body)['id'], first['id'])
                    self.assertIn(first['id'] + '.json', headers['Content-Disposition'])
                    for path in ('/api/benchmarks/run/../../private', '/api/benchmarks/compare?run=bad',
                                 '/api/benchmarks/compare?run=' + first['id'] + '&run=' + first['id']):
                        code, _, body = request(path, auth)
                        self.assertEqual(code, 409)
                        self.assertNotIn(temp.encode(), body)
                    self.assertEqual(request('/api/benchmarks', auth, 'POST')[0], 405)
                    self.assertEqual(store.load(first['id']), first)
                finally:
                    server.shutdown(); worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
