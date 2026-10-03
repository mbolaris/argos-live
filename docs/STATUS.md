# Acceptance record

Updated October 3, 2026. This is a tested development candidate, not a completed production release.

## Generic live distribution

| Check | Current evidence |
|---|---|
| Updated image build | Fresh Debian root with pinned software, runtime sync/repack; 4,060,938,240 bytes; ISO SHA256 39c8c02f83b2b625ceedb3f33d243a3943a3a833bbd29c649ddf3f200a8e5a82 |
| Physical image update | Bounded USB boot-region write with current backup; full-device read-back, encrypted-persistence and retained partition-metadata hashes matched; no repartitioning |
| Physical UEFI boot | Passed October 3, desktop entry without kernel editing, console=tty0, nouveau blacklisted |
| Desktop and first run | XFCE/LightDM/window manager, coastline artwork and graphical welcome active; compositing disabled |
| Encrypted owner persistence | Mounted as live root backing; existing settings and trusted SSH identity retained |
| DATA storage | Stable UUID automounted despite device renumbering; owner write/read and model identity/blob SHA256 checks passed; running Ollama now uses DATA |
| SSH and diagnostics | Strict pinned-key LAN connection, restricted exporter, active logging timer, six retained physical boot IDs |
| GPU inference | RTX 3090, driver 550.163.01; CUDA offloaded 29/29 Qwen3 layers; approximately 4 GiB VRAM at 32768 context |
| Local OpenClaw conversation | Updated physical USB gateway passed two-turn reply and recall; ready endpoint true; loopback/token authentication and limited initial tools retained |
| Source verification | All 22 Linux Python tests pass, including shell menu fixtures; Windows passes 21 with the shell fixture skipped |
| Disposable candidate boot | KVM cold-root/ISO boot with no network or physical disks reached desktop/welcome/log timer and showed the artwork; firmware path tested separately by physical UEFI boot |

No internal partitions, Windows boot files, encryption passphrase, TPM keys or firmware security settings were changed. Secure Boot was observed disabled; compatibility with Secure Boot is not established. Generated BIOS menus are checked, but physical legacy boot remains unverified.

## Portable customization milestone

The project now explicitly separates the generic image, personal profile and model files. See PROJECT-GOALS.md.

The owner has narrowed the next milestone to personality and reviewed skill transfer, with independent Live model downloads. Both private reference archives were received and checked on Yugo; no model weights transferred and nothing activated. Source configuration cloning and copying Windows model weights are superseded by this direction. MODEL-ONBOARDING.md records the progress/benchmark design and implementation checklist; those features remain pending.

- Toronado is currently in Windows. Its local agent reports a verified redacted Argos/Nyx/Proteus configuration ZIP, excluding credentials/executable helpers. The full native recovery backup was stopped incomplete. The configuration-only ZIP was received over pinned-key, source-restricted SFTP and independently checked on Yugo: transfer digest, all 25 files and internal manifest passed. Nothing was activated. Private model/backend/helper inventory and Linux migration remain the next steps.
- Native Windows/WSL export and Linux verified-staging helpers are prepared. A disposable three-agent fixture passed installed OpenClaw schema validation, native backup creation/verification and staged restoration of all three personas. Incorrect transfer checksums and existing target directories were rejected.
- Windows helper argument forwarding and restrictive output ACLs were checked using a fixture CLI. The real Windows source/version, WSL placement, model tags, skills/plugins, credentials and permissions still require inspection.
- Configuration-only ZIP inspection and a private Windows read-only SFTP candidate preparer are now available; five ZIP validation tests pass, and the Windows preparer parses but is not yet endpoint-tested. Native helpers capture and stage private backups; they do not yet activate or continuously sync a personal roster. Windows-to-Linux path mapping, source/target policy review, model availability, explicit history selection, profile activation and rollback are the next implementation work after source inspection.
- Existing live configuration and conversations were not modified by the fixture tests. Personal exports do not belong in the public repository or unencrypted model/data folders.

## Stable update maintenance

Daily read-only GitHub Actions discovery is configured for OpenClaw, Ollama and Node. The October 3 upstream check found OpenClaw 2026.9.8 and Ollama 0.35.1; the current ISO/USB still runs 2026.9.7 and 0.35.0. Candidate pins and metadata were generated, not promoted. Four discovery tests and Linux shell syntax checks pass. Debian security/stable-update repositories are now enabled in the build source with a separately pinned security snapshot, but this requires a clean candidate build and package audit. See RELEASE-PROCESS.md.

## Release follow-ups

The exact pinned runtime npm audit has 25 findings: 24 high, one moderate, zero critical. Dependency remediation remains open; successful inference/configuration audits do not resolve it. Evaluate supported stable upstream releases with regression tests rather than applying blind runtime updates.

Further work: legacy firmware boot, Secure Boot policy/testing, repeated answer-quality tests, completely disconnected conversation, process cleanup/error acceptance, saved conversation recall through a further physical reboot, profile import/rollback and unattended rebuild/reproducibility checks.

Host installation remains outside this milestone. See PHYSICAL-BOOT-TODO.md for the detailed remaining checklist.

The generic inert migration planner now preserves roster IDs/models, proposes independent Linux paths and rejects overwriting existing stages. Three fixture tests and planning against the received private ZIP pass. It does not activate anything or create target OpenClaw config; backend/model/helper inventory and target validation remain pending.
