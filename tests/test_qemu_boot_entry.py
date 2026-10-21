import importlib.util
import base64
import hashlib
import json
import tempfile
import re
import zlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_smoke', ROOT / 'scripts/smoke-qemu-iso.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootEntryTests(unittest.TestCase):
    def test_managed_lab_uses_native_firefox_click_not_qmp_mouse_input(self):
        managed = (ROOT / 'scripts/qemu-managed-check.py').read_text()
        harness = (ROOT / 'scripts/smoke-qemu-iso.py').read_text()
        self.assertIn('with FirefoxLabSession() as native_lab', managed)
        self.assertIn('native_lab.click_baseline()', managed)
        self.assertIn("'scripts/qemu-firefox-check.py'", harness)
        self.assertNotIn('ARGOS_C3_UI_READY', managed)
        self.assertNotIn('click_rendered_baseline', harness)

    def test_dashboard_capture_removes_token_bearing_toolbar_rows(self):
        width, height, crop = 800, 760, 160
        toolbar = b'\xff\x00\x00' * width * crop
        content = b'\x01\x02\x03' * width * (height - crop)
        raw = f'P6\n{width} {height}\n255\n'.encode() + toolbar + content
        value = module.crop_ppm_top(raw, crop)
        header = f'P6\n{width} {height - crop}\n255\n'.encode()
        self.assertTrue(value.startswith(header))
        self.assertEqual(value[len(header):], content)

    def test_dashboard_capture_refuses_unredactable_frame(self):
        raw = b'P6\n800 700\n255\n' + b'\0' * (800 * 700 * 3)
        with self.assertRaisesRegex(ValueError, 'safely crop'):
            module.crop_ppm_top(raw, 160)

    def test_lab_progress_capture_only_accepts_ability_phase(self):
        self.assertEqual(module.lab_progress_phase('{"phase":"ability"}'), 'ability')
        self.assertEqual(module.lab_progress_phase(
            '{"token":"private","phase":"ability"}'), 'ability')
        for line in ('{"phase":"model-service"}', '{"phase":"completed"}', 'not json'):
            self.assertIsNone(module.lab_progress_phase(line))

    def test_guest_entry_refuses_persistence_arguments(self):
        entry = ('menuentry "Argos guest - resets on reboot, no passphrase" {\n'
                 ' linux /live/vmlinuz boot=live console=tty0 nopersistence argos.guest=1\n'
                 ' initrd /live/initrd.img\n}\n')
        self.assertIn('nopersistence', module.desktop_entry(entry, guest=True)[2])
        for replacement in ('persistence', 'nopersistence persistence-encryption=luks', ''):
            with self.assertRaises(ValueError):
                module.desktop_entry(entry.replace('nopersistence', replacement), guest=True)

    def test_managed_record_cannot_claim_physical_or_browser_reply_acceptance(self):
        value = {'schema': 'argos-qemu-managed/1', 'setup_mode': 'managed',
            'desktop_started': True, 'dashboard_authenticated': True, 'automatic_first_boot': True,
            'bundled_read_only_source': True, 'model_reply_verified': True,
            'mission_control_visible': True, 'chat_destination_available': True,
            'requires_screenshot_review': True, 'model_lab_launcher_available': True,
            'model_lab_launch_command_succeeded': True, 'model_lab_ui_visible': True,
            'model_lab_button_clicked': True, 'model_lab_baseline_completed': True,
            'model_lab_speed_result_saved': True, 'model_lab_ability_result_saved': True,
            'model_lab_assistant_resumed': True,
            'network_routes': False, 'physical_acceptance': False, 'browser_chat_reply_verified': False,
            'startup_metrics': {'backend': {'mode': 'CPU'}}}
        def wire(item): return 'ARGOS_C3_RESULT ' + json.dumps(item) + '\n'
        self.assertEqual(module.guest_result(wire(value), setup_mode='managed'), value)
        with self.assertRaisesRegex(ValueError, 'RAM-only'):
            module.guest_result(wire(value), setup_mode='managed', guest=True)
        self.assertEqual(module.guest_result(wire(dict(value, guest_ram_policy_verified=True)),
                         setup_mode='managed', guest=True)['guest_ram_policy_verified'], True)
        self.assertIsNone(module.guest_result(wire(value)[:-1], setup_mode='managed'))
        for changed in (dict(value, physical_acceptance=True), dict(value, browser_chat_reply_verified=True),
                        dict(value, mission_control_visible=False), dict(value, chat_destination_available=False),
                        dict(value, model_lab_launch_command_succeeded=False),
                        dict(value, model_lab_ui_visible=False),
                        dict(value, model_lab_button_clicked=False),
                        dict(value, model_lab_baseline_completed=False),
                        dict(value, model_lab_speed_result_saved=False),
                        dict(value, model_lab_ability_result_saved=False),
                        dict(value, model_lab_assistant_resumed=False),
                        dict(value, network_routes=True), dict(value, schema='argos-qemu-smoke/1')):
            with self.assertRaises(ValueError):
                module.guest_result(wire(changed), setup_mode='managed')

    def test_real_proctor_smoke_requires_signed_uncalibrated_receipt_and_recovery(self):
        value = {'schema': 'argos-qemu-managed/1', 'setup_mode': 'managed',
            'desktop_started': True, 'dashboard_authenticated': True, 'automatic_first_boot': True,
            'bundled_read_only_source': True, 'model_reply_verified': True,
            'mission_control_visible': True, 'chat_destination_available': True,
            'requires_screenshot_review': True, 'model_lab_launcher_available': True,
            'model_lab_launch_command_succeeded': True, 'model_lab_ui_visible': True,
            'model_lab_button_clicked': True, 'model_lab_baseline_completed': True,
            'model_lab_speed_result_saved': True, 'model_lab_ability_result_saved': True,
            'model_lab_assistant_resumed': True, 'network_routes': False,
            'physical_acceptance': False, 'browser_chat_reply_verified': False,
            'startup_metrics': {'backend': {'mode': 'CPU'}},
            'proctor_practice_recorded': True, 'proctor_practice_completed': True,
            'proctor_practice_outcome': 'COMPLETED', 'proctor_transcript_saved': True,
            'proctor_signature_verified': True, 'proctor_model_identity_bound': True,
            'proctor_assistant_resumed': True, 'proctor_calibration_status': 'uncalibrated',
            'proctor_campaign_started': False, 'proctor_backend_weights_loaded_attested': False,
            'proctor_transcript_id': 'a' * 32, 'proctor_model_tag': 'qwen3:0.6b',
            'proctor_score': {'correct': 3, 'total': 4}, 'proctor_answered': 4}
        wire = 'ARGOS_C3_RESULT ' + json.dumps(value) + '\n'
        self.assertEqual(module.guest_result(wire, setup_mode='managed', proctor_smoke=True), value)
        incomplete = dict(value, proctor_practice_completed=False, proctor_practice_outcome='ABANDONED',
                          proctor_score={'correct': 1, 'total': 2})
        with self.assertRaisesRegex(ValueError, 'practice did not complete'):
            module.guest_result('ARGOS_C3_RESULT ' + json.dumps(incomplete) + '\n',
                                setup_mode='managed', proctor_smoke=True)
        for changed in (dict(value, proctor_signature_verified=False),
                        dict(value, proctor_practice_recorded=False),
                        dict(value, proctor_transcript_id='bad'),
                        dict(value, proctor_practice_outcome='ABANDONED'),
                        dict(value, proctor_calibration_status='calibrated'),
                        dict(value, proctor_campaign_started=True),
                        dict(value, proctor_backend_weights_loaded_attested=True),
                        dict(value, proctor_score={'correct': 1, 'total': 1}),
                        dict(value, proctor_score={'correct': 5, 'total': 4}),
                        dict(value, proctor_answered=0), dict(value, proctor_answered=True)):
            with self.assertRaises(ValueError):
                module.guest_result('ARGOS_C3_RESULT ' + json.dumps(changed) + '\n',
                                    setup_mode='managed', proctor_smoke=True)

    def test_real_proctor_smoke_refuses_guest_tcg_and_nonmanaged_runs_before_io(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'empty'
            for options in ({'setup_mode': 'managed', 'accel': 'tcg'},
                            {'setup_mode': 'managed', 'guest_mode': True, 'accel': 'kvm'},
                            {'setup_mode': 'interactive', 'accel': 'kvm'}):
                with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'requires managed'):
                    module.run(Path('missing.iso'), output, proctor_smoke=True, **options)

    def test_acceptance_payload_sets_modes_and_is_valid_python(self):
        payload = module.acceptance_payload('managed', False, True)
        self.assertTrue(payload.startswith(
            b"ARGOS_QEMU_SETUP_MODE = 'managed'\nARGOS_QEMU_GUEST_MODE = False\n"
            b"ARGOS_QEMU_PROCTOR_SMOKE = True\n"))
        compile(payload, '<qemu-acceptance-payload>', 'exec')

    def test_large_guest_payload_is_chunked_checked_and_never_shell_source(self):
        source = b'$(untrusted shell text)' + b''.join(hashlib.sha256(str(i).encode()).digest() for i in range(200))
        commands = module.guest_commands(source)
        self.assertGreater(len(commands), 3)
        self.assertTrue(all(len(command) < 2000 for command in commands))
        chunks = [re.search(r"printf %s '([^']+)'", command)[1] for command in commands[:-1]]
        self.assertTrue(all(len(chunk) <= module.GUEST_PAYLOAD_CHUNK_SIZE for chunk in chunks))
        encoded = ''.join(chunks)
        packed = base64.b64decode(encoded)
        self.assertEqual(zlib.decompress(packed), source)
        self.assertIn(hashlib.sha256(packed).hexdigest(), commands[-1])
        self.assertNotIn('$(untrusted', ''.join(commands))

    def test_placeholder_screenshot_cannot_pass_graphical_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'screen.ppm'
            for raw in (b'not a PPM', b'P6\n640 480\n255\n' + b'\0' * (640 * 480 * 3),
                        b'P6\n800 600\n255\n' + b'\0' * (800 * 600 * 3)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    module.graphical_frame(path)
            near_blank = bytearray([249, 249, 251] * (800 * 600))
            for index in range(0, 30000, 3):
                near_blank[index:index + 3] = bytes((index % 251, index % 127, index % 31))
            path.write_bytes(b'P6\n800 600\n255\n' + near_blank)
            with self.assertRaisesRegex(ValueError, 'blank or placeholder'):
                module.graphical_frame(path)
            path.write_bytes(b'P6\n800 600\n255\n' +
                             bytes(value for pixel in range(800 * 600) for value in
                                   (pixel % 251, pixel % 127, pixel % 31)))
            module.graphical_frame(path)

    def test_dashboard_capture_retries_transient_blank_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'screen.ppm'
            blank = b'P6\n800 600\n255\n' + b'\0' * (800 * 600 * 3)
            rendered = b'P6\n800 600\n255\n' + bytes(
                value for pixel in range(800 * 600) for value in
                (pixel % 251, pixel % 127, pixel % 31))
            frames = iter([blank, rendered])
            def capture(_qmp, target): target.write_bytes(next(frames))
            with unittest.mock.patch.object(module, 'screenshot_dashboard_content',
                                            side_effect=capture), \
                    unittest.mock.patch.object(module.time, 'sleep') as pause:
                module.capture_graphical_dashboard(Path('qmp.sock'), path)
            self.assertEqual(pause.call_args.args, (.5,))

    def test_dashboard_capture_fails_after_bounded_blank_frame_wait(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'screen.ppm'
            blank = b'P6\n800 600\n255\n' + b'\0' * (800 * 600 * 3)
            with unittest.mock.patch.object(module.time, 'monotonic', side_effect=[0, 0, 2]), \
                    unittest.mock.patch.object(module, 'screenshot_dashboard_content',
                                                side_effect=lambda qmp, target: target.write_bytes(blank)), \
                    unittest.mock.patch.object(module.time, 'sleep'):
                with self.assertRaisesRegex(ValueError, 'remained blank'):
                    module.capture_graphical_dashboard(Path('qmp.sock'), path, timeout=1)

    def test_serial_result_waits_for_whole_nested_record(self):
        value = {'schema': 'argos-qemu-smoke/1', 'desktop_started': True,
                 'dashboard_authenticated': True, 'result_round_trip': True,
                 'native_firefox_dashboard': True,
                 'model_lab_launcher_available': True,
                 'network_routes': False, 'automatic_first_boot': False,
                 'physical_acceptance': False, 'backend': 'CPU', 'generation_limit': 8,
                 'setup_mode': 'interactive', 'bundled_read_only_source': False,
                 'generation_tokens_per_second': {'median': 1.4, 'reported_runs': 3}}
        wire = 'noise\r\nARGOS_C3_RESULT ' + json.dumps(value) + '\r\n'
        for end in range(len(wire)):
            self.assertIsNone(module.guest_result(wire[:end]))
        self.assertEqual(module.guest_result(wire), value)
        automatic = dict(value, setup_mode='auto', bundled_read_only_source=True)
        automatic_wire = 'ARGOS_C3_RESULT ' + json.dumps(automatic) + '\n'
        self.assertEqual(module.guest_result(automatic_wire, setup_mode='auto'), automatic)
        with self.assertRaises(ValueError):
            module.guest_result(automatic_wire)
        for changed in (dict(value, desktop_started=False), dict(value, network_routes=True),
                        dict(value, backend='GPU'), dict(value, generation_limit=128)):
            with self.assertRaises(ValueError):
                module.guest_result('ARGOS_C3_RESULT ' + json.dumps(changed) + '\n')

    def test_original_desktop_arguments_preserved_and_serial_only_added_for_vm(self):
        text = '''menuentry "Argos desktop" {
 linux /live/vmlinuz boot=live components persistence console=tty0 module_blacklist=nouveau
 initrd /live/initrd.img
}'''
        kernel, initrd, append = module.desktop_entry(text)
        self.assertEqual(kernel, '/live/vmlinuz')
        self.assertEqual(initrd, '/live/initrd.img')
        self.assertEqual(append, 'boot=live components persistence console=tty0 module_blacklist=nouveau console=ttyS0,115200')

    def test_missing_or_traversal_entry_rejected(self):
        for text in ('', 'menuentry "Argos desktop" { linux /live/../escape boot=live console=tty0\ninitrd /live/initrd.img\n}',
                     'menuentry "Argos desktop" {\nlinux /live/vmlinuz console=tty0\ninitrd /live/initrd.img\n}'):
            with self.assertRaises(ValueError):
                module.desktop_entry(text)


if __name__ == '__main__':
    unittest.main()
