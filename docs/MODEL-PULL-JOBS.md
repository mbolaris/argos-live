# Verified model pull jobs

MD4a supplies durable job/progress state. MD4b adds Linux-owned Ollama, exact integrity checks, a fixed reply test and `argos pull` commands. Agent assignments and desktop autostart are unchanged. Dashboard wiring and actual Live/physical acceptance remain later work.

## Commands

Use existing Argos setup state and identity-marked model storage. Private queue metadata stays under `~/.config/argos-live/pull-jobs`, following encrypted persistence or RAM-only lifetime. Do not relocate state to unencrypted DATA.

```sh
argos pull init
argos pull create qwen3:1.7b
argos pull status JOB_ID
# Stop the assistant before competing for GPU/RAM:
argos pull run JOB_ID --assistant-stopped
# From another terminal while run is active:
argos pull pause JOB_ID
argos pull cancel JOB_ID
# After pause, failure, interruption or reboot:
argos pull retry JOB_ID
argos pull run JOB_ID --assistant-stopped
```

Commands emit JSON; run emits progress snapshots. `--state PATH` before the subcommand selects an existing reviewed Argos state file. The stopped acknowledgement does not detect or stop a service. Unrelated services are never terminated. `argos start` can restart the unchanged starter afterward. Cancelled jobs remain cancelled; create a new reviewed job if needed. Retries are explicit, with no retry storm or automatic reboot scheduler.

## Staging and verification

Downloads go to `<selected models>/.argos-pulls/JOB_ID`. Queue and store-wide OS-held locks exclude cooperating workers, including different queue roots for the same selected store. Storage marker/optional UUID and catalog identity are rechecked. No mounts, fallback storage, partitions, firmware or USB rewrites are involved.

The registry manifest must match the reviewed catalog SHA256 before weights are requested. The raw local manifest and every full blob are checked afterward, catching a mutable-tag race during pull. Existing destination tags with different revisions are never replaced. Existing full staged blobs receive space-budget credit only after SHA verification; partials receive no trusted credit. Missing bytes plus 1 GiB must be free. Conservative recovery can require additional free space. Corrupt files fail closed and remain available for review.

Visible stages are downloading, verifying, loading, testing, publishing and ready. Progress validates each digest, total and completed counter, aggregates without double counting, and rejects decreasing counters within an attempt. Recent MiB/s and ETA use measured deltas over at least a second; unknown rates remain null. A resumed attempt starts a new measurement window, so already-downloaded bytes are not advertised as network throughput.

The fixed reply uses public text, context 2048, at most 32 output tokens, temperature zero, seed one and thinking disabled. Quantization/family must match; an empty reply fails. Retained timing/count fields come from Ollama, with missing fields null. This verifies basic text generation, not answer quality, tools, vision, a 32k context, GPU offload or a full benchmark.

After unload and backend shutdown, verified blobs are published through atomic hard links; the raw manifest is linked last without replacing an existing tag. Existing destination blobs are reverified. Hard-link support is probed before download: supported local filesystems include ext4/NTFS; unsupported filesystems such as exFAT fail closed. Staging remains for recovery; shared links do not duplicate published weights. No automatic cleanup or agent-selection/configuration change is implemented.

Ready requires exact integrity, the basic reply and successful publication. Later activation must reverify instead of trusting an old receipt after changes. Interrupted publication can leave complete reusable blobs; retry rechecks everything. No partial artifact is used as an active model.

## Daemon ownership and recovery

The adapter binds to a private loopback port. Linux `/proc` socket ownership must establish that the listener belongs to the child before trusting its version/API, so a port-allocation race cannot silently reuse another daemon. The pinned version is 0.35.0. Cloud/pruning are disabled, with one loaded model and one parallel request.

A Linux parent-death supervisor stops the daemon/runner group on worker death or normal/error exit. The store lock stays held through ordinary supervisor shutdown. Forced termination of the supervisor itself by an unrelated administrator is outside the cleanup contract. Cancellation is checked between reads/hash chunks; stalled API reads are bounded by 30 seconds, with additional bounded unload/shutdown time. A crash before the worker finishes shutdown can temporarily leave the supervisor cleaning up; explicit retry never reuses that old backend.

One bounded private JSON record per job contains its random ID, catalog tag/revision, storage identity, timestamps, attempt count, state, progress and acceptance evidence. Updates use same-directory temporary files, fsync and atomic replacement; Linux also fsyncs the directory. Pause/cancel controls have separate atomic files, so progress updates cannot overwrite requests. New private directories use the existing owner-only POSIX/Windows ACL helper. Linked paths and oversized metadata are rejected.

Stale downloading/verifying/loading/testing/publishing records can be explicitly requeued after acquiring exclusion. Runtime state and profile credentials stay out of DATA. Model weights are public artifacts and may be stored on owner-selected unencrypted DATA. Uncooperative external writers/admin filesystem replacement races are outside these locks; do not run other writers against the model store during publication.

## Evidence

Unit tests use authored loopback responses and tiny temporary artifacts, never registry traffic, a GPU or owner data. They cover interrupted streams/resume, counters/rate/ETA, pause/cancel, stale-state recovery, lock lifetime, storage/capacity failures, corrupt blobs/manifests, empty replies, pinned-version rejection, starter preservation, staged publication and CLI/status. Linux fake-executable tests exercise socket ownership, environment, error cleanup and worker-death supervision.

`scripts/smoke-model-onboarding.py` is separately labeled NETWORK integration. Its dedicated CI workflow fetches the checksum-pinned real Ollama binary, pauses a qwen3:0.6b pull, verifies retained partial files, retries through artifact verification/reply/publication and reports real timings. This does not establish physical Live/NVIDIA acceptance. Full model performance cards, addon capability checks and welcome-window wiring remain separate backlog items.

Pinned upstream references: [raw manifest preservation and pull pruning](https://github.com/ollama/ollama/blob/v0.35.0/server/images.go), [partial download recovery](https://github.com/ollama/ollama/blob/v0.35.0/server/download.go), [environment settings](https://github.com/ollama/ollama/blob/v0.35.0/envconfig/config.go).
