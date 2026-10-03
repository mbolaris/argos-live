# Implementation backlog

Updated October 3, 2026. Goals and milestones: [PROJECT-GOALS.md](PROJECT-GOALS.md). Model onboarding design: [MODEL-ONBOARDING.md](MODEL-ONBOARDING.md). Personality transfer rules: [PROFILE-SYNC.md](PROFILE-SYNC.md).

Each item is sized for one agent session and one pull request. Pick an item whose dependencies are done, keep the change to its scope, and meet every acceptance criterion before opening the PR. If an item proves too large, split it in the PR description and update this file.

## Rules for implementing agents

1. **Branch and PR per item.** Title the PR with the item ID, for example `B3: speed benchmark`. Update the item's status in this file in the same PR.
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

## Owner decisions needed

These block the noted items. Agents must not decide them.

| ID | Decision | Blocks |
|---|---|---|
| D1 | Where to host public ISOs. GitHub release assets are limited to 2 GiB per file and the current ISO is about 4.06 GB. Options: slim the ISO, split it, or host it elsewhere. | C4 |
| D2 | Whether this repository is or will be public, and whether owner-specific files are moved to a private repository (history still contains them). | R1 |
| D3 | NVIDIA driver policy. The pinned 550 driver supports the RTX 3090; newer GPUs such as RTX 50-series are believed to need a newer driver. Options: keep 550, use a newer packaged driver, or ship variants. | H1 |
| D4 | Which sample personality packs and starter catalog models ship publicly. | P6, MD1 |
| D5 | Fate of the `bench.py` started on Toronado outside this repository: push it for F3 to reconcile, or discard it. | F3 |

## E0 Foundations

### F1 Make the test suite environment-independent — `todo`
Depends on: none.
- `tests/test_welcome.py` must skip with a clear reason, not error, when `tkinter` is missing.
- Add `.github/workflows/tests.yml` running `bash scripts/check.sh` and the Node upstream tests on `ubuntu-latest` for every push and PR.
- Accept: `scripts/check.sh` passes on a clean Ubuntu runner without `python3-tk`; CI job is green.

### F2 Runtime package skeleton and install path — `todo`
Depends on: F1.
- Create `runtime/argoslive/__init__.py` with a version string, and teach `runtime/argos.py` to import the package from its source checkout or from `/usr/local/lib/argos-live`.
- Update `scripts/build.sh` and `scripts/sync-build-runtime.sh` to install the package directory into the image.
- Accept: `python3 runtime/argos.py --help` works from a checkout; a unit test confirms the import path logic; build scripts pass `bash -n`; the repack path copies the package (checked by reading the script, verified by the next ISO build).

### F3 Reconcile the out-of-repo bench prototype — `blocked (D5)`
Depends on: F2, D5.
- Bring the Toronado prototype in on a branch, then refactor it into the E1 modules or close it with notes on what E1 should reuse.

## E1 Benchmarks (M1)

### B1 Hardware probe — `todo`
Depends on: F2.
- `hw.py` returns CPU model, cores/threads, RAM total/available, GPU list (name, VRAM total/used, driver) from `nvidia-smi --query-gpu ... --format=csv`, AMD/Intel GPUs from `lspci` names only, disks and free space for candidate model directories, kernel, Secure Boot state if readable.
- Missing tools or files produce `null`s, not exceptions.
- Accept: unit tests with recorded fixtures for an NVIDIA desktop, a CPU-only laptop and a no-`nvidia-smi` system; `argos hw --json` prints the snapshot.

### B2 Ollama client — `todo`
Depends on: F2.
- `ollama.py`: version, list, show (parameters, quantization, context length, capabilities), pull with streamed progress callbacks and cancellation, generate/chat with streaming that records time to first token and returns the final timing fields, unload (`keep_alive: 0`), and `ps` (loaded models, VRAM size).
- Base URL configurable; default `http://127.0.0.1:11434`. Clear errors for "not running", "model missing" and HTTP failures.
- Accept: unit tests against a fake HTTP server serving recorded responses, including streaming chunks and an interrupted stream; field names checked against the pinned Ollama version's API documentation.

### B3 Speed benchmark — `todo`
Depends on: B1, B2.
- Implements the speed method above. Generation limit fixed (for example 128 tokens). Thinking disabled. Records whether the model ran on GPU, CPU or split, from `ps`.
- Unloads the model afterwards and restores the previously loaded model if one was loaded.
- Accept: unit tests verify statistics, cold/warm separation, skipped long prompts and `null` handling when timing fields are missing; a smoke run against a real Ollama with `qwen3:0.6b` completes in under 60 seconds on CPU and writes an `argos-bench/1` file.

### B4 Ability datasets and scorers — `todo`
Depends on: F2. Can run in parallel with B1–B3.
- Vendored `quick` and `standard` suites per the dataset rules above, with licence notices added to the image's notices.
- Scorers: numeric answer extraction tolerant of formatting, multiple-choice letter extraction, instruction-following checks (length, format, keywords), JSON schema validation, tool-call shape validation, and code tasks run in a subprocess with timeout, no network, and a temporary directory.
- Accept: every item has a passing reference answer and a failing wrong answer in unit tests; format failures and wrong answers are distinguished; code sandbox enforces timeout and cannot write outside its temporary directory.

### B5 Ability runner — `todo`
Depends on: B2, B4.
- Runs a suite against a model with the ability method above; streams progress (item n of N, elapsed, ETA from measured per-item time); supports cancel; records per-item output, score and latency.
- Accept: unit tests with a fake model producing known right, wrong and malformed answers give exact expected scores; a smoke run of `quick` against `qwen3:0.6b` completes and records results.

### B6 Results store and comparison — `todo`
Depends on: B3 (format), B5.
- `results.py`: save, list, load, delete; comparison table across runs that only ranks runs with the same benchmark kind and suite version; CSV export.
- Accept: unit tests for round trip, schema version rejection, mixed-version comparison refusal and CSV output.

### B7 CLI wiring — `todo`
Depends on: B3, B5, B6.
- `argos bench speed|ability [--suite quick|standard]|all --model TAG [--json]`, `argos bench results [--compare ID...]`, `argos hw`.
- Human-readable summary tables by default; `--json` prints the result file.
- Works without `argos setup` against any reachable Ollama (`--ollama URL`), so it is useful outside the live image.
- Accept: CLI tests with the fake server; documented in README.

## E2 Models and storage

### MD1 Curated catalog — `blocked (D4 for the final list)`
Depends on: B1, B2.
- `runtime/argoslive/data/catalog.json`: 8–12 entries (tag, family, parameter count, quantization, licence, capabilities such as tools/vision/thinking, description, registry manifest digest pinned at catalog update time, total download bytes from the manifest).
- `catalog.py`: fit estimate = weight bytes + KV cache estimate at the default context + overhead, compared with free VRAM (GPU) or available RAM (CPU), giving fits / tight / won't fit and the reason.
- `scripts/update-catalog.py` refreshes digests and sizes from the registry and fails on missing metadata.
- Accept: unit tests for fit classification at boundaries; a catalog file validates against its schema; an agent can propose the list before D4 and the owner approves it.

### MD2 Model storage selection — `todo`
Depends on: B1.
- `storage.py`: choose a model directory automatically: owner-configured DATA directory if present and its identity marker matches; otherwise the largest writable non-USB-boot filesystem with enough space; otherwise RAM-backed storage only when available RAM exceeds the selected model's size plus a safety margin. Report the choice, whether it is encrypted, and why.
- Keep the existing identity-marker and fail-closed rules for configured storage (`argos.py load()`).
- Accept: unit tests over fixture mount tables cover each branch and the "no suitable storage" message.

### MD3 Read-only starter model — `todo`
Depends on: MD2.
- Serve the bundled seed model without copying it: point Ollama at a model directory that combines the read-only image blobs and manifests with writable storage for pulls (for example, a directory whose blobs and manifests are symlinks into the image, plus copy-on-pull), or run a second read-only model path if the pinned Ollama supports one. Verify with the pinned Ollama version.
- Accept: in a VM, chat with the starter model works with no persistence and no copy; pulling another model writes only to the selected storage; `argos verify` still checks hashes.

### MD4 Pull jobs with progress and recovery — `todo`
Depends on: B2, MD2.
- Durable job state for pulls: bytes done/total, recent MiB/s, ETA, pause/cancel/retry, and resume after reboot (Ollama resumes partial blobs). Space check before starting using the manifest size. One active pull at a time. Hash verification and load test as separate visible steps (see MODEL-ONBOARDING.md).
- Accept: unit tests with a fake server simulate progress, interruption, resume, disk-full and corrupt-blob cases.

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

### W1 Server skeleton — `todo`
Depends on: F2.
- `web/server.py` per the dashboard decision; JSON API under `/api/`, static files under `/`, per-session token check, CSRF-safe (token in header for POSTs), loopback-only bind, graceful shutdown.
- Accept: unit tests: missing or wrong token rejected, non-loopback bind refused, static and JSON routes served.

### W2 Home: hardware and status — `todo`
Depends on: W1, B1.
- Hardware card, backend in use, model storage location and encryption status, persistence/try mode, Ollama and gateway health, network status. Button to open chat in OpenClaw.
- Accept: API tests with fixtures; page renders in Firefox ESR without console errors (checked with headless Chromium in CI as a proxy, noted as such).

### W3 Models page — `todo`
Depends on: W2, MD1, MD4.
- Installed models and catalog with fit badges, exact sizes, pull progress (bytes, speed, ETA), pause/cancel/retry, delete installed model with confirmation.
- Accept: API tests with the fake server; manual run against a real Ollama documented in the PR.

### W4 Benchmarks page — `todo`
Depends on: W2, B7.
- Run speed, quick ability or both on a selected model with live progress and cancel; results table; select runs to compare side by side; CSV/JSON download.
- Accept: API tests; manual run against a real Ollama documented in the PR.

### W5 Agents page — `todo`
Depends on: W2, P3.
- Lists agents and their model and permission profile; open chat for an agent; import a personality pack (upload a file, show the P3 preview, apply via P4); create a blank agent from a name and model.
- Accept: API tests with sample packs; nothing is applied without an explicit confirm.

### W6 Retire the tkinter welcome — `todo`
Depends on: O2, W2.
- Remove `runtime/welcome.py`, its tests and `python3-tk` from the package list; move any still-useful checks (persistence detection, gateway readiness, owned-process stop) into the package with tests.
- Accept: no reference to tkinter remains; ISO smoke boot (C3) reaches the dashboard.

## E5 Portable personalities (M3)

### P1 Pack format specification — `todo`
Depends on: none.
- `docs/PERSONALITY-PACKS.md` specifying `argos-pack/1`: manifest schema, allowed file types (Markdown, plain text, JSON skill definitions), size limits, hashing, forbidden content (credentials, memory/history, permissions, providers, executables, absolute paths), and how a model preference is expressed and resolved against the catalog.
- `runtime/argoslive/packs.py`: manifest validation and archive inspection (reuse the checks in `scripts/inspect-config-bundle.py`: traversal, links, duplicates, CRC, expansion limits, executables).
- Accept: unit tests with valid and invalid fixture packs; no extraction occurs during inspection.

### P2 Exporter from an existing OpenClaw install — `todo`
Depends on: P1.
- `argos pack export` (cross-platform, runs from a checkout on Windows, WSL or Linux): reads an OpenClaw installation's agent roster, lets the user select agents, copies only allowlisted persona and selected skill files into a pack, records each agent's model reference as a preference, and prints what was excluded and why.
- Supersedes the default use of `scripts/export-personal-config.py` for personality transfer; the older scripts remain for optional full-backup recovery.
- Accept: unit tests over a fixture OpenClaw tree for Windows and Linux path styles; output passes P1 validation; credentials planted in the fixture are never copied.

### P3 Verified import, staging and preview — `todo`
Depends on: P1.
- `argos pack import FILE [--sha256 HASH]`: validates, stages to a fresh directory under the staging location, and prints a preview: agents to add or update, file-level diffs against existing agents, model preference resolution (installed / in catalog / unresolved), skills needing review, and conflicts. Nothing is activated.
- Accept: unit tests for new agents, updates with diffs, ID conflicts and unresolved models; existing staging directories are never overwritten.

### P4 Apply with rollback — `todo`
Depends on: P3.
- `argos pack apply STAGE_ID`: snapshots the current OpenClaw config and agent directories, creates or updates each agent with its own workspace and agentDir, writes persona files, assigns the resolved model or leaves the agent visibly pending a model, applies the default conversation-only tool policy, validates with `openclaw config validate`, and rolls back automatically if validation fails. `argos pack rollback SNAPSHOT_ID` restores a snapshot.
- Accept: unit tests with a fake OpenClaw config; a smoke test with the pinned OpenClaw validates a three-agent sample pack, then rolls back and restores the original byte-for-byte.

### P5 Per-agent permission profiles — `todo`
Depends on: P4.
- Named permission profiles (`chat`, `sandbox`, `full`) applied per agent, with `sandbox` confining file tools to the agent workspace and denying network and shell. Widening requires explicit confirmation and is shown on the agent card. Validate tool-policy keys against the pinned OpenClaw.
- Accept: smoke test with the pinned OpenClaw proves denied tools are denied per profile.

### P6 Public sample packs — `blocked (D4)`
Depends on: P1.
- Two or three original sample agents (for example a helpful generalist, a terse coding assistant and a playful storyteller) as packs under `live/config/includes.chroot/usr/local/share/argos-live/packs/`, installed on first boot.
- Accept: packs pass validation and P4 smoke; content reviewed by the owner.

### P7 Owner personality acceptance — `todo`
Depends on: P2, P4, MD4, physical hardware. Private; evidence stays out of this repository except a pass/fail summary in STATUS.md.
- Export Argos, Nyx and Proteus with P2 on Toronado's source install, transfer per PROFILE-SYNC.md, import and preview with P3, resolve and download their models from Live, apply with P4, then verify each agent's identity, model, tool policy, conversation and independent state, and recall after a reboot.

## E6 Build, CI and release

### C1 Tests in CI — covered by F1.

### C2 ISO build in GitHub Actions — `todo`
Depends on: F1.
- Workflow (manual trigger and on tags) that frees runner disk, installs the builder per `scripts/bootstrap-builder.sh`, runs `scripts/lock-runtime.sh` check, fetches the seed model with `scripts/fetch-seed-model.py`, runs `scripts/build.sh`, and uploads the ISO, `SHA256SUMS`, package manifest and build log as workflow artifacts.
- Accept: a green run producing an ISO whose checksum is recorded in the run summary; the build log contains no secrets.

### C3 QEMU smoke boot in CI — `todo`
Depends on: C2.
- Boot the ISO under QEMU without KVM (software emulation, slow but GPU-free), no network, and check over a serial console or forwarded port that the desktop session starts, the dashboard answers with its token, and a speed benchmark of the starter model completes on CPU.
- Accept: green run with captured timings and a screenshot artifact; failures attach the console log.

### C4 Release publishing — `blocked (D1)`
Depends on: C2, C3, D1.
- On a version tag, publish the accepted ISO, checksums, package manifest, notices and release notes per RELEASE-PROCESS.md.

### C5 Candidate bump PRs from upstream discovery — `todo`
Depends on: C2.
- Extend `upstream.yml` to open a PR updating `versions.env` and the runtime lock when discovery finds new stable versions, triggering C2 and C3 on that PR. Promotion still requires the release process.
- Accept: dry run on a fork or test branch produces the expected PR diff.

## E7 Hardware and release hardening (M4)

### H1 NVIDIA driver coverage — `blocked (D3)`
- Implement the chosen driver policy; document supported GPU generations; keep the CPU path working.

### H2 Dependency audit — `todo`
- Re-run the pinned OpenClaw npm audit (25 findings: 24 high, 1 moderate) against the newest stable candidate; document each remaining finding's exposure given loopback-only binding, or remediate through supported upstream versions.

### H3 Remaining physical checks — `todo`
- Track the open items in PHYSICAL-BOOT-TODO.md (legacy boot, Secure Boot policy, reboot recall, offline chat, process cleanup). Physical hardware only.

## E8 Repository organization

### R1 Separate owner-specific material — `blocked (D2)`
- Move owner-specific inventories, handoffs and Windows/USB procedures (for example `docs/INVENTORY.md`, the October handoff sections of PROFILE-SYNC.md, `scripts/*.ps1`, `scripts/plan-boot-repair.py`, `scripts/repair-resume-stages.sh`) to the location chosen in D2, leaving generic tooling and a short pointer. Do not delete anything without the owner's approval.
- Accept: README tells the lab story first; all remaining tests pass.

## Suggested parallel tracks

| Track | Sequence |
|---|---|
| Benchmarks | F1 → F2 → B1, B2, B4 (parallel) → B3, B5 → B6 → B7 |
| Personalities | P1 → P2, P3 (parallel) → P4 → P5 |
| Build | F1 → C2 → C3 → C5 |
| Out-of-box lab | (after B1, B2) MD2 → MD3 → O1; W1 → W2 → W3, W4; O2 → W6 |
