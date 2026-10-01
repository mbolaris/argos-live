from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib

class ImagePartitionTests(unittest.TestCase):
    def test_preserves_nested_boot_partitions_and_updates_both_crcs(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'test.raw'
            capacity = 8 * 1024**2
            table = bytearray(128 * 128)
            for i, (start, end) in enumerate([(64, 4095), (512, 800)]):
                table[i*128:(i+1)*128] = struct.pack('<16s16sQQQ72s', uuid.uuid4().bytes_le, uuid.uuid4().bytes_le, start, end, 0, b'\0'*72)
            header = bytearray(512)
            struct.pack_into('<8sIIIIQQQQ16sQIII', header, 0, b'EFI PART', 0x10000, 92, 0, 0, 1, 4095, 64, 4094, uuid.uuid4().bytes_le, 12, 128, 128, zlib.crc32(table))
            struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
            with path.open('wb') as f:
                f.truncate(capacity); f.seek(512); f.write(header); f.seek(12*512); f.write(table)
            script = Path(__file__).parents[1] / 'scripts/append-persistence-partition.py'
            subprocess.run([sys.executable, str(script), str(path), str(2 * 1024**2)], check=True, capture_output=True)
            with path.open('rb') as f:
                f.seek(12*512); actual = f.read(len(table))
                self.assertEqual(actual[:256], table[:256])
                for lba in [1, capacity//512-1]:
                    f.seek(lba*512); h = bytearray(f.read(512)); crc = struct.unpack_from('<I', h, 16)[0]
                    struct.pack_into('<I', h, 16, 0)
                    self.assertEqual(zlib.crc32(h[:92]), crc)
                    table_lba = struct.unpack_from('<Q', h, 72)[0]
                    f.seek(table_lba*512); self.assertEqual(f.read(len(table)), actual)

if __name__ == '__main__':
    unittest.main()
