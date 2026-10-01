# Acceptance record

Milestone 1 is **in progress**, not accepted.

| Check | Evidence / state |
|---|---|
| Local hardware and disk inventory | Completed; INVENTORY.md |
| GitHub ownership / visibility | mbolaris confirmed, public selected; repository created |
| Build environment | WSL2 + dedicated Debian builder created |
| Software compatibility and pins | Primary runtime releases/checksums verified; SOFTWARE.md |
| Encrypted persistence choice | Confirmed; local unlock prompts designed |
| Build ISO + checksum | Completed: 4,227,858,432 bytes; SHA256 355fe67e7da74796672f2581f2b7f9e94c982fd492b026c58cbc8b405b7a79e2 |
| Bundled tiny model | Qwen3 0.6B included, manifest and five blobs verified, Apache-2.0 license retained |
| USB target identified | Kingston 29.31 GiB; erasure confirmation pending |
| Physical USB written / read-back | Not performed |
| Windows full-disk USB VM boot | KVM machine creation verified; launcher implemented, guest boot pending |
| Persistence reboot test | Pending |
| OpenClaw local model conversation | Passed in isolated WSL CPU runtime, OpenClaw 2026.9.7 + Ollama 0.35.0 + Qwen3 0.6B; live guest pending |
| Physical Linux GPU use | Pending; Windows GPU inventory is not proof |
| Download interruption / artifact recovery | Passed actual Ollama Qwen3 8B daemon interruption/resume in dedicated WSL test storage; physical external volume pending |
| Missing external storage | Missing/wrong identity and insufficient space tests pass |
| Private restoration | Milestone 2, not implemented |
| Host installation | Milestone 3, not implemented |

No internal partitions, Windows boot configuration, GPU power settings, or USB contents have been altered. Repository source is generic. Private state and model artifacts stay outside source control.

Validation: six Python tests pass (missing storage, wrong identity, space rejection, corrupted model artifact, invalid registry target, hybrid GPT boot-partition preservation and CRCs); Bash syntax checks and Windows writer PowerShell parsing pass. QEMU 10.2.1 successfully created a paused KVM guest under local WSL2 and exited via its monitor. This verifies acceleration availability, not guest boot.

Runtime audit found three vulnerable dependency packages inside OpenClaw's bundled npm tree: brace-expansion (high), undici (high), ip-address (moderate). `npm audit fix --package-lock-only` did not clear them. Keep these recorded as release blockers until patched compatibility is evaluated; do not declare the image production-ready. See local audit report (excluded from public source); advisories include GHSA-qhr7-859c-m2p7, GHSA-rfgv-xxqx-mfg5, GHSA-rpw4-54j3-4h4q.

CPU runtime smoke passed after setting Ollama context length to 32768. The first attempt used Ollama's 4096-token default and rejected OpenClaw's 6685-token prompt; the explicit context setting fixes that mismatch. `openclaw config validate` passed. Local model response: "Hello! I'm your new assistant, and I'm here to help with anything you need." No provider account or GitHub login was used in that isolated test. OpenClaw emitted SQLite reclamation warnings at CLI teardown; review upstream behavior before release. Source checks and WSL smoke do not substitute for USB/live VM boot.

Build completed with Debian kernel 6.12.107+deb13-amd64 and NVIDIA 550.163.01-2. Verified initramfs contains cryptsetup; the built live root has no DKMS private signing key. Build recovery exposed two issues (concurrent cleanup and bootstrap-cache replacement); source now uses an outer lock and resumes only chroot/binary stages. The final artifact was exported separately after a running shell source edit disrupted the export tail. Clean rebuild verification remains required before release.

An encrypted 24 GiB disposable full-disk VM image was created with a 20.06 GiB persistence partition and a local temporary test key. Debian's hybrid ISO has intentional ISO/EFI partition overlap, so generic sgdisk conversion failed. The image-only append helper preserves existing partition entries and recalculates both GPT copies/CRCs; a dedicated test verifies this. The physical USB remains unmodified.
