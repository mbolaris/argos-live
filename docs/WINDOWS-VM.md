# Windows VM workflow

Selected development route: QEMU under local WSL2 Ubuntu, with WSLg providing its desktop window and KVM providing nested acceleration. This is a Linux guest VM launched from Windows; it is separate from direct physical USB boot. `/dev/kvm` exists locally, but actual accelerated guest startup must still be verified.

Native Hyper-V management and VirtualBox/VMware were not found in the initial inventory. Physical USB/raw-disk passthrough would require elevated exclusive device attachment and host dismounting. The first workflow therefore uses a **full-disk image attached as virtual USB**, not an ISO in a virtual CD drive. It exercises the same hybrid boot media and an appended persistence partition. Hardware USB transport reliability and the RTX 3090 must be tested separately on the physical computer.

Install QEMU, qemu-utils, OVMF, cryptsetup, gdisk in the WSL build environment. Create a new 24 GiB raw image from the build ISO using `scripts/make-vm-image.sh`; this adds encrypted persistence and prompts locally for a passphrase. It refuses block-device destinations and existing files. The VM image contains personal state after setup: do not commit or publish it. The generic ISO is the public build artifact.

```powershell
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/make-vm-image.sh /mnt/c/Projects/Argos-Live/artifacts/argos-live-amd64.iso /var/lib/argos-live/test-usb.raw 24G
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/run-vm.sh /var/lib/argos-live/test-usb.raw
```

Do not mount the raw image while QEMU runs. QEMU and a launcher lock enforce guest ownership; filesystem mounts outside the launcher still require operator discipline. Shut down the guest and wait for QEMU to exit before copying or inspecting storage. Never attach the physical USB simultaneously to Windows and a writable guest.

The initial launcher tests legacy firmware boot. UEFI and Secure Boot need separate OVMF testing with per-VM writable NVRAM; do not imply legacy success verifies Toronado's enabled Secure Boot. KVM inference is CPU-only unless separately configured GPU passthrough is verified; no GPU assignment is implemented here.

Acceptance: boot the raw image as USB, unlock persistence, configure generic assistant, download model, converse, write a sentinel, fully shut down, relaunch the same raw image, verify state and sentinel. Remove the selected optional data volume and confirm Argos refuses startup. Record commands and results in STATUS. These checks remain pending until executed.
