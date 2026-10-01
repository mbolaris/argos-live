# Recovery and development limits

Always preserve the generic ISO checksum and a separate encrypted backup of personal state. A forgotten LUKS passphrase cannot be recovered by Argos.

If model storage is missing, mount the explicitly selected original volume at its original path and rerun `argos start`. Argos will not fall back to an internal disk or create a replacement directory. The `.argos-storage-id` marker is a volume-directory identity, not authentication or encryption. Cloning the selected directory intentionally preserves that identity. Avoid concurrent writable access from the Windows host and VM.

If a model download is interrupted, repeat `argos download`; existing Ollama partial artifacts are retained. The runtime inspects registry sizes and verifies model blobs. `argos verify` checks existing artifacts. Corrupted completed blobs are reported; inspect them before removal and redownload. No silent fallback to cloud inference occurs.

For a larger model, run `argos select-model --model qwen3:8b`, review the choice, then `argos download`. Registry metadata determines missing artifact size and a margin before the download confirmation. Stop the running assistant before changing its configuration.

If a build fails, inspect its log and wait for all build processes to exit. `scripts/resume-build.sh` resumes chroot and binary stages without restoring bootstrap over an installed root filesystem. Both build entry points acquire an outer lock. Never start a second live-build process on the same tree. `repair-resume-stages.sh` is a narrowly scoped repair for the documented bootstrap-stage recovery error; it is not a routine clean-build step.

A DKMS public certificate is retained in the image; its generated private signing key is removed. Secure Boot acceptance and enrollment need separate testing and owner action. Do not copy the test VM's encryption key to a physical USB. Disposable VM images are named `TEST-DO-NOT-WRITE.raw` and are private test artifacts.

`review-usb-write.ps1` is read-only. `write-usb.ps1` performs real destructive writes and has not yet been tested on the physical Kingston. Use it only after the owner confirms the exact reviewed device and erasure, with a newly verified image checksum and elevated Windows privileges. If that confirmation was already obtained in the chat, `-OwnerErasureConfirmed -Confirm:$false` avoids requesting it twice. It still checks identity, volume locks, image capacity, source location, and read-back. A lock failure aborts before writing; do not force access or select an internal disk instead.

Milestone 2 will add an explicit private configuration repository choice, limited authentication, import allowlists, disconnect, and backup/restore. Until then, no GitHub personalization import is offered. Never put provider keys, GitHub tokens, or unlock passwords into build configuration, this repository, or logs.

Milestone 3 will implement selected-destination installation and migration. No installer, internal disk formatting, repartitioning, or boot configuration changes are part of this prototype.
