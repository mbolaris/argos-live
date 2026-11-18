#!/usr/bin/env python3
"""Let live-boot's USB-only persistence search include USB disks that report removable=0.

The image boots with `persistence-media=removable-usb`. Debian live-boot implements that in
`removable_dev` (9990-misc-helpers.sh) by first keeping only block devices whose sysfs
`removable` flag is 1, then keeping only those with a USB ancestor. USB SSD enclosures such as
Toronado's Realtek RTL9201 report removable=0, so a stock image silently boots without its
encrypted persistence on them (root on RAM, no paired SSH).

This changes one condition: in USB mode the removable flag is no longer required. The USB
ancestry check stays mandatory, so internal disks (NVMe, SATA, removable or not) are still never
persistence candidates. The ordinary removable-only mode (no USB requirement) is unchanged.

Until November 2026 the same edit was applied by hand to each image's initrd after CI built it
(work/ssd-boot-20261023, work/toronado-fixed-43734658440). It now runs in the chroot before
010-argos.hook.chroot regenerates the initramfs, so CI produces the bootable image directly.
"""
import os
import re
from pathlib import Path
import sys

HELPERS = Path('/usr/lib/live/boot/9990-misc-helpers.sh')
STOCK = 'if [ "$(cat ${sysblock}/removable)" = "1" ]'
PATCHED = STOCK + ' || [ -n "${want_usb}" ]'
USB_ONLY = 'if readlink ${sysblock} | grep -q usb'
WANT_USB = 'want_usb="${2}"'
NOT_USB_MODE = 'if [ -z "${want_usb}" ]'


def function_span(text):
    """Start and end offsets of the removable_dev shell function; refuse anything unexpected.

    Anchored at a line start: the same file also defines non_removable_dev ().
    """
    starts = [m.start() for m in re.finditer(r'^removable_dev \(\)\n\{\n', text, re.M)]
    if len(starts) != 1:
        raise ValueError('live-boot removable_dev() not found exactly once')
    begin = starts[0]
    end = text.find('\n}\n', begin)
    if end < 0:
        raise ValueError('live-boot removable_dev() has no end')
    return begin, end + 3


def is_patched(function):
    """True only for the reviewed edit with the USB ancestry check still in place."""
    return (function.count(PATCHED) == 1 and function.count(STOCK) == 1 and
            function.count(USB_ONLY) == 1 and function.count(WANT_USB) == 1 and
            function.count(NOT_USB_MODE) == 1 and
            function.index(PATCHED) < function.index(NOT_USB_MODE) < function.index(USB_ONLY))


def patch(text):
    """Return text with the reviewed edit applied. Idempotent; raises on any other shape."""
    begin, end = function_span(text)
    function = text[begin:end]
    if is_patched(function):
        return text
    if PATCHED in function:
        raise ValueError('removable_dev() carries a partial or altered USB edit')
    if (function.count(STOCK) != 1 or function.count(USB_ONLY) != 1 or
            function.count(WANT_USB) != 1 or function.count(NOT_USB_MODE) != 1):
        raise ValueError('live-boot removable_dev() differs from the reviewed version; '
                         'review the new live-boot before extending this patch')
    function = function.replace(STOCK, PATCHED)
    if not is_patched(function):
        raise ValueError('Edited removable_dev() failed its own check')
    return text[:begin] + function + text[end:]


def main(path=HELPERS):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SystemExit('live-boot helper is missing or linked: ' + str(path))
    original = path.read_text(encoding='utf-8')
    changed = patch(original)
    if changed != original:
        temporary = path.with_name(path.name + '.argos-new')
        temporary.write_text(changed, encoding='utf-8', newline='\n')
        os.chmod(temporary, path.stat().st_mode & 0o7777)
        os.replace(temporary, path)
    begin, end = function_span(changed)
    if not is_patched(changed[begin:end]):
        raise SystemExit('live-boot fixed-USB persistence edit is not in place')
    print('live-boot: USB-only persistence now includes fixed USB disks (' +
          ('applied' if changed != original else 'already present') + ')')


if __name__ == '__main__':
    main(*sys.argv[1:2])
