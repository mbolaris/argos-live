# Argos Live

A generic Debian live distribution with a complete OpenClaw environment, local inference through Ollama, and optional portable personal profiles. See the [project goals and next profile-sync milestone](docs/PROJECT-GOALS.md).

**Development status:** Development candidate physically verified on Toronado on October 3, 2026: desktop, encrypted persistence, DATA automount, SSH/logging and GPU-backed OpenClaw conversation pass. Dependency remediation and broader release acceptance remain open. Personal three-agent migration is the next milestone; no host installation is included.

## Build on Toronado

Use the local Ubuntu-26.04 WSL2 environment. Build filesystems stay on WSL ext4, while source and final artifacts live in this checkout. No internal disk partition or Windows boot files are modified.

```powershell
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/bootstrap-builder.sh
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/lock-runtime.sh
wsl -d Ubuntu-26.04 -u root -- python3 /mnt/c/Projects/Argos-Live/scripts/fetch-seed-model.py /var/lib/argos-live/seed-model
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/build.sh
```

The builder needs debootstrap, Debian archive keys, and Linux mount access. The live root includes XFCE, networking, diagnostics, cryptsetup, OpenClaw, Node, Ollama, and NVIDIA DKMS. Output: `artifacts/argos-live-amd64.iso`, `SHA256SUMS`, package manifest. Preserve build logs locally; never log credentials.

## First run

The **Argos Welcome and Assistant** window opens when XFCE starts and is also available in the applications menu. It reports local model availability, mounted encrypted persistence, and network connectivity (a network connection does not imply internet access). Choose a writable model directory, accept the conversation-only permissions, and click **Start Assistant**. Setup uses the bundled model without downloading weights; progress appears in the welcome window. A session without persistence requires explicit temporary-session confirmation. Storage is remembered by an explicit directory and identity marker; if missing, startup stops without creating fallback directories. External model volumes are not automatically mounted or encrypted.

The build includes a SHA256-pinned Qwen3 0.6B model (522,653,767 bytes including metadata), with its Apache-2.0 license. Setup copies it into selected writable storage and verifies it. For larger models, inspect their advertised download size first and supply an adequate `argos download --required-gib` budget. Downloads require internet, can resume via repeated Ollama pulls, and all referenced blobs are SHA256-verified. `argos verify` repeats the integrity check. The tiny model is intended for basic conversation; its quality is limited.

The welcome window waits for gateway readiness before opening the authenticated local conversation in Firefox. Startup logs stay in a private file and can be inspected with **View diagnostics**; the known gateway token is redacted in that view. Closing the welcome window keeps a running assistant available. **Stop Assistant** is available for a process started by that window; reopening the window can reuse an already-ready assistant without starting another daemon. `argos start` remains available for command-line diagnostics. Neither service is exposed to the LAN by default. GitHub is unnecessary for generic local use. Optional provider setup uses OpenClaw's local onboarding prompt; keys must never enter the repository.

## Persistence and USB safety

Large models and other files can use an existing internal data volume; see [optional data storage](docs/DATA-STORAGE.md). Disk identity and mount configuration stay local to each computer. Conversations and authentication settings remain on encrypted persistence by default.

The physical boot menu defaults to the NVIDIA desktop with nouveau blocked, keeps `console=tty0`, and offers text diagnostics with GPU drivers disabled. Automatic screen locking and compositing are disabled for this live desktop; this does not remove the account password or the disk-unlock passphrase. Boot snapshots run independently of the desktop, with bounded persistent journaling and serialized export through `argos-export-boot`. Persistence must be unlocked for logs to survive a reboot.

SSH remains disabled until explicitly configured with an owner public key and trusted directly attached LAN controller. An administrator can use `scripts/setup-local-ssh.sh PUBLIC_KEY CONTROLLER_IP [USER]` from the source bundle. It enables key-only restricted access, disables forwarding, and grants only the fixed boot-evidence export command. Verify the printed host-key fingerprint on the controller. Never forward SSH through the router or distribute private keys.

Owner selected encrypted persistence with a passphrase at boot. Final media preparation must add a LUKS partition and ext4 filesystem labeled `persistence`, containing `/persistence.conf` with `/ union`. Boot parameters include `persistence persistence-encryption=luks`. Enter passphrases in a local secure prompt only. Keep a separate encrypted backup; the live image has no recovery key.

The current USB candidate and internal disks are recorded in [docs/INVENTORY.md](docs/INVENTORY.md). Disk numbers and letters are transient. Never use them alone for selection. No destructive operations until the exact device, final image checksum, and erasure are confirmed.

## Acceptance and future milestones

See [docs/STATUS.md](docs/STATUS.md), [docs/SOFTWARE.md](docs/SOFTWARE.md), and [docs/WINDOWS-VM.md](docs/WINDOWS-VM.md). Private GitHub customization and host installation are later milestones. Import configuration only after explicit repo selection; never execute imported setup scripts by default. No personalization credentials or previous private workspace files are copied into this image.
