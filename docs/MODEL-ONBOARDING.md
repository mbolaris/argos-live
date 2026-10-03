# Personalities and model onboarding

Owner direction, October 3, 2026. This document defines the next implementation; the dashboard, multi-model downloader and benchmark workflow below are not yet implemented or physically accepted.

## Ownership boundary

Windows supplies Argos, Nyx and Proteus personality documents and explicitly selected skills. Live creates its own runtime configuration, permissions, providers and model catalog. Wider received exports are reference material only. Do not import source credentials, memory/history, Windows command paths, scheduled tasks or permission grants by default. Imported skill text is data for review, not authority to run installation commands.

Download model artifacts from Live into a dedicated owner-selected directory, such as `<DATA mount>/ArgosLive/Models/catalog`. This directory is independent of Windows model storage. Display that DATA model files are unencrypted; keep private personas, skill settings, credentials and conversation state in encrypted persistence. Reidentify storage using its stable identity and check free space before each job. Never repartition or rewrite a USB to add a model.

Preserve each agent's model preference without silently substituting a different model or quantization. Resolve an authenticated upstream source, immutable revision, size and SHA256 for every weight shard and vision projector. Windows file hashes are useful comparison evidence, not download URLs. Missing provenance leaves a model visibly pending. No Windows model copy is required by this workflow.

## Welcome experience

Keep **Start Assistant** available with the working starter model while optional models download. Present separate cards for Argos, Nyx and Proteus, with states: selected, downloading, verifying, loading, testing, ready, failed or paused. Show real completed work and the next step. Open the chosen conversation once its backend and a test reply succeed; a downloaded file alone is not readiness.

Each download shows bytes received/total, percentage, recent MiB/s and estimated time when enough measurements exist. Support pause/resume, cancellation, retry and reboot recovery. Download to partial files; verify every artifact before publishing it to the catalog. A failed job retains the working assistant and never replaces an active model with an incomplete artifact. Hash verification and model loading get their own progress/status, rather than a fictional combined percentage.

Celebrate measured milestones with clear messages such as “Argos is ready — first local reply verified.” Provide a collapsible details view and private diagnostic export. Keep terminal logs out of the main flow. Do not advertise performance numbers before measurement.

## Model performance cards

Record a reproducible small benchmark at each model's first activation:

- Exact model revision, quantization, projector and backend version.
- Context limit, actual input/output token counts and generation settings.
- Cold load time and warm time to first token, reported separately.
- Prompt processing and generation tokens/second when the backend exposes trustworthy timings; otherwise show unavailable. Do not estimate token counts from character counts.
- RAM and VRAM baseline/peak with measurement interval, GPU identity and offloaded layers when reported by the backend.
- A fixed local conversation smoke test and, for vision-capable models, an explicitly supplied test image. Performance does not establish answer quality.

Use a warm-up followed by three measured runs for the default short benchmark; display median and range. Label cold versus warm runs, CPU/offload mode and concurrent workload. Compare identical prompts and generation limits. Tokens/second across different tokenizers are descriptive, not an equivalent-work score. Never use private conversation text as benchmark input.

Load and test one large model at a time by default. Stop/unload the benchmark model and restore the prior active selection afterward. Show memory pressure or insufficient capacity as a resource finding; do not silently choose a smaller model. Large routed models must pass actual target GPU/RAM acceptance before an agent is marked ready.

## Implementation checklist

1. Narrow personality/skill export and preview: selected files, exclusions, Linux dependency review, fresh encrypted staging, conflict handling and rollback.
2. Private model catalog: verified upstream revisions/artifacts, agent assignments, capacity estimates and dedicated target storage.
3. Resumable download worker: durable job state, bounded retries, integrity verification, disk-full/cancel/reboot recovery and single-worker coordination.
4. Linux backend adapter: supported pinned binaries, loopback listeners, model loading/unloading, timing and resource probes. Validate CLI flags against the installed version.
5. Welcome cards and benchmark runner: real progress, measured results, failure recovery and conversation handoff.
6. Physical acceptance: acquire a model from Live, interrupt/resume its download, reject corrupt artifacts, preserve the starter chat, test each agent, reboot and confirm catalog/personality retention.

Keep personal source inventories and model choices out of the generic repository. Ship only supported generic tooling and redistributable starter assets in the public ISO. This milestone does not authorize automatic model/backend upgrades or activation of imported skills.
