# Durable model pull jobs

MD4a adds an internal, stdlib-only job engine in `runtime/argoslive/pull_jobs.py`.
It has no user-facing command, autostart hook or production Ollama adapter yet.
Those belong to MD4b; this change does not download or activate models on Live.

## State and progress

Initialize a fresh private queue directory under the user's Argos config/state
location. The caller must first establish encrypted persistence or explicitly
label RAM-only operation. Do not place the queue on unencrypted DATA: its model
choices are private. The queue accepts only existing, identity-marked model
storage, with the optional filesystem UUID checked by MD2. It never mounts,
adopts, creates or falls back to another model directory.

Each `argos-pull/1` record contains a random job ID, exact catalog tag and pinned
manifest digest, selected storage identity, timestamps, attempt count, state and
progress. Updates use a same-directory temporary file, file fsync and atomic
replacement; Linux also fsyncs the directory. State and control files are bounded
to 1 MiB and path links are rejected. New private directories use the existing
owner-only POSIX/Windows ACL helper.

States are `queued`, `downloading`, `paused`, `cancelled`, `interrupted`, `failed`
and `downloaded_needs_verification`. Integrity and inference readiness always
remain false in this step. Ollama reporting pull success does not prove the
download matches the pinned catalog or that a model can answer.

Progress validates each reported digest and size against the catalog and sums
per-artifact counters without double counting repeated events. Counters cannot
decrease within an attempt. Recent speed uses a bounded rolling sample window;
ETA is unavailable until a positive rate has been measured over at least a
second. Resume starts a new measurement window, allowing Ollama to report the
already-completed partial bytes without treating them as new network throughput.
Unreported artifacts remain incomplete rather than inventing a 100% result.

## Recovery and exclusion

Pause/cancel requests have a separate atomic control file, so progress updates do
not overwrite them. Cancellation retains files and cannot be retried in place;
create a new reviewed job if desired. Failed, paused or interrupted jobs require
explicit retry. A record left `downloading` after process death can be requeued
only after acquiring the worker lock. No automatic retry loop is implemented.

An OS-held lock excludes cooperating operations using the same queue root and is
released by process death. Its file is never removed. All workers for a selected
store must share that root; this is not a lock on other Ollama services or writers.

The internal `run` API requires an **owned backend context**: it yields a B2 client
and must terminate all backend writes before context exit, including on errors or
cancellation. The queue lock stays held through that exit. Closing an HTTP stream
alone cannot guarantee server-side cancellation. Until MD4b implements and tests
the owned daemon adapter, the engine is exercised only with fixture contexts.

Before starting, the engine rechecks catalog/storage identity, hashes existing
complete blobs, and requires missing artifact bytes plus 1 GiB free space.
Corrupt complete blobs fail closed and are retained for review. Partial blobs
receive no space-budget credit: recovery is conservative and may require extra
free space. Ollama owns partial-file resume; the engine does not copy Windows
weights, delete partials or rewrite manifests. Storage identity is checked again
at progress events and after completion. Filesystem replacement races by an
uncooperative concurrent administrator are outside this API's exclusion.

## Remaining MD4b work

- Own a loopback Ollama process pointed exclusively at the selected model store,
  validate its pinned version and stop it before releasing exclusion.
- Recheck the registry revision and verify the local manifest descriptors and all
  downloaded blob hashes against the reviewed catalog. A mutable tag must never
  be published as the pinned revision merely because its pull succeeded.
- Show `verifying` and `loading/testing` separately; exercise a fixed test reply,
  record real backend timings, unload and preserve the starter assistant.
- Wire CLI/status/recovery and later the welcome dashboard; physical interruption,
  reboot recovery and model inference acceptance remain pending.

## Evidence

Unit tests use an authored loopback HTTP fixture, a temporary identity-marked
store and the bundled catalog with a tiny test-only weight descriptor. They cover
progress/ETA, detached UI snapshots, interrupted streams, explicit resume,
pause/cancel, exclusion through backend exit, stale-state recovery, disk-full
preflight, corrupt full blobs, changed identities/revisions and malformed counters.
They use no registry traffic, downloaded model, GPU or private owner data. They
do not establish real Ollama resume or physical readiness.
