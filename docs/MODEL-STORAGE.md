# Model storage selection

`argos storage --json --required-gib 4` previews a location with a four-GiB model budget plus a one-GiB safety margin. It reads the current mount table, block-device topology, free capacity and available RAM. It does not mount or unlock volumes, create folders or markers, change configuration, copy weights, or download models. Interactive setup remains unchanged; automatic setup and download jobs will consume this planning interface in O1/MD4.

Selection order:

1. Existing owner-configured model directory, with its matching `.argos-storage-id`. A recorded `storage_uuid` must also match the currently mounted filesystem. Missing, mismatched, read-only, inaccessible or undersized configured storage stops the operation. It never selects another disk as a fallback.
2. The largest eligible already-mounted writable filesystem with a known UUID and enough free space. Its proposed location is `<mount>/ArgosLive/Models/catalog`. The live boot medium must be identifiable from `/run/live/medium` or `/lib/live/mount/medium`; all devices sharing its ancestry are excluded, including its persistence partition. Mounted filesystem views with a non-root mount root, stacked mount ambiguity, and nested filesystem mismatches are excluded rather than guessed.
3. Existing writable tmpfs at `<mount>/argos-live-<uid>/models`, only when both available RAM and tmpfs free space cover the full budget. This is temporary: models disappear after reboot. No new tmpfs is mounted and no system memory limit is changed.

Locked/unmounted Windows volumes and network filesystems are not automatic candidates. No repartitioning, formatting or Windows boot changes are involved. A proposed filesystem is a preview, not permission to write arbitrary internal-disk files. The later setup/download step must recheck identity, space and actual write access before creating its dedicated directory. An access-bit check is not a completed write test. Existing storage and model files are not adopted or changed by this command.

The JSON report includes the chosen path, filesystem UUID, capacity, budget, selection reason, persistence assessment and encryption assessment. `encrypted: true` requires encryption evidence in the lsblk ancestry; `false` indicates an observed ordinary disk ancestry; `null` means unknown, including incomplete/loop-backed or mixed ancestry. These are filesystem observations, not a cryptographic audit. RAM is marked temporary and its encryption stays unknown. Overlay-backed configured storage has unknown persistence unless backed by a recognized block filesystem.

For owner-configured storage without a recorded filesystem UUID, the existing marker remains the compatibility check and the report shows any discoverable UUID. This command does not silently rewrite that state. An identity marker plus UUID helps detect accidental drive changes; it is not authentication against a malicious clone.

DATA may hold downloaded public model weights and other owner-authorized files. Unencrypted DATA must not hold private personalities, credentials, history, pack receipts or backups; those remain on verified encrypted persistence. Reports can include private paths, so keep real machine reports out of public Git/CI artifacts.

The parser follows [kernel mountinfo fields](https://docs.kernel.org/filesystems/proc.html) and uses explicit [lsblk output columns](https://man7.org/linux/man-pages/man8/lsblk.8.html), retaining repeated-device ancestry. Tests use fictional mount/device fixtures and injected capacity/access results; physical Toronado acceptance and real downloads are separate checks.

## Read-only starter service foundation

`argoslive.starter.serve()` is an internal Linux inference context for the image's
`qwen3:0.6b` seed. It checks the reviewed catalog manifest and every artifact SHA
before starting pinned Ollama directly on the seed. It refuses a source writable
to the inference user. The supervisor lease uses a separate private temporary
directory, and cloud requests/pruning are disabled. No weights are copied, no
OpenClaw configuration is written, and no selected download store is adopted.
Shutdown removes the temporary lease after daemon/runner cleanup.

Read-only verification skips fsync on the image's read descriptors; downloaded
model publication retains its existing sync checks. The public Linux integration
fixture makes its seed unwritable to an unprivileged hosted-runner user, generates
a real measured CPU reply, and rechecks the complete source inventory and hashes.
This tests file-permission enforcement, not a SquashFS mount or physical USB.

The dashboard displays the bundled starter separately from downloaded models,
including when selected download storage needs attention. This bounded metadata
probe checks manifest identity, artifact sizes and read-only access; it never
hashes the full weights or claims current inference readiness. An absent image
source is omitted; incomplete or writable source files need attention. Unknown
source selections are rejected without a fallback model store.

Existing interactive setup still copies the seed. Automatic source selection,
downloaded-model switching and no-copy VM acceptance remain MD3b/O1/O2.
The caller must own the overall single assistant lifecycle;
this helper does not adopt a daemon or provide automatic first-boot startup.
