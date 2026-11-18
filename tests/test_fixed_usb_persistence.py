"""The image must find encrypted persistence on USB disks that report removable=0.

Toronado's SSD sits in a Realtek RTL9201 enclosure that reports removable=0. Stock live-boot's
`persistence-media=removable-usb` keeps only removable=1 devices, so a stock image boots it with
root on RAM and no paired SSH. Until November 2026 each image's initrd was patched by hand after CI;
005-fixed-usb-persistence.hook.chroot now makes the same one-condition edit in the build.
"""
import gzip
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / 'live/config/includes.chroot/usr/local/share/argos-live/patch-live-boot-usb.py'
HOOKS = ROOT / 'live/config/hooks/live'
# Verbatim excerpt of Debian trixie live-boot's 9990-misc-helpers.sh from the November 15, 2026 CI
# image initrd: removable_dev, removable_usb_dev and non_removable_dev. The last contains the text
# 'removable_dev ()', so the patcher must anchor at a line start.
HELPERS_EXCERPT = (ROOT / 'tests/fixtures/live-boot-removable-helpers.sh').read_text(encoding='utf-8')
STOCK_FUNCTION = HELPERS_EXCERPT[:HELPERS_EXCERPT.index('\n}\n') + 3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


usb = load('patch_live_boot_usb', PATCHER)
checker = load('check_iso_usb_persistence', ROOT / 'scripts/check-iso-usb-persistence.py')
STOCK_FILE = '#!/bin/sh\n\nsys2dev ()\n{\n\techo x\n}\n\n' + HELPERS_EXCERPT + '\nother ()\n{\n\t:\n}\n'
ON_LINUX_BASH = sys.platform.startswith('linux') and shutil.which('bash')


def newc(members):
    """A newc cpio archive of {name: bytes}, with the trailer."""
    out = bytearray()
    for index, (name, data) in enumerate([*members.items(), ('TRAILER!!!', b'')]):
        encoded = name.encode() + b'\0'
        fields = [index + 1, 0o100644 if data or name != 'TRAILER!!!' else 0, 0, 0, 1, 0, len(data),
                  0, 0, 0, 0, len(encoded), 0]
        out += b'070701' + b''.join(b'%08x' % value for value in fields) + encoded
        out += bytes((-len(out)) % 4) + data + bytes((-len(data)) % 4)
    return bytes(out)


class PatchTests(unittest.TestCase):
    def test_stock_function_is_the_reviewed_shape(self):
        self.assertFalse(usb.is_patched(STOCK_FUNCTION))
        self.assertEqual(STOCK_FUNCTION.count(usb.STOCK), 1)

    def test_finds_removable_dev_and_not_non_removable_dev(self):
        self.assertIn('\nnon_removable_dev ()\n{\n', STOCK_FILE)
        begin, end = usb.function_span(STOCK_FILE)
        self.assertEqual(STOCK_FILE[begin:end], STOCK_FUNCTION)
        patched = usb.patch(STOCK_FILE)
        self.assertEqual(patched.count(usb.PATCHED), 1)
        marker = '\nremovable_usb_dev ()'
        self.assertEqual(patched[patched.index(marker):], STOCK_FILE[STOCK_FILE.index(marker):])

    def test_patch_changes_exactly_one_condition_and_keeps_the_usb_check(self):
        patched = usb.patch(STOCK_FILE)
        self.assertEqual(patched.replace(usb.PATCHED, usb.STOCK), STOCK_FILE)
        begin, end = usb.function_span(patched)
        self.assertTrue(usb.is_patched(patched[begin:end]))
        self.assertIn(usb.USB_ONLY, patched[begin:end])
        self.assertEqual(usb.patch(patched), patched)  # idempotent

    def test_refuses_an_unreviewed_live_boot(self):
        cases = {
            'no USB ancestry check': STOCK_FILE.replace(usb.USB_ONLY, 'if true'),
            'condition reworded': STOCK_FILE.replace(usb.STOCK, 'if [ "$(cat ${sysblock}/removable)" -eq 1 ]'),
            'function missing': STOCK_FILE.replace('removable_dev ()', 'removable_devices ()'),
            'function twice': STOCK_FILE + STOCK_FUNCTION,
            'altered edit': STOCK_FILE.replace(usb.STOCK, usb.PATCHED).replace(usb.NOT_USB_MODE, 'if false'),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                usb.patch(text)

    def test_main_rewrites_in_place_and_keeps_the_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '9990-misc-helpers.sh'
            path.write_text(STOCK_FILE, encoding='utf-8', newline='\n')
            os.chmod(path, 0o644)
            before = path.stat().st_mode
            usb.main(path)
            self.assertIn(usb.PATCHED, path.read_text(encoding='utf-8'))
            self.assertEqual(path.stat().st_mode, before)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['9990-misc-helpers.sh'])
            usb.main(path)  # second run is a no-op
            self.assertEqual(path.read_text(encoding='utf-8').count(usb.PATCHED), 1)


class BuildWiringTests(unittest.TestCase):
    def test_hook_runs_before_the_initramfs_is_regenerated(self):
        hook = HOOKS / '005-fixed-usb-persistence.hook.chroot'
        self.assertIn('python3 /usr/local/share/argos-live/patch-live-boot-usb.py', hook.read_text())
        chroot_hooks = sorted(p.name for p in HOOKS.glob('*.hook.chroot'))
        regenerating = [name for name in chroot_hooks if 'update-initramfs' in (HOOKS / name).read_text()]
        self.assertEqual(regenerating, ['010-argos.hook.chroot'])
        self.assertLess(chroot_hooks.index(hook.name), chroot_hooks.index('010-argos.hook.chroot'))

    def test_built_iso_is_checked_and_repack_refuses_an_unpatched_rootfs(self):
        build = (ROOT / '.github/workflows/iso-build.yml').read_text(encoding='utf-8')
        self.assertIn('scripts/check-iso-usb-persistence.py artifacts/argos-live-amd64.iso', build)
        self.assertLess(build.index('check-iso-usb-persistence.py'), build.index('Boot built ISO'))
        repack = (ROOT / 'scripts/repack-image.sh').read_text(encoding='utf-8')
        self.assertIn(usb.PATCHED, repack)

    def test_shutdown_smoke_can_attach_a_fixed_usb_disk(self):
        smoke = (ROOT / 'scripts/smoke-encrypted-shutdown.py').read_text(encoding='utf-8')
        self.assertIn("'usb-storage,drive=media,removable=' + removable", smoke)
        self.assertIn("removable='off' if fixed_usb else 'on'", smoke)
        workflow = (ROOT / '.github/workflows/iso-boot.yml').read_text(encoding='utf-8')
        self.assertIn('--fixed-usb', workflow)


class InitrdReaderTests(unittest.TestCase):
    def test_reads_the_helper_after_an_uncompressed_early_archive(self):
        helper = usb.patch(STOCK_FILE).encode()
        early = newc({'kernel/x86/microcode/GenuineIntel.bin': b'\x01' * 13})
        main = gzip.compress(newc({'usr/lib/live/boot/9990-misc-helpers.sh': helper, 'init': b'#!/bin/sh\n'}))
        found = checker.members(early + bytes(512) + main)
        self.assertEqual(found[checker.HELPER_PATH], helper)
        self.assertIn('kernel/x86/microcode/GenuineIntel.bin', found)

    def test_fixture_script_targets_mock_sysfs_only(self):
        script = checker.fixture_script(usb.patch(STOCK_FUNCTION), '/tmp/mock')
        self.assertNotIn('/sys/block', script)
        self.assertIn('TEST_SYS_BLOCK=/tmp/mock', script)


@unittest.skipUnless(ON_LINUX_BASH, 'The live-boot shell fixture runs on Linux with bash')
class ShellFixtureTests(unittest.TestCase):
    def test_patched_function_accepts_fixed_usb_and_still_refuses_internal_disks(self):
        self.assertEqual(checker.check_function(usb.patch(STOCK_FUNCTION)), checker.EXPECTED)

    def test_stock_function_skips_the_fixed_usb_disk(self):
        observed = checker.run_fixture(STOCK_FUNCTION)
        self.assertEqual(observed['usb_mode'], checker.STOCK_USB_MODE)
        self.assertEqual(observed['ordinary_mode'], checker.EXPECTED['ordinary_mode'])
        with self.assertRaises(ValueError):
            checker.check_function(STOCK_FUNCTION)


if __name__ == '__main__':
    unittest.main()
