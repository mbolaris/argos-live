# Argos Live verification and remaining updates

Updated October 3, 2026. Source integrates Toronado's reviewed UEFI repairs and Yugo's welcome, diagnostics, artwork and build changes. The candidate ISO is built from a fresh Debian root with the pinned snapshot and runtime lockfile, followed by runtime synchronization and repacking. This is not proof of byte-identical reproducibility. The updated image has now booted physically through UEFI with existing encrypted persistence preserved.

## Implemented in the image

- Desktop is the default boot entry. Keep `console=tty0` and blacklist nouveau for NVIDIA; a separate diagnostic entry disables graphics drivers. Generated UEFI and legacy menus are inspected.
- First boot opens the graphical welcome. Start Assistant uses the verified bundled model, shows setup progress and storage/network status, waits for actual gateway readiness, and opens the authenticated local conversation. No terminal launcher dependency remains. Network status means a route exists, not verified internet access.
- Encrypted persistence is reported only when the mounted writable persistence is backed by dm-crypt. Temporary setup requires explicit acceptance. The public image includes no personal conversations, configuration, tokens, SSH keys or model-storage identity.
- Coastline artwork is the desktop default. XFCE compositing and automatic screen locking are disabled for this live-image profile to avoid the observed black-screen and unexpected-password experience.
- Boot collection is independent of the desktop. Bounded persistent journals, snapshot boot IDs, command line, storage, display, NVIDIA signature/module information, and Secure Boot observations are included. Collection/export is serialized and incomplete files excluded; retention is bounded.
- SSH stays disabled in the clean image until an owner installs a public key and trusted LAN restrictions. Setup disables password/root login and forwarding; host keys are generated on the target. No router forwarding is required.
- Build runtime downloads are integrity pinned. HTTPS snapshot pipeline settings avoid the observed stalled downloads. Build-only npm cache and private generated build keys are removed before publication.
- Optional existing DATA-volume storage is documented. It is owner-selected, unencrypted storage; its UUID and personal state are not embedded in the image.

## Evidence already collected

- Physical Toronado boots reached XFCE with nouveau blacklisted. NVIDIA 550.163.01 loaded on kernel 6.12.107+deb13-amd64 and the RTX 3090 generated locally, offloading 29/29 Qwen3 layers.
- Physical encrypted persistence, restricted LAN SSH and retained boot exports passed. Secure Boot was observed disabled; this session did not change firmware, TPM or Windows security settings.
- Disposable physical OpenClaw tests passed setup, local conversation, recall across gateway process restart, token rejection and denied shell/file-tool invocation. The configuration audit reported zero critical findings; that is separate from dependency auditing.
- The graphical welcome was exercised in a disposable desktop profile. The existing owner gateway was reused and its browser connection observed. Complete owner acceptance and physical transcript recovery still require coordinated reboot testing.
- Toronado's existing DATA volume passed a safe NTFS write/read check. Model copies were hash verified before owner storage configuration changed. The original encrypted-USB model copy remains. The running old daemon continues to use its original model directory until restarted.
- The candidate ISO passed structural checks for generated boot entries, expected runtime/assets, verified seed hashes, logging timer enablement, SSH disabled by default, and absence of personalized state/private keys.
- A disposable KVM guest booted the candidate rootfs with the ISO attached as a read-only virtual USB, no networking and no physical disks. LightDM and the welcome opened; the logging timer was active. This kernel/initramfs smoke check does not exercise the firmware bootloader or real NVIDIA hardware.
- Python tests pass on Linux, including shell menu fixtures. Windows runs the same suite with the shell fixture skipped.

## Before calling this a release

- [x] Boot the updated image through real UEFI: desktop, welcome, artwork, encrypted persistence, logging and pinned-key LAN SSH passed without kernel edits.
- [ ] Test legacy firmware boot separately; generated-menu inspection is insufficient.
- [x] Verify updated-USB desktop startup, DATA automount by stable UUID despite device renumbering, owner DATA write/read, model identity/blob hashes, selected DATA model path, gateway readiness and GPU generation. Qwen3 offloaded 29/29 layers; two-turn gateway conversation recalled its benign test phrase.
- [ ] Verify that retained conversation through a further physical reboot. Settings and SQLite session stores survived; full transcript-recall acceptance remains pending.
- [ ] Before any physical USB write, reidentify the device and current layout, create a current backup, and review which ranges change. An ISO fitting before the persistence offset alone does not prove a safe write. Never overwrite a mounted live USB; obtain approval for any new erasure.
- [ ] Address the exact pinned OpenClaw dependency audit: 25 findings (24 high, one moderate, zero critical). Evaluate patched upstream versions with local-model, tool-policy and auth regression checks; do not silently change runtime pins.
- [ ] Improve Qwen3 0.6B answer quality. Tests observed occasional empty output and tool-like text. Evaluate prompt/thinking behavior and optional larger models with owner-reviewed size/free-space requirements; no unsolicited model download.
- [ ] Exercise stop, startup failure and process-tree cleanup on the new image. Welcome only stops a daemon it started; reusing an existing gateway must not terminate it.
- [ ] Test completely disconnected conversation, saved settings/transcripts across physical reboot, cancellation, repeat startup and low-storage diagnostics. A VM without networking only proves offline welcome/setup presentation, not full offline chat acceptance.
- [ ] Verify LAN access controls after DHCP changes and reconnect after physical reboot. Keep key-only access and forwarding restrictions.
- [ ] Define and test Secure Boot support separately. Never clear keys or change firmware/BitLocker settings as an implicit fix.
- [ ] Verify unattended clean build from current source and archive package/runtime/license inventories. The recovered and repacked candidate is not yet byte-reproducibility evidence.

## Storage and security limits

Toronado DATA files and models are unencrypted by the owner's choice. Conversations, assistant configuration and credentials remain on encrypted USB persistence. Locked BitLocker volumes, internal partition tables, Windows boot files, TPM keys and firmware keys were not modified. The rebuilt image was subsequently applied only to the reviewed USB boot range. Full read-back, encrypted-persistence and retained partition-metadata checksums passed. Physical UEFI boot passed. No passphrase or partition layout changed.
