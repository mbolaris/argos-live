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
import subprocess
import time

directory = Path('/var/lib/argos-live/vm-test')
image = directory / 'TEST-DO-NOT-WRITE.raw'
key = (directory / 'test-only.key').read_text()
if not image.is_file():
    raise SystemExit('Prepare the disposable test image first.')

def boot(second=False):
    log = []
    p = subprocess.Popen(['qemu-system-x86_64', '-accel', 'kvm', '-cpu', 'host', '-m', '16384', '-smp', '8',
        '-drive', f'file={image},format=raw,if=none,id=media', '-device', 'qemu-xhci',
        '-device', 'usb-storage,drive=media,bootindex=1', '-nic', 'none',
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
                buffer += data
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
        wait_for(['login:'])
        send('argos\n')
        token = wait_for(['Password:', 'argos@argos-live:'])
        if token == 'Password:':
            send('live\n')
            wait_for(['argos@argos-live:'])
        if not second:
            send("printf 'yes\\n\\nyes\\n\\n' | argos setup; echo SETUP_EXIT=$?\n")
            wait_for(['SETUP_EXIT=0'], 180)
            send("test -f ~/.config/argos-live/state.json && touch ~/argos-persistence-sentinel && echo STATE_SAVED\n")
            wait_for(['\r\nSTATE_SAVED\r\n'])
            send("OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=$HOME/Models/argos-models OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=32768 ollama serve > /tmp/argos-test-ollama.log 2>&1 &\n")
            time.sleep(5)
            send("openclaw agent --local --agent main --session-id vm-acceptance --message 'Say hello in one sentence. /no_think'; echo CONVERSATION_EXIT=$?\n")
            wait_for(['CONVERSATION_EXIT=0'], 300)
            print('Virtual USB boot, encrypted unlock, generic setup, and local conversation passed.', flush=True)
        else:
            send("test -f ~/argos-persistence-sentinel && test -f ~/.config/argos-live/state.json && argos verify && echo PERSISTENCE_REBOOT_OK\n")
            wait_for(['\r\nPERSISTENCE_REBOOT_OK\r\n'], 120)
            print('Encrypted persistence and model artifact verification survived a full guest restart.', flush=True)
        send('sudo poweroff\n')
        p.wait(timeout=90)
    finally:
        if p.poll() is None:
            p.terminate(); p.wait(timeout=30)
        (directory / ('second-boot.log' if second else 'first-boot.log')).write_text(''.join(log))
        selector.close()

boot()
boot(second=True)
