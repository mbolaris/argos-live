# Acceptance record

Milestone 1 is **in progress**, not accepted.

October 2 physical-boot follow-up: owner reports successful encrypted unlock, followed by a stalled display. A bounded offline UEFI boot-menu repair was applied and read-back verified. It supplies selectable diagnostic/desktop entries with visible screen prompts; partition tables and encryption-header checks passed unchanged, and no write entered persistence. Diagnostic physical boot and Yugo SSH/logging installation remain pending. See OFFLINE-BOOT-REPAIR.md.

Yugo's verified public-key access/logging bundle is now staged as an automatic next-boot hook through a second bounded, read-back-verified repair. It installs logging before attempting network package installation and restricts SSH to Yugo. The encrypted partition was not written. Actual installation, host-key verification, SSH access and persistence of logs still require the next physical boot. Ten source checks pass.

| Check | Evidence / state |
|---|---|
| Local hardware and disk inventory | Completed; INVENTORY.md |
| GitHub ownership / visibility | mbolaris confirmed, public selected; repository created |
| Build environment | WSL2 + dedicated Debian builder created |
| Software compatibility and pins | Primary runtime releases/checksums verified; SOFTWARE.md |
| Encrypted persistence choice | Confirmed; local unlock prompts designed |
| Build ISO + checksum | Corrected image: 4,232,200,192 bytes; SHA256 f9f22b17e993e489b70f3e4c99108d03e57e227abf138344c09193cc78fbea24 |
| Bundled tiny model | Qwen3 0.6B included, manifest and five blobs verified, Apache-2.0 license retained |
| USB target identified | Kingston 29.31 GiB; owner erasure approval received; physical image written and verified |
| Physical USB written / read-back | Passed on October 1, 2026: all 31,474,057,216 bytes written, flushed, then read back with matching SHA256; 25.37 GiB owner-passphrase encrypted persistence |
| Windows full-disk USB VM boot | Passed actual full-disk removable USB guest under Windows WSL2/KVM; XFCE desktop verified |
| Persistence reboot test | Passed encrypted unlock, configuration/model/sentinel retention and five artifact hashes after full guest restart |
| OpenClaw local model conversation | Passed offline live VM through both local CLI and argos start gateway: OpenClaw 2026.9.7 + Ollama 0.35.0 + Qwen3 0.6B |
| Physical Linux GPU use | Pending; Windows GPU inventory is not proof |
| Download interruption / artifact recovery | Passed actual Ollama Qwen3 8B daemon interruption/resume in dedicated WSL test storage; physical external volume pending |
| Missing external storage | Missing/wrong identity and insufficient space tests pass |
| Private restoration | Milestone 2, not implemented |
| Host installation | Milestone 3, not implemented |

No internal partitions, Windows boot configuration, or GPU power settings have been altered. The explicitly approved Kingston USB has been erased and written. Repository source is generic. Private state and model artifacts stay outside source control.

Validation: six Python tests pass (missing storage, wrong identity, space rejection, corrupted model artifact, invalid registry target, hybrid GPT boot-partition preservation and CRCs); Bash syntax checks and Windows writer PowerShell parsing pass. QEMU 10.2.1 booted the complete raw image as USB with networking disabled. Generic setup, encrypted unlock, actual model conversation, XFCE desktop, and restart persistence passed. The gateway launch path also passed. Physical boot remains distinct.

Runtime audit found three vulnerable dependency packages inside OpenClaw's bundled npm tree: brace-expansion (high), undici (high), ip-address (moderate). `npm audit fix --package-lock-only` did not clear them. Keep these recorded as release blockers until patched compatibility is evaluated; do not declare the image production-ready. See local audit report (excluded from public source); advisories include GHSA-qhr7-859c-m2p7, GHSA-rfgv-xxqx-mfg5, GHSA-rpw4-54j3-4h4q.

CPU runtime smoke passed after setting Ollama context length to 32768. The first attempt used Ollama's 4096-token default and rejected OpenClaw's 6685-token prompt; the explicit context setting fixes that mismatch. `openclaw config validate` passed. Local model response: "Hello! I'm your new assistant, and I'm here to help with anything you need." No provider account or GitHub login was used in that isolated test. OpenClaw emitted SQLite reclamation warnings at CLI teardown; review upstream behavior before release. Source checks and WSL smoke do not substitute for USB/live VM boot.

Build completed with Debian kernel 6.12.107+deb13-amd64 and NVIDIA 550.163.01-2. Verified initramfs contains cryptsetup; the built live root has no DKMS private signing key. Build recovery exposed two issues (concurrent cleanup and bootstrap-cache replacement); source now uses an outer lock and resumes only chroot/binary stages. The final artifact was exported separately after a running shell source edit disrupted the export tail. Clean rebuild verification remains required before release.

An encrypted 24 GiB disposable full-disk VM image was created with a 20.06 GiB persistence partition and a local temporary test key. Debian's hybrid ISO has intentional ISO/EFI partition overlap, so generic sgdisk conversion failed. The image-only append helper preserves existing partition entries and recalculates both GPT copies/CRCs; a dedicated test verifies this. This disposable test image was never written to hardware. The physical Kingston now contains a separate owner-passphrase image.

First actual virtual USB run reached encrypted unlock and live user login, then exposed root-only test metadata in the seed bundle during generic setup. Source now stages only model blobs, manifests, and the license, with readable permissions; runtime copy is also allowlisted. The final checksum in the table supersedes both earlier images. Reboot/conversation acceptance passed on a fresh encrypted test image. The gateway path also passed. Persistence discovery is restricted to removable USB devices to exclude internal disks; the final image passed a fresh generic setup, offline conversation, USB-only boot-policy check, full guest restart, and persisted artifact verification after that change.

Physical writer recovery: corrected unsigned Win32 access-mask conversion, replaced unsupported managed raw-device writes with synchronous native Windows I/O, and corrected the read-back size calculation to use 64-bit integers. The full write completed before the final verification-only retry; that retry read all bytes and matched the encrypted image checksum. No passphrase was recorded. Local ciphertext image/checksum and result are excluded from source control.
