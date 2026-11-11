"""The Samsung SSD's Realtek RTL9201 (0bda:9201) must boot on usb-storage, not UAS.

On 2026-11-11 the enclosure stopped answering on UAS about 30-110 seconds into boot, dropped off the bus
and corrupted the encrypted persistence three times. `usb-storage.quirks=0bda:9201:u` fixed it. One
hand-typed mistake (`storage.quirks=...`, without `usb-`) is silently ignored by the kernel, so the
exact spelling is pinned here for every place that sets it.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUIRK = 'usb-storage.quirks=0bda:9201:u'
HOOK = ROOT / 'live/config/hooks/live/050-argos-menu.hook.binary'


class SsdUasQuirkTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('sh'), 'Shell fixture requires sh')
    def test_every_boot_menu_entry_carries_the_quirk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'boot/grub').mkdir(parents=True)
            (root / 'isolinux').mkdir()
            (root / 'boot/grub/grub.cfg').write_text('linux /live/vmlinuz-test boot=live\ninitrd /live/initrd-test\n')
            subprocess.run(['sh', str(HOOK)], cwd=root, check=True)
            grub = (root / 'boot/grub/grub.cfg').read_text()
            linux = [line for line in grub.splitlines() if line.startswith(' linux ')]
            self.assertEqual(len(linux), 5)
            for line in linux:
                self.assertEqual(line.split().count(QUIRK), 1, line)
                self.assertTrue(line.endswith(QUIRK) or QUIRK in line.split(), line)
            # The persistent and the guest entries both get it; the quirk is never on the initrd line.
            for line in grub.splitlines():
                if line.startswith(' initrd '):
                    self.assertNotIn('quirks', line)
            bios = (root / 'isolinux/live.cfg').read_text()
            append = [line for line in bios.splitlines() if line.strip().startswith('append ')]
            self.assertEqual(len(append), 5)
            for line in append:
                self.assertEqual(line.split().count(QUIRK), 1, line)

    @unittest.skipUnless(shutil.which('sh'), 'Shell fixture requires sh')
    def test_serial_test_console_keeps_the_quirk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'boot/grub').mkdir(parents=True)
            (root / 'isolinux').mkdir()
            (root / 'boot/grub/grub.cfg').write_text('linux /live/vmlinuz-test boot=live\ninitrd /live/initrd-test\n')
            subprocess.run(['sh', str(HOOK)], cwd=root, check=True, env={'ARGOS_TEST_SERIAL_CONSOLE': '1', 'PATH': '/usr/bin:/bin'})
            grub = (root / 'boot/grub/grub.cfg').read_text()
            for line in grub.splitlines():
                if line.startswith(' linux '):
                    self.assertIn(QUIRK, line.split(), line)

    def test_build_and_repack_set_the_same_spelling(self):
        for relative in ('scripts/build.sh', 'scripts/repack-image.sh', 'scripts/test-usb-vm.py', 'live/config/hooks/live/050-argos-menu.hook.binary'):
            text = (ROOT / relative).read_text(encoding='utf-8')
            self.assertIn('0bda:9201:u', text, relative)
        self.assertIn(QUIRK, (ROOT / 'scripts/build.sh').read_text(encoding='utf-8'))
        self.assertIn(QUIRK, (ROOT / 'scripts/repack-image.sh').read_text(encoding='utf-8'))
        self.assertIn(QUIRK, (ROOT / 'scripts/test-usb-vm.py').read_text(encoding='utf-8'))
        self.assertIn("quirk='" + QUIRK + "'", HOOK.read_text(encoding='utf-8'))

    def test_no_mistyped_quirk_anywhere(self):
        # `storage.quirks=` without the usb- prefix is ignored by the kernel with no error.
        pattern = re.compile(r'(?<!usb-)storage\.quirks=')
        for relative in ('scripts/build.sh', 'scripts/repack-image.sh', 'scripts/test-usb-vm.py',
                         'live/config/hooks/live/050-argos-menu.hook.binary', 'docs/USB-SSD-UAS.md'):
            text = (ROOT / relative).read_text(encoding='utf-8')
            self.assertIsNone(pattern.search(text), relative)
            for match in re.finditer(r'quirks=\S*', text):
                self.assertEqual(match.group(0).rstrip("'\"`.,)"), 'quirks=0bda:9201:u', relative)


if __name__ == '__main__':
    unittest.main()
