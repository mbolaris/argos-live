import base64
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shutdown_smoke', ROOT / 'scripts/smoke-encrypted-shutdown.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EncryptedShutdownTests(unittest.TestCase):
    def test_journal_recovery_or_error_state_cannot_pass_as_clean(self):
        good = 'Filesystem state: clean\nFilesystem features: has_journal extent\n'
        self.assertEqual(module.filesystem_header(good)['Filesystem state'], 'clean')
        for bad in (good.replace('clean', 'clean with errors'), good.replace('extent', 'needs_recovery'), ''):
            with self.assertRaises(ValueError):
                module.filesystem_header(bad)

    def test_backup_requires_real_bytes_hashes_and_bounded_paths(self):
        prefix = 'home/argos/.local/state/argos-live/shutdown-test/'
        raw = b'explicitly synthetic persistence record'
        entry = {'base64': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
        receipt = {'cycle': 1, 'scope': 'synthetic persistence sentinels', 'upper_relative': 'rw',
                   'files': {prefix + '1-record.json': entry, prefix + '1-snapshot.json': entry}}
        self.assertEqual(len(module.checked_files(receipt, 1)), 2)
        with self.assertRaises(ValueError):
            module.checked_files(receipt, 2)
        for name in ('/etc/shadow', prefix + '../../secret', 'home/argos/other.json'):
            bad = {**receipt, 'files': {name: entry, prefix + '1-snapshot.json': entry}}
            with self.assertRaises(ValueError):
                module.checked_files(bad, 1)
        bad_entry = {**entry, 'sha256': '0' * 64}
        with self.assertRaises(ValueError):
            module.checked_files({**receipt, 'files': {prefix + '1-record.json': bad_entry,
                                                      prefix + '1-snapshot.json': entry}}, 1)

    def test_guest_command_fits_real_terminal_limit_and_is_syntactically_valid(self):
        import re
        import zlib
        line = module.guest_payload('a' * 32, 3)
        self.assertLess(len(line), 3500)
        encoded = re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)", line)[1]
        source = zlib.decompress(base64.b64decode(encoded)).decode()
        compile(source, '<disposable-guest>', 'exec')
        self.assertIn('argos.shutdown_test=' + 'a' * 32, source)


if __name__ == '__main__':
    unittest.main()
