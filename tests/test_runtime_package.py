import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_cli', ROOT / 'runtime/argos.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class RuntimePackageTests(unittest.TestCase):
    def test_checkout_and_installed_paths(self):
        self.assertEqual(cli.runtime_package_path(), ROOT / 'runtime')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(cli.runtime_package_path(root / 'bin/argos'),
                             Path('/usr/local/lib/argos-live'))
            self.assertEqual(cli.runtime_package_path(root / 'bin/argos', root / 'lib'),
                             root / 'lib')

    def test_checkout_cli_help(self):
        result = subprocess.run([sys.executable, str(ROOT / 'runtime/argos.py'), '--help'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('setup', result.stdout)
        for name in ('bench', 'pull', 'pack', 'dashboard', 'addons'):
            self.assertIn(name, result.stdout)
        self.assertTrue(cli.argoslive.__version__)

    def test_group_and_delegated_help(self):
        for command in (['bench'], ['pack'], ['bench', 'speed'], ['pull'],
                        ['pack', 'export'], ['pack', 'import'], ['pack', 'apply'],
                        ['pack', 'rollback'], ['dashboard'], ['addons']):
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, str(ROOT / 'runtime/argos.py'),
                                         *command, '--help'], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)

    def test_delegation_preserves_options_and_pack_operation(self):
        from unittest.mock import Mock, patch
        module = Mock()
        with patch('importlib.import_module', return_value=module):
            cli.main(['bench', 'speed', '--model', 'fixture:test', '--size', 'short', '--json'])
            module.main.assert_called_with(['--model', 'fixture:test', '--size', 'short', '--json'])
            cli.main(['pull', '--state', 'fixture.json', 'create', 'fixture:test'])
            module.main.assert_called_with(['--state', 'fixture.json', 'create', 'fixture:test'])
            cli.main(['pack', 'apply', 'fixture-stage', '--gateway-stopped'])
            module.main.assert_called_with(['apply', 'fixture-stage', '--gateway-stopped'])

    def test_legacy_json_option_on_either_side_of_command(self):
        for argv in (['--json', 'hw'], ['hw', '--json']):
            args, remaining = cli.command_parser().parse_known_args(argv)
            self.assertTrue(args.json)
            self.assertEqual(args.command, 'hw')
            self.assertEqual(remaining, [])

    @unittest.skipUnless(sys.platform != 'win32' and shutil.which('bash'),
                         'Package installation fixture requires Linux bash/tar')
    def test_package_installs_without_caches_and_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'lib'
            subprocess.run(['bash', str(ROOT / 'scripts/install-runtime-package.sh'),
                            str(target)], check=True, timeout=30)
            self.assertEqual((target / 'argoslive/__init__.py').read_bytes(),
                             (ROOT / 'runtime/argoslive/__init__.py').read_bytes())
            self.assertEqual(list(target.rglob('*.pyc')), [])
            self.assertEqual(list(target.rglob('__pycache__')), [])
            program = ('import sys; sys.path.insert(0, sys.argv[1]); '
                       'import argoslive, argoslive.pack_apply, argoslive.catalog, argoslive.addons; '
                       'from argoslive.web.server import ASSETS; '
                       'from argoslive.ability import load, DATA; '
                       'assert len(load()["items"]) == 20; assert (DATA / "NOTICE.txt").is_file(); '
                       'assert (ASSETS / "index.html").is_file(); '
                       'argoslive.catalog.load(); argoslive.addons.load(); print(argoslive.__version__)')
            result = subprocess.run([sys.executable, '-c', program, str(target)],
                                    capture_output=True, text=True, check=True, timeout=30)
            self.assertEqual(result.stdout.strip(), cli.argoslive.__version__)
