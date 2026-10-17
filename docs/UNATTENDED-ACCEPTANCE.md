# Unattended image acceptance ledger

The goal is a fresh-card unattended campaign, an honest machine-audited record,
independent signed baseline/final replication, enforced safety, and reproducible
image/storage acceptance. Passing a subset does not complete the goal.

## Current evidence and gaps (2026-10-17)

- Option A: owner reconfirmed and applied on the existing Toronado card. Protected
  snapshots and session evidence are in work/TORONADO-COORDINATION.md in the owner
  checkout. This was operator intervention: that campaign is diagnostic only.
- Repository prerequisites: this branch combines origin/main (including merged
  proctor core #114) and the existing containment branch used for ISO38991911464.
  The prerequisite containment PR #113 is still open; no new merged-image claim.
- New admission: cooperative assistant benchmark CLI/API calls and the append
  log tool share one OS lock plus durable reservation. Busy requests do not
  replace live progress or start inference. Failed/abandoned evaluations remain
  quarantined instead of being silently recycled on a timeout. There is no
  automatic recovery claim. This is not a complete workload broker: dashboard
  trials, direct Ollama calls, controller/heartbeat inference, model operations
  and arbitrary filesystem edits are not yet all mediated.
- New argos_log: one text argument, append-only interface, host timestamp,
  pre-append snapshot, checked saved-run receipts, and no write while a cooperating
  evaluation holds admission. Natural-language change claims remain unverified.
  An automated complete campaign-log verifier and protected experiment journal
  are still required. Same-UID shell access can bypass these interfaces.
- Heartbeat: stricter prompt and status facts prevent common accidental actions
  by instruction. Owner authorization and dispatch exclusion must additionally
  be enforced by the host; a prompt is not that enforcement.
- Independent verification: proctor core/signing smoke exists. The interactive
  adapter, protected service identity, shared admission on every execution path,
  repeated baseline/final runs and Yugo-verified transcripts are still required.
  See PROCTOR-INTEGRATION-DESIGN.md. Do not run a proctor during the campaign.
- Storage: the previous card was damaged after poweroff. Root cause and a verified
  clean-unmount path remain unresolved. No poweroff on Toronado in this work.
- Build acceptance: no ISO has been built for these new changes, no stricter
  exact-image VM acceptance, fresh physical card write or full readback yet.
- Unattended plateau: NOT ACHIEVED. Require one fresh verified card and one owner
  message, baseline/model decision, two more one-change experiments with evidence,
  and ## Done without any operator rescue. Preserve failed attempts as failures.

## Configuration evidence follow-up

The existing-card evaluator omitted per-model generation params, so its claimed
thinking experiments are not proof that those settings were exercised. The v2
evaluation path copies allowlisted generation scopes, records a private-safe
configuration digest and requested-settings receipt, and invalidates a suite if
the copied configuration changes. Comparisons require one changed dimension and
explicitly label configuration evidence separately from effective requests.
Old v1 results require a fresh v2 baseline. The hosted pinned-SDK protocol fixture
checks actual outgoing options against a synthetic local Ollama endpoint without
model inference; this is transport evidence, never a quality result. That fixture
must pass before claiming the transport fix works. Nothing is hot-deployed.

## Shutdown evidence gate

Do not treat a successful poweroff command, VM exit, sync, or later journal
replay as clean-unmount proof. The root overlay uses the encrypted persistence
filesystem; attempting to unmount its backing store while that overlay is still
live is not a shutdown design. Systemd describes a supported return to an initrd
through /run/initramfs/shutdown, where complex root storage can be detached:
https://github.com/systemd/systemd/blob/main/docs/INITRD_INTERFACE.md

Read-only Toronado inspection found live-boot 1:20250815~deb13u1, live-tools
1:20240525 and systemd 257.13-1~deb13u1. The live-tools shutdown hook calls only
live-medium-eject. Initial unprivileged access to /run/initramfs was denied;
the owner then explicitly approved a narrowly scoped root read. That inspection
found the directory empty: no shutdown executable. No files were changed and
no poweroff occurred. These facts do not prove
which final unmount path ran or caused the earlier corruption.

The image-source candidate now stages the pinned systemd-shutdown binary and
its dependency closure in a dedicated executable tmpfs under /run/initramfs.
The binary stays at its original path so its relative library lookup is retained;
an initrd marker and small /shutdown entry point allow the documented second
shutdown phase after leaving the old overlay root. Staging checks all template
hashes before enabling the entry point. LightDM requires successful preparation.
This code has not been executed as root or installed on Toronado. It remains an
unverified candidate until the exact-image encrypted VM/offline checks below
pass. The normal systemd finalizer may still report teardown failures; neither
the readiness marker nor shutdown-helper exit is proof of a clean filesystem.

Before approving the next image for physical use:

1. Identify the exact pinned shutdown/initrd implementation and ordering. Add
   any required fix in image source, with failure behavior and no forced detach
   of active persistence. No manual root mutation on Toronado without approval.
2. On a disposable encrypted VM disk made from the exact ISO, write and fsync
   record/snapshot sentinels; preserve their hashes outside the guest. Back up
   those records before each poweroff, just as on the physical machine.
3. Capture serial shutdown output through QEMU exit; a timeout or forced QEMU
   termination fails acceptance. Preserve kernel/unmount errors verbatim in
   private evidence. Inspect the stopped filesystem read-only before another
   boot can replay its journal: require a clean superblock, no recovery needed
   and a read-only full filesystem check with no errors. Never repair to pass.
4. Repeat at least three cold boot/write/poweroff/offline-check cycles; verify
   every sentinel and campaign record survives. Report only the tested scope.
5. Document the exact owner shutdown procedure. After a backed-up physical
   acceptance run, check the card offline before reusing it. Filesystem errors
   require stopping and asking the owner; preserve the damaged evidence.

## Executable storage test

The `shutdown_only` mode of `iso-boot.yml` runs `scripts/smoke-encrypted-shutdown.py` only on an
explicitly approved disposable GitHub-hosted root runner. It requires the ISO
checksum and build commit to match the exact test checkout. It creates only a
new regular virtual USB file, keeps its generated test key outside artifacts,
and performs three cold boots/poweroffs. Every poweroff is preceded by an
fsynced host backup of synthetic record/snapshot sentinels. Every stopped disk
is opened read-only, its clean bit and absence of journal-recovery are required,
and `e2fsck -f -n` must exit 0 before a `ro,noload` mount verifies every backup
byte. Earlier sentinels must also match across subsequent boots. A forced VM
termination, missing RAM handoff, incomplete detachment, dirty filesystem or
changed sentinel fails the test. It performs no repair. This does not substitute
for firmware boot, stricter evaluator containment or physical-card acceptance.

The owner approved privileged writes solely in disposable GitHub build/VM
runners for this candidate. That approval does not authorize Toronado root
writes or poweroff.
