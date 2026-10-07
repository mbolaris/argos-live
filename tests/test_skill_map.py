import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'tests'))
from argoslive import skill_map, command_center as cc
from argoslive.results import Store
from argoslive.web.server import DashboardServer
from test_results import ability_result


class SkillMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / '.config/argos-live').mkdir(parents=True)
        self.store = Store(self.home / 'results')
        self.selected = {'model': 'qwen3:0.6b', 'digest': 'a' * 64}

    def test_empty_skill_map_has_correct_states_and_tally(self):
        facts = {'runs': [], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        result = skill_map.build_skill_map(facts, self.selected)
        self.assertEqual(result['schema'], 'argos-skill-map/1')
        self.assertEqual(result['model'], 'qwen3:0.6b')
        self.assertEqual(result['manifest_digest'], 'a' * 64)

        domains = {d['id']: d for d in result['domains']}
        self.assertEqual(len(domains), 6)
        self.assertIn('understanding', domains)
        self.assertIn('reasoning', domains)
        self.assertIn('planning', domains)
        self.assertIn('tools', domains)
        self.assertIn('memory', domains)
        self.assertIn('perception', domains)

        # Active nodes are untested initially
        doc_node = next(n for n in domains['understanding']['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node['state'], 'untested')
        self.assertTrue(doc_node['available'])

        # Future nodes are unavailable
        long_doc = next(n for n in domains['understanding']['nodes'] if n['id'] == 'long-documents')
        self.assertEqual(long_doc['state'], 'unavailable')
        self.assertFalse(long_doc['available'])
        self.assertIsNone(long_doc['action'])

        self.assertEqual(result['tally']['total_nodes'], 14)
        self.assertEqual(result['tally']['active_nodes'], 7)
        self.assertEqual(result['tally']['untested'], 7)
        self.assertEqual(result['tally']['unavailable'], 7)

    def test_document_qualification_qualifies_only_doc_short_node(self):
        doc_run = {
            'id': '11111111111111111111111111111111',
            'kind': 'ability',
            'suite': 'documents-short',
            'state': 'completed',
            'coverage': {'complete': True},
            'model': 'qwen3:0.6b',
            'manifest_digest': 'sha256:' + 'a' * 64,
            'qualification': {'qualified': True, 'checks': [{'name': 'answer', 'met': True}]},
            'summary': {'correct': 8, 'total': 8, 'format_errors': 0},
            'created': '2026-10-07T12:00:00+00:00',
        }
        facts = {'runs': [doc_run], 'doc_models': [doc_run], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        result = skill_map.build_skill_map(facts, self.selected)
        domains = {d['id']: d for d in result['domains']}
        doc_node = next(n for n in domains['understanding']['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node['state'], 'qualified')
        self.assertTrue(doc_node['evidence']['qualified'])

        # Other nodes remain unaffected
        inst_node = next(n for n in domains['understanding']['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(inst_node['state'], 'untested')

    def test_document_missed_criteria_sets_attention(self):
        doc_run = {
            'id': '11111111111111111111111111111111',
            'kind': 'ability',
            'suite': 'documents-short',
            'state': 'completed',
            'coverage': {'complete': True},
            'model': 'qwen3:0.6b',
            'manifest_digest': 'sha256:' + 'a' * 64,
            'qualification': {'qualified': False, 'checks': [{'name': 'answer', 'met': False}]},
            'summary': {'correct': 4, 'total': 8, 'format_errors': 1},
            'created': '2026-10-07T12:00:00+00:00',
        }
        facts = {'runs': [doc_run], 'doc_models': [doc_run], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        result = skill_map.build_skill_map(facts, self.selected)
        domains = {d['id']: d for d in result['domains']}
        doc_node = next(n for n in domains['understanding']['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node['state'], 'attention')

    def test_stale_model_or_unidentified_digest_cannot_qualify(self):
        doc_run = {
            'id': '11111111111111111111111111111111',
            'kind': 'ability',
            'suite': 'documents-short',
            'state': 'completed',
            'coverage': {'complete': True},
            'model': 'other:model',
            'manifest_digest': 'sha256:' + 'b' * 64,
            'qualification': {'qualified': True},
            'summary': {'correct': 8, 'total': 8, 'format_errors': 0},
            'created': '2026-10-07T12:00:00+00:00',
        }
        facts = {'runs': [doc_run], 'doc_models': [doc_run], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        # Run matches 'other:model' not 'qwen3:0.6b'
        result = skill_map.build_skill_map(facts, self.selected)
        domains = {d['id']: d for d in result['domains']}
        doc_node = next(n for n in domains['understanding']['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node['state'], 'untested')

        # Selected model has no digest
        no_digest = {'model': 'qwen3:0.6b', 'digest': None}
        result2 = skill_map.build_skill_map(facts, no_digest)
        domains2 = {d['id']: d for d in result2['domains']}
        doc_node2 = next(n for n in domains2['understanding']['nodes'] if n['id'] == 'doc-short')
        self.assertEqual(doc_node2['state'], 'untested')

    def test_cancelled_or_partial_run_ignored(self):
        cancelled_run = {
            'id': '22222222222222222222222222222222',
            'kind': 'ability',
            'suite': 'quick',
            'state': 'cancelled',
            'coverage': {'complete': False, 'completed': 5, 'total': 20},
            'model': 'qwen3:0.6b',
            'manifest_digest': 'sha256:' + 'a' * 64,
            'summary': {'correct': 5, 'total': 5, 'format_errors': 0,
                        'categories': {'instruction': {'correct': 4, 'total': 4, 'format_errors': 0}}},
            'created': '2026-10-07T12:00:00+00:00',
        }
        facts = {'runs': [cancelled_run], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        result = skill_map.build_skill_map(facts, self.selected)
        domains = {d['id']: d for d in result['domains']}
        inst_node = next(n for n in domains['understanding']['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(inst_node['state'], 'untested')

    def test_quick_suite_category_states(self):
        quick_run = {
            'id': '33333333333333333333333333333333',
            'kind': 'ability',
            'suite': 'quick',
            'state': 'completed',
            'coverage': {'complete': True, 'completed': 20, 'total': 20},
            'model': 'qwen3:0.6b',
            'manifest_digest': 'sha256:' + 'a' * 64,
            'summary': {
                'correct': 15, 'total': 20, 'format_errors': 1,
                'categories': {
                    'instruction': {'correct': 4, 'total': 4, 'format_errors': 0},  # qualified
                    'numeric': {'correct': 3, 'total': 4, 'format_errors': 0},      # measured
                    'choice': {'correct': 2, 'total': 4, 'format_errors': 1},       # attention
                    'json': {'correct': 0, 'total': 4, 'format_errors': 0},         # attention
                    'tool-call': {'correct': 4, 'total': 4, 'format_errors': 0},    # qualified
                }
            },
            'created': '2026-10-07T12:00:00+00:00',
        }
        facts = {'runs': [quick_run], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        result = skill_map.build_skill_map(facts, self.selected)
        domains = {d['id']: d for d in result['domains']}

        inst = next(n for n in domains['understanding']['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(inst['state'], 'qualified')

        num = next(n for n in domains['reasoning']['nodes'] if n['id'] == 'numeric-reasoning')
        self.assertEqual(num['state'], 'measured')

        choice = next(n for n in domains['reasoning']['nodes'] if n['id'] == 'knowledge-logic')
        self.assertEqual(choice['state'], 'attention')

        json_node = next(n for n in domains['planning']['nodes'] if n['id'] == 'structured-json')
        self.assertEqual(json_node['state'], 'attention')

        tool_node = next(n for n in domains['tools']['nodes'] if n['id'] == 'tool-formatting')
        self.assertEqual(tool_node['state'], 'qualified')
        self.assertIn('NOT execute tools', tool_node['scope'])

    def test_storage_retention_node_states(self):
        # 1. Qualified when reboot is retained
        view_retained = {
            'confirmed': True,
            'locations': [{'key': 'models', 'reboot': {'state': 'retained', 'verified_at': '2026-10-07T10:00:00Z'}}]
        }
        facts = {'runs': [], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': view_retained}
        res = skill_map.build_skill_map(facts, self.selected)
        mem = next(n for n in res['domains'][4]['nodes'] if n['id'] == 'storage-retention')
        self.assertEqual(mem['state'], 'qualified')

        # 2. Measured when confirmed but pending reboot
        view_confirmed = {
            'confirmed': True,
            'locations': [{'key': 'models', 'reboot': {'state': 'pending'}}]
        }
        facts['storage'] = view_confirmed
        res = skill_map.build_skill_map(facts, self.selected)
        mem = next(n for n in res['domains'][4]['nodes'] if n['id'] == 'storage-retention')
        self.assertEqual(mem['state'], 'measured')

        # 3. Attention when state is needs-attention
        view_att = {'confirmed': False, 'state': 'needs-attention', 'locations': []}
        facts['storage'] = view_att
        res = skill_map.build_skill_map(facts, self.selected)
        mem = next(n for n in res['domains'][4]['nodes'] if n['id'] == 'storage-retention')
        self.assertEqual(mem['state'], 'attention')

    def test_server_api_skill_map_route(self):
        command = cc.Controller(self.home, self.store,
                                identity=lambda _: {'model': 'qwen3:0.6b', 'digest': 'a' * 64})
        with DashboardServer(port=0, command=command) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
            worker.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                headers = {'Host': f'127.0.0.1:{server.server_port}', 'X-Argos-Token': server.token}

                # Authenticated GET /api/skill-map
                conn.request('GET', '/api/skill-map', headers=headers)
                res = conn.getresponse()
                self.assertEqual(res.status, 200)
                data = json.loads(res.read().decode('utf-8'))
                self.assertEqual(data['schema'], 'argos-skill-map/1')
                self.assertEqual(data['model'], 'qwen3:0.6b')
                self.assertEqual(len(data['domains']), 6)
                conn.close()
            finally:
                server.shutdown()

    def test_tightened_qualification_rejects_arbitrary_settings_or_versions(self):
        # 1. Arbitrary context (512 instead of 2048) rejected
        quick_bad_ctx = {
            'id': '44444444444444444444444444444444',
            'kind': 'ability',
            'suite': 'quick',
            'suite_version': '1.0.0',
            'settings': {'context': 512, 'temperature': 0},
            'state': 'completed',
            'coverage': {'complete': True, 'completed': 20, 'total': 20},
            'model': 'qwen3:0.6b',
            'manifest_digest': 'sha256:' + 'a' * 64,
            'summary': {'correct': 20, 'total': 20, 'format_errors': 0,
                        'categories': {'instruction': {'correct': 4, 'total': 4, 'format_errors': 0}}},
            'created': '2026-10-07T12:00:00+00:00',
        }
        facts = {'runs': [quick_bad_ctx], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        res = skill_map.build_skill_map(facts, self.selected)
        inst = next(n for n in res['domains'][0]['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(inst['state'], 'untested')

        # 2. Unsupported suite version rejected
        quick_bad_ver = dict(quick_bad_ctx, settings={'context': 2048, 'temperature': 0}, suite_version='0.9.0')
        facts2 = {'runs': [quick_bad_ver], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        res2 = skill_map.build_skill_map(facts2, self.selected)
        inst2 = next(n for n in res2['domains'][0]['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(inst2['state'], 'untested')

        # 3. Incomplete coverage rejected
        quick_incomplete = dict(quick_bad_ctx, settings={'context': 2048, 'temperature': 0}, suite_version='1.0.0',
                                coverage={'complete': False, 'completed': 19, 'total': 20})
        facts3 = {'runs': [quick_incomplete], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        res3 = skill_map.build_skill_map(facts3, self.selected)
        inst3 = next(n for n in res3['domains'][0]['nodes'] if n['id'] == 'instruction-following')
        self.assertEqual(inst3['state'], 'untested')

    def test_memory_domain_separates_storage_from_recall(self):
        facts = {'runs': [], 'doc_models': [], 'baseline': [], 'accepted_tasks': [], 'storage': None}
        res = skill_map.build_skill_map(facts, self.selected)
        mem_domain = next(d for d in res['domains'] if d['id'] == 'memory')
        self.assertEqual(mem_domain['label'], 'Memory & Recall')
        self.assertIn('separately', mem_domain['summary'])

        node_ids = [n['id'] for n in mem_domain['nodes']]
        self.assertIn('storage-retention', node_ids)
        self.assertIn('episodic-memory', node_ids)

        storage_node = next(n for n in mem_domain['nodes'] if n['id'] == 'storage-retention')
        self.assertIn('Filesystem', storage_node['title'])
        self.assertIn('host filesystem persistence only', storage_node['scope'])

        recall_node = next(n for n in mem_domain['nodes'] if n['id'] == 'episodic-memory')
        self.assertEqual(recall_node['title'], 'Conversational Memory & Recall')
        self.assertEqual(recall_node['state'], 'unavailable')
        self.assertIn('distinct from host drive filesystem persistence', recall_node['scope'])


if __name__ == '__main__':
    unittest.main()
