# Automatic SSH after owner pairing

Future images enable `ssh.service` at boot. It starts after networking when an
existing owner pairing and host identity are available in unlocked encrypted
live persistence. The owner no longer needs to run `systemctl start ssh` after
each boot. A fresh image still needs one owner pairing; no owner key or private
host key is distributed in the generic ISO.

The service waits for `network-online.target` and retries startup every five
seconds if its configured LAN address is not available yet. This covers systems
whose network manager reports readiness before DHCP assigns that address. Each
retry repeats the pairing gate; it never broadens the listener or authentication
policy. A skipped pairing gate does not trigger retries.

The unit's read-only startup gate requires the existing root-owned
`/etc/ssh/sshd_config.d/00-argos-lan.conf` (or the earlier
`00-argos-yugo-pairing.conf`), an existing private ED25519 host key,
and a valid local authorized_keys file for every allowlisted account. It checks
the effective sshd configuration, including each user's connection context:
public-key authentication only, non-root users explicitly restricted to owner
IPv4 addresses, private LAN listeners, and forwarding disabled. Missing keys,
unsafe policy or unknown/unencrypted storage skip startup. Guest sessions also
skip startup. The gate never generates or replaces keys or modifies pairing.

Use the existing owner-run `scripts/setup-local-ssh.sh` procedure to pair a fresh
USB. Preserve the encrypted persistence partition and its `/etc/ssh` identity
across image updates. Disabling `ssh.service` is the owner opt-out. Inspect startup
with `systemctl status ssh --no-pager` and `journalctl -u ssh -b`.

This boot default does not repair or accept an already changed host key. If the
controller reports a mismatch, retain the saved pin, verify the fingerprint
directly on the device, and obtain owner approval for any identity repair or
new pairing. Never release a workload quarantine to enable SSH.
