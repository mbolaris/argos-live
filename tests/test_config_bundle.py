import hashlib
import importlib.util
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('config_bundle', Path(__file__).resolve().parents[1] / 'scripts/inspect-config-bundle.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfigurationBundleTests(unittest.TestCase):
    def inspect_members(self, members, wrong_hash=False):
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / 'profile.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for name, value in members:
                    if isinstance(name, str):
                        raw = zipfile.ZipInfo(name)
                        raw.filename = name
                        raw.orig_filename = name
                        name = raw
                    bundle.writestr(name, value)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            return module.inspect(archive, '0' * 64 if wrong_hash else digest)

    def test_inventories_personas_without_extracting(self):
        report = self.inspect_members([('agents/argos/SOUL.md', 'fixture'), ('agents/nyx/SOUL.md', 'fixture'), ('agents/proteus/SOUL.md', 'fixture')])
        self.assertEqual(report['fileCount'], 3)
        self.assertFalse(report['recoveryBackup'])

    def test_wrong_hash_rejected(self):
        with self.assertRaises(ValueError):
            self.inspect_members([('config.json', '{}')], True)

    def test_traversal_and_platform_paths_rejected(self):
        for path in ('../config.json', '/config.json', 'C:/config.json', 'agents\\config.json', 'a/./config.json', 'file.json:stream'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.inspect_members([(path, '{}')])

    def test_case_collision_and_helpers_rejected(self):
        for files in ([('Config.json', '{}'), ('config.json', '{}')], [('helper.ps1', 'fixture')]):
            with self.assertRaises(ValueError):
                self.inspect_members(files)

    def test_link_rejected(self):
        link = zipfile.ZipInfo('profile-link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            self.inspect_members([(link, '../target')])


if __name__ == '__main__':
    unittest.main()
