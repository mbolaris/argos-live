import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('iso_report', ROOT / 'scripts/report-iso-build.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ISOReportTests(unittest.TestCase):
    def fixture(self, root):
        data = b'\0' * 0x8001 + b'CD001' + b'public fixture'
        (root / 'argos-live-amd64.iso').write_bytes(data)
        (root / 'SHA256SUMS').write_text(hashlib.sha256(data).hexdigest() + '  argos-live-amd64.iso\n')
        (root / 'packages.txt').write_text('linux-image-amd64 1\nxfce4 1\nlightdm 1\npython3 1\n')
        (root / 'build.log').write_text('Public isolated build fixture\n')

    def test_report_verifies_output_without_claiming_boot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            report = module.report(root, 'a' * 40)
            self.assertEqual(report['schema'], 'argos-iso-build/1')
            self.assertFalse(report['boot_acceptance'])
            self.assertFalse(report['physical_acceptance'])
            self.assertTrue(report['credential_pattern_scan_passed'])
            self.assertEqual(report['pins']['DEBIAN_SUITE'], 'trixie')

    def test_wrong_checksum_type_packages_or_commit_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, value in [('SHA256SUMS', '0' * 64 + '  argos-live-amd64.iso'),
                                ('argos-live-amd64.iso', 'not an ISO'),
                                ('packages.txt', 'python3 1\n')]:
                self.fixture(root)
                (root / name).write_text(value)
                with self.assertRaises(ValueError):
                    module.report(root, 'a' * 40)
            self.fixture(root)
            with self.assertRaises(ValueError):
                module.report(root, 'main')

    def test_credential_patterns_and_chunk_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'build.log'
            for value in (b'-----BEGIN OPENSSH PRIVATE KEY-----', b'ghp_' + b'a' * 30,
                          b'github_pat_' + b'a' * 40, b'sk-' + b'a' * 30):
                path.write_bytes(b'x' * (1024**2 - 10) + b'\n' + value)
                with self.assertRaises(ValueError):
                    module.scan_log(path)


if __name__ == '__main__':
    unittest.main()
