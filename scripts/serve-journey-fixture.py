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
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtime'), str(ROOT / 'tests')]
from argoslive import assistant_trial, command_center, lab as lab_module, storage, storage_view
from argoslive.results import Store
from argoslive.web.benchmarks import View as BenchmarkView
from argoslive.web.server import DashboardServer
from test_bench_speed import Backend
from test_doc_trial import DocBackend
from test_lab import Assistant
from test_assistant_trial import Runner as TrialRunner


class FixtureAssistant(Assistant):
    """Retains the existing Lab recovery fixture; supports reserved trial restarts."""
    def start(self, *, _reserved=False):
        assert _reserved or not self.lab_active
        self.calls.append('resume')
        self.active = True


class TrialStartup:
    """Only the trial sees immediate fake readiness; the Lab still tests delayed recovery."""
    def __init__(self, assistant):
        self.assistant = assistant
        self.home, self.lock = assistant.home, assistant.lock

    @property
    def lab_active(self):
        return self.assistant.lab_active

    @lab_active.setter
    def lab_active(self, value):
        self.assistant.lab_active = value

    @property
    def chat_claimed(self):
        return self.assistant.chat_claimed

    @chat_claimed.setter
    def chat_claimed(self, value):
        self.assistant.chat_claimed = value

    def snapshot(self):
        active = self.assistant.active
        return {'active': active, 'phase': 'ready' if active else 'stopped', 'model_reply_verified': active}

    def stop(self):
        self.assistant.stop()

    def start(self, *, _reserved=False):
        self.assistant.start(_reserved=_reserved)


class SlowTrialRunner(TrialRunner):
    """Fixture assistant replies, paced so trial progress is visible. Never a real model."""
    def turn(self, message):
        time.sleep(STREAM_DELAY * 10)
        return super().turn(message)

# Visual acceptance can slow streaming to capture a live answer; default keeps tests fast.
STREAM_DELAY = float(os.environ.get('ARGOS_FIXTURE_STREAM_DELAY', '0.012'))
PASSAGE_ANSWER = {'status': 'answered', 'answer': '35 minutes', 'quote': 'Crossings take 35 minutes.'}


class Fixture(DocBackend):
    """Answers suite items from references and any pasted document with a supported quotation."""
    def generate(self, model, prompt, **kwargs):
        callback = kwargs.get('callback')
        cancel = kwargs.get('cancel')
        system = kwargs.get('system')
        result = super().generate(model, prompt, **kwargs)
        if prompt and 'MEASURED RECEIPT:' in prompt:
            result['text'] = 'I found most facts, but one answer ignored the required format. I would try strict format instructions for lab tests and compare on the same trial.'
        elif prompt and 'DOCUMENT:' in prompt:
            result['text'] = json.dumps(PASSAGE_ANSWER)
        elif prompt in self.answers:
            item = self.answers[prompt]
            if not item.get('scored'):
                result['text'] = 'A short summary.'
            else:
                # If concise system instructions are present, answer reference format (0 format errors)
                # If uninstructed standard calibration, simulate 1 format error to demonstrate recipe intervention
                if not system and item.get('id') == 'answer-01':
                    result['text'] = item.get('malformed', 'I could not find it.')
                else:
                    result['text'] = item['reference']

        text = result.get('text', '')
        if callback and text:
            chunk_size = 5
            for i in range(0, len(text), chunk_size):
                if cancel is not None and cancel.is_set():
                    break
                chunk = text[i:i + chunk_size]
                callback({'response': chunk})
                time.sleep(STREAM_DELAY)
        else:
            time.sleep(0.02)
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
    assistant = FixtureAssistant(home)
    # A fixture everyday-assistant workspace for the U10 trial: persona files and operating notes.
    workspace = home / '.openclaw/workspace'
    workspace.mkdir(parents=True)
    (home / '.openclaw/openclaw.json').write_text(json.dumps({'agents': {'defaults': {'workspace': str(workspace)}}}))
    (workspace / 'AGENTS.md').write_text('# Operating notes\nBe kind and brief.\n')
    for name in ('SOUL.md', 'IDENTITY.md', 'USER.md'):
        (workspace / name).write_text(f'Fixture {name}\n')
    trial = assistant_trial.Controller(TrialStartup(assistant), home=home, runner=SlowTrialRunner(home), ready_timeout=10,
                                       validate_profile=lambda home: (home, 'fixture:latest'))
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
    with DashboardServer(port=0, lab=lab, storage=storage_controller, command=command, assistant_trial=trial,
                         benchmarks=BenchmarkView(store),
                         models_provider=partial(models.snapshot, home=home, hardware=lambda *a, **kw: fixture_hw),
                         status_provider=partial(live_status.snapshot, home=home, hardware=lambda *a, **kw: fixture_hw)) as server:
        print(server.url, flush=True)
        t = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        t.start()
        sys.stdin.read()
        try:
            server.shutdown()
        except Exception:
            pass
        t.join(timeout=1)
    trial.close()
    lab.close()
    try:
        temp.cleanup()
    except Exception:
        pass


if __name__ == '__main__':
    main()
