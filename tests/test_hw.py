import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import hw


class HardwareTests(unittest.TestCase):
    def probe(self, fixture):
        data = json.loads((ROOT / 'tests/fixtures/hw' / fixture).read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / 'proc'
            proc.mkdir()
            for name in ('cpuinfo', 'meminfo'):
                (proc / name).write_text(data[name])
            (proc / 'sys/kernel').mkdir(parents=True)
            (proc / 'sys/kernel/osrelease').write_text('fixture-kernel\n')
            if data['secure_boot'] is not None:
                efivars = root / 'sys/firmware/efi/efivars'
                efivars.mkdir(parents=True)
                (efivars / 'SecureBoot-fixture').write_bytes(b'\x07\0\0\0' + bytes([data['secure_boot']]))
            outputs = {'nvidia-smi': data['nvidia'], 'lspci': data['pci'], 'lsblk': data['lsblk']}
            return hw.snapshot(proc_root=proc, sys_root=root / 'sys',
                               run=lambda args: outputs[args[0]])

    def test_nvidia_desktop(self):
        result = self.probe('nvidia.json')
        self.assertEqual(result['cpu']['cores'], 1)
        self.assertEqual(result['cpu']['threads'], 2)
        self.assertEqual(result['ram']['total_bytes'], 64 * 1024**3)
        self.assertEqual(len(result['gpus']), 1)
        self.assertEqual(result['gpus'][0]['vram_total_bytes'], 24 * 1024**3)
        self.assertEqual(result['gpus'][0]['vram_used_bytes'], 4 * 1024**3)
        self.assertEqual(result['disks'][0]['children'][0]['filesystem'], 'ext4')
        self.assertFalse(result['secure_boot'])

    def test_cpu_only_laptop(self):
        result = self.probe('cpu-only.json')
        self.assertEqual(result['gpus'], [])
        self.assertEqual(result['ram']['available_bytes'], 4 * 1024**3)
        self.assertTrue(result['secure_boot'])

    def test_missing_nvidia_tool_retains_pci_names(self):
        result = self.probe('no-nvidia-smi.json')
        self.assertEqual([g['vendor'] for g in result['gpus']], ['Intel', 'AMD'])
        self.assertTrue(all(g['vram_total_bytes'] is None for g in result['gpus']))
        self.assertIsNone(result['cpu']['cores'])
        self.assertIsNone(result['ram']['available_bytes'])
        self.assertIsNone(result['secure_boot'])
        self.assertIsNone(result['disks'])

    def test_unavailable_probes_and_storage_never_create_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / 'not-created'
            result = hw.snapshot([missing, root], proc_root=root, sys_root=root,
                                 run=lambda args: None,
                                 disk_usage=lambda path: (_ for _ in ()).throw(OSError('denied')))
            self.assertFalse(missing.exists())
            self.assertIsNone(result['gpus'])
            self.assertIsNone(result['kernel'])
            self.assertTrue(all(p['free_bytes'] is None for p in result['model_directories']))

    def test_malformed_or_unavailable_fields_are_unknown(self):
        self.assertIsNone(hw.nvidia_info('wrong,column,count'))
        result = hw.nvidia_info('bus, GPU, [N/A], 0, [N/A]')[0]
        self.assertIsNone(result['vram_total_bytes'])
        self.assertEqual(result['vram_used_bytes'], 0)
        self.assertIsNone(result['driver'])
        self.assertIsNone(hw.disk_info('{"blockdevices":"wrong"}'))
        with patch.object(hw.subprocess, 'run', side_effect=hw.subprocess.TimeoutExpired('probe', 5)):
            self.assertIsNone(hw.command(['probe']))

    def test_existing_storage_reports_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usage = Mock(total=1000000, free=700000)
            result = hw.snapshot([root], proc_root=root, sys_root=root,
                                 run=lambda args: None, disk_usage=lambda path: usage)
            self.assertEqual(result['model_directories'][0]['total_bytes'], 1000000)
            self.assertEqual(result['model_directories'][0]['free_bytes'], 700000)

    def test_cli_json_does_not_require_setup(self):
        spec = importlib.util.spec_from_file_location('hw_cli', ROOT / 'runtime/argos.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        output = io.StringIO()
        expected = {'schema': 'argos-hw/1', 'gpus': None}
        with patch.object(sys, 'argv', ['argos', 'hw', '--json', '--model-dir', '/fixture']), \
             patch.object(hw, 'snapshot', return_value=expected) as probe, \
             patch.object(cli, 'load', side_effect=AssertionError('setup not allowed')), \
             contextlib.redirect_stdout(output):
            cli.main()
        self.assertEqual(json.loads(output.getvalue()), expected)
        probe.assert_called_once_with(['/fixture'])
