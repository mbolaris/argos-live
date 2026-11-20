"""Read-only live resource measurements for the authenticated status dashboard."""
import csv
from datetime import datetime, timezone
import io
from pathlib import Path
import shutil
import time

from argoslive import hw


def _integer(value):
    try:
        number = float(value.strip())
        return int(number) if number >= 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def _decimal(value):
    try:
        number = float(value.strip())
        return round(number, 1) if number >= 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def _thermal_zones(root=Path('/sys/class/thermal')):
    """Report a CPU/package sensor only when its label identifies one."""
    values = []
    try:
        zones = sorted(root.glob('thermal_zone*'))
    except OSError:
        return None
    for zone in zones:
        label = hw.read(zone / 'type')
        raw = hw.read(zone / 'temp')
        if not label or raw is None:
            continue
        name = label.strip()
        if not any(mark in name.lower() for mark in ('cpu', 'package', 'tctl', 'tdie', 'coretemp')):
            continue
        temp = _integer(raw)
        if temp is None:
            continue
        # Linux thermal zones commonly expose millidegrees Celsius.
        celsius = temp / 1000 if temp > 1000 else temp
        if -20 <= celsius <= 150:
            values.append({'sensor': name[:64], 'temperature_c': round(celsius, 1)})
    return values or None


def _gpu(run):
    raw = run(['nvidia-smi', '--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit',
               '--format=csv,noheader,nounits'])
    if raw is None:
        return None
    result = []
    try:
        for row in csv.reader(io.StringIO(raw)):
            if len(row) != 7:
                return None
            name, temp, util, used, total, watts, limit = (part.strip() for part in row)
            result.append({'name': name[:96], 'temperature_c': _integer(temp),
                           'utilization_percent': _integer(util),
                           'vram_used_mib': _integer(used), 'vram_total_mib': _integer(total),
                           'power_w': None if watts in ('N/A', '[N/A]') else _decimal(watts),
                           'power_limit_w': None if limit in ('N/A', '[N/A]') else _decimal(limit)})
    except csv.Error:
        return None
    return result


def snapshot(*, run=hw.command, proc=Path('/proc'), sys_thermal=Path('/sys/class/thermal'),
             disk_usage=shutil.disk_usage, now=None):
    """Take a brief read-only sample; unavailable measurements stay null."""
    started = time.monotonic()
    memory = hw.memory_info(hw.read(Path(proc) / 'meminfo'))
    try:
        disk = disk_usage('/')
        root_disk = {'free_bytes': disk.free, 'total_bytes': disk.total}
    except OSError:
        root_disk = {'free_bytes': None, 'total_bytes': None}
    try:
        uptime = hw.read(Path(proc) / 'uptime')
        uptime_seconds = float(uptime.split()[0]) if uptime else None
        if uptime_seconds is not None and uptime_seconds < 0:
            uptime_seconds = None
    except (ValueError, IndexError, TypeError):
        uptime_seconds = None
    return {'schema': 'argos-telemetry/1',
            'captured_utc': (now or datetime.now(timezone.utc)).isoformat(),
            'gpu': _gpu(run), 'cpu_temperature_sensors': _thermal_zones(Path(sys_thermal)),
            'memory': memory, 'root_disk': root_disk,
            'uptime_seconds': uptime_seconds,
            'sample_seconds': round(time.monotonic() - started, 3)}
