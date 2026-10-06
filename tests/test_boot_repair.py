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

    def test_access_hook_is_present_in_all_entries(self):
        old=b'linux /live/vmlinuz-test\ninitrd /live/initrd-test\n'+b' '*1950
        new=repair.menu(old,hook=True)
        self.assertEqual(len(new),len(old))
        self.assertEqual(new.count(b'live-config.hooks=file:///run/live/medium/live/filesystem.packages'),3)
        self.assertEqual(new.count(b'initrd /live/initrd-test'),3)

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
            self.assertEqual(menu.count('initrd /live/initrd-test'),5)
            self.assertNotIn('ttyS0',menu)
            self.assertIn('set default=3',menu)
            self.assertIn('set timeout=15',menu)
            desktop=menu.split('menuentry "Argos desktop" {',1)[1].split('}',1)[0]
            self.assertIn('module_blacklist=nouveau',desktop)
            self.assertNotIn('systemd.unit=multi-user.target',desktop)
            bios=(root/'isolinux/live.cfg').read_text()
            self.assertEqual(bios.count('initrd /live/initrd.img'),5)
            guest=menu.split('menuentry "Argos guest - resets on reboot, no passphrase" {',1)[1].split('}',1)[0]
            self.assertIn('nopersistence',guest)
            self.assertIn('argos.guest=1',guest)
            self.assertNotIn('persistence-encryption',guest)
            self.assertNotIn(' persistence ',guest)
            self.assertIn('persistence-encryption=luks',desktop)
            guest_bios=bios.split('label argos-guest\n',1)[1].split('label argos-guest-basic',1)[0]
            self.assertIn('menu default',guest_bios)
            self.assertIn('nopersistence',guest_bios)
            self.assertNotIn('persistence-encryption',guest_bios)

if __name__=='__main__':unittest.main()
