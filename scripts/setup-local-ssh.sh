#!/bin/bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo bash setup-local-ssh.sh PUBLIC_KEY CONTROLLER_IP [USER]'; exit 1; }
key_file=$(realpath "${1:?Owner public key required}")
controller=${2:?Trusted LAN controller address required}
diagnostic_user=${3:-argos-diagnostics}
[[ "$diagnostic_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 1
cd "$(dirname "$0")"
# Both endpoints must be on the same directly attached trusted private LAN.
lan=$(ip -4 -j address show scope global | python3 -c '
import ipaddress,json,sys
controller=ipaddress.IPv4Address(sys.argv[1])
trusted=any(controller in ipaddress.ip_network(n) for n in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"))
if trusted:
 for iface in json.load(sys.stdin):
  for address in iface.get("addr_info",[]):
   network=ipaddress.ip_interface(address["local"]+"/"+str(address["prefixlen"]))
   if controller in network.network:print(network.ip);sys.exit(0)
sys.exit(1)' "$controller")
[[ -n "$lan" ]] || { echo 'Controller must be on the directly attached trusted private LAN.'; exit 1; }
[[ -s "$key_file" && -f argos-collect-boot && -f argos-export-boot ]] || exit 1
ssh-keygen -l -f "$key_file"
# Refuse to promise durable setup when the encrypted persistence overlay is absent.
findmnt -rn | grep -qE '/(live/persistence|lib/live/mount/persistence)|persistence' || {
  echo 'Persistence mount not detected. Stop: boot with encrypted persistence unlocked first.'; exit 1;
}
# Prevent package installation from starting an unrestricted SSH listener.
systemctl mask --runtime --now ssh.service
systemctl mask --runtime --now ssh.socket 2>/dev/null || true
apt-get update
apt-get install -y openssh-server mokutil
id "$diagnostic_user" >/dev/null 2>&1 || useradd -m -s /bin/bash "$diagnostic_user"
home=$(getent passwd "$diagnostic_user" | cut -d: -f6)
install -d -m 700 -o "$diagnostic_user" -g "$(id -gn "$diagnostic_user")" "$home/.ssh"
key=$(awk 'NR==1 {print $1" "$2}' "$key_file")
touch "$home/.ssh/authorized_keys"
grep -Fq "$key" "$home/.ssh/authorized_keys" || printf 'from="%s",no-agent-forwarding,no-port-forwarding,no-X11-forwarding %s\n' "$controller" "$key" >>"$home/.ssh/authorized_keys"
chown "$diagnostic_user":"$(id -gn "$diagnostic_user")" "$home/.ssh/authorized_keys"
chmod 600 "$home/.ssh/authorized_keys"
install -d /etc/ssh/sshd_config.d /etc/systemd/journald.conf.d
# Preserve originals; an unexpected existing ListenAddress must be reviewed locally.
if grep -E '^[[:space:]]*ListenAddress' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | grep -v argos-lan; then
  echo 'Existing ListenAddress configuration found; review it before enabling SSH.'; exit 1
fi
cat >/etc/ssh/sshd_config.d/00-argos-lan.conf <<EOF
ListenAddress $lan
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers $diagnostic_user@$controller
DisableForwarding yes
EOF
ssh-keygen -A
/usr/sbin/sshd -t
# Confirm effective configuration, including distribution defaults.
/usr/sbin/sshd -T -C user=$diagnostic_user,addr=$controller,host=controller | grep -E '^(listenaddress|passwordauthentication|kbdinteractiveauthentication|permitrootlogin|allowusers|disableforwarding) '
cat >/etc/systemd/journald.conf.d/argos-persistent.conf <<EOF
[Journal]
Storage=persistent
SystemMaxUse=256M
SystemKeepFree=512M
RuntimeMaxUse=64M
SyncIntervalSec=30s
EOF
mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal
install -m 755 argos-collect-boot /usr/local/sbin/argos-collect-boot
cat >/etc/systemd/system/argos-boot-log.service <<EOF
[Unit]
Description=Argos boot evidence snapshot
After=local-fs.target systemd-journald.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/argos-collect-boot
EOF
cat >/etc/systemd/system/argos-boot-log.timer <<EOF
[Unit]
Description=Capture boot evidence before and after desktop startup
[Timer]
OnBootSec=20s
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
EOF
# Grant only the fixed collector/export command, not general passwordless sudo.
install -m 755 argos-export-boot /usr/local/sbin/argos-export-boot
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/argos-export-boot\n' "$diagnostic_user" >/etc/sudoers.d/argos-diagnostics
chmod 440 /etc/sudoers.d/argos-diagnostics
visudo -cf /etc/sudoers.d/argos-diagnostics
systemctl daemon-reload
systemctl restart systemd-journald
journalctl --flush
systemctl enable --now argos-boot-log.timer
systemctl unmask --runtime ssh.service ssh.socket
systemctl enable ssh
systemctl restart ssh
/usr/local/sbin/argos-collect-boot
printf '\nToronado SSH address: %s\nHost key fingerprint (verify on Yugo):\n' "$lan"
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
printf '\nVerify journal retention after reboot: sudo journalctl --list-boots\n'
