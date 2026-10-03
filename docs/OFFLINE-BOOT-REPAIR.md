# Offline boot-menu repair

Toronado's physical USB unlocked encrypted persistence, but the desktop has not been reached. The original menu selected a serial console for prompts. Temporary manual edits also produced a root-filesystem panic in one attempt. A bounded offline repair eliminates manual command entry without rebuilding or erasing persistence.

`plan-boot-repair.py` reads the existing regular image, locates the ISO9660 GRUB menu and SHA256 manifest, preserves their exact allocated lengths, and creates two sector-aligned patches. Kernel/initrd paths and persistence settings remain intact. It offers a default text diagnostic entry with GPU drivers disabled, a normal desktop entry, and basic graphics. Prompts go to `console=tty0`.

`apply-boot-repair.ps1` needs local administrator access. It identifies the Kingston by USB bus, serial, capacity, and unique ID; locks target volumes; validates every original patch byte before writing; and restricts writes to the boot region. It saves a reversible patch backup and verifies both updated regions. Both GPT copies and the first 16 MiB of encrypted persistence must remain unchanged. It never decrypts or writes into persistence, and does not touch internal disks or firmware settings.

Local plan, backup, and result files are under `local/` and excluded from Git. The repaired media differs from the original whole-image checksum; the repair verifies the exact changed regions rather than claiming a new full-image read-back.

The binary build hook creates the same selectable menu in future images, before checksums are generated. Physical media use the screen console. `ARGOS_TEST_SERIAL_CONSOLE=1` is an explicit opt-in for headless serial test builds only; it selects the desktop entry and adds the VM serial console.

SSH/logging from Yugo's separate bundle is not installed by this boot-menu repair. The bundle or Yugo's public key must be obtained and its setup reviewed before configuring restricted LAN access. Firmware changes and BitLocker suspension have not been verified as performed.

On October 2, 2026 the physical Kingston GRUB repair passed: both patched boot-file regions read back exactly, the first and last MiB protecting GPT structures remained unchanged, and the first 16 MiB of encrypted persistence remained unchanged. No write entered persistence. This repair affects the UEFI GRUB menu; the legacy BIOS menu changes are in the future-build hook. Physical boot of the diagnostic entry is still pending.
