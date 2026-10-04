"""Read-only Linux hardware snapshot; unavailable measurements stay unknown."""
import csv
import io
import json
from pathlib import Path
import re
import shutil
import subprocess


def command(args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              check=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def read(path):
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return None


def number(value, scale=1):
    try:
        result = int(value)
        return result * scale if result >= 0 else None
    except (TypeError, ValueError):
        return None


def cpu_info(text):
    result = {'model': None, 'cores': None, 'threads': None}
    if not text:
        return result
    records = []
    for block in text.strip().split('\n\n'):
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.partition(':')
            if sep:
                fields[key.strip()] = value.strip()
        if 'processor' in fields:
            records.append(fields)
    if records:
        result['threads'] = len(records)
        result['model'] = records[0].get('model name') or records[0].get('Processor')
        if all('physical id' in r and 'core id' in r for r in records):
            result['cores'] = len({(r['physical id'], r['core id']) for r in records})
    return result


def memory_info(text):
    fields = {}
    for line in (text or '').splitlines():
        match = re.fullmatch(r'(MemTotal|MemAvailable):\s+(\d+)\s+kB', line.strip())
        if match:
            fields[match[1]] = number(match[2], 1024)
    return {'total_bytes': fields.get('MemTotal'),
            'available_bytes': fields.get('MemAvailable')}


def nvidia_info(text):
    if text is None:
        return None
    result = []
    try:
        for row in csv.reader(io.StringIO(text)):
            if not row:
                continue
            if len(row) != 5:
                return None
            bus, name, total, used, driver = (value.strip() for value in row)
            result.append({'bus': bus, 'name': name, 'vendor': 'NVIDIA',
                           'vram_total_bytes': number(total, 1024**2),
                           'vram_used_bytes': number(used, 1024**2),
                           'driver': None if driver in ('N/A', '[N/A]') else driver})
    except csv.Error:
        return None
    return result


def pci_gpus(text):
    if text is None:
        return None
    result = []
    for line in text.splitlines():
        match = re.match(r'^(\S+)\s+(?:VGA compatible|3D|Display) controller:\s*(.*)$', line)
        if not match:
            continue
        bus, name = match.groups()
        vendor = next((v for v in ('NVIDIA', 'Intel', 'AMD') if v.lower() in name.lower()), None)
        if vendor is None and 'Advanced Micro Devices' in name:
            vendor = 'AMD'
        result.append({'bus': bus, 'name': name, 'vendor': vendor,
                       'vram_total_bytes': None, 'vram_used_bytes': None, 'driver': None})
    return result


def secure_boot(sys_root):
    try:
        files = list((sys_root / 'firmware/efi/efivars').glob('SecureBoot-*'))
        if len(files) != 1:
            return None
        data = files[0].read_bytes()
        # efivarfs exposes four attribute bytes before the variable value.
        if len(data) == 5 and data[4] in (0, 1):
            return bool(data[4])
    except OSError:
        pass
    return None


def disk_info(text):
    try:
        devices = json.loads(text)['blockdevices']
        if not isinstance(devices, list):
            return None
        def convert(item):
            return {'name': item.get('name'), 'type': item.get('type'),
                    'size_bytes': number(item.get('size')),
                    'filesystem': item.get('fstype'), 'mountpoints': item.get('mountpoints'),
                    'children': [convert(child) for child in item.get('children', [])]}
        return [convert(item) for item in devices]
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def snapshot(candidate_dirs=(), *, proc_root=Path('/proc'), sys_root=Path('/sys'),
             run=command, disk_usage=shutil.disk_usage):
    """Probe without mounting disks, starting drivers or creating directories."""
    proc_root, sys_root = Path(proc_root), Path(sys_root)
    nvidia = nvidia_info(run(['nvidia-smi',
                             '--query-gpu=pci.bus_id,name,memory.total,memory.used,driver_version',
                             '--format=csv,noheader,nounits']))
    pci = pci_gpus(run(['lspci', '-D']))
    if nvidia is None:
        gpus = pci
    else:
        # lspci identifies non-NVIDIA adapters; NVIDIA metrics come from its driver.
        gpus = nvidia + [g for g in (pci or []) if g['vendor'] != 'NVIDIA']
    storage = []
    for directory in candidate_dirs:
        path = Path(directory).expanduser()
        entry = {'path': str(path), 'total_bytes': None, 'free_bytes': None}
        try:
            if path.is_dir():
                usage = disk_usage(path)
                entry.update(total_bytes=usage.total, free_bytes=usage.free)
        except OSError:
            pass
        storage.append(entry)
    kernel = read(proc_root / 'sys/kernel/osrelease')
    return {'schema': 'argos-hw/1', 'cpu': cpu_info(read(proc_root / 'cpuinfo')),
            'ram': memory_info(read(proc_root / 'meminfo')), 'gpus': gpus,
            'disks': disk_info(run(['lsblk', '--json', '--bytes', '--output',
                                   'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS'])),
            'model_directories': storage, 'kernel': kernel.strip() if kernel else None,
            'secure_boot': secure_boot(sys_root)}
