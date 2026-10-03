import importlib.util
from pathlib import Path
import unittest
import shutil
import subprocess
import tempfile

spec=importlib.util.spec_from_file_location('boot_repair',Path(__file__).resolve().parents[1]/'scripts/plan-boot-repair.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)

class BootRepairTests(unittest.TestCase):
    def test_menu_keeps_kernel_initrd_and_length(self):
        old=b'menuentry "live" {\n linux /live/vmlinuz-test boot=live console=ttyS0,115200\n initrd /live/initrd-test\n}\n'+b' '*1900
        new=repair.menu(old)
        self.assertEqual(len(old),len(new))
        self.assertEqual(new.count(b'initrd /live/initrd-test'),3)
        self.assertEqual(new.count(b'linux /live/vmlinuz-test'),3)
        self.assertEqual(new.count(b'persistence-encryption=luks'),3)
        self.assertNotIn(b'console=ttyS0',new)
        self.assertIn(b'set default=0',new)
        self.assertIn(b'module_blacklist=nouveau',new)

    def test_small_allocation_is_rejected(self):
        with self.assertRaises(ValueError):
            repair.menu(b'linux /live/vmlinuz\ninitrd /live/initrd\n')

    @unittest.skipUnless(shutil.which('sh'),'Shell fixture requires sh')
    def test_binary_hook_creates_both_firmware_menus(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'boot/grub').mkdir(parents=True)
            (root/'isolinux').mkdir()
            (root/'boot/grub/grub.cfg').write_text('linux /live/vmlinuz-test boot=live\ninitrd /live/initrd-test\n')
            hook=Path(__file__).resolve().parents[1]/'live/config/hooks/live/050-argos-menu.hook.binary'
            subprocess.run(['sh',str(hook)],cwd=root,check=True)
            menu=(root/'boot/grub/grub.cfg').read_text()
            self.assertEqual(menu.count('initrd /live/initrd-test'),3)
            self.assertNotIn('ttyS0',menu)
            self.assertIn('set default=0',menu)
            bios=(root/'isolinux/live.cfg').read_text()
            self.assertEqual(bios.count('initrd /live/initrd.img'),3)

if __name__=='__main__':unittest.main()
