# Implementation backlog

Updated October 4, 2026. Goals and milestones: [PROJECT-GOALS.md](PROJECT-GOALS.md). Model onboarding design: [MODEL-ONBOARDING.md](MODEL-ONBOARDING.md). Personality transfer rules: [PROFILE-SYNC.md](PROFILE-SYNC.md).

Each item is sized for one agent session and one pull request. Pick an item whose dependencies are done, keep the change to its scope, and meet every acceptance criterion before opening the PR. If an item proves too large, split it in the PR description and update this file.

## Rules for implementing agents

1. **Branch and PR per item.** Title the PR with the item ID, for example `B3: speed benchmark`. Update the item's status in this file in the same PR. After checks pass and merge is authorized, merge through GitHub's PR action and delete the landed branch. Before deleting an older branch, verify its tip matches the merged PR and retain a local recovery reference; preserve branches with additional commits. Mark implemented items done when their scoped acceptance passes, and keep physical USB/release acceptance separate.
2. **Stdlib-only Python 3.11+** for everything under `runtime/`. No pip dependencies in the image. Tests use `unittest` and must pass with `bash scripts/check.sh` on Linux; keep them importable on Windows (skip, don't fail, for Linux-only behavior).
3. **No live network or GPU in unit tests.** Mock Ollama HTTP responses, `nvidia-smi` output and `/proc` files with recorded fixtures under `tests/fixtures/`. Integration checks that need a real Ollama go in `scripts/smoke-*.sh` and are labeled as such.
4. **Say how it was verified.** Every PR states which acceptance criteria were checked by unit test, by a real Ollama run, by a CI ISO boot, or by physical hardware, and which remain unverified. Never claim physical acceptance from a VM.
5. **Keep protections.** Services bind to loopback; local web endpoints require a per-session token; the default agent permission stays conversation-only. Do not log tokens or credentials.
6. **No private data in this repository.** The owner's personas, inventories, model choices, receipts and exports stay in private storage. Use the public sample packs and fixtures for tests.
7. **Pinned upstream versions only.** Do not bump `versions.env` outside E6/E7 items. Validate OpenClaw and Ollama CLI flags and API fields against the pinned versions.

Status values: `todo`, `in progress (PR link)`, `done (PR link)`, `blocked (reason)`.

## Shared design decisions

These decisions prevent parallel agents from diverging. Change them only through a PR that updates this section.

- **Runtime layout.** New modules live in `runtime/argoslive/` (a package): `hw.py`, `ollama.py`, `bench_speed.py`, `bench_ability.py`, `results.py`, `catalog.py`, `storage.py`, `packs.py`, `web/`. `runtime/argos.py` stays the CLI entry point and imports the package. The image installs the package to `/usr/local/lib/argos-live/argoslive` and the CLI adds that directory to `sys.path`.
- **State locations.** Config/state: `~/.config/argos-live/`. Benchmark results: `~/.local/share/argos-live/results/`. Personality staging: `~/.local/share/argos-live/packs/staging/`. These are on encrypted persistence when it is mounted, in RAM otherwise.
- **Results format.** One JSON file per run, `schema: "argos-bench/1"`, containing: run ID, UTC timestamp, benchmark kind and version, model tag and manifest digest, quantization/parameter metadata from `/api/show`, Ollama and Argos versions, hardware snapshot (from `hw.py`), backend mode (GPU/CPU, offloaded layers when reported), settings (context, seed, temperature, think flag, generation limit), per-run raw timings and token counts, summary statistics, and for ability runs per-item results and per-category scores. Unknown values are `null`, never estimated.
- **Speed method.** One warm-up, then three measured runs per prompt size; report median and range. Load time from the first (cold) request is reported separately. Tokens/s from Ollama `prompt_eval_count/prompt_eval_duration` and `eval_count/eval_duration`; time to first token from streamed responses. Prompt sizes: short (~128 tokens), medium (~2k) and long (~8k, skipped with a reason when the model's context is smaller).
- **Ability method.** Deterministic: temperature 0, fixed seed, thinking disabled where the model supports the flag. Two suites: `quick` (about 20 items, target under 3 minutes for a 7–8B model on a mid-range GPU) and `standard` (about 70 items). Categories: arithmetic reasoning, knowledge multiple choice, instruction following, structured JSON output, tool-call formatting, and small code tasks checked by a sandboxed test runner. Scoring is programmatic; no LLM judge. Format failures are reported separately from wrong answers.
- **Datasets.** Vendored under `runtime/argoslive/data/` with item IDs, the source dataset, the licence and a version. Only redistributable sources (for example GSM8K and MMLU, both MIT) or items written for this project. Changing items bumps the suite version, and results from different suite versions are never ranked together.
- **Dashboard.** Python `http.server` on `127.0.0.1:8765`, static HTML/JS/CSS with no build step and no CDN (works offline). A random per-session token is required on every request and passed in the URL opened in Firefox. Chat links to the OpenClaw dashboard; the lab does not reimplement chat.
- **Personality pack format.** `argos-pack/1`, specified in P1. A ZIP with `manifest.json` (pack ID, version, created time, per-agent entries: ID, display name, persona files, skill files, model preference as data, notes) and a SHA256 for every file. Packs contain no credentials, memory or history, permissions, provider configuration, executables or absolute source paths.

## Owner decisions

Resolved October 3, 2026. Agents implement these; changing one needs the owner.

| ID | Decision | Affects |
|---|---|---|
| D1 | **Public ISOs are hosted on Google Drive.** The ISO (about 4 GB) exceeds GitHub's 2 GiB release-asset limit. A GitHub release carries the Drive link, `SHA256SUMS`, package manifest, notices and release notes, so users verify the download against GitHub. | C4 |
| D2 | **Machine-specific material lives in a private GitHub repository or the owner's Google Drive, never in this repository.** Versioned scripts and notes go to the private repository; exports, archives and receipts go to Drive. This repository keeps only generic tooling. Whether to rewrite this repository's history to remove already-committed material is a separate owner decision; R1 does not rewrite history. | R1 |
| D3 | **Do not pin a specific NVIDIA driver version.** Install Debian's `nvidia-driver` package as resolved by the build's Debian snapshot (preferring the newest supported branch Debian offers for the suite, such as backports, when it adds GPU support). The package manifest records the version actually shipped. Detect at boot whether the driver supports the installed GPU and fall back to CPU with a visible explanation. | H1 |
| D4 | **Ship one generic Argos-like sample agent publicly.** A capable, friendly primary assistant, written fresh for the public image and not derived from the owner's private Argos persona. The starter catalog list is proposed by the MD1 agent and approved by the owner in that PR. | P6, MD1 |
| D5 | **The Toronado `bench.py` prototype is not a dependency.** E1 is built from this backlog. If the prototype is pushed to a branch, E1 agents may reuse ideas or items from it, subject to this backlog's design decisions and dataset licensing rules. | F3 (closed) |
| D6 | **Ollama is the supported language-model inference backend.** No separate llama-cpp plugin/server or GGUF download path in this milestone. Resolve personality model preferences to verified Ollama artifacts; unresolved choices remain pending rather than silently substituted. | B2, MD1–MD4, A2, P3–P4 |

## E0 Foundations

### F1 Make the test suite environment-independent — `done ([PR #2](https://github.com/mbolaris/argos-live/pull/2))`
Depends on: none.
- `tests/test_welcome.py` must skip with a clear reason, not error, when `tkinter` is missing.
- Add `.github/workflows/tests.yml` running `bash scripts/check.sh` and the Node upstream tests on `ubuntu-latest` for every push and PR.
- Accept: `scripts/check.sh` passes on a clean Ubuntu runner without `python3-tk`; CI job is green.

### F2 Runtime package skeleton and install path — `done ([PR #3](https://github.com/mbolaris/argos-live/pull/3))`
Depends on: F1.
- Create `runtime/argoslive/__init__.py` with a version string, and teach `runtime/argos.py` to import the package from its source checkout or from `/usr/local/lib/argos-live`.
- Update `scripts/build.sh` and `scripts/sync-build-runtime.sh` to install the package directory into the image.
- Accept: `python3 runtime/argos.py --help` works from a checkout; a unit test confirms the import path logic; build scripts pass `bash -n`; the repack path copies the package (checked by reading the script, verified by the next ISO build).
- Evidence: checkout CLI/path tests pass on Windows; Linux CI passes the temporary package-install/import fixture and shell syntax checks. Both includes and existing-chroot repack paths call the installer. Actual ISO contents remain for the next build verification.

### F3 Reconcile the out-of-repo bench prototype — `closed (D5)`
- Not needed. See D5.

## E1 Benchmarks (M1)

### B1 Hardware probe — `done ([PR #5](https://github.com/mbolaris/argos-live/pull/5))`
Depends on: F2.
- `hw.py` returns CPU model, cores/threads, RAM total/available, GPU list (name, VRAM total/used, driver) from `nvidia-smi --query-gpu ... --format=csv`, AMD/Intel GPUs from `lspci` names only, disks and free space for candidate model directories, kernel, Secure Boot state if readable.
- Missing tools or files produce `null`s, not exceptions.
- Accept: unit tests with recorded fixtures for an NVIDIA desktop, a CPU-only laptop and a no-`nvidia-smi` system; `argos hw --json` prints the snapshot.
- Evidence: Windows and Linux CI pass hardware/CLI tests using authored, sanitized command-output fixtures (not owner hardware captures). NVIDIA fields/units checked against official documentation. Physical Live output and ISO inclusion remain unverified. Depends on F2 integration [PR #4](https://github.com/mbolaris/argos-live/pull/4) reaching main.

### B2 Ollama client — `done ([PR #6](https://github.com/mbolaris/argos-live/pull/6))`
Depends on: F2.
- `ollama.py`: version, list, show (parameters, quantization, context length, capabilities), pull with streamed progress callbacks and cancellation, generate/chat with streaming that records time to first token and returns the final timing fields, unload (`keep_alive: 0`), and `ps` (loaded models, VRAM size).
- Base URL configurable; default `http://127.0.0.1:11434`. Clear errors for "not running", "model missing" and HTTP failures.
- Accept: unit tests against a fake HTTP server serving recorded responses, including streaming chunks and an interrupted stream; field names checked against the pinned Ollama version's API documentation.
- Evidence: Windows and Linux CI pass tests against a loopback fake server with authored protocol fixtures checked against pinned v0.35.0 API types. Progress, cancellation, chat/generation timings, unload and interruption/error paths pass. Real Ollama/model/GPU acceptance remains pending. See OLLAMA-CLIENT.md for bounded cancellation behavior.

### B3 Speed benchmark — `done ([PR #18](https://github.com/mbolaris/argos-live/pull/18))`
Depends on: B1, B2.
- Implements the speed method above. Generation limit fixed (for example 128 tokens). Thinking disabled. Records whether the model ran on GPU, CPU or split, from `ps`.
- Unloads the model afterwards and restores the previously loaded model if one was loaded.
- Accept: unit tests verify statistics, cold/warm separation, skipped long prompts and `null` handling when timing fields are missing; a smoke run against a real Ollama with `qwen3:0.6b` completes in under 60 seconds on CPU and writes an `argos-bench/1` file.
- Implementation: `argos bench speed --model TAG [--json] [--ollama URL]` runs without setup against an installed exact model; private result files include hardware, revision/settings, raw backend counts/timings, per-size warm-up/three-run medians/ranges and conservative placement. Explicit unload separates the initial load sample; finally unload/previous-model reload restores its advertised context. Unknown/undersized contexts skip with reasons. See [SPEED-BENCHMARK.md](SPEED-BENCHMARK.md). Full B6 results management and remaining B7 commands are still pending.
- Evidence: eight fixture tests pass for statistics, cold/warm separation, context skips, unknown fields, placement, restoration on error and CLI output. The first real CPU full run exceeded the general 30-second API timeout during long prefill. Benchmark reads now use a bounded 120-second timeout. The short onboarding smoke is gated under 60 seconds; the full three-size run is tested separately. 134 Windows tests passed (seven platform skips), Linux Python/shell/Node CI passed, and real pinned Ollama CPU acceptance passed: short 9.87 seconds, full 177.89 seconds, with model/context restoration and result-file round trip ([run](https://github.com/mbolaris/argos-live/actions/runs/37183286399)). Long CPU requests use an explicit 600-second bound in the lab; CLI --timeout permits 1–600 seconds (default 120). This clarifies the quick smoke target without claiming that a full CPU lab run finishes under 60 seconds. Physical GPU acceptance remains separate.

### B4 Ability datasets and scorers — `split into B4a and B4b`
Depends on: F2. Can run in parallel with B1–B3.
- Vendored `quick` and `standard` suites per the dataset rules above, with licence notices added to the image's notices.
- Scorers: numeric answer extraction tolerant of formatting, multiple-choice letter extraction, instruction-following checks (length, format, keywords), JSON schema validation, tool-call shape validation, and code tasks run in a subprocess with timeout, no network, and a temporary directory.
- Accept: every item has a passing reference answer and a failing wrong answer in unit tests; format failures and wrong answers are distinguished; code sandbox enforces timeout and cannot write outside its temporary directory.

### B4a Original suites and nonexecuting scorers — `done ([PR #24](https://github.com/mbolaris/argos-live/pull/24))`
Depends on: F2.
- Original versioned MIT-licensed quick (20) and standard (70) suites for numeric,
  choice, instruction, closed JSON and inert tool-call formatting. Every item has
  passing, wrong and malformed reference fixtures. Packaged notices and an offline
  reproducible generator ship with the runtime.
- Accept: all item fixtures pass, format/wrong outcomes differ, duplicate keys,
  ambiguous numbers, malformed Unicode, bounds and invalid suites are rejected;
  installed package contains both suites and their notice. No model or tool is
  invoked. See [ABILITY-BENCHMARK.md](ABILITY-BENCHMARK.md).

### B4b Code tasks and enforced execution sandbox — `split into B4b1 and B4b2`
Depends on: B4a.
- Add versioned coding fixtures only with actual OS-enforced filesystem/network
  isolation and bounded subprocess lifetime. Merely setting cwd to a temporary
  directory is insufficient. Test timeout, outside-write and network rejection.
- Code category is explicitly omitted by B4a; full B4 acceptance remains here.

### B4b1 Sandbox foundation — `done ([PR #29](https://github.com/mbolaris/argos-live/pull/29))`
Depends on: F2.
- Fail-closed Linux amd64 bubblewrap namespaces, no writable host mount, seccomp
  denial of network/process creation, bounded tmpfs/output/source and hard resource
  limits. Actual Linux tests cover filesystem/network rejection, timeout and cleanup.
- Root-hosted CI exercises kernel enforcement without changing host security policy;
  unprivileged Live availability and generated-code suite activation remain B4b2.
  See [CODE-SANDBOX.md](CODE-SANDBOX.md).
- Evidence: actual Linux namespace/seccomp/resource tests passed
  ([run](https://github.com/mbolaris/argos-live/actions/runs/37217988219));
  normal Linux/Windows portability tests pass. Code suites remain omitted.

### B4b2 Coding fixtures and Live sandbox acceptance — `todo`
Depends on: B4a, B4b1, C3.
- Add versioned original code items with passing/wrong/malformed references,
  verified scoring harness and unprivileged Live sandbox probe. Keep code omitted
  when isolation is unavailable; use distinct suite identities for differing coverage.

### B5 Ability runner — `split into B5a and B5b`
Depends on: B2, B4.
- Runs a suite against a model with the ability method above; streams progress (item n of N, elapsed, ETA from measured per-item time); supports cancel; records per-item output, score and latency.
- Accept: unit tests with a fake model producing known right, wrong and malformed answers give exact expected scores; a smoke run of `quick` against `qwen3:0.6b` completes and records results.

### B5a Nonexecuting ability runner — `done ([PR #25](https://github.com/mbolaris/argos-live/pull/25))`
Depends on: B2, B4a.
- Run the versioned 20/70 original probes, deterministic settings, measured progress,
  per-item scores/output/timings and private results; cancellation preserves partial
  coverage and restores the prior model/context. Expose discoverable ability CLI.
- Acceptance: reference/wrong/malformed fixtures score exactly; failure/cancellation,
  coverage, context, bounds and restoration pass tests; real pinned CPU Ollama quick
  suite completes and its result round-trips. Code execution is explicitly omitted.
- Evidence: 188 Windows tests passed (seven platform skips), Linux CI passed, and
  the real pinned Ollama CPU quick-suite completion, result round trip and unload
  check passed ([run](https://github.com/mbolaris/argos-live/actions/runs/37215054664)).
  No minimum score, GPU timing target or physical Live acceptance is claimed.

### B5b Sandboxed code-runner integration — `todo`
Depends on: B4b, B5a.
- Add the verified code category to version-bumped suites and runner results.
- Test actual sandbox enforcement before enabling generated code execution.

### B6 Results store and comparison — `done ([PR #26](https://github.com/mbolaris/argos-live/pull/26))`
Depends on: B3 (format), B5a. Code results follow B5b with distinct suite versions.
- `results.py`: save, list, load, delete; comparison table across runs that only ranks runs with the same benchmark kind and suite version; CSV export.
- Accept: unit tests for round trip, schema version rejection, mixed-version comparison refusal and CSV output.
- Implementation: private bounded store, exact-ID inspect/delete, invalid listing
  reporting, evidence-derived summaries, matching settings/coverage and complete
  ability runs required. CLI comparison/CSV includes digest and timestamp; missing
  speed measurements remain unranked. See [BENCHMARK-RESULTS.md](BENCHMARK-RESULTS.md).
- Evidence: Windows and Linux tests pass for store, comparison, CSV and CLI paths;
  real pinned CPU speed/ability results pass validated store save/load equality
  ([run](https://github.com/mbolaris/argos-live/actions/runs/37215548515)).
  No physical Live/GPU result acceptance claimed.

### B7 CLI wiring — `done ([PR #27](https://github.com/mbolaris/argos-live/pull/27))`
Depends on: B3, B5a, B6. Sandboxed code follows B5b with versioned suites.
- `argos bench speed|ability [--suite quick|standard]|all --model TAG [--json]`, `argos bench results [--compare ID...]`, `argos hw`.
- Human-readable summary tables by default; `--json` prints the result file.
- Works without `argos setup` against any reachable Ollama (`--ollama URL`), so it is useful outside the live image.
- Accept: CLI tests with the fake server; documented in README.
- Implementation: discoverable speed/ability/results/all commands; combined runs
  save separate typed/versioned results and emit one JSON batch when requested.
  Hardware and speed use readable defaults with explicit unknown measurements.
  An actual loopback HTTP fixture runs the combined CLI without setup and verifies
  deterministic payloads, scores, result-store round trips and candidate unload.
- Evidence: 198 Windows tests passed (eight platform skips), Linux tests passed,
  and unchanged real pinned CPU speed/ability store smoke passed
  ([run](https://github.com/mbolaris/argos-live/actions/runs/37215960836)).
  Code execution and physical Live/GPU acceptance remain separate.

## E2 Models and storage

### MD1 Curated catalog — `merged (included in PR #16; PR #15 closed as redundant)`
Depends on: B1, B2.
- `runtime/argoslive/data/catalog.json`: 8–12 entries (tag, family, parameter count, quantization, licence, capabilities such as tools/vision/thinking, description, registry manifest digest pinned at catalog update time, total download bytes from the manifest).
- `catalog.py`: fit estimate = weight bytes + KV cache estimate at the default context + overhead, compared with free VRAM (GPU) or available RAM (CPU), giving fits / tight / won't fit and the reason.
- `scripts/update-catalog.py` refreshes digests and sizes from the registry and fails on missing metadata.
- Accept: unit tests for fit classification at boundaries; a catalog file validates against its schema; the agent proposes the list in the PR and the owner approves it (D4).
- Proposed nine explicit local Ollama tags: qwen3:0.6b, 1.7b, 4b, 8b, 14b, 30b; qwen3-vl:4b; qwen2.5-coder:7b; optional huihui_ai/qwen3-abliterated:8b. Registry manifests, config/license blob sizes and hashes, immutable upstream architecture sources, full artifact byte totals and packaged licenses are checked. Claims/fit estimates never mark inference ready; source Windows aliases are not remapped. `argos catalog` lists the catalog; pack import resolves exact catalog preferences as needing download, not installed. Live downloads/capability tests remain MD4/physical work. See [MODEL-CATALOG.md](MODEL-CATALOG.md).
- Evidence: metadata-only refresh of all nine live registry/upstream sources passed; 107 Windows tests passed (five platform skips); Linux Python/shell and Node CI passed, including installed catalog/license validation ([run](https://github.com/mbolaris/argos-live/actions/runs/37171194148)). Fit boundaries, full-context scaling, vision/MoE accounting, exact preference/quantization matches, duplicate artifact totals, malformed metadata, checksum/size/revision failures and license integrity are covered. No real inference or physical acceptance claimed.

### MD2 Model storage selection — `merged (PR #14)`
Depends on: B1.
- `storage.py`: choose a model directory automatically: owner-configured DATA directory if present and its identity marker matches; otherwise the largest writable non-USB-boot filesystem with enough space; otherwise RAM-backed storage only when available RAM exceeds the selected model's size plus a safety margin. Report the choice, whether it is encrypted, and why.
- Keep the existing identity-marker and fail-closed rules for configured storage (`argos.py load()`).
- Accept: unit tests over fixture mount tables cover each branch and the "no suitable storage" message.
- Read-only `argos storage [--json] --required-gib N` previews existing identity-matched storage, otherwise the largest eligible mounted filesystem, otherwise mounted tmpfs with adequate free capacity and available RAM. The budget adds a 1 GiB safety margin. Missing/mismatched configured storage never falls back; optional persisted filesystem UUID is also checked. Automatic disk selection requires identifying the live boot medium and excludes its entire device ancestry, readonly/ambiguous/bind views, unknown UUIDs and nested-mount mismatches. No directory, marker, model, mount or state changes occur. Preparation and persistence of the selection belong to O1/MD4. Encryption evidence is conservative and does not authorize private profiles on DATA.
- Evidence: 100 Windows tests passed (five platform skips); Linux Python/shell and Node CI passed ([run](https://github.com/mbolaris/argos-live/actions/runs/37170157999)). Fixture tests cover priority, boot siblings, budget boundaries, readonly/access failures, RAM pressure, configured marker/UUID mismatch, encrypted/mixed ancestry, path links, nested/stacked mounts and no suitable storage. Physical selection/creation and downloads remain unverified. See [MODEL-STORAGE.md](MODEL-STORAGE.md).

### MD3 Read-only starter model — `split into MD3a and MD3b`
Depends on: MD2.
- Serve the bundled seed model without copying it: point Ollama at a model directory that combines the read-only image blobs and manifests with writable storage for pulls (for example, a directory whose blobs and manifests are symlinks into the image, plus copy-on-pull), or run a second read-only model path if the pinned Ollama supports one. Verify with the pinned Ollama version.
- Accept: in a VM, chat with the starter model works with no persistence and no copy; pulling another model writes only to the selected storage; `argos verify` still checks hashes.

### MD3a Verified immutable starter service — `done ([PR #33](https://github.com/mbolaris/argos-live/pull/33))`
Depends on: MD2, MD4b.
- Internal owned Ollama context reads the exact reviewed starter directly from
  an unwritable image model tree, with full manifest/blob SHA checks and a private
  temporary process lease outside the source. No model copies or setup changes.
- Accept: fixture integrity/cleanup tests and real pinned unprivileged Linux CPU
  inference; source file inventory and hashes remain unchanged. VM wiring is MD3b.
- Evidence: Windows/Linux fixture/process tests and real checksum-pinned Ollama
  CPU inference on an unwritable seed passed ([run](https://github.com/mbolaris/argos-live/actions/runs/37229233608)).
  This is permission-enforced Linux acceptance; SquashFS/VM wiring remains MD3b.

### MD3b First-boot model-source wiring — `in progress`
Depends on: MD3a, C3a.
- Auto setup selects the bundled read-only source for starter inference and keeps
  the identity-matched writable store for managed pulls. Show both locations in
  the dashboard and include the seed in verification; retain existing owner state.
- Accept: fresh offline VM replies without copying seed weights or persistence;
  new model pulls publish only to selected storage, then model switching works.
- Dashboard projection distinguishes the immutable starter from downloaded models
  without claiming a full hash check or reply. Automatic setup/source switching
  and VM acceptance are separate pending gates.

### MD4 Pull jobs with progress and recovery — `split into MD4a and MD4b`
Depends on: B2, MD2.
- Durable job state for pulls: bytes done/total, recent MiB/s, ETA, pause/cancel/retry, and resume after reboot (Ollama resumes partial blobs). Space check before starting using the manifest size. One active pull at a time. Hash verification and load test as separate visible steps (see MODEL-ONBOARDING.md).
- Accept: unit tests with a fake server simulate progress, interruption, resume, disk-full and corrupt-blob cases.

### MD4a Durable pull-job engine — `done ([PR #16](https://github.com/mbolaris/argos-live/pull/16))`
Depends on: B2, MD1, MD2.
- Internal queue with atomic private state/control files, OS-held single-worker exclusion, validated artifact counters, measured speed/ETA and explicit pause/cancel/retry/stale-state recovery.
- Recheck selected storage identity and pinned catalog revision; budget missing bytes plus safety margin, giving credit only to SHA-verified complete blobs. Reject corrupt blobs without deleting them.
- Requires a caller-owned backend context that stops server-side writes before the lock releases. No production adapter/CLI/autostart yet; successful HTTP pulls end at `downloaded_needs_verification`, never ready.
- Evidence: authored loopback fixture tests cover interrupted streams, explicit resume, controls, lock lifetime, stale-state recovery, space/corruption and identity/progress failures. See [MODEL-PULL-JOBS.md](MODEL-PULL-JOBS.md). Real Ollama resume and physical acceptance remain pending.

### MD4b Owned daemon, integrity and load acceptance — `done ([PR #17](https://github.com/mbolaris/argos-live/pull/17))`
Depends on: MD4a.
- Implement/test the pinned isolated Ollama adapter, shutdown on controls/errors and retry/reboot CLI wiring. Keep one active pull per selected store and preserve the starter service.
- Check registry revision and downloaded manifest/artifact integrity against MD1; show verification and load/test as separate steps before publication. Measure a fixed first reply and unload afterward.
- Accept: fake-server/daemon tests cover cancellation cleanup, changed tags, corrupt post-pull artifacts and failed loading; real pinned Ollama smoke proves partial resume, verification and reply. Physical reboot/download acceptance remains separately required.
- Implementation: Linux-supervised private Ollama listener/version, isolated staging with pruning/cloud disabled, registry/local manifest and full blob SHA checks, fixed 2048-context/32-token reply test, unload/shutdown before atomic blob/manifest publication without replacing existing tags. `argos pull init/create/status/run/pause/cancel/retry` exposes durable JSON progress; explicit stopped-assistant acknowledgement protects load testing. Model assignment, starter config and private profiles stay unchanged. Hard-link support is required and probed before downloading. See [MODEL-PULL-JOBS.md](MODEL-PULL-JOBS.md).
- Evidence: 126 Windows tests passed (seven platform skips); Linux process/shell/Node CI and real checksum-pinned Ollama network smoke passed. The smoke retained seven partial files, resumed qwen3:0.6b, verified its exact pinned manifest/artifacts and generated a CPU reply. Final supervisor-held store-lease/fsync hardening also passed Linux tests and the real smoke ([run](https://github.com/mbolaris/argos-live/actions/runs/37181979824)). Full benchmark, vision/tool capability and physical Live/GPU acceptance remain separate.

## E3 Questionless first boot (M2)

### O1 Try-mode setup — `todo`
Depends on: MD2, MD3.
- New non-interactive `argos setup --auto`: no prompts. Detects persistence, chooses storage via MD2, uses the starter model, writes the same safe OpenClaw config as today (loopback, token, conversation-only tools), and records `mode: try` or `mode: persistent`.
- Keep the interactive path for owners who want explicit choices.
- Accept: unit tests for both modes; existing setup tests still pass; no prompt is printed in auto mode.

### O2 Autostart flow — `todo`
Depends on: O1, W1.
- On desktop login: run auto setup if needed, start Ollama and the OpenClaw gateway in the background, start the dashboard, open Firefox at the tokenized dashboard URL. Single-instance lock. Logs to `~/.local/state/argos-live/`.
- Accept: in a CI or local VM boot (C3), the dashboard responds within a measured time of reaching the desktop; reusing an already-running assistant does not start a second one.

### O3 Offer persistence later — `todo`
Depends on: W2.
- Dashboard banner in try mode explaining what is lost on reboot and linking to documented steps for creating encrypted persistence. No disk writes from the dashboard in this item.
- Accept: banner appears only in try mode; documentation reviewed.

## E4 Dashboard (M2)

### W1 Server skeleton — `done ([PR #20](https://github.com/mbolaris/argos-live/pull/20))`
Depends on: F2.
- Implemented loopback/token-protected server and a read-only capability preview.
  Disposable HTTP fixtures verify static/JSON routes, token/Origin/Host rejection,
  traversal and mutation blocking, token-free logs and listener shutdown. W2/O2
  still own assistant startup, live metrics, browser acceptance and boot wiring.
  See [DASHBOARD.md](DASHBOARD.md).
- `web/server.py` per the dashboard decision; JSON API under `/api/`, static files under `/`, per-session token check, CSRF-safe (token in header for POSTs), loopback-only bind, graceful shutdown.
- Accept: unit tests: missing or wrong token rejected, non-loopback bind refused, static and JSON routes served.

### W2 Home: hardware and status — `done ([PR #21](https://github.com/mbolaris/argos-live/pull/21))`
Depends on: W1, B1.
- Live read-only hardware, storage identity/encryption, persistence, route and
  service probes; measured loaded-model placement and authenticated chat link.
  Default route is not internet proof, health is not ownership or inference proof,
  missing probes remain unknown. Chromium CI uses the locked Playwright package;
  physical Firefox/ISO acceptance remains pending. Startup wiring is O2/W6.
- Hardware card, backend in use, model storage location and encryption status, persistence/try mode, Ollama and gateway health, network status. Button to open chat in OpenClaw.
- Accept: API tests with fixtures; page renders in Firefox ESR without console errors (checked with headless Chromium in CI as a proxy, noted as such).

### W3 Models page — `todo`
Depends on: W2, MD1, MD4.
- Split delivery: W3a is the read-only selected-store/catalog/job projection;
  W3b adds confirmed download/pause/cancel/retry and deletion controls with
  assistant/process/storage safeguards. W3a does not initialize jobs or start
  a daemon; real downloading and mutation acceptance belongs to W3b.
- Installed models and catalog with fit badges, exact sizes, pull progress (bytes, speed, ETA), pause/cancel/retry, delete installed model with confirmation.
- Accept: API tests with the fake server; manual run against a real Ollama documented in the PR.

### W3a Read-only model inventory and progress — `done ([PR #22](https://github.com/mbolaris/argos-live/pull/22))`
Depends on: W1, W2, MD1, MD4.
- Reuse Ollama's manifest layout, reviewed catalog/fit estimator and durable job
  receipts. Show selected-store models, exact sizes, CPU/single-GPU fit estimates,
  and recorded bytes/speed/ETA. Reject stale storage/catalog job identities;
  omit invalid or oversized metadata with a visible review indicator.
- Accept: fixture/API tests separate presence, metadata identity and readiness;
  no writes or service startup. Browser CI renders catalog and inventory states.
  W3b retains full W3 mutation and real-download acceptance.

### W4 Benchmarks page — `split into W4a and W4b`
Depends on: W2, B7.
- Run speed, quick ability or both on a selected model with live progress and cancel; results table; select runs to compare side by side; CSV/JSON download.
- Accept: API tests; manual run against a real Ollama documented in the PR.

### W4a Saved lab results and comparison — `done ([PR #31](https://github.com/mbolaris/argos-live/pull/31))`
Depends on: W2, B6, B7.
- Read-only bounded result cards, select compatible complete runs, comparison,
  authenticated CSV/JSON downloads. Reuse the validated result store and comparison
  rules; no benchmark startup, deletion or profile change. Test API and real browser
  with public scored fixtures; no owner output enters CI.
- Evidence: Windows/Linux API tests and real Chromium comparison/download checks
  passed; physical Firefox acceptance and job controls remain pending.

### W4b Benchmark job controls — `todo`
Depends on: W4a, owned assistant/backend lifecycle.
- Start speed/ability/both with live progress and cancellation, release resources,
  restore prior owned assistant state and test real Ollama. Do not run a competing
  benchmark against an unrelated or active assistant daemon.

### W5 Agents page — `todo`
Depends on: W2, P3.
- Lists agents and their model and permission profile; open chat for an agent; import a personality pack (upload a file, show the P3 preview, apply via P4); create a blank agent from a name and model.
- Accept: API tests with sample packs; nothing is applied without an explicit confirm.

### W6 Retire the tkinter welcome — `todo`
Depends on: O2, W2.
- Remove `runtime/welcome.py`, its tests and `python3-tk` from the package list; move any still-useful checks (persistence detection, gateway readiness, owned-process stop) into the package with tests.
- Accept: no reference to tkinter remains; ISO smoke boot (C3) reaches the dashboard.

## E5 Portable personalities (M3)

### P1 Pack format specification — `done ([PR #8](https://github.com/mbolaris/argos-live/pull/8))`
Depends on: none.
- `docs/PERSONALITY-PACKS.md` specifying `argos-pack/1`: manifest schema, allowed file types (Markdown, plain text, JSON skill definitions), size limits, hashing, forbidden content (credentials, memory/history, permissions, providers, executables, absolute paths), and how a model preference is expressed and resolved against the catalog.
- `runtime/argoslive/packs.py`: manifest validation and archive inspection (reuse the checks in `scripts/inspect-config-bundle.py`: traversal, links, duplicates, CRC, expansion limits, executables).
- Accept: unit tests with valid and invalid fixture packs; no extraction occurs during inspection.
- Evidence: Windows and Linux CI pass valid/invalid generic fixture packs, including integrity/CRC, traversal/links/executables, field/assignment exclusions and bounded expansion. Inspection performs no extraction or activation. Actual owner export/import and OpenClaw activation remain P2–P4 work.

### P2 Exporter from an existing OpenClaw install — `done ([PR #9](https://github.com/mbolaris/argos-live/pull/9))`
Depends on: P1.
- `argos pack export` (cross-platform, runs from a checkout on Windows, WSL or Linux): reads an OpenClaw installation's agent roster, lets the user select agents, copies only allowlisted persona and selected skill files into a pack, records each agent's model reference as a preference, and prints what was excluded and why.
- Supersedes the default use of `scripts/export-personal-config.py` for personality transfer; the older scripts remain for optional full-backup recovery.
- Accept: unit tests over a fixture OpenClaw tree for Windows and Linux path styles; output passes P1 validation; credentials planted in the fixture are never copied.
- Evidence: Windows and Linux CI pass fictional native/custom roster, selected-skill, mounted Windows path mapping, redaction, source preservation, overwrite rejection and CLI fixtures; Linux checks linked-persona rejection. P1 inspection gates archive publication. Actual owner export/import remains unverified; shared/global skill roots are outside this first exporter.

### P3 Verified import, staging and preview — `done ([PR #10](https://github.com/mbolaris/argos-live/pull/10))`
Depends on: P1.
- `argos pack import FILE [--sha256 HASH]`: validates, stages to a fresh directory under the staging location, and prints a preview: agents to add or update, file-level diffs against existing agents, model preference resolution (installed / in catalog / unresolved), skills needing review, and conflicts. Nothing is activated.
- Accept: unit tests for new agents, updates with diffs, ID conflicts and unresolved models; existing staging directories are never overwritten.
- Evidence: Windows/Linux CI pass generic new/update/file-status/conflict, exact model-inventory matching, checksum/source-mutation, retained-stage and CLI fixtures. No active files or permissions change. CLI catalog wiring awaits MD1; actual owner staging and P4 activation/rollback remain unverified.

### P4a Pinned schema and native recovery compatibility gate — `merged (PR #12)`
Depends on: P3.
- Run a disposable three-agent config through the pinned OpenClaw CLI, verify a native backup and restore into fresh staging with byte-identical config/personas. Reject an invalid config. CI uses the exact Node pin and checked-in transitive lock; no owner profiles or inference service.
- This is preparation for P4, not active pack apply or rollback implementation. Record real-runtime CI separately from physical acceptance.
- Evidence: pinned OpenClaw 2026.9.7 and Node 26.10.0 Linux CI passed three-agent schema validation, invalid-policy rejection, verified native backup, and fresh restore with byte-identical config/personas ([runtime run](https://github.com/mbolaris/argos-live/actions/runs/37167980872)). Windows suite: 58 tests, three platform skips; Linux tests passed. No owner profile activation or physical acceptance claimed.

### P4 Apply with rollback — `done ([PR #13](https://github.com/mbolaris/argos-live/pull/13))`
Depends on: P3.
- `argos pack apply STAGE_ID`: snapshots the current OpenClaw config and agent directories, creates or updates each agent with its own workspace and agentDir, writes persona files, assigns the resolved model or leaves the agent visibly pending a model, applies the default conversation-only tool policy, validates with `openclaw config validate`, and rolls back automatically if validation fails. `argos pack rollback SNAPSHOT_ID` restores a snapshot.
- Accept: unit tests with a fake OpenClaw config; a smoke test with the pinned OpenClaw validates a three-agent sample pack, then rolls back and restores the original byte-for-byte.
- Implementation: reviewed archive digest and fresh config/document baseline required; explicit stopped-gateway acknowledgment; verified native backup plus scoped originals; per-file atomic writes; candidate and active schema validation; automatic restoration on failure; rollback refuses later edits or damaged originals. Unmatched models stay pending outside the active roster; inventory CLI is explicit caller-supplied evidence until MD1 integration. Skills require a separate review acknowledgment. Encryption and gateway shutdown remain caller preconditions. Physical persona/model/tool acceptance remains P7/P5.
- Evidence: 77 Windows tests passed (four platform skips) after integrating the merged F2/B1 foundations, including failure restoration, add/update, stale review, edits during backup, rollback drift/corruption and pending models. Pinned OpenClaw 2026.9.7 Linux smoke passed actual three-agent apply/schema validation and byte-exact rollback, with new workspace removal ([runtime run](https://github.com/mbolaris/argos-live/actions/runs/37168658979)). Fictional inventory only; no real inference, effective tool-denial or owner/physical acceptance claim. The installed-package CI fixture imports the activation module; ISO/physical acceptance remain pending.

### P5 Per-agent permission profiles — `todo`
Depends on: P4.
- Named permission profiles (`chat`, `sandbox`, `full`) applied per agent, with `sandbox` confining file tools to the agent workspace and denying network and shell. Widening requires explicit confirmation and is shown on the agent card. Validate tool-policy keys against the pinned OpenClaw.
- Accept: smoke test with the pinned OpenClaw proves denied tools are denied per profile.

### P6 Public sample pack — `todo`
Depends on: P1 (format); installing on first boot also needs P4 and O1.
- One original, generic Argos-like primary assistant (D4) as a pack under `live/config/includes.chroot/usr/local/share/argos-live/packs/`, installed as the default agent on first boot. Its model preference is the bundled starter model. Do not use or paraphrase the owner's private Argos persona.
- Accept: pack passes validation and P4 smoke; content reviewed by the owner in the PR.

### P7 Owner personality acceptance — `todo`
Depends on: P2, P4, MD4, physical hardware. Private; evidence stays out of this repository except a pass/fail summary in STATUS.md.
- Export Argos, Nyx and Proteus with P2 on Toronado's source install, transfer per PROFILE-SYNC.md, import and preview with P3, resolve and download their models from Live, apply with P4, then verify each agent's identity, model, tool policy, conversation and independent state, and recall after a reboot.

## E6 Build, CI and release

### C1 Tests in CI — covered by F1.

### C2 ISO build in GitHub Actions — `done ([PR #28](https://github.com/mbolaris/argos-live/pull/28))`
Depends on: F1.
- Workflow (manual trigger and on tags) that frees runner disk, installs the builder per `scripts/bootstrap-builder.sh`, runs `scripts/lock-runtime.sh` check, fetches the seed model with `scripts/fetch-seed-model.py`, runs `scripts/build.sh`, and uploads the ISO, `SHA256SUMS`, package manifest and build log as workflow artifacts.
- Accept: a green run producing an ISO whose checksum is recorded in the run summary; the build log contains no secrets.
- Implementation: hosted-runner-only wrapper, isolated reviewed Debian keyring,
  nonmutating pinned runtime lock check, verified seed, candidate artifacts and
  checksum/provenance report. Failure logs pass a credential-pattern scan before
  upload. Actual green image build is required before marking done. See [ISO-CI.md](ISO-CI.md).
- Evidence: the clean hosted build produced and verified the ISO, package list,
  checksum/provenance report and scanned logs, then uploaded the 4.07 GB candidate
  artifact ([run](https://github.com/mbolaris/argos-live/actions/runs/37216494685)).
  Unit/shell and real CPU Ollama checks passed. QEMU/physical boot remains C3/H3.

### C3 QEMU smoke boot in CI — `todo`
Depends on: C2.
- Boot the ISO under QEMU without KVM (software emulation, slow but GPU-free), no network, and check over a serial console or forwarded port that the desktop session starts, the dashboard answers with its token, and a speed benchmark of the starter model completes on CPU.
- Accept: green run with captured timings and a screenshot artifact; failures attach the console log.

### C4 Release publishing — `todo`
Depends on: C2, C3.
- On a version tag, upload the accepted ISO to the owner's Google Drive release folder (D1) and create a GitHub release with the Drive link, `SHA256SUMS`, package manifest, notices and release notes per RELEASE-PROCESS.md.
- Drive credentials: a Google service account cannot own files in a personal My Drive, so use either an OAuth refresh token for the owner's account or a shared drive, stored only as a GitHub Actions secret, scoped to the release folder. The owner creates and installs the credential; agents never handle it in chat or logs.
- Document for users that Google Drive shows a "can't scan for viruses" confirmation for large files and may temporarily limit downloads of popular files, and that the GitHub checksum is the authority.
- Accept: a test tag publishes to a test Drive folder and a draft GitHub release; downloaded bytes match `SHA256SUMS`.

### C5 Candidate bump PRs from upstream discovery — `todo`
Depends on: C2.
- Extend `upstream.yml` to open a PR updating `versions.env` and the runtime lock when discovery finds new stable versions, triggering C2 and C3 on that PR. Promotion still requires the release process.
- Accept: dry run on a fork or test branch produces the expected PR diff.

## E7 Hardware and release hardening (M4)

### H1 NVIDIA driver coverage — `todo`
- Implement D3: remove the version pin from `live/config/package-lists/argos.list.chroot` and `NVIDIA_VERSION` from `versions.env` (record the resolved version in the package manifest instead); evaluate whether the suite's backports branch offers a newer supported driver and use it if it builds against the shipped kernel.
- Boot-time check: if the NVIDIA module fails to load or does not support the GPU, show this on the dashboard hardware card and run on CPU. Keep the text-diagnostics boot entry.
- Update SOFTWARE.md and RELEASE-PROCESS.md; a driver change still requires physical GPU acceptance (H3).
- Accept: CI ISO build (C2) succeeds and its manifest shows the resolved driver; C3 CPU smoke boot passes; physical RTX 3090 acceptance recorded before release.

### H2 Dependency audit — `todo`
- Re-run the pinned OpenClaw npm audit (25 findings: 24 high, 1 moderate) against the newest stable candidate; document each remaining finding's exposure given loopback-only binding, or remediate through supported upstream versions.

### H3 Remaining physical checks — `todo`
- Track the open items in PHYSICAL-BOOT-TODO.md (legacy boot, Secure Boot policy, reboot recall, offline chat, process cleanup). Physical hardware only.

## E9 OpenClaw capabilities and addons

Capability contract: [OPENCLAW-ADDONS.md](OPENCLAW-ADDONS.md). These items cover functional dependencies beyond the model lab; the catalog and dashboard must expose their readiness.

### A1 Pinned addon inventory and capability catalog — `in progress ([PR #19](https://github.com/mbolaris/argos-live/pull/19))`
Depends on: F2; candidate inventory can be prepared before runtime wiring.
- Inventory groundwork is merged: PR #19 adds verified published-package metadata, inert
  `argos addons` capability rows, installed-package hash checks and disposable
  snapshot/runtime registration inspection. External engine selection, transitive
  license review, per-agent grants and functional acceptance remain pending;
  package discovery and registration do not establish readiness.
- Inspect the pinned installation's plugin/skill inventory and shipped package contents. Record bundled/external source, exact compatible version/integrity, licenses, Linux dependencies/assets, credentials/network needs and effective tool grants. Treat imported skill metadata as inert data.
- Include Ollama local chat/vision, memory, browser, documents, voice, image generation and optional channels. Choose external addon versions through verified compatibility metadata, not guessed package tags; no separate language-model backend.
- Accept: generic schema/fixtures validate; actual pinned-install inventory distinguishes available, loaded and exercised; missing dependencies have explicit reasons. No private settings or automatic capability grants.

### A2 Ollama model and vision capability acceptance — `todo`
Depends on: A1, B2, MD1, MD4.
- Implement D6: resolve selected model preferences to verified Ollama manifests and capabilities. Exercise native OpenClaw Ollama integration, image input where supported, GPU/offload, capacity failures and unload/restore behavior. Do not install a separate llama-cpp provider/server.
- Accept: actual target chat and supported vision smoke tests; failure retains the starter assistant; exact host/Ollama/model versions recorded. Unsupported or unresolved preferences are visibly pending, with no silent replacement.

### A3 Local memory, browser and document readiness — `todo`
Depends on: A1, P5.
- Configure supported bundled capabilities per agent and their Linux dependencies; use local embeddings when semantic memory is enabled. Show policy/dependency/network status separately.
- Accept: reboot recall, offline memory retrieval, sample document extraction, controlled browser task and denied-tool tests; independent agent state; rollback passes.

### A4 Local voice and image workflows — `todo`
Depends on: A1, B1, MD2, P5.
- Select/pin Linux transcription, speech output and image-generation engines/adapters/assets. Port needed skill dependencies separately. Coordinate GPU-heavy work with model inference and expose progress.
- Accept: supplied audio transcription, audible local speech, controlled image generation and resource recovery on physical hardware; offline boundaries explicit. No cloud requirement for basic chat.

### A5 Capability dashboard and addon update acceptance — `todo`
Depends on: A1 and dashboard E4; feature smoke tests depend on A2–A4.
- Show per-agent addon states, missing dependencies/credentials and activation options. Track compatible stable external addon updates alongside host releases, with exact pins, license/audit checks and rollback.
- Accept: unavailable/disabled/failed providers do not appear ready; controlled invocation proves each claimed capability; candidate host update runs supported-addon regression tests. Optional channel setup never blocks first chat.

## E8 Repository organization

### R1 Separate owner-specific material — `todo`
Depends on: the owner creating the private repository (or Drive folder) and granting the implementing agent access.
- Propose the file list first in the PR description. Candidates: `docs/INVENTORY.md`, `docs/PHYSICAL-BOOT-TODO.md` hardware specifics, `docs/WINDOWS-VM.md`, `docs/OFFLINE-BOOT-REPAIR.md`, the October handoff sections of PROFILE-SYNC.md and STATUS.md, `scripts/*.ps1`, `scripts/plan-boot-repair.py`, `scripts/repair-resume-stages.sh`, and Toronado/Yugo references in generic docs. Generic tools (pack exporter/importer, bundle inspection, staging helpers) stay here.
- Copy to the private repository first and confirm the copy, then remove from this repository in the same PR with short pointers. No history rewrite (D2).
- Accept: README tells the lab story first; all remaining tests pass.

## Suggested parallel tracks

| Track | Sequence |
|---|---|
| Benchmarks | F1 → F2 → B1, B2, B4 (parallel) → B3, B5 → B6 → B7 |
| Personalities | P1 → P2, P3 (parallel) → P4 → P5 |
| Build | F1 → C2 → C3 → C5 |
| Out-of-box lab | (after B1, B2) MD2 → MD3 → O1; W1 → W2 → W3, W4; O2 → W6 |
