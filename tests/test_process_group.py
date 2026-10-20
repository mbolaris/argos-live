"""Guard invalid IDs without ever invoking a kernel signal function."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive.owned_ollama import stop_group


class ProcessGroupGuards(unittest.TestCase):
    def test_non_integer_and_reserved_ids_never_reach_signal_function(self):
        class Coerced:
            def __index__(self):
                return 1
        for pid in (MagicMock(), Coerced(), True, False, None, '123', 1, 0, -1):
            with self.subTest(kind=type(pid).__name__), \
                    patch('argoslive.owned_ollama.os.killpg', create=True) as kill:
                with self.assertRaisesRegex(ValueError, 'Refusing'):
                    stop_group(SimpleNamespace(pid=pid))
                kill.assert_not_called()

    def test_callers_own_group_and_session_are_never_signalled(self):
        with patch('argoslive.owned_ollama.os.getpgrp', return_value=101, create=True), \
                patch('argoslive.owned_ollama.os.getsid', return_value=202, create=True), \
                patch('argoslive.owned_ollama.os.killpg', create=True) as kill:
            for pid in (101, 202):
                with self.assertRaisesRegex(ValueError, 'Refusing'):
                    stop_group(SimpleNamespace(pid=pid))
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
