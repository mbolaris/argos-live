# Unattended image acceptance ledger

The goal is a fresh-card unattended campaign, an honest machine-audited record,
independent signed baseline/final replication, enforced safety, and reproducible
image/storage acceptance. Passing a subset does not complete the goal.

## Release checkpoint (2026-10-20)

PRs [117](https://github.com/mbolaris/argos-live/pull/117) and
[118](https://github.com/mbolaris/argos-live/pull/118) are merged. The older
containment/Auto Climb PRs 112, 113, 106 and harness draft 104 are closed as
superseded. Pinned build
[39445005714](https://github.com/mbolaris/argos-live/actions/runs/39445005714)
passed from main `d016e45febbd83eb7cdd601a7517c4e0af5d903b`; its ISO SHA-256 is
`4ace331123dc658cf8b92df412a4dce7d4db9918355e3d06fdc334d1062a673e`.

- Final-image guest acceptance 39447673254 passed with saved speed/ability IDs
  `f5c0851bb50df17fecd69c02402d32f7` and `34f3f933ac2ce046444565da95de8009`.
  Final-image encrypted shutdown 39447678206 passed all three clean-filesystem
  and read-only fsck cycles, preserving 2/4/6 cumulative synthetic backup files.
- Initial managed run 39447668689 failed a startup assertion after gateway
  readiness. Preserve that failure. The stricter diagnostic harness passed
  39448644453 on the same ISO with saved IDs `044624f9b9fa9195e452714dc47ceb76`
  and `c298b3184007b04d6f22246c125d7876`. The initial failure's cause is
  unconfirmed; one additional cold managed run 39450021324 is pending.
- The native Firefox Lab click uses an isolated test profile of the shipped
  binary. It does not establish interaction with the launcher's original tab
  or a browser chat reply. Reviewed progress frames show an active ability
  phase; completion claims derive from the saved result IDs.
- The separate `guest_reset_only` gate passed 39447721277 on this exact ISO.
  Five synthetic user-state markers disappear after a requested normal reboot
  under a different kernel boot ID. Receipts and scope are in
  [the guest-reset evidence](evidence/guest-reset-39447721277/README.md).
- Runtime progress now reaches the pinned OpenClaw semantic activity tracker;
  actual SDK cancellation evidence preserves a saved host evaluation while the
  Python host remains alive. The asynchronous job primitive is still unexposed;
  hard host-death survival is not established. Recovery never releases by age:
  it requires a valid persisted boot ID and a different current kernel boot ID.
- The separate 40-task challenge suite, matched-run instruction guidance and
  bounded Auto Climb restoration/validation fixes are implemented. These are
  software changes, not evidence of a further model ability gain.

The broader unattended plateau below remains unachieved: protected service
identity, backend-wide admission/drainage, a complete claim auditor, independent
signed baseline/final replication and a fresh-card campaign without operator
rescue still need acceptance. No physical USB was written and Toronado was not
changed for this release. The generic ISO bundles `qwen3:0.6b`; migrating an
existing 27B deployment requires preserving its model files and private config.

## Historical evidence and gaps (2026-10-18)

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
- Storage: candidate 98307ce passed three encrypted virtual-USB shutdown cycles
  and read-only offline checks in run39074075124. Physical-card acceptance and
  the previous damage's root cause remain unproven. No Toronado poweroff here.
- Build acceptance: ISO build39072374940 succeeded for the storage checkpoint;
  later source changes are excluded. The stricter containment test, a merged
  final-source ISO, fresh physical card write and full readback remain required.
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
model inference; this is transport evidence, never a quality result. Hosted run
39074201752 passed for source 653379a using the exact checked runtime lock.
It observed temperature 0.44, top_p 0.8, num_predict 73, provider-model num_ctx
24576 overriding the agent's 16384, and no tool schemas. Requested thinking low
became top-level think low with reasoning=true and false with reasoning=false.
The saved public receipt is evidence/evaluation-protocol-653379a.json. Linux CI
passed 743 Python tests (4 skips) and 28 Node tests. Nothing is hot-deployed.

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
This code was executed only in approved disposable build/VM runners and has not
been installed on Toronado. The exact-image encrypted VM/offline checks below
passed for candidate 98307ce. Initial busy unmount attempts are preserved in
the consoles; the RAM phase ultimately unmounted persistence and detached DM
in all three cycles. Neither a readiness marker nor helper exit alone is proof
of a clean filesystem; the offline checks supply the filesystem evidence.

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

## Saved storage evidence

Build39072374940, source98307ce342566f2db7bd6fb6e4798ad65cc29f03, ISO SHA256
23321073f93f30b5973a78315732ff1fd00eaac6487f321c066a1752d217f162.
Hosted VM run39074075124 used that exact checkout and ISO. The public saved
result and artifact hash manifest are in evidence/shutdown-39074075124/.
All three cycles reached natural QEMU exit after complete storage detachment;
before each subsequent boot, the stopped persistence filesystem was clean,
had no needs_recovery feature, and passed read-only e2fsck -f -n with exit0.
External pre-poweroff backups verified2,4,6 cumulative synthetic files unchanged.
No repair or journal replay was used to pass. Firmware, physical media and GPU
are outside this evidence's scope. The final merged image must repeat this gate.

## Termination evidence follow-up

The CLI now requests cancellation on SIGINT/SIGTERM/SIGHUP, drains the embedded
CLI group, saves a cancelled outcome and updates the liveboard. Failed/cancelled
admission remains quarantined and links the saved result, rather than silently
starting replacement work. A hosted subprocess test must verify the signal,
descendant exit, saved JSON and liveboard state. This is not hard-kill recovery,
nor proof that a model-server request has drained: quarantining is retained.

## Cooperative controller delegation checkpoint

Source697908a adds a parent reservation, one-use operation-scoped child grants,
fixed evaluation/log subprocess workers and fenced resume/finalization. A child
needs both a live parent lock and matching boot/process birth. The Python
evaluation API now saves completed or failed/cancelled results before release;
publication failure stays quarantined. The guarded Linux gate passed14 lifecycle
cases, including actual subprocess exit, killed workers/parents, stale callbacks,
contention, capability replay, lock I/O errors and failed publication. Full Tests
run39092122371 passed762 Python tests (4skips),28 Node tests and shell syntax.
See evidence/workload-delegation-697908a.json and its focused log.
The same source passed pinned compatibility run39092126565; its artifact hashes
are included in that receipt. This remains synthetic/request and native runtime
evidence, without a model-quality or physical acceptance claim.

This does not satisfy the full safety gate. Production controller/heartbeat
dispatch is not yet connected; trusted-host drainage assertions are not backend
inspection; direct model/desktop/maintenance paths and broad SDK filesystem/shell
tools still need mediation. Protected proctor/evaluator identity, the complete
log auditor, repeated independent signed exams and fresh-card unattended
acceptance remain unproven. No live Toronado change or exam occurred for this
checkpoint. The final merged image still needs every gate above.

## Managed SDK bridge checkpoint

Sourcea1d2247 passed Tests run39093712269 (768 Python tests,4skips;29 Node tests;
shell syntax and guarded signal tests) and pinned compatibility run39093712268.
The latter exercised the actual SDK entry/tool hooks through a private host
bridge: generic exec was denied, one synthetic20-task evaluation was saved,
its receipt-backed note was appended, and proctor admission stayed closed until
the host confirmed SDK worker/group exit and closed the context. Evidence is
under evidence/controller-bridge-a1d2247/, including the actual saved synthetic
result258e61073d48642bbf38a3cdf3a50198 and validated artifact hashes. The prior
6597e35 fixture failed binding its mock HTTP port before controller launch;
kernel-tested TIME_WAIT reuse resolved fixture sequencing without sharing or
interrupting a live listener.

The managed scope has only evaluation/compare/log tools. Production gateway and
heartbeat routing, durable owner campaign authorization, bounded inspection/
edit/model tools, protected service identity, backend-wide exclusion/drainage,
the complete claim auditor and the remaining physical/independent acceptance
gates are still required. No actual model made the fixture's scripted choices;
it is not an autonomous climb, proctor exam or model-quality measurement. The
feature remains opt-in and no Toronado change occurred for this checkpoint.

## Bounded instruction tools checkpoint

Source67fa777 adds optional managed inspection, one literal AGENTS.md patch,
private before/after/config/baseline snapshots, and keep/restore resolution.
Only a matching baseline from the same live host controller can authorize an
edit. Repeated matched evidence and an explicit conservative practice policy
gate keeps; restoring without a valid candidate exam does not count as a
measured experiment. Unknown writes and publication failures stay quarantined.
The instruction journal auditor replays patches, validates saved receipts and
checks final bytes. Its scope excludes free-form log claims and independent gain.

Exact-source Tests run39106875110 passed779 Python tests (4skips),29 Node tests,
shell syntax and seven guarded groups. Pinned compatibility run39106875111
passed actual SDK inspection/evaluation/edit/restore/log transport with seven
controller requests and20 isolated evaluation requests. Saved synthetic result
a69d6a762035ec1a2576c107625c394a has complete20-task coverage. The patch was
snapshotted and restored byte-for-byte, the journal audit passed, generic exec
was denied, and proctor admission stayed closed until host release. This fixture
has no candidate exam: it reports zero qualified experiments and no independent
gain. Repeated measured keep/restore policy is unit-tested. Reports, saved result,
worker/journal receipts and machine-checked hashes are in
evidence/instruction-tools-67fa777/. No actual model chose these scripted actions.

The feature is not enabled in the default conversation profile or on Toronado.
Deployment still requires receipts for every copied context/personality input
and installed weight identity, bounded model operations, production gateway/
heartbeat routing, durable owner authority, protected service identity and
backend-wide admission/drainage. Full claim auditing, independent signed exams
and every fresh-image/physical acceptance gate above remain open.

## Fresh direct-transport image candidate (cd9b2db)

Pinned ISO build [39370482787](https://github.com/mbolaris/argos-live/actions/runs/39370482787)
passed from source cd9b2db450abc89b2943ce902f4c527a0fb5b37e. The ISO SHA-256 is
88dcd719a2dbdb7bd777cafdc07e9eec2a3798c884d6d889c9f0fc13f370313d; build pins
and artifact report are preserved in `docs/evidence/managed-guest-39372199391/`.

Strict offline managed-guest KVM acceptance
[39372199391](https://github.com/mbolaris/argos-live/actions/runs/39372199391)
passed. The guest reported RAM policy, automatic first boot, visible Model Lab,
saved speed and ability results, and assistant resumption. Saved run IDs are
e8bef97fd8932b10474794f601e736bc and 9d38a584f1390f5948987999029b6f78. The
captured progress screen shows an active 0/20 ability phase; terminal scoring is
supported by the saved result record, not that screenshot. This synthetic CPU
fixture does not establish model improvement or an independent exam pass.

Physical firmware/card/persistence/reboot-reset acceptance and browser chat
reply remain unverified. The image is a validated USB-writing candidate, not a
physical-card acceptance claim. Toronado and its generation-36 quarantine were
not changed.
