# Argos Live

Debian live USB providing a generic personal OpenClaw assistant with local inference through Ollama. User control and privacy are product goals; no guarantee of model loyalty or resistance to manipulation is made.

**Development status:** Milestone 1 in progress. Physical USB writing and boot are not yet authorized or tested. No host installation is included.

## Build on Toronado

Use the local Ubuntu-26.04 WSL2 environment. Build filesystems stay on WSL ext4, while source and final artifacts live in this checkout. No internal disk partition or Windows boot files are modified.

```powershell
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/bootstrap-builder.sh
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/lock-runtime.sh
wsl -d Ubuntu-26.04 -u root -- bash /mnt/c/Projects/Argos-Live/scripts/build.sh
```

The builder needs debootstrap, Debian archive keys, and Linux mount access. The live root includes XFCE, networking, diagnostics, cryptsetup, OpenClaw, Node, Ollama, and NVIDIA DKMS. Output: `artifacts/argos-live-amd64.iso`, `SHA256SUMS`, package manifest. Preserve build logs locally; never log credentials.

## First run

Open **Argos Setup and Assistant** in the applications menu. Choose a writable model directory and accept the displayed conversation-only permissions. Storage is remembered by an explicit directory and identity marker; if missing, startup stops without creating fallback directories. External model volumes are not automatically mounted or encrypted.

Run `argos download --required-gib 4` for the configured tiny-model candidate. For larger models, inspect their advertised download size first and provide a larger space budget. Downloads require internet, can resume via repeated Ollama pulls, and all referenced blobs are SHA256-verified. `argos verify` repeats the integrity check. No weights are bundled in the initial development image; offline inference requires a completed model download.

`argos start` starts both the local Ollama daemon and OpenClaw gateway. Open the OpenClaw local dashboard using its CLI from another terminal. Neither service is exposed to the LAN by default. GitHub is unnecessary for generic local use. Optional provider setup uses OpenClaw's local onboarding prompt; keys must never enter the repository.

## Persistence and USB safety

Owner selected encrypted persistence with a passphrase at boot. Final media preparation must add a LUKS partition and ext4 filesystem labeled `persistence`, containing `/persistence.conf` with `/ union`. Boot parameters include `persistence persistence-encryption=luks`. Enter passphrases in a local secure prompt only. Keep a separate encrypted backup; the live image has no recovery key.

The current USB candidate and internal disks are recorded in [docs/INVENTORY.md](docs/INVENTORY.md). Disk numbers and letters are transient. Never use them alone for selection. No destructive operations until the exact device, final image checksum, and erasure are confirmed.

## Acceptance and future milestones

See [docs/STATUS.md](docs/STATUS.md), [docs/SOFTWARE.md](docs/SOFTWARE.md), and [docs/WINDOWS-VM.md](docs/WINDOWS-VM.md). Private GitHub customization and host installation are later milestones. Import configuration only after explicit repo selection; never execute imported setup scripts by default. No personalization credentials or previous private workspace files are copied into this image.
