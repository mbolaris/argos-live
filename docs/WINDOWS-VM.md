# Windows VM workflow

Selected development route: QEMU 10.2.1 under local WSL2 Ubuntu, with WSLg providing its desktop window and KVM providing nested acceleration. This is a Linux guest VM launched from Windows; it is separate from direct physical USB boot. Actual accelerated virtual USB boot, XFCE desktop, offline OpenClaw conversation, and encrypted persistence across a full guest restart have passed locally.

Native Hyper-V management and VirtualBox/VMware were not found in the initial inventory. Physical USB/raw-disk passthrough would require elevated exclusive device attachment and host dismounting. The first workflow therefore uses a **full-disk image attached as virtual USB**, not an ISO in a virtual CD drive. It exercises the same hybrid boot media and an appended persistence partition. Hardware USB transport reliability and the RTX 3090 must be tested separately on the physical computer.

Install QEMU, qemu-utils, OVMF, cryptsetup, gdisk in the WSL build environment. Create a new 24 GiB raw image from the build ISO using `scripts/make-vm-image.sh`; this adds encrypted persistence and prompts locally for a passphrase. It refuses block-device destinations and existing files. The VM image contains personal state after setup: do not commit or publish it. The generic ISO is the public build artifact.

```powershell
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/make-vm-image.sh /mnt/c/Projects/Argos-Live/artifacts/argos-live-amd64.iso /var/lib/argos-live/test-usb.raw 24G
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/run-vm.sh /var/lib/argos-live/test-usb.raw
```

Do not mount the raw image while QEMU runs. QEMU and a launcher lock enforce guest ownership; filesystem mounts outside the launcher still require operator discipline. Shut down the guest and wait for QEMU to exit before copying or inspecting storage. Never attach the physical USB simultaneously to Windows and a writable guest.

The initial launcher tests legacy firmware boot. UEFI and Secure Boot need separate OVMF testing with per-VM writable NVRAM; do not imply legacy success verifies Toronado's enabled Secure Boot. KVM inference is CPU-only unless separately configured GPU passthrough is verified; no GPU assignment is implemented here.

The automated `scripts/test-usb-vm.py` test attaches the full encrypted raw disk as removable USB, disables networking, unlocks the test-only persistence, completes generic setup, converses with the bundled model, writes a sentinel, fully shuts down, and checks configuration, sentinel, and all five model artifacts after another boot. `--gateway-only` also verifies the `argos start` gateway path. No GitHub or provider account is used. Test keys and personal disk images remain local and must never be written to the physical USB.

Persistence discovery is restricted to removable USB media using Debian live-boot's `persistence-media=removable-usb`; the launcher explicitly marks the virtual USB removable. Internal host volumes are not persistence candidates. Missing optional model storage is covered by runtime tests; actual host external-volume selection and download still need an owner-selected directory and a physical test.
