import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_smoke', ROOT / 'scripts/smoke-qemu-iso.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootEntryTests(unittest.TestCase):
    def test_placeholder_screenshot_cannot_pass_graphical_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'screen.ppm'
            for raw in (b'not a PPM', b'P6\n640 480\n255\n' + b'\0' * (640 * 480 * 3),
                        b'P6\n800 600\n255\n' + b'\0' * (800 * 600 * 3)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    module.graphical_frame(path)
            path.write_bytes(b'P6\n800 600\n255\n' +
                             bytes(value for pixel in range(800 * 600) for value in
                                   (pixel % 251, pixel % 127, pixel % 31)))
            module.graphical_frame(path)

    def test_serial_result_waits_for_whole_nested_record(self):
        value = {'schema': 'argos-qemu-smoke/1', 'desktop_started': True,
                 'dashboard_authenticated': True, 'result_round_trip': True,
                 'network_routes': False, 'automatic_first_boot': False,
                 'physical_acceptance': False, 'backend': 'CPU', 'generation_limit': 8,
                 'generation_tokens_per_second': {'median': 1.4, 'reported_runs': 3}}
        wire = 'noise\r\nARGOS_C3_RESULT ' + json.dumps(value) + '\r\n'
        for end in range(len(wire)):
            self.assertIsNone(module.guest_result(wire[:end]))
        self.assertEqual(module.guest_result(wire), value)
        for changed in (dict(value, desktop_started=False), dict(value, network_routes=True),
                        dict(value, backend='GPU'), dict(value, generation_limit=128)):
            with self.assertRaises(ValueError):
                module.guest_result('ARGOS_C3_RESULT ' + json.dumps(changed) + '\n')

    def test_original_desktop_arguments_preserved_and_serial_only_added_for_vm(self):
        text = '''menuentry "Argos desktop" {
 linux /live/vmlinuz boot=live components persistence console=tty0 module_blacklist=nouveau
 initrd /live/initrd.img
}'''
        kernel, initrd, append = module.desktop_entry(text)
        self.assertEqual(kernel, '/live/vmlinuz')
        self.assertEqual(initrd, '/live/initrd.img')
        self.assertEqual(append, 'boot=live components persistence console=tty0 module_blacklist=nouveau console=ttyS0,115200')

    def test_missing_or_traversal_entry_rejected(self):
        for text in ('', 'menuentry "Argos desktop" { linux /live/../escape boot=live console=tty0\ninitrd /live/initrd.img\n}',
                     'menuentry "Argos desktop" {\nlinux /live/vmlinuz console=tty0\ninitrd /live/initrd.img\n}'):
            with self.assertRaises(ValueError):
                module.desktop_entry(text)


if __name__ == '__main__':
    unittest.main()
