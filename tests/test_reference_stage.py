import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = load('exporter', 'export-personal-config.py')
stager = load('stager', 'stage-config-reference.py')


class ReferenceStageTests(unittest.TestCase):
    def test_real_export_stages_and_never_overwrites_existing_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'; source.mkdir()
            export = root / 'export'; export.mkdir()
            (source / 'openclaw.json').write_text(json.dumps({'agents': {'entries': {}}}))
            with contextlib.redirect_stdout(io.StringIO()):
                exporter.export(source, export)
            archive = export / 'argos-nyx-proteus-config.zip'
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            target = root / 'reference'
            self.assertEqual(stager.stage(archive, digest, target), 3)
            self.assertTrue((target / 'reference/openclaw.redacted.json').is_file())
            with self.assertRaises(ValueError):
                stager.stage(archive, digest, target)

    def test_checksum_and_unsafe_entries_fail_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../escaped', 'outside')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            for expected in ('0' * 64, digest):
                with self.assertRaises(ValueError):
                    stager.stage(archive, expected, root / 'target')
                self.assertFalse((root / 'target').exists())
            self.assertFalse((root.parent / 'escaped').exists())

    def test_cross_platform_paths_are_rejected(self):
        for path in ('C:/file', 'a\\file', '/absolute', 'a/../file', 'a//b', 'CON.txt', 'a./b'):
            with self.assertRaises(ValueError):
                stager.safe_name(path)

    def test_valid_zip_crc_and_transfer_hash_do_not_hide_payload_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {'reference/openclaw.redacted.json': b'{}', 'migration-reference.json': b'{}'}
            manifest = {'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()]}
            files['reference/openclaw.redacted.json'] = b'{"changed":true}'
            archive = root / 'tampered.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                for name, data in files.items():
                    z.writestr(name, data)
                z.writestr('manifest.json', json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'manifest hash mismatch'):
                stager.stage(archive, hashlib.sha256(archive.read_bytes()).hexdigest(), root / 'target')
            self.assertFalse((root / 'target').exists())


if __name__ == '__main__':
    unittest.main()
