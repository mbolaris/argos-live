import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import catalog, pack_import

spec = importlib.util.spec_from_file_location('catalog_refresh', ROOT / 'scripts/update-catalog.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.data = catalog.load()
        self.model = self.data['models'][0]

    def test_bundled_catalog_and_licenses_are_valid_and_exact_preferences_only(self):
        self.assertEqual(len(self.data['models']), 9)
        inventory = catalog.inventory(self.data)
        result = pack_import.model_resolution({'name': 'ollama/' + self.model['tag']}, inventory)
        self.assertEqual(result['status'], 'in catalog')
        self.assertFalse(result['ready'])
        self.assertEqual(pack_import.model_resolution({'name': 'windows-only-alias'}, inventory)['status'], 'unresolved')
        self.assertEqual(pack_import.model_resolution({'name': self.model['tag'], 'quantization': 'F16'}, inventory)['status'], 'unresolved')

    def test_fit_boundaries_and_full_context_cache_are_explicit(self):
        unknown = catalog.fit(self.model, None)
        required, comfortable = unknown['estimated_required_bytes'], unknown['comfortable_bytes']
        self.assertEqual(unknown['status'], 'unknown')
        self.assertEqual(catalog.fit(self.model, required - 1)['status'], "won't fit")
        self.assertEqual(catalog.fit(self.model, required)['status'], 'tight')
        self.assertEqual(catalog.fit(self.model, comfortable - 1)['status'], 'tight')
        self.assertEqual(catalog.fit(self.model, comfortable)['status'], 'fits')
        self.assertFalse(catalog.fit(self.model, comfortable)['inference_ready'])
        small = catalog.fit(self.model, comfortable, context_tokens=4096, device='cpu')
        self.assertEqual(unknown['kv_cache_bytes'], small['kv_cache_bytes'] * 8)
        with self.assertRaises(ValueError):
            catalog.fit(self.model, comfortable, context_tokens=0)

    def test_vision_overhead_and_moe_all_weight_size_are_counted(self):
        vision = copy.deepcopy(self.model)
        vision['capabilities'].append('vision')
        self.assertEqual(catalog.fit(vision, None)['overhead_bytes'] - catalog.fit(self.model, None)['overhead_bytes'], 512 * 1024**2)
        moe = next(m for m in self.data['models'] if m['family'] == 'qwen3moe')
        self.assertEqual(catalog.fit(moe, None)['weight_bytes'], moe['weight_bytes'])
        self.assertGreater(moe['weight_bytes'], 10 * 2**30)

    def test_missing_metadata_and_tampered_totals_are_rejected(self):
        for key in ('quantization', 'license', 'manifest_digest', 'kv_cache'):
            data = copy.deepcopy(self.data)
            del data['models'][0][key]
            with self.assertRaises(ValueError):
                catalog.validate(data)
        data = copy.deepcopy(self.data)
        data['models'][0]['total_download_bytes'] += 1
        with self.assertRaises(ValueError):
            catalog.validate(data)
        data = copy.deepcopy(self.data)
        data['models'][0]['tag'] = 'qwen3:cloud'
        with self.assertRaises(ValueError):
            catalog.validate(data)

    def fake_sources(self):
        choices = json.loads((catalog.DEFAULT.parent / 'catalog-spec.json').read_text())
        responses = {}
        for choice, model in zip(choices['models'], self.data['models']):
            name, tag = choice['tag'].rsplit(':', 1)
            name = name if '/' in name else 'library/' + name
            base = 'https://registry.ollama.ai/v2/' + name
            config = json.dumps({'model_format': 'gguf', 'model_family': choice['family'],
                                 'file_type': choice['quantization'], 'model_type': model['parameter_label']}).encode()
            config_descriptor = {'digest': 'sha256:' + hashlib.sha256(config).hexdigest(),
                                 'size': len(config), 'mediaType': 'application/vnd.docker.container.image.v1+json'}
            key = model['license_digests'][0]
            license_text = (catalog.DEFAULT.parent / 'licenses' / (key.split(':')[1] + '.txt')).read_bytes()
            license_descriptor = {'digest': key, 'size': len(license_text), 'mediaType': 'application/vnd.ollama.image.license'}
            manifest = {'config': config_descriptor,
                        'layers': [{'digest': 'sha256:' + 'a' * 64, 'size': model['weight_bytes'],
                                    'mediaType': 'application/vnd.ollama.image.model'},
                                   license_descriptor, license_descriptor]}
            responses[base + '/manifests/' + tag] = (json.dumps(manifest).encode(), {})
            responses[base + '/blobs/' + config_descriptor['digest']] = (config, {})
            responses[base + '/blobs/' + key] = (license_text, {})
            kv = model['kv_cache']
            architecture = json.dumps({'num_hidden_layers': kv['layers'], 'num_key_value_heads': kv['kv_heads'],
                                       'hidden_size': kv['head_dim'] * 8, 'num_attention_heads': 8}).encode()
            source = choice['architecture_source']
            responses[source] = (architecture, {'X-Repo-Commit': 'b' * 40})
            responses[source.replace('/main/', '/' + 'b' * 40 + '/')] = (architecture, {})
        return choices, responses

    def test_refresh_checks_metadata_and_deduplicates_without_fetching_weights(self):
        choices, responses = self.fake_sources()
        calls = []
        def get(url):
            calls.append(url)
            return responses[url]
        data, licenses = refresh.build(choices, get)
        self.assertEqual(len(data['models']), 9)
        self.assertTrue(licenses)
        self.assertFalse(any(url.endswith('sha256:' + 'a' * 64) for url in calls))
        self.assertEqual(len(data['models'][0]['license_digests']), 1)
        self.assertTrue(all(not m['capability_verified'] for m in data['models']))

    def test_refresh_rejects_bad_digest_size_revision_and_quantization(self):
        choices, responses = self.fake_sources()
        manifest_url = 'https://registry.ollama.ai/v2/library/qwen3/manifests/0.6b'
        original = responses[manifest_url]
        manifest = json.loads(original[0])
        manifest['config']['size'] += 3
        responses[manifest_url] = (json.dumps(manifest).encode(), {})
        with self.assertRaisesRegex(ValueError, 'checksum/size'):
            refresh.build(choices, responses.__getitem__)
        responses[manifest_url] = (original[0], {'Docker-Content-Digest': 'sha256:' + 'f' * 64})
        with self.assertRaisesRegex(ValueError, 'manifest digest'):
            refresh.build(choices, responses.__getitem__)
        responses[manifest_url] = original
        architecture_url = choices['models'][0]['architecture_source']
        body, headers = responses[architecture_url]
        responses[architecture_url] = (body, {})
        with self.assertRaisesRegex(ValueError, 'immutable revision'):
            refresh.build(choices, responses.__getitem__)
        responses[architecture_url] = (body, headers)
        choices['models'][0]['quantization'] = 'F16'
        with self.assertRaisesRegex(ValueError, 'Quantization changed'):
            refresh.build(choices, responses.__getitem__)

    def test_packaged_license_integrity_and_public_host_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'catalog.json').write_text(json.dumps(self.data))
            (root / 'licenses').mkdir()
            for source in (catalog.DEFAULT.parent / 'licenses').glob('*.txt'):
                (root / 'licenses' / source.name).write_bytes(source.read_bytes())
            key = self.model['license_digests'][0].split(':')[1]
            (root / 'licenses' / (key + '.txt')).write_bytes(b'Corrupt license fixture')
            with self.assertRaisesRegex(ValueError, 'license checksum'):
                catalog.load(root / 'catalog.json')
        with self.assertRaises(ValueError):
            refresh.fetch('http://127.0.0.1/private')
        with self.assertRaises(ValueError):
            refresh.PublicRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://unapproved.example/model')
