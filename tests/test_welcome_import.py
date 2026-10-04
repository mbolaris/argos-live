"""Ensure headless test discovery skips only an unavailable GUI dependency."""
from pathlib import Path
import subprocess
import sys
import unittest


class WelcomeImportTests(unittest.TestCase):
    def test_discovery_without_tkinter(self):
        program = '''
import importlib.abc
import sys
import unittest
class NoTk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'tkinter' or fullname.startswith('tkinter.'):
            raise ModuleNotFoundError('No tkinter in headless fixture', name='tkinter')
sys.meta_path.insert(0, NoTk())
suite = unittest.defaultTestLoader.discover('tests', pattern='test_welcome.py')
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful(), 'Missing tkinter must not fail discovery'
assert len(result.skipped) == 1, 'Expected a module-level GUI skip'
assert 'tkinter' in result.skipped[0][1]
'''
        result = subprocess.run(
            [sys.executable, '-c', program],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
