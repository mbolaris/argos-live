#!/usr/bin/env python3
"""Serve the real dashboard, controllers and storage code over fixture hardware and a fixture model.

Used by smoke-journey-browser.mjs. Real: HTTP routes, session token, storage choice and write
check, trial runners and scoring, results store, journal, Command Center. Simulated: mountinfo and
lsblk, and the model backend (a fixture that answers from the suite's own references).
Prints the tokenized URL on the first line.
"""
import contextlib
from functools import partial
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtime'), str(ROOT / 'tests')]
from argoslive import command_center, lab as lab_module, storage, storage_view
from argoslive.results import Store
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer
from test_bench_speed import Backend
from test_doc_trial import DocBackend
from test_lab import Assistant

PASSAGE_ANSWER = {'status': 'answered', 'answer': '35 minutes', 'quote': 'Crossings take 35 minutes.'}


class Fixture(DocBackend):
    """Answers suite items from references and any pasted document with a supported quotation."""
    def generate(self, model, prompt, **kwargs):
        callback = kwargs.get('callback')
        if callback:
            callback({'response': 'Examining passage… '})
        time.sleep(0.04)
        result = super().generate(model, prompt, **kwargs)
        if prompt and 'MEASURED RECEIPT:' in prompt:
            result['text'] = 'The quick exercises exposed limits in my structured answers. I would like to try the repair brief next and show the sentence I used.'
        if prompt and 'DOCUMENT:' in prompt:
            result['text'] = json.dumps(PASSAGE_ANSWER)
        return result


def main():
    temp = tempfile.TemporaryDirectory(prefix='argos-journey-')
    root = Path(temp.name).resolve()
    home, volume, medium, initial = root / 'home', root / 'volume', root / 'medium', root / 'initial'
    for path in (home / '.config/argos-live', volume, medium, initial):
        path.mkdir(parents=True)
    (initial / '.argos-storage-id').write_text('initial\n')
    (home / '.config/argos-live/state.json').write_text(json.dumps(
        {'storage': str(initial), 'storage_id': 'initial', 'model': 'fixture:latest'}))
    mountinfo = '\n'.join([f'20 1 8:17 / {medium} ro - iso9660 /dev/sdb1 ro', f'30 1 8:1 / {volume} rw - ext4 /dev/sda1 rw'])
    lsblk = json.dumps({'blockdevices': [
        {'name': '/dev/sda', 'type': 'disk', 'fstype': None, 'uuid': None, 'label': None, 'tran': 'sata', 'maj:min': '8:0',
         'children': [{'name': '/dev/sda1', 'type': 'part', 'fstype': 'ext4', 'uuid': 'fixture-volume', 'label': 'DATA', 'maj:min': '8:1'}]},
        {'name': '/dev/sdb', 'type': 'disk', 'fstype': None, 'uuid': None, 'label': None, 'tran': 'usb', 'maj:min': '8:16',
         'children': [{'name': '/dev/sdb1', 'type': 'part', 'fstype': 'iso9660', 'uuid': 'fixture-boot', 'label': 'ARGOS', 'maj:min': '8:17'}]}]})
    real_read, real_command = storage.read, storage.command
    for patch in (mock.patch.object(storage, 'LIVE_MEDIA', {str(medium)}),
                  mock.patch.object(storage, 'read', lambda p, *a, **k: mountinfo if str(p) == '/proc/self/mountinfo' else real_read(p, *a, **k)),
                  mock.patch.object(storage, 'command', lambda c, *a, **k: lsblk if c == storage.LSBLK else real_command(c, *a, **k))):
        patch.start()
    fixture_hw = {
        'schema': 'argos-hw/1',
        'cpu': {'model': 'AMD Ryzen 7 7800X3D (fixture)', 'cores': 8, 'threads': 16},
        'ram': {'total_bytes': 32 * 1024**3, 'available_bytes': 24 * 1024**3},
        'gpus': [{
            'bus': '0000:01:00.0',
            'name': 'NVIDIA GeForce RTX 4080 (fixture)',
            'vendor': 'NVIDIA',
            'vram_total_bytes': 16 * 1024**3,
            'vram_used_bytes': 2 * 1024**3,
            'driver': '550.54.14',
        }],
        'disks': [],
        'model_directories': [{'path': str(initial), 'total_bytes': 500 * 1024**3, 'free_bytes': 200 * 1024**3}],
        'kernel': '6.6.0-argos',
        'secure_boot': True,
    }
    from argoslive import bench_ability, bench_speed, doc_trial, hw
    from argoslive.web import models, status as live_status
    hw.snapshot = lambda *a, **kw: fixture_hw
    for mod in (bench_ability, bench_speed, doc_trial):
        if hasattr(mod, 'hw'):
            mod.hw.snapshot = lambda *a, **kw: fixture_hw
        for fn_name in ('run', 'execute'):
            fn = getattr(mod, fn_name, None)
            if fn and getattr(fn, '__kwdefaults__', None) and 'hardware' in fn.__kwdefaults__:
                fn.__kwdefaults__['hardware'] = lambda *a, **kw: fixture_hw
    for fn in (models.snapshot, live_status.snapshot):
        if getattr(fn, '__kwdefaults__', None) and 'hardware' in fn.__kwdefaults__:
            fn.__kwdefaults__['hardware'] = lambda *a, **kw: fixture_hw
    mock.patch.object(hw, 'snapshot', lambda *a, **kw: fixture_hw).start()
    topology = lambda: (storage.mount_table(mountinfo), storage.block_table(lsblk), 8 * 1024**3)
    assistant = Assistant(home)
    backend = Fixture()

    @contextlib.contextmanager
    def provide(target, **options):
        yield backend
    assistant.backend = provide
    store = Store(home / '.local/share/argos-live/results')
    lab = lab_module.Controller(assistant, store=store)
    view = partial(storage_view.snapshot, topology=topology, boot='11111111-1111-4111-8111-111111111111')
    storage_controller = storage_view.Controller(assistant, home=home, view=view,
                                                 chooser=partial(storage_view.choose, topology=topology))
    # The fixture store holds no real manifest, so its identity is supplied; the backend reports the same digest.
    command = command_center.Controller(home, store, lab=lab, storage=storage_controller,
                                        identity=lambda _: {'model': 'fixture:latest', 'digest': 'a' * 64})
    with DashboardServer(port=0, lab=lab, storage=storage_controller, command=command,
                         benchmarks=BenchmarkView(store),
                         models_provider=partial(models.snapshot, home=home, hardware=lambda *a, **kw: fixture_hw),
                         status_provider=partial(live_status.snapshot, home=home, hardware=lambda *a, **kw: fixture_hw)) as server:
        print(server.url, flush=True)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
        sys.stdin.read()
    lab.close()
    temp.cleanup()


if __name__ == '__main__':
    main()
