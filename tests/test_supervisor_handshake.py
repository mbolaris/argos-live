import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.owned_ollama import supervisor_pid


@unittest.skipUnless(sys.platform == 'linux', 'Linux supervisor pipe handshake')
class SupervisorHandshakeTests(unittest.TestCase):
    def process(self, source):
        process = subprocess.Popen([sys.executable, '-c', source],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            process.stdout.close()
        self.addCleanup(cleanup)
        return process

    def test_cold_supervisor_beyond_old_five_second_limit_and_split_record(self):
        process = self.process('import os,time\ntime.sleep(5.2)\n'
            'os.write(1,str(os.getpid()).encode())\ntime.sleep(.1)\nos.write(1,b"\\n")\ntime.sleep(30)')
        self.assertEqual(supervisor_pid(process, deadline=time.monotonic() + 8), process.pid)

    def test_partial_record_does_not_prevent_cancel_or_deadline(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                process = self.process('import os,time\nos.write(1,b"12")\ntime.sleep(30)')
                event = threading.Event()
                timer = threading.Timer(.2, event.set)
                if cancelled:
                    timer.start()
                    self.addCleanup(timer.join)
                started = time.monotonic()
                with self.assertRaisesRegex(ValueError, 'stopped' if cancelled else 'timed out'):
                    supervisor_pid(process, deadline=started + (.5 if not cancelled else 10),
                        cancel=event.is_set)
                self.assertLess(time.monotonic() - started, 2)

    def test_invalid_oversized_and_closed_records_never_publish_ownership(self):
        for record in (b'', b'0\n', b'-1\n', b'not a pid\n', b'2147483648\n', b'1' * 33):
            with self.subTest(record=record):
                process = self.process(f'import os\nos.write(1,{record!r})')
                with self.assertRaises(ValueError):
                    supervisor_pid(process, deadline=time.monotonic() + 2)

