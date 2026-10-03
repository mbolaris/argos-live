# Offline boot-menu repair

Toronado's physical USB unlocked encrypted persistence, but the desktop has not been reached. The original menu selected a serial console for prompts. Temporary manual edits also produced a root-filesystem panic in one attempt. A bounded offline repair eliminates manual command entry without rebuilding or erasing persistence.

`plan-boot-repair.py` reads the existing regular image, locates the ISO9660 GRUB menu and SHA256 manifest, preserves their exact allocated lengths, and creates two sector-aligned patches. Kernel/initrd paths and persistence settings remain intact. It offers a default text diagnostic entry with GPU drivers disabled, a normal desktop entry, and basic graphics. Prompts go to `console=tty0`.

`apply-boot-repair.ps1` needs local administrator access. It identifies the Kingston by USB bus, serial, capacity, and unique ID; locks target volumes; validates every original patch byte before writing; and restricts writes to the boot region. It saves a reversible patch backup and verifies both updated regions. Both GPT copies and the first 16 MiB of encrypted persistence must remain unchanged. It never decrypts or writes into persistence, and does not touch internal disks or firmware settings.

Local plan, backup, and result files are under `local/` and excluded from Git. The repaired media differs from the original whole-image checksum; the repair verifies the exact changed regions rather than claiming a new full-image read-back.

The binary build hook creates the same selectable menu in future images, before checksums are generated. Physical media use the screen console. `ARGOS_TEST_SERIAL_CONSOLE=1` is an explicit opt-in for headless serial test builds only; it selects the desktop entry and adds the VM serial console.

SSH/logging is separate from the initial menu-only repair. Firmware changes and BitLocker suspension have not been verified as performed.

On October 2, 2026 the physical Kingston GRUB repair passed: both patched boot-file regions read back exactly, the first and last MiB protecting GPT structures remained unchanged, and the first 16 MiB of encrypted persistence remained unchanged. No write entered persistence. This repair affects the UEFI GRUB menu; the legacy BIOS menu changes are in the future-build hook. Physical boot of the diagnostic entry is still pending.

## Yugo access bootstrap

Yugo's owner-supplied ZIP was downloaded over the trusted LAN and verified against SHA256 `1cdd537cab237e310e46ab75d0cc359f26007179e7b93ffec098a0acea21e8ed`. Its scripts were reviewed before staging. Only the public key is included. The ZIP remains local rather than published with the generic image.

`make-access-carrier.py` creates a verified boot-time setup hook. A second bounded physical patch places it in the existing, non-boot-critical `/live/filesystem.packages` allocation, updates its SHA256 manifest entry, and adds a local live-config hook URL to all three UEFI entries. The original package manifest is retained in the local patch backup and generic artifacts. No compressed root filesystem, kernel, initrd, GPT, or encrypted data is overwritten. All three patched regions read back correctly and protection checks passed.

On the next unlocked Argos boot, the hook installs persistent journal configuration and the boot-evidence timer first. A background service waits for a 192.168.1.x address and runs the inspected installer. Internet is required for official Debian SSH/mokutil packages if absent. SSH permits the supplied key only for `mbolaris` from Yugo at 192.168.1.31; passwords, root login and forwarding are disabled. Only the fixed root boot-log export command is granted without a password. A per-start helper binds SSH to the current trusted-LAN address; it fails closed when that LAN is absent.

Boot evidence: `/var/log/journal`, `/var/log/argos-boot/<boot-id>`. Installation evidence: `/var/log/argos-access-setup.log`. A completion marker prevents repeated package installation on later boots. This setup can run only after the live root and persistence are mounted; it cannot capture an earlier kernel panic. Successful physical bootstrap, SSH host-key verification, connection from Yugo, and log retention across another reboot remain unverified. Do not claim SSH is installed merely because its hook is staged.
