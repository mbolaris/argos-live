"""Failure paths for the personal-robot journey, using real storage code on real temp files.

Only device discovery (mountinfo/lsblk) and the model backend are simulated. Space and
permission failures are real filesystem or real OSError paths, and the permission test
runs for real when the suite is run as an unprivileged user.
"""
import errno
import json
import os
from pathlib import Path
import stat
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from argoslive import model_controls, storage_view as sv
from test_model_controls import Queue
from test_lab import Assistant
from test_storage_view import Base, GIB


class GateTests(Base):
    def state_file(self):
        return self.home / '.config/argos-live/state.json'

    def confirm(self):
        state = self.write_state()
        models = Path(state['storage'])
        state['storage_confirmed'] = {'path': state['storage'], 'storage_id': 'ident',
                                      'at': '2026-10-06T00:00:00+00:00'}
        self.state_file().write_text(json.dumps(state))
        return models

    def test_missing_state_file_is_a_clear_refusal(self):
        self.state_file().unlink(missing_ok=True)
        with self.assertRaisesRegex(ValueError, 'Choose where models are stored'):
            sv.require_ready_for_download(self.home)

    def test_corrupt_state_file_is_a_clear_refusal(self):
        self.state_file().write_text('{')
        with self.assertRaises(ValueError):
            sv.require_ready_for_download(self.home)

    def test_unconfirmed_store_is_refused(self):
        self.write_state()
        with self.assertRaisesRegex(ValueError, 'Choose where models are stored'):
            sv.require_ready_for_download(self.home)

    def test_unplugged_or_swapped_volume_is_refused(self):
        models = self.confirm()
        (models / '.argos-storage-id').write_text('another-volume\n')
        with self.assertRaisesRegex(ValueError, 'different identity'):
            sv.require_ready_for_download(self.home)
        (models / '.argos-storage-id').unlink()
        with self.assertRaises(ValueError):
            sv.require_ready_for_download(self.home)

    def test_full_drive_during_the_write_check_is_reported_as_full(self):
        self.confirm()
        with mock.patch('os.fsync', side_effect=OSError(errno.ENOSPC, 'No space left on device')):
            with self.assertRaisesRegex(ValueError, 'drive is full'):
                sv.require_ready_for_download(self.home)
        leftovers = [p.name for p in (self.persist / 'rw/models').iterdir() if p.name.startswith('.argos-write-check')]
        self.assertEqual(leftovers, [], 'a failed write check must clean up after itself')

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores directory permissions; run as an unprivileged user')
    def test_read_only_store_is_refused_without_writing(self):
        models = self.confirm()
        models.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            with self.assertRaisesRegex(ValueError, 'did not accept a test write'):
                sv.require_ready_for_download(self.home)
            self.assertEqual(sorted(p.name for p in models.iterdir()), ['.argos-storage-id'])
        finally:
            models.chmod(stat.S_IRWXU)

    def test_failed_gate_creates_no_job_and_never_touches_the_assistant(self):
        self.confirm()
        assistant, queue = Assistant(self.root / 'assistant-home'), Queue()
        (self.root / 'assistant-home').mkdir()
        assistant.home = self.home
        controller = model_controls.Controller(assistant, queue_factory=lambda _: queue)
        self.addCleanup(controller.close)
        with mock.patch('os.fsync', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(ValueError):
                controller.start(tag='qwen3:0.6b')
        self.assertEqual(queue.calls, [])
        self.assertEqual(assistant.calls, [])

    def test_choosing_a_full_drive_rolls_back_everything(self):
        self.write_state()
        before = self.state_file().read_bytes()
        rows = sv.candidates(*self.topology(), probe=self.probe)
        target = next(r for r in rows if r['path'].startswith(str(self.data)))
        with mock.patch('os.fsync', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(OSError):
                sv.choose(self.home, target['id'], topology=self.topology, probe=self.probe)
        self.assertEqual(self.state_file().read_bytes(), before)
        self.assertFalse((self.data / 'ArgosLive').exists(), 'directories created for the failed choice are removed')

    def target(self):
        rows = sv.candidates(*self.topology(), probe=self.probe)
        return next(r for r in rows if r['path'].startswith(str(self.data)))

    def choose(self):
        row = self.target()
        return row, lambda: sv.choose(self.home, row['id'], topology=self.topology, probe=self.probe)

    def test_failed_state_write_removes_only_what_the_choice_created(self):
        self.write_state()
        before = self.state_file().read_bytes()
        row, run = self.choose()
        with mock.patch.object(sv, 'write_json', side_effect=OSError(errno.EIO, 'io error')):
            with self.assertRaises(OSError):
                run()
        self.assertEqual(self.state_file().read_bytes(), before)
        self.assertFalse((self.data / 'ArgosLive').exists(), 'no unusable destination is left behind')

    def test_preexisting_empty_destination_survives_a_failed_choice_without_our_marker(self):
        self.write_state()
        row, run = self.choose()
        Path(row['path']).mkdir(parents=True)
        with mock.patch.object(sv, 'write_json', side_effect=OSError(errno.EIO, 'io error')):
            with self.assertRaises(OSError):
                run()
        self.assertTrue(Path(row['path']).is_dir())
        self.assertEqual(list(Path(row['path']).iterdir()), [], 'our marker is gone, nothing else was touched')

    def test_a_marker_someone_else_created_is_never_deleted(self):
        self.write_state()
        row, run = self.choose()
        def racing(path, raw):
            Path(path).write_text('belongs to someone else')
            raise FileExistsError(errno.EEXIST, 'exists', str(path))
        with mock.patch.object(sv.reboot_evidence, 'write_exclusive', side_effect=racing):
            with self.assertRaises(FileExistsError):
                run()
        self.assertEqual((Path(row['path']) / '.argos-storage-id').read_text(), 'belongs to someone else')

    def test_state_replaced_then_failing_is_restored_before_cleanup(self):
        state = self.write_state()
        before = self.state_file().read_bytes()
        row, run = self.choose()
        real = sv.write_json
        calls = []
        def replace_then_fail(path, value):
            calls.append(value.get('storage'))
            real(path, value)
            if len(calls) == 1:
                raise OSError(errno.EIO, 'directory sync failed')
        with mock.patch.object(sv, 'write_json', side_effect=replace_then_fail):
            with self.assertRaises(OSError):
                run()
        self.assertEqual(json.loads(self.state_file().read_text())['storage'], state['storage'])
        self.assertFalse((self.data / 'ArgosLive').exists())

    def test_destination_in_use_is_kept_when_the_old_state_cannot_be_restored(self):
        self.write_state()
        row, run = self.choose()
        real = sv.write_json
        calls = []
        def replace_then_fail_always(path, value):
            calls.append(1)
            if len(calls) == 1:
                real(path, value)
            raise OSError(errno.EIO, 'io error')
        with mock.patch.object(sv, 'write_json', side_effect=replace_then_fail_always):
            with self.assertRaises(OSError):
                run()
        self.assertEqual(json.loads(self.state_file().read_text())['storage'], row['path'])
        self.assertTrue((Path(row['path']) / '.argos-storage-id').is_file(), 'a destination the configuration uses is not deleted')

    def test_drive_without_room_is_never_offered(self):
        tiny = lambda path: {'total_bytes': 2 * GIB, 'free_bytes': GIB // 2}
        self.assertEqual([r for r in sv.candidates(*self.topology(), probe=tiny) if r['kind'] == 'disk'], [])


class DownloadFailureTests(Base):
    def setUp(self):
        super().setUp()
        self.assistant = Assistant(self.root / 'assistant-home', active=True)
        (self.root / 'assistant-home').mkdir()
        self.queue = Queue()
        self.controller = model_controls.Controller(self.assistant, queue_factory=lambda _: self.queue,
                                                    storage_gate=lambda home: None)
        self.addCleanup(self.controller.close)

    def finish(self):
        self.controller.worker.join(5)
        self.assertFalse(self.controller.worker.is_alive())

    def test_failed_download_restores_the_chat_assistant_and_reports_failure(self):
        self.queue.run_verified = lambda job, **kw: {'state': 'failed', 'reply_test': None}
        self.controller.start(tag='qwen3:0.6b')
        self.finish()
        value = self.controller.snapshot()
        self.assertEqual(value['phase'], 'failed')
        self.assertTrue(value['resume_requested'])
        self.assertEqual(self.assistant.calls[0], 'pause')
        self.assertEqual(self.assistant.calls[-1], 'resume')

    def test_backend_that_cannot_start_is_a_failure_not_a_success(self):
        def broken(job, **kw):
            raise OSError('model failed to start')
        self.queue.run_verified = broken
        self.controller.start(tag='qwen3:0.6b')
        self.finish()
        value = self.controller.snapshot()
        self.assertNotEqual(value['phase'], 'completed')
        self.assertEqual(self.assistant.calls[-1], 'resume')
        self.assertFalse(self.assistant.lab_active)

    def test_cancel_during_download_is_terminal_and_resumes_chat(self):
        import threading
        gate = threading.Event()
        self.queue.gate = gate
        self.controller.start(tag='qwen3:0.6b')
        self.assertTrue(gate.wait(3))
        self.controller.cancel()
        self.finish()
        self.assertEqual(self.controller.snapshot()['phase'], 'cancelled')
        self.assertEqual(self.assistant.calls[-1], 'resume')
        receipt = self.controller.snapshot()['reply_test']
        self.assertFalse(receipt and receipt.get('text_reply_verified'), 'a cancelled download must not claim a verified reply')


if __name__ == '__main__':
    unittest.main()
