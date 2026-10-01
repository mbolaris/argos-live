#!/usr/bin/env python3
"""Extend a Debian isohybrid GPT without removing its intentional ISO/EFI overlap.

Only accepts a regular raw image file. Never opens physical block devices.
Updates both GPT copies and their CRCs, preserving existing boot structures.
"""
from pathlib import Path
import os
import stat
import struct
import sys
import uuid
import zlib

image = Path(sys.argv[1])
iso_bytes = int(sys.argv[2])
if not stat.S_ISREG(image.stat().st_mode) or image.is_symlink():
    raise SystemExit('Regular non-symlink images only.')
capacity = image.stat().st_size
if capacity % 512:
    raise SystemExit('Image capacity must be sector aligned.')
with image.open('r+b') as f:
    f.seek(512); header = bytearray(f.read(512))
    fields = struct.unpack_from('<8sIIIIQQQQ16sQIII', header)
    sig, rev, size, crc, reserved, current, backup, first, last, guid, entries_lba, count, entry_size, entries_crc = fields
    if sig != b'EFI PART' or size != 92 or current != 1 or entry_size != 128 or count < 4:
        raise SystemExit('Unsupported GPT geometry.')
    struct.pack_into('<I', header, 16, 0)
    if zlib.crc32(header[:size]) != crc:
        raise SystemExit('Primary GPT header CRC mismatch.')
    f.seek(entries_lba * 512); entries = bytearray(f.read(count * entry_size))
    if zlib.crc32(entries) != entries_crc:
        raise SystemExit('GPT partition table CRC mismatch.')
    offset = 3 * entry_size
    if any(entries[offset:offset+16]):
        raise SystemExit('Partition 4 is already occupied.')
    final_lba = capacity // 512 - 1
    table_sectors = (len(entries) + 511) // 512
    backup_table = final_lba - table_sectors
    start = ((iso_bytes + 1048575) // 1048576) * 2048
    end = backup_table - 1
    if start >= end:
        raise SystemExit('Insufficient space after the ISO.')
    for index in range(count):
        existing = entries[index*entry_size:(index+1)*entry_size]
        if any(existing[:16]) and struct.unpack_from('<Q', existing, 40)[0] >= start:
            raise SystemExit('An existing partition extends into the requested persistence area.')
    label = 'ArgosPersistence'.encode('utf-16le').ljust(72, b'\0')
    entries[offset:offset+128] = struct.pack('<16s16sQQQ72s',
        uuid.UUID('ca7d7ccb-63ed-4c53-861c-1742536059cc').bytes_le,
        uuid.uuid4().bytes_le, start, end, 0, label)
    table_crc = zlib.crc32(entries)
    def make_header(at, other, table):
        out = bytearray(512)
        struct.pack_into('<8sIIIIQQQQ16sQIII', out, 0, sig, rev, size, 0, reserved,
                         at, other, first, end, guid, table, count, entry_size, table_crc)
        struct.pack_into('<I', out, 16, zlib.crc32(out[:size]))
        return out
    f.seek(entries_lba * 512); f.write(entries)
    f.seek(backup_table * 512); f.write(entries)
    f.seek(final_lba * 512); f.write(make_header(final_lba, 1, backup_table))
    f.seek(512); f.write(make_header(1, final_lba, entries_lba))
    # Preserve the hybrid MBR while making its fourth entry agree with the GPT.
    f.seek(494); f.write(struct.pack('<B3sB3sII', 0, b'\xfe\xff\xff', 0x83, b'\xfe\xff\xff', start, end-start+1))
    f.flush(); os.fsync(f.fileno())
print(f'Added persistence partition 4: sectors {start}..{end}; {((end-start+1)*512)/2**30:.2f} GiB.')
