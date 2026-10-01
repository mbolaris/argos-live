#!/usr/bin/env python3
"""Headless full-disk virtual USB boot and encrypted persistence acceptance test.

Only runs against the disposable TEST-DO-NOT-WRITE image with its local test key.
No physical devices are attached. Serial output stays in the private test directory.
"""
from pathlib import Path
import os
import selectors
import socket
import json
import re
import sys
import subprocess
import time

directory = Path('/var/lib/argos-live/vm-test')
image = directory / 'TEST-DO-NOT-WRITE.raw'
key = (directory / 'test-only.key').read_text()
if not image.is_file():
    raise SystemExit('Prepare the disposable test image first.')

def boot(second=False, gateway=False):
    log = []
    p = subprocess.Popen(['qemu-system-x86_64', '-accel', 'kvm', '-cpu', 'host', '-m', '16384', '-smp', '8',
        '-drive', f'file={image},format=raw,if=none,id=media', '-device', 'qemu-xhci',
        '-device', 'usb-storage,drive=media,bootindex=1,removable=on', '-nic', 'none',
        '-qmp', f'unix:{directory}/qmp.sock,server=on,wait=off',
        '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-no-reboot'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    selector = selectors.DefaultSelector(); selector.register(p.stdout, selectors.EVENT_READ)
    buffer = ''
    def wait_for(tokens, seconds=180):
        nonlocal buffer
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for token in tokens:
                if token in buffer:
                    buffer = buffer[buffer.index(token) + len(token):]
                    return token
            if p.poll() is not None:
                raise RuntimeError(f'Guest exited early ({p.returncode}).')
            for event, _ in selector.select(1):
                data = os.read(event.fileobj.fileno(), 65536).decode(errors='replace')
                log.append(data.replace(key, '[TEST KEY REDACTED]'))
                clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', data).replace('\r', '')
                buffer += clean
                (directory / ('second-boot.log' if second else 'first-boot.log')).write_text(''.join(log))
        raise RuntimeError('Guest timeout waiting for ' + repr(tokens))
    def send(text):
        p.stdin.write(text.encode()); p.stdin.flush()
    try:
        # Debian's boot menu waits for an explicit choice. Send Enter through
        # the emulated keyboard; serial input does not control that VGA menu.
        qmp = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        for _ in range(30):
            try:
                qmp.connect(str(directory / 'qmp.sock')); break
            except OSError:
                time.sleep(.2)
        qmp_file = qmp.makefile('rwb'); qmp_file.readline()
        def qcommand(command, arguments=None):
            body = {'execute': command}
            if arguments is not None: body['arguments'] = arguments
            qmp_file.write(json.dumps(body).encode() + b'\n'); qmp_file.flush()
            while True:
                result = json.loads(qmp_file.readline())
                if 'error' in result: raise RuntimeError(str(result['error']))
                if 'return' in result: return result['return']
        qcommand('qmp_capabilities')
        time.sleep(4)
        qcommand('human-monitor-command', {'command-line': 'sendkey ret'})
        wait_for(['Please unlock disk', 'Enter passphrase for', 'Please enter passphrase'])
        send(key + '\n')
        print('Encrypted persistence unlock submitted.', flush=True)
        wait_for(['login:'])
        send('argos\n')
        token = wait_for(['Password:', 'argos@argos-live:'])
        if token == 'Password:':
            send('live\n')
            wait_for(['argos@argos-live:'])
        print('Live guest login reached.', flush=True)
        send("grep -q 'persistence-media=removable-usb' /proc/cmdline && echo USB_ONLY_PERSISTENCE_OK\n")
        wait_for(['USB_ONLY_PERSISTENCE_OK\r\n', 'USB_ONLY_PERSISTENCE_OK\n'])
        if not second:
            qcommand('screendump', {'filename': '/mnt/c/Projects/Argos-Live/artifacts/live-desktop.png', 'format': 'png'})
        if not second:
            send("if test -f ~/.config/argos-live/state.json; then openclaw config validate; else printf 'yes\\n\\nyes\\n\\n' | argos setup; fi; echo SETUP_EXIT=$?\n")
            wait_for(['SETUP_EXIT=0'], 180)
            print('Generic setup completed.', flush=True)
            send("test -f ~/.config/argos-live/state.json && touch ~/argos-persistence-sentinel && echo STATE_SAVED\n")
            wait_for(['\nSTATE_SAVED\n'])
            print('Persistence sentinel saved.', flush=True)
            if gateway:
                send('argos start > /tmp/argos-test-stack.log 2>&1 &\n')
                send("python3 -c \"import socket,time; deadline=time.time()+120; ready=False; exec('while time.time()<deadline:\\n try:\\n  s=socket.create_connection((\\\"127.0.0.1\\\",18789),1); s.close(); ready=True; break\\n except OSError: time.sleep(1)'); print('GATEWAY_READY' if ready else 'GATEWAY_NOT_READY')\"\n")
                ready = wait_for(['\nGATEWAY_READY\n', '\nGATEWAY_NOT_READY\n'], 150)
                if ready != '\nGATEWAY_READY\n':
                    send('cat /tmp/argos-test-stack.log; echo STACK_LOG_END\n')
                    wait_for(['\nSTACK_LOG_END\n'])
                    raise RuntimeError('Gateway startup failed; inspect the private guest log.')
                print('Argos gateway listener ready.', flush=True)
                send("openclaw agent --agent main --session-id vm-gateway-acceptance --message 'Say hello in one sentence. /no_think'; echo CONVERSATION_EXIT=$?\n")
            else:
                send("OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=$HOME/Models/argos-models OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=32768 ollama serve > /tmp/argos-test-ollama.log 2>&1 &\n")
                time.sleep(5)
                send("openclaw agent --local --agent main --session-id vm-acceptance --message 'Say hello in one sentence. /no_think'; echo CONVERSATION_EXIT=$?\n")
            outcome = wait_for(['CONVERSATION_EXIT=0', 'CONVERSATION_EXIT=1'], 300)
            if outcome != 'CONVERSATION_EXIT=0':
                raise RuntimeError('OpenClaw conversation failed; inspect the private guest log.')
            send("systemctl is-active lightdm; pgrep -a Xorg; pgrep -a xfce4-session; echo DESKTOP_DIAGNOSTICS_DONE\n")
            wait_for(['\nDESKTOP_DIAGNOSTICS_DONE\n'])
            qcommand('screendump', {'filename': '/mnt/c/Projects/Argos-Live/artifacts/live-desktop.png', 'format': 'png'})
            print('Virtual USB boot, encrypted unlock, generic setup, and ' + ('gateway' if gateway else 'embedded') + ' local conversation passed.', flush=True)
        else:
            send("test -f ~/argos-persistence-sentinel && test -f ~/.config/argos-live/state.json && argos verify && echo PERSISTENCE_REBOOT_OK\n")
            wait_for(['\nPERSISTENCE_REBOOT_OK\n'], 120)
            print('Encrypted persistence and model artifact verification survived a full guest restart.', flush=True)
        send('sudo poweroff\n')
        p.wait(timeout=90)
    finally:
        if p.poll() is None:
            p.terminate(); p.wait(timeout=30)
        (directory / ('second-boot.log' if second else 'first-boot.log')).write_text(''.join(log))
        selector.close()

if __name__ == '__main__':
    if '--gateway-only' in sys.argv:
        boot(gateway=True)
    else:
        boot()
        boot(second=True)
