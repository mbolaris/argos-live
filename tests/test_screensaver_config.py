import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'live/config/includes.chroot/etc/xdg/xfce4/xfconf/'
          'xfce-perchannel-xml/xfce4-screensaver.xml')
GUEST_CHECK = ROOT / 'scripts/qemu-guest-check.py'


class ScreensaverConfigTests(unittest.TestCase):
    def test_next_image_uses_long_idle_delay_without_locking(self):
        tree = ET.parse(CONFIG)
        root = tree.getroot()

        def prop(path):
            value = root.find(path)
            self.assertIsNotNone(value, path)
            return value.attrib['value']

        self.assertEqual(prop("./property[@name='saver']/property[@name='idle-activation']/property[@name='delay']"),
                         '43200')
        self.assertEqual(prop("./property[@name='saver']/property[@name='idle-activation']/property[@name='enabled']"),
                         'true')
        self.assertEqual(prop("./property[@name='lock']/property[@name='enabled']"), 'false')
        self.assertEqual(prop("./property[@name='lock']/property[@name='saver-activation']/property[@name='enabled']"),
                         'false')

        spec = importlib.util.spec_from_file_location('argos_qemu_guest_check', GUEST_CHECK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.SCREENSAVER_DELAY_MINUTES, 43200)


if __name__ == '__main__':
    unittest.main()
