#!/usr/bin/env python3
"""Embed a verified owner-supplied access bundle in a boot-time setup hook."""
import base64, hashlib, pathlib, sys, zipfile

bundle,out=map(pathlib.Path,sys.argv[1:])
data=bundle.read_bytes()
if hashlib.sha256(data).hexdigest()!='1cdd537cab237e310e46ab75d0cc359f26007179e7b93ffec098a0acea21e8ed':
    raise SystemExit('Approved bundle checksum mismatch')
with zipfile.ZipFile(bundle) as z:
    for name in z.namelist():
        p=pathlib.PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or not name.startswith('toronado-access/'):
            raise SystemExit('Unsafe bundle path')
text=r'''#!/bin/bash
set -euo pipefail
umask 077
root=/var/lib/argos-access-setup
mkdir -p "$root" /var/log/argos-boot /etc/systemd/journald.conf.d /var/log/journal
python3 - "$root" <<'PY'
import base64,io,pathlib,sys,zipfile,hashlib
data=base64.b64decode('PAYLOAD')
assert hashlib.sha256(data).hexdigest()=='1cdd537cab237e310e46ab75d0cc359f26007179e7b93ffec098a0acea21e8ed'
zipfile.ZipFile(io.BytesIO(data)).extractall(sys.argv[1])
PY
install -m 755 "$root/toronado-access/argos-collect-boot" /usr/local/sbin/argos-collect-boot
cat >/etc/systemd/journald.conf.d/argos-persistent.conf <<'JOURNAL'
[Journal]
Storage=persistent
SystemMaxUse=256M
SystemKeepFree=512M
RuntimeMaxUse=64M
SyncIntervalSec=30s
JOURNAL
cat >/etc/systemd/system/argos-boot-log.service <<'UNIT'
[Unit]
Description=Argos boot evidence snapshot
After=local-fs.target systemd-journald.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/argos-collect-boot
UNIT
cat >/etc/systemd/system/argos-boot-log.timer <<'TIMER'
[Unit]
Description=Argos automatic boot evidence
[Timer]
OnBootSec=20s
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
TIMER
cat >"$root/run.sh" <<'RUN'
#!/bin/bash
set -euo pipefail
umask 077
exec >>/var/log/argos-access-setup.log 2>&1
echo "Argos access setup started: $(date -Is)"
for attempt in $(seq 1 90); do
 if ip -4 -o addr show scope global | grep -q '192\.168\.1\.'; then break; fi
 sleep 2
done
bash /var/lib/argos-access-setup/toronado-access/setup-local.sh
touch /var/lib/argos-access-setup/complete
echo "Argos access setup completed: $(date -Is)"
RUN
chmod 700 "$root/run.sh"
install -d /etc/systemd/system/ssh.service.d
cat >/usr/local/sbin/argos-ssh-bind-lan <<'BIND'
#!/bin/bash
set -euo pipefail
for attempt in $(seq 1 90); do
 lan=$(ip -4 -o addr show scope global | awk '$4 ~ /^192\.168\.1\./ {split($4,a,"/"); print a[1]; exit}')
 if [ -n "$lan" ]; then
  test -f /etc/ssh/sshd_config.d/00-argos-lan.conf
  sed -i "s/^ListenAddress .*/ListenAddress $lan/" /etc/ssh/sshd_config.d/00-argos-lan.conf
  exit 0
 fi
 sleep 2
done
exit 1
BIND
chmod 755 /usr/local/sbin/argos-ssh-bind-lan
cat >/etc/systemd/system/ssh.service.d/argos-lan.conf <<'SSHUNIT'
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
ExecStartPre=/usr/local/sbin/argos-ssh-bind-lan
SSHUNIT
systemctl daemon-reload
systemctl restart --no-block systemd-journald
systemctl enable argos-boot-log.timer
systemctl start --no-block argos-boot-log.timer
# Configure once. On future boots the installed listener/journal survive in persistence.
if [ ! -f "$root/complete" ]; then
 systemd-run --no-block --unit=argos-access-setup --property=After=network-online.target --property=Wants=network-online.target /bin/bash "$root/run.sh"
fi
exit 0
'''.replace('PAYLOAD',base64.b64encode(data).decode())
out.write_text(text)
print('Verified access hook bytes:',len(text.encode()))
