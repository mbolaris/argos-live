#!/usr/bin/env python3
"""Prove a built ISO's boot initrd finds encrypted persistence on fixed USB disks.

Reads the desktop entry's initrd out of the ISO (xorriso), unpacks the cpio archives in memory,
checks that live-boot's removable_dev() carries exactly the reviewed fixed-USB edit, and runs that
extracted shell function against a mock /sys/block:

  USB mode       fixed USB and removable USB accepted; internal disks (fixed or removable) refused
  ordinary mode  unchanged: removable devices only, USB or not

No physical device, VM or network is used. Writes a JSON receipt with --output.
"""
import argparse
import hashlib
import importlib.util
import json
import lzma
import gzip
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = 'usr/lib/live/boot/9990-misc-helpers.sh'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


usb = _load('patch_live_boot_usb', ROOT / 'live/config/includes.chroot/usr/local/share/argos-live/patch-live-boot-usb.py')

# name: (sysfs removable flag, device path; USB devices have a usb ancestor)
DEVICES = {
    'fixed_usb': ('0', '../devices/pci0000:00/0000:00:14.0/usb6/6-4/6-4:1.0/host0/target0:0:0/0:0:0:0/block/fixed_usb'),
    'removable_usb': ('1', '../devices/pci0000:00/0000:00:14.0/usb6/6-3/6-3:1.0/host1/target1:0:0/1:0:0:0/block/removable_usb'),
    'internal_nvme': ('0', '../devices/pci0000:00/0000:00:1d.0/0000:3d:00.0/nvme/nvme0/nvme0n1'),
    'internal_removable': ('1', '../devices/pci0000:00/0000:00:17.0/ata1/host2/target2:0:0/2:0:0:0/block/internal_removable'),
}
EXPECTED = {'usb_mode': ['/dev/fixed_usb', '/dev/removable_usb'],
            'ordinary_mode': ['/dev/internal_removable', '/dev/removable_usb']}
STOCK_USB_MODE = ['/dev/removable_usb']


def cpio_members(data):
    """Yield (name, content) for newc cpio members; stops at the first non-cpio byte."""
    pos = 0
    while pos < len(data):
        while pos < len(data) and data[pos] == 0:
            pos += 1
        if data[pos:pos + 6] not in (b'070701', b'070702'):
            return pos
        size = int(data[pos + 54:pos + 62], 16)
        namesize = int(data[pos + 94:pos + 102], 16)
        name = data[pos + 110:pos + 110 + namesize - 1].decode('utf-8', 'replace')
        start = (pos + 110 + namesize + 3) & ~3
        yield name, data[start:start + size]
        pos = (start + size + 3) & ~3
    return pos


def members(blob):
    """Every member of a (possibly multi-segment, compressed) initramfs."""
    found = {}
    pos = 0
    while pos < len(blob):
        while pos < len(blob) and blob[pos] == 0:
            pos += 1
        if pos >= len(blob):
            break
        segment = blob[pos:]
        if segment[:6] in (b'070701', b'070702'):
            iterator = cpio_members(segment)
            try:
                while True:
                    name, content = next(iterator)
                    found[name] = content
            except StopIteration as stop:
                consumed = stop.value
            # A TRAILER!!! entry ends an uncompressed early archive; continue after it.
            if not consumed:
                break
            pos += consumed
            continue
        if segment[:4] == bytes.fromhex('28b52ffd'):
            try:
                from compression import zstd  # Python 3.14+
            except ImportError:
                zstd = None
            if zstd is not None:
                decompressor = zstd.ZstdDecompressor()
                payload = decompressor.decompress(segment)
                # The kernel accepts zero padding after the last archive (hand-patched images use it).
                if not decompressor.eof or decompressor.unused_data.strip(b'\0'):
                    raise ValueError('initramfs zstd segment is truncated or followed by data')
            elif shutil.which('zstd'):
                payload = subprocess.run(['zstd', '-dc'], input=segment, capture_output=True, check=True).stdout
            else:
                raise ValueError('zstd (tool or Python 3.14) is required to read this initramfs')
        elif segment[:2] == b'\x1f\x8b':
            payload = gzip.decompress(segment)
        elif segment[:6] == bytes.fromhex('fd377a585a00'):
            payload = lzma.decompress(segment)
        else:
            raise ValueError('Unrecognized initramfs segment at byte %d' % pos)
        for name, content in cpio_members(payload):
            found[name] = content
        break
    return found


def fixture_script(function, sys_block):
    """A bash script that runs the extracted removable_dev() against mock sysfs entries."""
    body = function.replace('/sys/block/*', '"${TEST_SYS_BLOCK}"/*')
    if body.count('"${TEST_SYS_BLOCK}"/*') != 1:
        raise ValueError('removable_dev() does not enumerate /sys/block exactly once')
    return ('#!/bin/bash\nset -eo pipefail\n'
            f'TEST_SYS_BLOCK={sys_block}\n'
            'readlink(){ cat "$1/ancestry"; }\n'
            "sys2dev(){ printf '/dev/%s\\n' \"${1##*/}\"; }\n" + body +
            '\necho "usb_mode=$(removable_dev dev want_usb | xargs)"\n'
            'echo "ordinary_mode=$(removable_dev dev \'\' | xargs)"\n')


def run_fixture(function):
    """Run the shell function on mock sysfs. Returns {'usb_mode': [...], 'ordinary_mode': [...]}."""
    bash = shutil.which('bash')
    if not bash or sys.platform == 'win32':
        raise ValueError('The shell fixture needs bash on Linux')
    with tempfile.TemporaryDirectory(prefix='argos-usb-filter-') as directory:
        root = Path(directory) / 'block'
        for name, (flag, path) in DEVICES.items():
            (root / name).mkdir(parents=True)
            (root / name / 'removable').write_text(flag + '\n')
            (root / name / 'ancestry').write_text(path + '\n')
        script = Path(directory) / 'fixture.sh'
        script.write_text(fixture_script(function, root), newline='\n')
        out = subprocess.run([bash, str(script)], capture_output=True, text=True, timeout=30, check=True).stdout
    rows = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    return {key: sorted(rows.get(key, '').split()) for key in EXPECTED}


def check_function(function):
    if not usb.is_patched(function):
        raise ValueError('initrd removable_dev() lacks the reviewed fixed-USB edit')
    observed = run_fixture(function)
    if observed != EXPECTED:
        raise ValueError('removable_dev() fixture gave %r, expected %r' % (observed, EXPECTED))
    return observed


def check_iso(iso, work):
    sys.path.insert(0, str(ROOT / 'scripts'))
    boot = _load('qemu_boot', ROOT / 'scripts/smoke-qemu-iso.py')

    def extract(source, target):
        subprocess.run(['xorriso', '-osirrox', 'on', '-indev', str(iso), '-extract', source, str(target)],
                       check=True, capture_output=True)
    extract('/boot/grub/grub.cfg', work / 'grub.cfg')
    _, initrd_path, append = boot.desktop_entry((work / 'grub.cfg').read_text())
    if 'persistence-media=removable-usb' not in append.split():
        raise ValueError('Desktop entry lost the USB-only persistence policy')
    extract(initrd_path, work / 'initrd')
    blob = (work / 'initrd').read_bytes()
    found = members(blob)
    helper = found.get(HELPER_PATH)
    if helper is None:
        raise ValueError('initrd has no ' + HELPER_PATH)
    text = helper.decode('utf-8')
    begin, end = usb.function_span(text)
    function = text[begin:end]
    observed = check_function(function)
    return {'schema': 'argos-iso-usb-persistence/1', 'passed': True,
            'initrd': initrd_path, 'initrd_sha256': hashlib.sha256(blob).hexdigest(),
            'helper_sha256': hashlib.sha256(helper).hexdigest(),
            'reviewed_edit_present': True, 'fixture': observed,
            'scope': 'shell function from the exact ISO initrd on mock sysfs; not a boot test'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('iso', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    result = {'schema': 'argos-iso-usb-persistence/1', 'passed': False}
    try:
        with tempfile.TemporaryDirectory(prefix='argos-iso-usb-') as directory:
            result = check_iso(args.iso.resolve(strict=True), Path(directory))
    except Exception as error:  # the receipt records why; the exit code fails the job
        result['failure'] = type(error).__name__ + ': ' + str(error)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
