import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import code_sandbox as sandbox


class SandboxPolicyTests(unittest.TestCase):
    def test_unsupported_platform_never_executes(self):
        with patch.object(sandbox.sys, 'platform', 'win32'), patch.object(sandbox.subprocess, 'Popen') as spawn:
            with self.assertRaises(sandbox.Unavailable):
                sandbox.run('print(1)')
            self.assertFalse(sandbox.available())
            spawn.assert_not_called()

    def test_source_and_timeout_bounds(self):
        for source, timeout in [('', 3), ('x' * 65537, 3), (None, 3), ('pass', 0), ('pass', 11),
                                ('pass', float('nan')), ('pass', True)]:
            with self.assertRaises(ValueError):
                sandbox.run(source, timeout=timeout)

    def test_seccomp_is_native_instruction_stream(self):
        program = sandbox.seccomp()
        self.assertEqual(len(program) % 8, 0)
        self.assertGreater(len(program), 100)


@unittest.skipUnless(sys.platform == 'linux', 'Actual sandbox requires Linux')
class LinuxSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sandbox.available():
            if os.environ.get('ARGOS_SANDBOX_REQUIRED') == '1':
                raise RuntimeError('Required actual Linux sandbox probe failed')
            raise unittest.SkipTest('bubblewrap/isolation unavailable; code execution remains disabled')

    def assert_completed(self, source):
        result = sandbox.run(source)
        self.assertEqual(result['state'], 'completed', result)
        return result

    def test_temporary_work_only_no_host_reads_or_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            outside = Path(temp) / 'outside'
            source = '\n'.join([
                'from pathlib import Path', 'import os',
                'Path("result").write_text("sandbox-only")',
                'assert Path("result").read_text() == "sandbox-only"',
                'assert not Path("/etc/passwd").exists()',
                'assert not Path("/proc/self/environ").exists()',
                'assert "ARGOS_SANDBOX_TEST_SECRET" not in os.environ',
                f'paths = [{str(outside)!r}, "/escaped", "/usr/bin/escaped"]',
                'for path in paths:', '    try: Path(path).write_text("bad")',
                '    except OSError: pass', '    else: raise AssertionError("outside write permitted")',
                'print("isolated")'])
            with patch.dict(os.environ, ARGOS_SANDBOX_TEST_SECRET='private fixture'):
                result = self.assert_completed(source)
            self.assertEqual(result['stdout'], 'isolated\n')
            self.assertFalse(outside.exists())
            result = self.assert_completed('from pathlib import Path\nassert not Path("result").exists()')

    def test_network_and_process_creation_are_kernel_denied(self):
        self.assert_completed('''import socket, os, errno, ctypes
for operation in (socket.socket, os.fork):
    try: operation()
    except OSError as error: assert error.errno == errno.EPERM
    else: raise AssertionError("kernel restriction absent")
libc = ctypes.CDLL(None, use_errno=True)
for number in (435, 272, 308, 250, 310, 438, 0x40000000 + 41):
    assert libc.syscall(number, 0, 0) == -1
    assert ctypes.get_errno() == errno.EPERM
''')

    def test_timeout_cancel_output_and_memory_are_bounded(self):
        result = sandbox.run('while True: pass', timeout=0.3)
        self.assertEqual(result['state'], 'timeout')
        self.assertLess(result['elapsed_seconds'], 2.5)
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(sandbox.run('while True: pass', cancel=cancel)['state'], 'cancelled')
        result = sandbox.run('print("x" * 30000)')
        self.assertEqual(result['state'], 'output_limit')
        self.assertLessEqual(len(result['stdout']), sandbox.OUTPUT_LIMIT)
        self.assert_completed('try:\n    a = bytearray(512 * 1024**2)\nexcept MemoryError:\n    print("bounded")\nelse:\n    raise AssertionError("memory unrestricted")')

    def test_wrong_and_malformed_code_have_explicit_error(self):
        for source in ('assert 1 == 2', 'def broken('):
            result = sandbox.run(source)
            self.assertEqual(result['state'], 'error')
            self.assertNotEqual(result['returncode'], 0)


if __name__ == '__main__':
    unittest.main()
