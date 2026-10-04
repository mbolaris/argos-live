import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('packs', Path(__file__).parents[1] / 'runtime/argoslive/packs.py')
packs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packs)


class PackTests(unittest.TestCase):
    def fixture(self):
        files = {'agents/guide/persona/SOUL.md': b'Be a clear and helpful guide.\n',
                 'agents/guide/skills/example/SKILL.md': b'---\nname: example\n---\nA reviewed example.\n'}
        manifest = {'schema': 'argos-pack/1', 'id': 'example', 'version': '1.0',
                    'created': '2026-10-03T00:00:00Z',
                    'agents': [{'id': 'guide', 'name': 'Guide',
                                'persona_files': ['agents/guide/persona/SOUL.md'],
                                'skill_files': ['agents/guide/skills/example/SKILL.md'],
                                'model_preference': {'name': 'qwen3:0.6b'}}],
                    'files': [{'path': name, 'bytes': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()}
                              for name, data in files.items()]}
        return manifest, files

    def inspect_fixture(self, manifest, files, *, extra=(), expected=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'pack.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('manifest.json', json.dumps(manifest))
                for name, data in files.items():
                    bundle.writestr(name, data)
                for name, data in extra:
                    bundle.writestr(name, data)
            before = set(root.iterdir())
            result = packs.inspect(archive, expected)
            self.assertEqual(before, set(root.iterdir()))
            return result

    def test_valid_pack_is_inert(self):
        result = self.inspect_fixture(*self.fixture())
        self.assertFalse(result['extracted'])
        self.assertFalse(result['activation'])
        self.assertEqual(result['file_count'], 3)
        self.assertEqual(result['manifest']['agents'][0]['model_preference']['name'], 'qwen3:0.6b')

    def test_wrong_transfer_digest_and_tampered_payload(self):
        manifest, files = self.fixture()
        with self.assertRaisesRegex(ValueError, 'Transfer'):
            self.inspect_fixture(manifest, files, expected='0' * 64)
        files['agents/guide/persona/SOUL.md'] = b'Changed persona'
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.inspect_fixture(manifest, files)

    def test_forbidden_config_memory_and_unlisted_files(self):
        manifest, files = self.fixture()
        for field in ('credentials', 'permissions', 'providers', 'history'):
            invalid = copy.deepcopy(manifest)
            invalid[field] = {}
            with self.assertRaises(ValueError):
                self.inspect_fixture(invalid, files)
        invalid = copy.deepcopy(manifest)
        invalid['agents'][0]['persona_files'] = ['agents/guide/persona/MEMORY.md']
        with self.assertRaises(ValueError):
            self.inspect_fixture(invalid, files)
        with self.assertRaises(ValueError):
            self.inspect_fixture(manifest, files, extra=[('openclaw.json', b'{}')])

    def test_paths_duplicates_links_and_executables(self):
        manifest, files = self.fixture()
        for name in ('../outside.md', 'C:/secret.md', '/tmp/file', 'a\\b.md',
                     'a//b.md', 'a/NUL.txt', 'a/trailing.', 'a\0b.md'):
            with self.assertRaises(ValueError):
                self.inspect_fixture(manifest, files, extra=[(name, b'text')])
        with self.assertRaises(ValueError):
            self.inspect_fixture(manifest, files, extra=[('agents/guide/persona/soul.md', b'text')])
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFREG | 0o755):
            info = zipfile.ZipInfo('extra.md')
            info.create_system = 3
            info.external_attr = mode << 16
            with self.assertRaises(ValueError):
                self.inspect_fixture(manifest, files, extra=[(info, b'text')])

    def test_agent_and_assignment_conflicts(self):
        manifest, files = self.fixture()
        invalid = copy.deepcopy(manifest)
        duplicate = copy.deepcopy(invalid['agents'][0])
        duplicate['id'] = 'GUIDE'
        invalid['agents'].append(duplicate)
        with self.assertRaises(ValueError):
            self.inspect_fixture(invalid, files)
        invalid = copy.deepcopy(manifest)
        invalid['agents'][0]['model_preference']['name'] = 'C:/Windows/model.gguf'
        with self.assertRaises(ValueError):
            self.inspect_fixture(invalid, files)
        invalid = copy.deepcopy(manifest)
        invalid['files'][0]['bytes'] = True
        with self.assertRaises(ValueError):
            self.inspect_fixture(invalid, files)

    def test_json_skill_definition_is_declarative(self):
        manifest, files = self.fixture()
        old = manifest['agents'][0]['skill_files'][0]
        name = 'agents/guide/skills/example/definition.json'
        files.pop(old)
        data = json.dumps({'name': 'example', 'description': 'Example',
                           'instructions': 'Describe the result.', 'dependencies': ['ffmpeg']}).encode()
        files[name] = data
        manifest['agents'][0]['skill_files'] = [name]
        manifest['files'][1] = {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        self.inspect_fixture(manifest, files)
        files[name] = b'{"name":"example","description":"Example","instructions":"Describe","exec":"run"}'
        manifest['files'][1].update(bytes=len(files[name]), sha256=hashlib.sha256(files[name]).hexdigest())
        with self.assertRaises(ValueError):
            self.inspect_fixture(manifest, files)

    def test_size_limits_and_duplicate_json_fields(self):
        manifest, files = self.fixture()
        with patch.object(packs, 'MAX_TOTAL', 10):
            with self.assertRaises(ValueError):
                self.inspect_fixture(manifest, files)
        with self.assertRaises(ValueError):
            packs.decode(b'{"id":"a","id":"b"}')

    def test_corrupt_crc_is_rejected_without_extraction(self):
        manifest, files = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'corrupt.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('manifest.json', json.dumps(manifest))
                for name, data in files.items():
                    bundle.writestr(name, data)
            raw = archive.read_bytes()
            raw = raw.replace(b'Be a clear and helpful guide.', b'Be a clear and harmful guide.', 1)
            archive.write_bytes(raw)
            with patch.object(zipfile.ZipFile, 'extractall', side_effect=AssertionError('Never extract')):
                with self.assertRaises(ValueError):
                    packs.inspect(archive)
