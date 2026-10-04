import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_smoke', ROOT / 'scripts/smoke-qemu-iso.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootEntryTests(unittest.TestCase):
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
