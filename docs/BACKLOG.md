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

### U6 — One complete play session before another image

Agreed October 8, 2026. [PLAY-SESSION.md](PLAY-SESSION.md) is the experience release
target: Challenge → Watch → Debrief → Try one change → Retest → Keep/Restore →
Validate → Use. J6b/J7/J8 complete the inexpensive Lab loop; J3 adds the guided
storage/model route. SI1/SI2 remain later validated-agent-proposal work. Keep one
recommended next action, one skill map, and task-scoped evidence. No prototype
scores or simulated qualification may enter the released app. A benchmark pass
does not establish that a new user understands how to play; record that review.

### S6 — Model storage on systemd automounts — `done` ([PR #65](https://github.com/mbolaris/argos-live/pull/65))

- Resolve a mounted filesystem above its direct autofs parent using mountinfo
  identities. Keep unrelated or multiple filesystem stacks blocked, and retain
  UUID, boot-device, read-only, capacity and explicit write-check protections.
- Unit coverage checks the normal automount pair, read-only child and unrelated
  stacks. Physical DATA selection and write-check acceptance remain separate.
- The guided storage/model upgrade journey and clearer explanations remain J3;
  this fix restores eligibility without mounting, formatting or adopting data.

### U5 — Shared foundations before specialization

Agreed October 8, 2026. [Shared foundations](FOUNDATION-CURRICULUM.md) defines the
common early ladder: following directions, reading, numbers, reasoning/planning,
actual sandboxed tools and integrated useful missions. "K–12" is a progression
metaphor, not a grade equivalence, intelligence score or AGI claim. Do not ask new
owners to select a profession or design a curriculum. Lead with one recommended
mission and one Start action; specialization follows demonstrated foundations.

The goal is owner-controlled system improvement: the AI interprets evidence,
proposes a concrete experiment, executes only the approved bounded plan, and
reports tradeoffs for Keep/Restore. Fixed scoring, independent validation,
permission boundaries and reversible staging remain mandatory. The current
debrief is an opinion, not an executable plan. J5/J6a/J6b/J7 remain the immediate
document-loop implementation sequence; J3/J4/P8 keep their existing scope.

### SI1 — Evidence-grounded improvement proposal — `todo`

Depends on J6a, J6b and J7. Turn the optional debrief into one recommended
experiment using a fixed schema and an allowlist of implemented interventions.
Show hypothesis, evidence references, candidate recipe, matched tests, cost,
limits and rollback before approval. Validate independently of the model; reject
unknown interventions, answer references, permissions, private inputs and
unsupported claims. Opinion failure leaves scores and manual actions usable.
Accept: valid/invalid proposal fixtures, evidence/model/recipe binding, safe
rendering, no execution without approval and an obvious default next action.

### SI2 — Execute an approved bounded experiment plan — `todo`

Depends on SI1 and J7. Owner approval binds exact candidates, trial conditions and
resource limits; execution occurs under existing workload ownership in reversible
Lab staging. No approval bypass, duplicate runs or permission expansion. Retain
live progress, cancellation and reload, and report observed deltas separately
from confirmed improvement. Keep/Restore remains Lab-only unless separate agent
promotion is implemented and accepted. Accept: approval mismatch/expiry,
budget/cancellation/failure cleanup, evidence retention and selected-recipe restore.

### SI3 — Independent validation for a shared foundation rung — `todo`

Depends on J7; integrate SI2 when available. Start with document reading rather
than building all rungs at once. Define versioned original held-out tasks and
fixed criteria, with answers and detailed validation feedback inaccessible to
the proposing/tuning model. Record repeated-measurement uncertainty and an owner
useful-task verdict separately. Accept: inaccessible validation inputs, tuning
vs validation separation, no qualification from partial runs or mismatched
recipes, and no broader claims from a small unconfirmed score difference.
Later tool rungs depend on J4; specialization remains future work after shared
foundations, not a first-run question.

### U4 — A visible mission ladder and a local-model debrief

Status: in progress ([PR #55](https://github.com/mbolaris/argos-live/pull/55)). Lead with a selected-file-bound trial receipt: solved
exercises, repeated output speed, first-token wait, category bars and a factual
next practice area. Show the existing four document-build checks as numbered
rungs. No global intelligence rank, XP, inferred GPU use or score inflation.
Offer previewable original expedition, repair and missing-information briefs.
These demonstrations use the existing pasted-document runner and owner verdict;
they are not new scored suites or proof of tool use.

After baseline/document scoring, ask the selected local model for a brief opinion
under the existing owned Lab lease, cancellation and total workload budget. Only
aggregate public measurements enter the prompt; no personal documents, profile,
paths or tool permissions. Keep this opinion in memory, identify its exact trial
runs/model files, render as text, and never use it as qualification evidence.
An unavailable opinion does not invalidate completed scores. The opinion request
uses at most 180 output tokens and a 45-second read timeout. Personal OpenClaw
profile integration and model-chosen executable next actions remain future work.

Acceptance: selected identity regressions, median/count receipt correctness,
private-input exclusion, opinion failure/cancellation/timeout cleanup, actual
Chromium journey with readable scores, safe opinion rendering, previews and
390px layout. Linux checks required before promotion. Shipped Firefox, a real
model debrief, ISO and physical USB experience remain separate acceptance.

### U3 — Target the shipped Firefox trial control reliably

Status: in progress ([PR #54](https://github.com/mbolaris/argos-live/pull/54)). Navigate through Firefox's location
bar to the authenticated Lab button fragment, then focus and activate the button
with ordinary keyboard input. Do not infer success from input delivery: retain
the active-job, saved speed/ability results and assistant-resumption checks.

Acceptance: wrong-window refusal and modifier cleanup regression checks, followed
by an actual offline WHPX run of ISO build 37576377593. The trial completed and
the reviewed shipped Firefox screenshot showed both saved results. Hosted TCG
run 37580789500 failed earlier with an HTTP error; that remains a separate,
unresolved result. Browser chat replies, firmware, physical GPU and persistence
acceptance remain separate. No runtime, ISO contents or deadlines changed.

### U2 — Start with a trial and show the build path

Status: in progress ([PR #53](https://github.com/mbolaris/argos-live/pull/53)). A fresh configured build should offer its first local
baseline before choosing storage for future downloads. The download gate remains
unchanged. Re-run the baseline when selected model files change. Show the
short-document path (measure, qualify, owner task, matched candidate) with states
derived from selected-file-bound evidence. Failed criteria mean needs work;
comparison availability never means an improvement or an intelligence rank.
Temporary model stores do not recommend a reboot-retention check.

Acceptance: first baseline before storage confirmation in the real dashboard
browser journey, deliberate storage/download gate still tested, unknown/different
model identities inherit no progress, mismatched candidate trials inherit no
comparison stage, and temporary-store guidance. Shipped Firefox, image and
physical experience acceptance remain separate.

### U1 — Mission Control as the primary workspace

Status: in progress ([PR #52](https://github.com/mbolaris/argos-live/pull/52)). Keep the managed dashboard visible after startup; open chat
only on its named owner action. Lead with one recommended mission, a robot
schematic, selected-file-bound speed and task evidence. Mission trial buttons
start the named trial with the chat pause explicit. Make the catalog visible,
hide idle cancellation controls, and combine identical complete starter entries
only when tag and manifest digest match. Routine moments remain compact.

Acceptance: backend identity regression tests, browser journey (direct mission
launch and catalog visibility), native startup checks, and exact-image shipped
Firefox review. Physical boot and owner usability review remain separate.
The current local review uses fixture Chromium, not deployed Firefox. Subsequent
work must give the companion a reviewed read-only evidence report and connect
recommendations to the owner's chosen useful mission; rule-based UI advice does
not establish that the conversational agent understands its current capability.

### G1 — Fresh guest boot (implementation candidate)

User-requested October 6: new default media plus a no-passphrase guest mode.
Adds explicit nonpersistent guest and basic-graphics entries; the default is
guest. Argos uses RAM, refuses disk stores/retention checks, and labels the
session lifetime. Personal encrypted entries remain available. See
`GUEST-MODE.md` for fresh-media procedure and acceptance boundaries. Status:
in progress; ISO, reboot-reset and physical acceptance still required.

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

### O1 Try-mode setup — `done ([PR #35](https://github.com/mbolaris/argos-live/pull/35))`
Depends on: MD2, MD3.
- New non-interactive `argos setup --auto`: no prompts. Detects persistence, chooses storage via MD2, uses the starter model, writes the same safe OpenClaw config as today (loopback, token, conversation-only tools), and records `mode: try` or `mode: persistent`.
- Keep the interactive path for owners who want explicit choices.
- Accept: unit tests for both modes; existing setup tests still pass; no prompt is printed in auto mode.
- Implementation: explicit `argos setup --auto` creates private conversation-only
  configuration and an identity-marked planned model store, uses the bundled
  image source, records settings persistence and model-storage encryption
  separately, and never replaces existing owner configuration. No service starts.
  Native pinned schema, Linux filesystem and no-copy VM acceptance passed.
  [Run 37233824509](https://github.com/mbolaris/argos-live/actions/runs/37233824509)
  used questionless setup on the fresh O1 ISO, confirmed a try session with
  immutable SquashFS starter inference and no weight copies, exercised the
  native Firefox dashboard and saved three CPU benchmark runs. OpenClaw first
  conversation, automatic desktop startup and physical persistence remain separate.

### O2 Autostart flow — `in progress`
Depends on: O1, W1.
- On desktop login: run auto setup if needed, start Ollama and the OpenClaw gateway in the background, start the dashboard, open Firefox at the tokenized dashboard URL. Single-instance lock. Logs to `~/.local/state/argos-live/`.
- Accept: in a CI or local VM boot (C3), the dashboard responds within a measured time of reaching the desktop; reusing an already-running assistant does not start a second one.

### O2a Owned backend at the native provider endpoint — `done ([PR #36](https://github.com/mbolaris/argos-live/pull/36))`
Depends on: MD4b.
- Allow the Linux supervisor to reserve an explicit loopback port and requested
  context for first-chat integration. Keep exact-version/PID-port checks, store
  exclusion and parent-death cleanup. An unrelated listener is never adopted.
- Existing onboarding keeps ephemeral ports and 2048-token context. This internal
  API does not change OpenClaw configuration or enable automatic desktop startup.
- Accept: real Linux process tests for busy/fixed ports, context environment,
  invalid options and cleanup; pinned Ollama regression smoke.
- Evidence: real Linux process tests and checksum-pinned Ollama CPU onboarding,
  fixed native endpoint, benchmarks and immutable-starter regression passed
  ([run](https://github.com/mbolaris/argos-live/actions/runs/37232807741)).

### O2b Owned native gateway and private startup diagnostics — `done ([PR #40](https://github.com/mbolaris/argos-live/pull/40))`
Depends on: O1, O2a.
- Reserve the reviewed local/token gateway endpoint; never adopt or kill an
  unrelated listener. Verify the pinned host version and require the listening
  PID to belong to the launched Node process group before reporting readiness.
- Reuse Linux parent-death supervision and supervisor-held exclusion until the
  whole launcher/gateway group stops. Private owner-only logs retain diagnostics;
  configuration, tokens and tool permissions are not changed.
- Accept: real Linux tests cover launcher child ownership, busy ports, version
  mismatch, safe executable symlinks, linked log refusal and parent-death cleanup.
  Native pinned gateway must pass authenticated health, UI document, competing
  launch refusal and listener shutdown. This is not model-reply or browser-chat
  acceptance; automatic dashboard login wiring remains O2.
- Evidence: Linux process tests and native OpenClaw 2026.9.8 gateway health/UI/
  shutdown passed [37236247571](https://github.com/mbolaris/argos-live/actions/runs/37236247571).
  Ollama 0.35.1 supervisor regression also passed the real CPU onboarding and
  immutable starter checks [37236247586](https://github.com/mbolaris/argos-live/actions/runs/37236247586).

### O2c Managed desktop progress and conversation handoff — `in progress`
Depends on: O1, O2a, O2b, W2.
- `argos desktop` starts the loopback dashboard immediately, performs questionless
  setup and full selected-model verification, warms up with a bounded local reply,
  then starts the owned gateway. Show measured first-token/generation metrics and
  startup stages; claim automatic chat handoff once per started assistant.
- Authenticated same-origin empty POSTs control only the owned start/stop job.
  Repeated starts reuse one worker. Reopening checks a private descriptor's process
  start identity, owned listening port and authenticated startup API; no unrelated
  service is adopted. Changed or unsupported owner policies remain untouched and
  require review rather than silently narrowed or widened.
- New desktop login uses this launcher instead of the tkinter welcome. Legacy
  welcome code is retained during acceptance; full retirement remains W6.
- Accept: lifecycle/authentication/owner-preservation fixtures, browser controls
  and actual pinned hosted startup, model warmup, session reuse and stop. Fresh ISO
  automatic Firefox/chat acceptance and firmware boot remain C3b before promotion.
- Evidence: [37238664640](https://github.com/mbolaris/argos-live/actions/runs/37238664640)
  passed real OpenClaw 2026.9.8/Ollama 0.35.1 CPU reply, managed setup/warmup,
  gateway start, verified reopen, repeated-start reuse, once-only handoff and
  clean stop with configuration/immutable weights unchanged. Hosted warmup was
  65.62 generation tokens/s and 1.744 seconds to first token; this is not
  Toronado performance or browser conversation acceptance.

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

### W3b Guided acquisition controls � `in progress`
Depends on: W3a, MD2, owned desktop workload lifecycle.
- Candidate: catalog review/confirm, byte/rate/ETA progress, durable pause/cancel,
  explicit retry, exact verification and local reply before publication. The
  owned assistant is paused, benchmarks excluded and prior startup requested.
  Active model/configuration/permissions remain unchanged. Native acquisition passed in PR45;
  ISO and physical control acceptance pending; deletion and model activation
  remain separate. See [GUIDED-DOWNLOADS.md](GUIDED-DOWNLOADS.md).

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
- Candidate: guided configured-model quick baseline pauses the managed assistant, runs short speed plus quick ability in an owned service, saves results, supports cancellation and requests prior assistant restart. Local lifecycle/browser and native Linux job/results/assistant-resume checks passed in PR44. ISO/physical job acceptance and broader model/suite selection remain pending. See [GUIDED-MODEL-LAB.md](GUIDED-MODEL-LAB.md).

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

### P8a Meet your AI: name and reviewed personality editor — `todo`
Depends on: P4, current Mission Control. Design: [Identity and personality](PERSONAL-ROBOT-EXPERIENCE.md#identity-and-personality-meet-your-ai).
- Use “your AI” in generic journey copy, including “How far can your AI go?” Keep Argos Live as the product name; use the selected agent's display name for its own card and voice. Never rename internal agent IDs, paths or conversation keys when editing a display name.
- Add a quiet “Meet your AI” entry beside the active agent identity and in settings, with a dismissible first-session invitation. Do not interrupt the recommended mission or require setup before chat/testing.
- Edit display name, optional original style presets and bounded owner instructions. Show the current identity and a plain-language summary; preview a fixed public conversation before explicit Save. Preserve unsaved drafts and show cancel/restore paths.
- Reuse reviewed profile staging/validation/rollback patterns; check pinned OpenClaw's supported identity/persona fields first. Apply only the selected agent's reviewed files, preserve unrelated owner edits and history, refuse stale previews, and coordinate with owned startup/workload reservations. Do not grant tools, change providers/models or import skills as a personality side effect.
- Accept: native pinned OpenClaw chat reflects the saved identity/persona; invalid, cancelled and failed saves leave prior files unchanged; rollback preserves intervening edits or refuses safely. Test names containing markup, bounds, concurrent edits and guest/persistent mode messaging. Fixture UI alone is not effective-persona acceptance. No USB rewrite needed for supported profile edits.

### P8b Personality-aware debrief and profile recovery evidence — `todo`
Depends on: P8a, mission_report and a reviewed isolated persona-preview path.
- Use the selected reviewed persona in optional trial debriefs only through an explicitly tool-disabled, bounded local path; do not silently load credentials, history, tools or arbitrary workspace files. Record which persona revision produced an opinion and hide stale opinions after identity changes.
- Keep code-scored trials persona-independent and comparable. Label opinion separately; personality cannot qualify a model, alter criteria or claim learning. If persona isolation cannot be verified, retain the generic debrief and state that limitation.
- Accept: same fixed public preview before/after; actual local-model debrief demonstrates the reviewed style without changing scores or permissions. Verify guest reset on a second boot and encrypted profile recovery separately from conversation recovery; report each independently.

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

### C3 QEMU smoke boot in CI — `split into C3a and C3b`
Depends on: C2.
- Boot the ISO under QEMU without KVM (software emulation, slow but GPU-free), no network, and check over a serial console or forwarded port that the desktop session starts, the dashboard answers with its token, and a speed benchmark of the starter model completes on CPU.
- Accept: green run with captured timings and a screenshot artifact; failures attach the console log.

### C3a Offline desktop and CPU guest acceptance — `done ([PR #30](https://github.com/mbolaris/argos-live/pull/30))`
Depends on: C2.
- Reuse an existing candidate, verify its exact SHA256, extract its original desktop
  kernel/initrd and append a test-only serial console at VM launch. TCG, no NIC,
  no host disks, no writable ISO, no KVM. Serial login uses factory test credentials.
- In a fresh guest, check XFCE, setup, authenticated dashboard APIs, native Firefox
  DOM and real CPU starter speed/result round trip. Record timings, screenshot
  and console on failure. This does not verify firmware/menu boot or O2.
- Evidence: [run 37233824509](https://github.com/mbolaris/argos-live/actions/runs/37233824509)
  passed on the O1 ISO with questionless setup, immutable SquashFS starter
  inference, no copied weights and three eight-token CPU benchmark runs. The
  1280 × 800 native Firefox dashboard capture was visually reviewed. Timings
  start at the guest test stage and are not hardware boot/performance scores.
  Services are test-started; native OpenClaw conversation remains separate.

### C3b Firmware boot and automatic dashboard acceptance — `in progress (automatic startup; firmware pending)`
Depends on: C3a, O2.
- Boot unchanged ISO through UEFI/GRUB, reach the automatic dashboard, measure
  first-boot readiness and a native chat reply, and verify startup reuse. Keep
  physical acceptance separate; do not start setup/services from the test harness.
- Candidate managed mode in [PR #41](https://github.com/mbolaris/argos-live/pull/41)
  observes shipped autostart, real warmup and Firefox gateway connection using
  direct-kernel boot. It does not establish firmware boot or a browser-submitted
  reply. Require the actual run and visual review before recording any acceptance.

### C4 Release publishing — `todo`
Depends on: C2, C3.
- On a version tag, upload the accepted ISO to the owner's Google Drive release folder (D1) and create a GitHub release with the Drive link, `SHA256SUMS`, package manifest, notices and release notes per RELEASE-PROCESS.md.
- Drive credentials: a Google service account cannot own files in a personal My Drive, so use either an OAuth refresh token for the owner's account or a shared drive, stored only as a GitHub Actions secret, scoped to the release folder. The owner creates and installs the credential; agents never handle it in chat or logs.
- Document for users that Google Drive shows a "can't scan for viruses" confirmation for large files and may temporarily limit downloads of popular files, and that the GitHub checksum is the authority.
- Accept: a test tag publishes to a test Drive folder and a draft GitHub release; downloaded bytes match `SHA256SUMS`.

### C5 Candidate bump PRs from upstream discovery — `split into C5a and C5b`
Depends on: C2.
- Extend `upstream.yml` to open a PR updating `versions.env` and the runtime lock when discovery finds new stable versions, triggering C2 and C3 on that PR. Promotion still requires the release process.
- Accept: dry run on a fork or test branch produces the expected PR diff.

### C5a Verified candidate preparation — `done ([PR #37](https://github.com/mbolaris/argos-live/pull/37))`
Depends on: C2.
- Prepare stable public runtime pins in a fresh artifact without changing accepted
  files. Reject stale reports, downgrades, Node major changes, checksum drift and
  unrelated Debian/driver changes. Regenerate the lock with pinned Node and inert
  addon metadata from the SHA512-verified host package; attach npm audit findings.
- Accept: unit fixtures preserve accepted bytes and a hosted dry run produces the
  candidate artifact. See [RUNTIME-CANDIDATES.md](RUNTIME-CANDIDATES.md).
- Evidence: fixture and Linux checks passed; hosted pinned-Node generation
  produced verified OpenClaw 2026.9.8/Ollama 0.35.1 candidate files, refreshed addon
  inventory, audit, exact provenance and per-file checksums
  ([run](https://github.com/mbolaris/argos-live/actions/runs/37233645763)).
  Accepted runtime pins were unchanged; candidate promotion remains pending.

### C5b Automatic reviewed candidate PR — `todo`
Depends on: C5a.
- Open a candidate PR from the verified artifact, synchronize runtime test pins,
  trigger all compatibility/onboarding/ISO/VM gates and attach audit/exposure
  review. No automatic release, installed update or owner-profile migration.
- Accept: a tested candidate PR with exact provenance, artifacts and rollback.

## E7 Hardware and release hardening (M4)

### H1 NVIDIA driver coverage — `todo`
- Implement D3: remove the version pin from `live/config/package-lists/argos.list.chroot` and `NVIDIA_VERSION` from `versions.env` (record the resolved version in the package manifest instead); evaluate whether the suite's backports branch offers a newer supported driver and use it if it builds against the shipped kernel.
- Boot-time check: if the NVIDIA module fails to load or does not support the GPU, show this on the dashboard hardware card and run on CPU. Keep the text-diagnostics boot entry.
- Update SOFTWARE.md and RELEASE-PROCESS.md; a driver change still requires physical GPU acceptance (H3).
- Accept: CI ISO build (C2) succeeds and its manifest shows the resolved driver; C3 CPU smoke boot passes; physical RTX 3090 acceptance recorded before release.

### H2 Dependency audit — `in progress`
- Re-run the pinned OpenClaw npm audit (25 findings: 24 high, 1 moderate) against the newest stable candidate; document each remaining finding's exposure given loopback-only binding, or remediate through supported upstream versions.
- The October 4 candidate report has four vulnerable packages (three high, one
  moderate), all under npm's dependency subtree. Paths and exposure questions are
  recorded in [RUNTIME-AUDIT-20261004.md](RUNTIME-AUDIT-20261004.md). Supported fixes
  and effective invocation/policy acceptance remain open; no clean audit claimed.

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

### A2 Ollama model and vision capability acceptance — `split into A2a and A2b`
Depends on: A1, B2, MD1, MD4.
- Implement D6: resolve selected model preferences to verified Ollama manifests and capabilities. Exercise native OpenClaw Ollama integration, image input where supported, GPU/offload, capacity failures and unload/restore behavior. Do not install a separate llama-cpp provider/server.
- Accept: actual target chat and supported vision smoke tests; failure retains the starter assistant; exact host/Ollama/model versions recorded. Unsupported or unresolved preferences are visibly pending, with no silent replacement.

### A2a Native OpenClaw CPU starter conversation — `done ([PR #39](https://github.com/mbolaris/argos-live/pull/39))`
- A checksum-pinned disposable hosted fixture uses the same fresh conversation
  configuration as questionless setup and the native bundled Ollama provider.
  Native `agent --local` must return nonempty text with the exact provider/model,
  and real Ollama placement must establish CPU execution. No owner credentials
  or profile overrides are inherited; weights remain read-only and unchanged.
- The report contains versions, reply byte count, elapsed time and explicit scope,
  not prompts, replies, tokens or raw configuration. The 32-token fixture budget
  does not change the normal assistant budget. Downloads need networking; this
  hosted check is not no-NIC offline acceptance.
- Evidence: [37236087392](https://github.com/mbolaris/argos-live/actions/runs/37236087392)
  passed native OpenClaw 2026.9.8/Ollama 0.35.1 CPU chat without seed copies.
  The prior 2026.9.7/0.35.0 pair also passed. Gateway UI, effective
  tool denial, model switching, vision/GPU and physical acceptance remain pending.

### A2b Model switching, vision and capacity recovery — `todo`
Depends on: A2a, MD3b, P5.
- Exercise verified downloaded model selection through native OpenClaw, supplied
  image input on a supported vision model, unload/restore and failed-load recovery.
  Record actual GPU placement and capacity errors on physical hardware. No silent
  model substitution or separate language-model backend.

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

## E9 Hardware-aware assistant personality — future work

Design: [HARDWARE-AWARE-ASSISTANT.md](HARDWARE-AWARE-ASSISTANT.md).
These requirements are recorded; no implementation or physical acceptance is claimed.

### HA1 Verified self-state and first greeting — `todo`
Depends on: B1, O2, A1.
- Give each agent bounded, timestamped context for CPU, total/available RAM,
  GPU/VRAM, actual model placement, model/context, storage, configuration health,
  known bugs and safe OpenClaw doctor summaries. Prefer supported OpenClaw
  mechanisms/addons; do not grant shell access just to read these facts.
- First conversation includes a short hardware opinion. "How do you feel?"
  refreshes available evidence and explains limitations or satisfaction in the
  agent's voice. Missing/stale probes remain explicitly unknown.
- Accept: real native chat uses current context; fixture coverage for powerful,
  CPU-only, low-memory, missing-GPU, broken-driver and failed/stale diagnostics;
  no owner persona overwrite or secret/raw-doctor output in public context.

### HA2 Thermal awareness and useful seasonal compute — `todo`
Depends on: HA1, B1, owned job lifecycle.
- Observe supported temperature, power and throttling signals separately from
  optional owner-provided or measured ambient conditions. On hot days recommend
  lighter work or cooling. On cold days offer concrete useful queued compute
  within owner-selected power, temperature, noise and time budgets.
- Accept: missing sensors, hot/cold conditions, throttling, cancellation and
  thermal limits tested; no fabricated ambient temperature or generic unsafe
  threshold. No meaningless load, sustained stress test or heater claim.
  Unattended compute requires an explicit owner policy and stops at its limits.

### HA3 Resource proposals and expanding usefulness — `todo`
Depends on: HA1, HA2, capability/permission dashboard.
- Proactively suggest useful tasks, models, compatible addons and improvements.
  Explain each proposed extra RAM/VRAM/compute/storage/hardware permission using
  an observed bottleneck, expected benefit, alternatives, cost and uncertainty.
- Accept: proposals reflect evidence, preserve local/offline options, respect
  declines and do not repeatedly nag. No automatic purchase, cloud spending,
  download, permission widening, driver change or workload outside owner policy.

### HA4 Task-specific competence and confidence — `todo`
Depends on: B4–B7, HA1.
- Summarize measured ability by task with suite/model/version/settings/coverage,
  weaknesses and confidence. Optional kindergarten/high-school/PhD/professor
  language is a qualified analogy for the tested task, not a global credential,
  human IQ or claim that one small suite establishes research competence.
- Accept: unseen domains and absent evidence remain unassessed; compare only
  compatible runs; distinguish hardware speed from accuracy and tools/access.
  Reassess after model/config changes and surface actual failures.

### HA5 Personal-AI cultivation experience — `todo`
Depends on: HA1–HA4, model onboarding, capability dashboard and profile persistence.
- Add a playful companionship/growth loop: useful goal, reviewed hardware or
  optional online compute/model/software/addon change, measured outcome and a
  milestone celebration. Preserve persona/history across model changes/reboots.
- Show competence, capabilities, responsiveness, headroom and health separately.
  Online compute includes visible provider/data destination, permissions and
  cost/time budgets; private credentials stay private. Keep local/offline paths.
- Accept: verified gains and regressions appear honestly; compatible before/after
  results and rollback work; denied/offline/budget-exhausted upgrades remain usable.
  No invented intelligence/happiness score, artificial decay or spending rewards.
  Respect declined requests; improvements serve owner-selected useful tasks.

## Suggested parallel tracks

| Track | Sequence |
|---|---|
| Benchmarks | F1 → F2 → B1, B2, B4 (parallel) → B3, B5 → B6 → B7 |
| Personalities | P1 → P2, P3 (parallel) → P4 → P5 |
| Build | F1 → C2 → C3 → C5 |
| Out-of-box lab | (after B1, B2) MD2 → MD3 → O1; W1 → W2 → W3, W4; O2 → W6 |


### W3c Reviewed model selection and upgrade guidance — in progress
- Candidate: single-agent model switching with full artifact verification, private durable recovery journal, exact configuration rollback, owner-edit preservation and startup validation. Hardware guidance uses measured RAM/VRAM at 32K context; no quality claim.
- Local transaction/browser checks pass; native pinned starter reselection and OpenClaw reply, fresh ISO and physical upgrade acceptance pending. See [GUIDED-MODEL-SELECTION.md](GUIDED-MODEL-SELECTION.md).

## E10 Guided journey (personal robot experience)

October 8 implementation direction: [Mission 1: Read this brief](PROVING-GROUND-MISSION-1.md).
J1/J2 implementations are already merged; extend them. Current order is
J5 → J6a → J6b → J7 → J3 → J8. J6c and J4 follow their own prerequisites.

### J5 Mission-first home and truthful terminal states — `done`
- Start the existing short-document mission above the fold at 390×844 and desktop;
  one tap when ready, one workload, no starter storage/download prerequisite.
- Move the full map and inventory below the primary action; retain accessible
  navigation and name the current unavailable/startup phase.
- Clear working indicators on complete/cancel/failure; show retained partial
  evidence, actual cleanup state and concise wrong/format/unassessed explanations.
  Rename unchanged Practice to Retest. Preserve fixed scoring and existing budgets.
- Accept: meaningful browser checks for ready/start/busy/reload/cancel/failed states,
  phone/desktop screenshots and keyboard controls. No implementation of training,
  recipe experiments or new suite in this slice.
- Verification: "Start: Read this brief" (`#cc-next-go`) is the single primary action above the fold on desktop and phone (measured at 390×844: y=605.4, bottom=650.4, fully visible without scrolling) for ready first-time users, initiating the document mission without baseline or download prerequisites. Baseline testing remains available in `#lab-controls` ("Pause chat and run baseline trial") and via the skill map. Duplicate `#cc-start-documents-quick` button removed. Consistent lock ordering (`startup.lock` before `lab.lock` via `_order_locks`) across `snapshot()`, `start()`, `cancel()`, `clear_task()`, `close()`, and `run()` cleanup eliminates lock-order deadlocks, verified by bounded multi-threaded regression test `test_concurrent_polling_and_cleanup_no_deadlock`. Truthful terminal states and recovery status in `lab.py` and `app.js`: unconditional "Assistant resumption ready" claim removed; reports actual recovery state (`recovering`, `failed`, `ready`, `not-running`). `formatRecoveryStatus()` normalizes startup `{phase, active}` and lab `{state, message}`, updating the cancellation banner on live transitions and preventing stale initial arena values from downgrading newer terminal recovery status. Qualification handled as three states in `#cc-hero-result` (`Qualified`, `Criteria not met`, `Not assessed`), preventing baseline trials from displaying "Missed". Python regression suite in `tests/test_mission_first_home.py` (6 tests including concurrency regression). Browser smoke in `scripts/smoke-mission-first.mjs` verifies rendered DOM behavior: fold visibility at 390×844, single workload dispatch and busy-disabled state, mid-trial cancellation with retained partial receipts, rendered `#arena-summary-detail` recovering → ready/failed transitions, stale arena downgrade protection, and `#cc-hero-result` qualification tri-state via real `refreshStartup()` and `refreshCommand()` execution. Added to `.github/workflows/openclaw-compatibility.yml` with path triggers and portable Python defaults. Also verified by `tests/test_command_center.py`, `tests/test_lab.py`, `tests/test_mission_report.py`, and `scripts/smoke-journey-browser.mjs`. Real model requests, shipped Firefox ESR, and physical ISO deployment remain separate acceptance.

### J6a Versioned instruction recipe and backend execution — `completed`
Depends on: J5.
- Separate standard calibration from instructed Lab experiments. Record canonical
  instruction preset/hash and actual context/thinking/seed/temperature/output cap,
  request format, suite, manifest digest, hardware and runtime identity.
- Pass one bounded public instruction preset to the pinned backend after verifying
  its request interface. Keep standard requests and fixed item prompts/scorers unchanged.
- Accept: real request fixture proves instructions reach backend, standard behavior
  stays identical, invalid/unknown recipes are refused, legacy records cannot match
  experiment evidence. Preserve workload/cancel/privacy bounds; no profile changes.
- Verification: canonical versioned trial recipe schema ('argos-recipe/1') in `runtime/argoslive/recipe.py`, recording preset, sha256 instruction hash, context, output_cap, temperature, seed, thinking, and request_format. Reviewed public presets 'standard' (no response instructions) and 'concise' ("Follow the requested output format; omit extra prose."). Pinned Ollama backend accepts system parameter on `Client.generate()` and `Client.chat()`; standard calibration requests omit the system parameter byte-for-byte unchanged. `bench_ability.py` and `doc_trial.py` resolve canonical recipes, pass instructions to backend calls, and attach recipe identity to benchmark results. Strict comparison rules in `results.py:compare()` enforce identical recipes and reject comparisons between legacy and experiment records. Lab `Controller` validates recipes before acquiring locks or pausing chat, exposes recipe in snapshot and arena, and passes recipe to runners. Web server accepts optional bounded JSON payload on `POST /api/lab/start` and `/api/lab/start-documents`. Tested in `tests/test_recipe.py` (25 unit and integration tests covering schema, bounds, tamper rejection, backend requests, results persistence, strict comparison, Lab controller, server endpoints, and profile isolation) with all existing test suites passing. Shipped Firefox and physical USB acceptance remain later checks.

### J6b Previewable fast Lab experiment and recipe restore — `completed`
Depends on: J6a.
- Preview/select a reviewed public response-instruction preset, run the existing
  document suite and select/restore a Lab recipe. Guest selection is session-only.
- Clearly label that this changes Lab configuration, not the OpenClaw personality
  or model weights. Defer private custom persona import/editing to reviewed work.
- Accept: visible preview/start/cancel/restore paths, bounded authenticated input,
  selected recipe roundtrip and protected assistant/profile/history; no leaked
  instruction/private text and no silent promotion into the actual agent.
- Verification: Public reviewed presets listing (`recipe.list_presets()`) and authenticated `GET /api/lab/recipes` returning reviewed instruction presets (`standard`, `concise`) and current session selection. Session-only in-memory recipe selection and restoration via `Controller.select_recipe()` and `Controller.restore_recipe()`, exposed via authenticated `POST /api/lab/recipe/select` and `POST /api/lab/recipe/restore` with strict request size bounds (<=512 bytes) and parameter validation. Truthful UI labeling in `#recipe-modal` explicitly informing user that experiments modify Lab configuration only and do not alter OpenClaw personality, model weights, or conversational system prompts. Active recipe HUD indicators in `#lab-recipe-bar` and `#arena-recipe`, with direct "Restore standard" action when non-standard presets are active. Receipt replay displays tested recipe indicator with scoped restore action. Verified by 37 unit tests in `tests/test_recipe.py` covering schema, preset listing, controller selection/restore lifecycle, busy-workload mutation rejection, profile/config directory isolation, and API endpoint bounds. Browser smoke in `scripts/smoke-mission-first.mjs` verifies modal activation via `#receipt-change`, verified concise instruction preview, assistant protection notice, concise selection updating `#lab-active-recipe`, and standard recipe restoration. Shipped Firefox and physical USB deployment remain later checks.

### J7 Controlled comparison and recipe-bound task evidence — `completed`
Depends on: J6a, J6b.
- Retain strict `results.compare`. Add an explicit baseline/candidate experiment
  validator allowing exactly one declared intervention, matching all other recipe,
  suite/version/coverage/hardware/runtime fields and required identities/restoration.
- Bind selected qualification/map evidence to tested recipe plus model digest;
  stale/partial/unknown recipe evidence is history only. Speed gain needs its own
  compatible speed pair. Observed +1 is not confirmed general improvement; do not
  claim within-noise without measured repeats. Use held-out items before broader claims.
- Accept: mutation-sensitive tests reject undeclared/multiple changes, mismatched
  hardware/runtime/suite, missing recipe identity, partial/stale evidence and failed
  restoration. Fixed task qualification bars remain fixed; no comparator bypass.
- Verification: Implemented `results.compare_experiment(baseline, candidate, *, allowed_intervention=None)` enforcing strictly one intervention variable (`'recipe'` or `'model'`), rejecting identical runs (repeated practice), rejecting multiple changed variables, requiring verified 64-hex manifest digests, matching complete hardware evidence (CPU model, GPU list, positive RAM bytes), matching recorded Ollama and Argos versions, complete coverage, and successful cleanup/restoration. Removed unsupported blanket claim that differences < 20% are noise; median token rates and latency deltas are inspected directly across paired runs. Structured delta reports `observed_gain`, `regression`, or `no_change` with side-by-side changed item output comparisons and explicit limitation disclaimer (not generalized improvement without independent validation). Task-bound evidence is implemented across `results.py`, `recipe.py`, `command_center.py`, and `skill_map.py` (independent validation across held-out suites remains separate pending work under SI3). Bound skill map qualification and command center facts strictly to active recipe. Added authenticated `GET /api/benchmarks/experiment` with baseline/candidate auto-orientation in `web/benchmarks.py` and UI deck integration in `app.js`, `index.html`, and `style.css` via `#compare-experiment`. Verified by 19 unit tests in `tests/test_experiment_compare.py` covering adversarial rejection, identical run rejection, multiple intervention rejection, hardware completeness/mismatch, Ollama/Argos version mismatch, failed restoration, valid recipe/model/speed deltas, and skill map recipe qualification isolation. Verified in browser smoke via `scripts/smoke-mission-first.mjs`, `scripts/smoke-dashboard-browser.mjs`, and `scripts/smoke-journey-browser.mjs`. Shipped Firefox and physical deployment remain separate checks.

### J8 Focused watch/debrief and useful validation missions — `completed`
Depends on: J5, J7; integrate the J3 flow when available.
- Keep current challenge/real answer/latest receipt/progress/Stop visible on phone
  and desktop. Debrief leads with a measured outcome, representative reason, separate
  speed/wait and optional opinion; one next intervention is previewable.
- Expand original useful exercises and held-out validation with versioned criteria.
  No scope inflation from JSON/tool formatting or filesystem retention. Public
  fixtures only; owner document tasks retain their memory-only boundaries.
- Accept: actual browser rendering/keyboard/reconnect/cancel, fixture-versus-real
  model scope reported, versioned scoring/held-out coverage and useful next action.
- Verification: Unified loop connecting Challenge → Watch → Debrief → Change → Retest → Keep/Restore → Validate → Use. Added prominent single next action `#receipt-use` ("Use this build in Mission Brief ↓") when qualified, leading directly into Mission Brief; added `#arena-next-action` ("Review result & debrief ↑") on completed Arena trials. Upgraded Arena receipts with explicit observable answer and readable miss descriptions (distinguishing format contract vs answer criteria failures). Bounded debrief with prominent `.opinion-tag` disclaimer ("Model opinion · memory only · not scored evidence") and model provenance tag (`[from <model>]`). Implemented 3-state Skill Map legend with explicit status marks (`● Qualified`, `◐ Tested · validation pending`, `▲ Needs work`, `○ Untested`, `◇ Future`) and unified `formatNodeStateBadge`. Added mobile responsiveness down to 320px and 360px viewport widths in `style.css`. Explicitly labeled simulated fixtures with `(simulated fixture)` tag in HUD and hero cards. Verified in browser smoke via `scripts/smoke-mission-first.mjs` and `scripts/smoke-journey-browser.mjs`, and unit test suites across Python test runner. Shipped Firefox and physical deployment remain separate checks.

### J6c Thinking/context experiments — `todo`
Depends on: J7.
- Offer only pinned-backend/model-supported modes, one variable at a time, within
  existing budgets. Record actual values and qualify only the explicit tested scope.
  Report thinking-inclusive time separately from first visible answer; no hidden
  reasoning stream. Quantization belongs to catalog/model transactions.
- Accept: unsupported/over-budget settings refused with a reason; exact request,
  comparison and task-evidence binding checked. No blind timeout or context increase.

### G2 Persistent desktop default on next USB rebuild — `in progress`
- Owner requested October8: next personal USB rebuild should default to Argos
  desktop with encrypted persistence. Keep explicit no-passphrase guest/reset and
  basic graphics entries. This supersedes G1's default choice for that rebuild.
- Accept: boot-menu tests/docs updated; actual default selection verified and guest
  entry isolation retained. GRUB selects desktop index1 and BIOS selects only the
  desktop label by default. Shell fixture checks both menu outputs; actual ISO
  menu inspection and physical default boot remain separate acceptance.
  Missing/locked persistence handled honestly. No firmware
  changes or mutation of a running USB; physical preservation remains local deployment.

### J1 Live test arena and incremental receipts — `in progress`
- Primary product focus: configure → watch → qualify → improve. Extend existing lab progress callbacks with bounded sequenced per-item public prompt, answer output, status, elapsed time and scored receipt events; no hidden reasoning, private profile/text or configuration in event logs.
- Show real streamed output, completed items/total, growing outcomes and Stop. Reconnect without restarting; distinguish incomplete/cancelled observations from completed qualification. Keep existing workload ownership and deadlines.
- Accept: real local model/shipped Firefox visibly updates during a long run; slow generation, cancellation, reconnect, bounded buffers and escaped output work; no fabricated progress. Fixture screenshots are insufficient.
- Verification: Bounded sequenced event journal (`MAX_EVENTS = 1200`) in `runtime/argoslive/lab.py`, streaming answer deltas and scored receipts in `runtime/argoslive/bench_ability.py`, authenticated `/api/lab/events` route with sequence cursor and gap detection in `runtime/argoslive/web/server.py`. Live Proving Ground arena deck in web UI (`index.html`, `app.js`, `style.css`) with telemetry HUD, active challenge prompt, live streamed output, growing verified receipts list, Stop control, and seamless reconnect from snapshot. Verified by unit tests (`test_arena_events.py`, `test_lab.py`, `test_bench_ability.py`, `test_doc_trial.py`, `test_dashboard*.py`), syntax checks, and browser smoke assertions including 320px/390px/768px viewports. Shipped Firefox ESR, ISO build, real inference on Toronado, and physical USB deployment remain separate acceptance.

### J2 Task-scoped skill map and readable result replay — `in progress`
Depends on: J1.
- Replace the document-only rail as the main navigation with a large connected skill map, grouped by useful tasks. Measured, qualified, untested and needs-attention use labels/icons as well as color; unavailable future suites stay unavailable. Phone equivalent is a usable grouped list.
- Each node opens fixed criteria, task/model-digest/configuration scope, current evidence and one Start test action. Results lead with pass/failure reasons and representative answer replay, separate speed metrics and optional opinion. Advanced records are secondary.
- Accept: absent/partial/stale-model evidence cannot color a node qualified; small probes cannot qualify entire domains; matched comparisons retain current validators. No AGI percentage or tool-execution claims from answer-format tests.
- Verification: Task-scoped skill map engine in `runtime/argoslive/skill_map.py` binding evidence strictly to selected model manifest digest across 6 task domains (Understanding, Reasoning, Planning, Tool use, Memory, Perception). Authenticated `/api/skill-map` endpoint and integration into `/api/command-center`. Web UI Proving Ground skill map deck (`index.html`, `app.js`, `style.css`) with desktop cluster graph and mobile navigable grouped list, interactive node inspection modal with fixed criteria, task scope/guardrails, bound model digest, current evidence, and direct Start actions. Readable Result Replay in `mission_report.py` and UI displaying representative passed and failed challenge outputs with plain-language failure reasons, qualification criteria checklist, side-by-side responsiveness metrics, local-model debrief opinion, and Practice/Upgrade actions. Verified by 13 unit tests (`test_skill_map.py`, `test_mission_report.py`), command center tests (`test_command_center.py`), arena events tests (`test_arena_events.py`), and syntax validation. Real Toronado GPU runs, shipped Firefox ESR review, and physical ISO deployment remain separate acceptance.

### J3 Guided stronger-model choice with inline storage — `completed`
Implementation specification: [CURATED-MODEL-JOURNEY.md](CURATED-MODEL-JOURNEY.md).
Worker sequence and delivery: [WORKER-PLAY-SESSION.md](WORKER-PLAY-SESSION.md).
- Curate at most three downloadable general choices plus the bundled fallback;
  qualify usefulness locally, preserve legacy installed/rollback identities and
  audit the 4B alias/architecture mismatch. Replace the historical eight-entry
  minimum without weakening artifact/license verification.
- Make post-success Keep/Restore a real model transaction with owner-edit and
  recovery protection, distinct from selecting a Lab instruction recipe.
Depends on: J2 and existing reviewed storage/model transactions.
- “Try a different model” carries the selected skill into a short reviewed-catalog choice, fit/download costs, inline “Choose where to keep models”, verified download, explicit switch, matched retest and Keep/Restore.
- Storage choices show device labels, free space, persistence/encryption and recommended eligible choice with rationale; Review/Use this location confirms the folder and profile/history separation. Explain blocked choices; starter chat remains available. No auto-adopt/format/move.
- Accept: first-time owner can complete the flow without finding a separate storage section; no-space/missing-drive/cancel/switch failure retain current protections. Real larger-model comparison and phone/shipped Firefox checks reported separately.
- Verification: Resolved 4B model identity discrepancy by verifying full artifacts: `359d7dd4bcda` is the thinking variant (`Qwen3-4B`), while `0edcdef34593` (`qwen3:4b-instruct-2507-q4_K_M`) is the explicit Instruct candidate with verified manifest digest `sha256:0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` and layers; added the explicit candidate without rewriting historical identities or hashes. Replaced 8-12 model count requirement with reviewed bounded policy (`1 <= len(models) <= 24`). Implemented curated introductory lineup (`qwen3:0.6b` bundled fallback, `qwen3:4b-instruct-2507-q4_K_M` recommended compact upgrade, `qwen3:8b` balanced, `qwen3:14b` capacity) with distinct role badges, rationale, and fit guidance; legacy 9-model inventory is collapsed by default under `<details id="catalog-panel">` to avoid cluttering the shortlist, with no unsupported promises of 'higher accuracy' before testing. Added inline storage selection (`#inline-storage-section`) within model download flow with explicit candidate drive choices, free/needed space, and write check verification via `/api/storage/choose`. Implemented exact and durable model transaction rollback in `runtime/argoslive/model_selection.py`: restores exact saved configuration bytes (`raw_previous`), writes rollback record `model-rollback.json` before finishing recovery journal without swallowing write failures, and protects against concurrent external owner edits. Added authenticated `POST /api/models/restore` and `POST /api/models/keep` in `web/server.py` and UI assistant transaction bar `#receipt-model-rollback-bar`. Verified by unit tests in `tests/test_catalog.py` (8 tests) and `tests/test_model_selection.py` (10 tests), browser smoke in `scripts/smoke-mission-first.mjs`, `scripts/smoke-dashboard-browser.mjs`, and `scripts/smoke-journey-browser.mjs`. Shipped Firefox and physical USB deployment remain separate acceptance.

### J4 Bounded observable agentic qualification — `todo`
Depends on: J1, validated pinned tool policy and disposable sandbox isolation.
- Opt-in actual multi-step original-fixture task with allowlisted tools, observable action trace, code-verified artifact, action/time budgets and recovery evidence. Conversation/formatting suites stay separate.
- Accept: denied operations remain denied; no host personal files/network/shell widening; actual pinned agent executes allowed tools and produces a verified artifact. Qualify only that workflow, not general autonomy. No hidden chain-of-thought display.

Plan: [PERSONAL-ROBOT-EXPERIENCE.md](PERSONAL-ROBOT-EXPERIENCE.md). Implemented in the order below; each stage keeps its own acceptance and states what was and was not verified.

### S1-S5 Storage evidence and deliberate choice — `in progress`
- S1 location report: `storage_view.snapshot` resolves the backing device of models, profile, conversations, results and settings, following an overlay root to its persistence upper directory. Unknown stays null.
- S2 reboot evidence: `reboot_evidence` writes a marker (random id, schema, boot id) exclusively inside Argos directories, flushes it, and reports `retained` only when read back under a different boot id. It proves retention of that directory, not encryption or conversation recovery.
- S3 bounded write check before every download and on confirmation.
- S4 deliberate choice: every eligible location is listed with label, capacity, encryption and a temporary warning. Downloads require a confirmed store. Existing data is never adopted; a store that already holds models is not moved automatically.
- S5 capacity: candidates must hold the budget plus safety margin; each download re-checks its own space.
- Verified: unit and fixture tests (`test_storage_view`, `test_reboot_evidence`, `test_dashboard_storage`, `test_model_controls`). Not verified: real devices, shipped Firefox, physical reboot.

### D1-D4 Short-document trials and matched comparison — `in progress`
- D1 suite: `doc_trial` and `data/documents/short.json` (suite 1.0.0, generated by `scripts/build-document-suite.py`). Eight original passages, each with a plain answer, a supported quotation, a question the passage cannot answer, and an owner-judged summary. Closed JSON schema; format errors are separate from wrong answers; no model judge.
- Fixed criteria live in the suite file (answers 7/8, quotations 6/8, "not stated" 7/8, at most 2 format errors). A baseline never changes them. Changing any criterion bumps the suite version.
- D2 context: the trial runs at a recorded 4,096-token context and reports the longest prompt actually tested. Longer-document and file-reading support are not qualified by it.
- D3 lab plan `documents`: speed at short and medium prompts, then the document trial, under the existing pause/restore workload reservation. The quick baseline plan is unchanged.
- Verified: unit and fixture tests including exact threshold boundaries, quote support, closed-schema failures, partial runs and result comparison. Not verified: a real model, real GPU or CPU timing, shipped Firefox.
- D4 matched comparison: `results.compare` still enforces same kind, suite version, settings and coverage, then adds per-run prompt tok/s, generation tok/s, first-token wait (medians need all three runs) and accuracy as separate fields, with per-item side-by-side outputs. The Model Lab shows them as before/after tables and states that speed and accuracy are separate. CSV export keeps its original columns.
- Verified: unit tests; whole-journey browser test in Chromium (`scripts/smoke-journey-browser.mjs`, fixture model and simulated device discovery); real pinned Ollama onboarding smoke with real storage choice and write check (`scripts/smoke-model-onboarding.py`). Not verified: a real larger model, GPU timing, shipped Firefox, physical USB.

### X Command Center — `implemented, browser-tested with a fixture model`
- `command_center` derives next action and seven system states from saved evidence. Unknown stays unknown; nothing is invented. `journal` keeps owner-private Routine, Qualified and Commissioned entries, each recorded once per evidence key, so reinstalls and repeated trials never replay a ceremony. One moment (the highest unseen tier) is shown; the owner can dismiss it or turn acknowledgments quiet.
- Qualified: a model meets the fixed document criteria (scope stated); a new model qualifies where the old one did not; a leaner build (at least 20% faster on the short prompt with both qualifying). Commissioned: model storage directory retained across a reboot; first qualified model whose answer to the owner's own pasted document was accepted. A regression is a routine line with a restore offer.
- Pasted-document task: up to 6,000 characters and one question, run under the lab reservation; the answer must quote the text and the quote is checked against it; a document that fills the context is refused, not truncated. The document and answer are in memory only; the journal stores the verdict and model tag.
- Evidence rules: a comparative claim (improvement, regression, leaner build, restore offer) needs `results.compare` to accept the pair (suite version, settings including context, coverage) plus matching CPU, GPU and total RAM; the speed claim needs its own matched speed pair. Qualification and commissioning attach to the model's manifest digest, not its tag: an updated manifest under the same tag inherits nothing, an unidentified selection matches nothing, and an accepted answer must carry the digest it was produced with. Journal history is kept and marked as not evidence for the files selected now.
- Not verified: shipped Firefox, a real model, physical use. Hosted VM gateway failures recorded earlier remain unresolved and are not covered by any of this.

### Failure paths — `tested`
Unavailable or swapped storage, missing or corrupt state, full drive (during the write check and during a storage choice, with rollback), a failed configuration write after the destination and marker were created (only this operation's marker and directories are removed; a destination the configuration already points at is kept unless the previous configuration is restored), a real read-only store (run as an unprivileged user), failed download, a model backend that fails to start, and cancellation all stop before any job or restore chat. See `tests/test_journey_failures.py`. One onboarding-smoke step failed once on a push that changed nothing it uses and passed on rerun of the same code; the cause was not identified.

### PR73 acceptance correction — model-selection outcomes

Normal polling and lost-response reconciliation now share controller outcome
handling. Idle does not prove completion; rollback, cancellation, failure and
owner-edit recovery blocks retain their specific outcomes. Twelve Node behavioral
regressions execute the production functions and run in CI. The complete Chromium
fixture journey passes, including real page reload and a switch lasting over 60
seconds. Shipped Firefox, real model upgrades and physical USB acceptance remain
separate; no backend budgets or permission boundaries were changed.

### U7 Playable loop redesign & storage dialog hierarchy — `done` ([PR #74](https://github.com/mbolaris/argos-live/pull/74))

Redesigned the experience around one playable loop: Challenge → Watch → Understand the result → Try one recommended improvement → Retest → Keep or restore. Resolved usability confusion observed on physical Toronado USB hardware without altering fixed scorers, test thresholds, backend permissions, or data assets.
- **Home as Mission Screen:**
  - Hero card `#cc-next` displays AI build identity (`AI: your AI`, `Model: Current model`), last tested result, concrete challenge preview (8 passages · 24 challenges · Reading & Comprehension baseline), and one dominant Start button `#cc-next-go` ("Start: Read this brief") positioned well above the fold on mobile (y=530.3 at 390×844) and desktop. Redundant subtitle and duplicate pause notice eliminated to prevent repeating introductory text.
  - Added single curriculum progression map `#curriculum-map` (K–12 Foundation Progression: 01 Short Document Comprehension active mission, 02 Fact Extraction & Quote Fidelity next, 03 Multi-Paragraph Synthesis, 04 Rule & Constraint Following, 05 Step-by-Step Reasoning, and 06 Tool & Function Calling specialization gateway). Future stages clearly delineated from active evidence.
  - Competing ladders and hardware blueprint `#cc-schematic` moved into secondary details container to keep the primary path uncluttered while preserving DOM nodes for automated test harnesses.
- **Enjoyable Watch & Understandable Result:**
  - Arena layout prioritizes the active challenge question (`#arena-current-question`) and observable streamed response (`#arena-current-stream`) at the top of `#arena-live-card`. Multi-paragraph passage and schema collapsed under `<details id="arena-source-details"><summary>Read source</summary>`, with `#arena-current-prompt` preserved internally for test harnesses.
  - Eliminated excessive vertical gaps in Watch HUD: replaced `flex: 1 1 200px` on `.arena-hud-progress` with `flex: 0 0 auto; width: 100%`, grouped Phase, Model, and Recipe into a compact top row, reduced padding/gaps, reducing computed HUD height from 395px down to 122px (total `.arena-deck` down from 882px to 490px–547px on phone viewports).
  - Debrief leads with plain-language outcome explanation (`#cc-takeaway`). When qualification passes, `#receipt-use` ("Use this build in Mission Brief ↓") is rendered as the sole visible primary debrief action (`.mission-primary`). Experiments and retesting (`#receipt-change`, `#receipt-practice`, `#receipt-upgrade`) are collapsed under `<details id="receipt-secondary-options"><summary>More options (Experiments & retesting)</summary>`. Scoreboard metrics and qualification criteria checklist are collapsed under `<details id="receipt-metrics-details"><summary>Metrics & criteria (Details)</summary>`, allowing representative replay (`#receipt-replay`) to be immediately visible below.
  - Weakness diagnosis spotlights failure rationale and representative pass; bounded local model debrief opinion (`#cc-debrief`) prominently tagged with disclaimer.
- **Storage Selection & Acquisition Fix (Toronado Root Cause):**
  - Converted `<dialog id="download-review">`, `<dialog id="storage-review">`, and `<dialog id="selection-review">` to `.modal-fixed-layout` with `.modal-sticky-header`, `.modal-scroll-body`, and `.modal-sticky-footer`. Prevents dialog heading and confirm/exit buttons from scrolling off-screen when multiple candidate locations exist.
  - Eliminated excessive vertical gap in storage card: replaced `flex: 1 1 200px` on `.dest-compact-info` with `flex: 0 0 auto; width: 100%`, reducing `.dest-compact-strip` height from 252px down to 113px and recommended card height from 401px down to 240px. Concise drive name, free/needed space, and selection button are grouped together tightly.
  - Technical mountpoint paths collapsed under `<details class="dest-details-collapse"><summary>Drive path & details</summary>`.
  - Excluded storage policy guardrails collapsed under `<details class="storage-policy-collapse"><summary>Excluded destinations & policy guardrails</summary>`, clearly explaining USB persistence reservation for AI profiles and existing data protection without unsupported read-only claims.
  - Recommended destination filtered strictly for selectable candidate drives (`!contains_data && (current || can_change)`). Temporary RAM alternatives grouped secondarily with explicit session-only warning.
  - Strictly respected Content Security Policy (`style-src 'self'`) with CSS classes and zero inline style attributes.
- **Verification:**
  - Complete 6-stage production journey recaptured across mobile phone (390×844) and desktop (1200×900) via `scripts/capture-production-journey.mjs`, verified visually and archived in `work/production-screenshots/` and IDE artifact screenshots.
  - `scripts/smoke-mission-first.mjs` passed 100% with all 8 regression suites:
    - Regressions 1–4: 6-rung curriculum map, secondary schematic bay, sticky storage modal layout, 320px viewport responsiveness.
    - Regression 5: Clean home intro without duplicated subtitles or pause notices.
    - Regression 6: Arena hierarchy & computed HUD layout (question and streaming tokens first, passage collapsed under "Read source", computed HUD height <= 180px, progress height <= 60px, deck padding <= 16px).
    - Regression 7: Debrief hierarchy & qualified action state ("Use this build" sole visible primary action, secondary options collapsed under Details, metrics/criteria checklist collapsed under Details).
    - Regression 8: Storage hierarchy & computed card layout (compact strip <= 150px, card <= 300px, modal padding <= 16px, selectable-only recommendation, collapsed path/policies, no unsupported read-only claims).
  - `scripts/demonstrate-journey.mjs` passed 100% (10 continuous experiment steps, auto-paired comparator, Keep/Restore actions, mobile responsive).
  - `scripts/smoke-dashboard-browser.mjs` passed 100% (CSP compliance, sticky storage modal, collapsed catalog).
  - `scripts/smoke-journey-browser.mjs` passed 100% (full journey, 320px phone responsiveness, moments).
  - `runtime/argoslive/data/documents/short.json` preserved intact without edits.
  - PR #74 merged to main; no ISO built. Physical USB deployment, physical GPU inference, and shipped Firefox ESR acceptance remain separate.

### U8 Focused mission screen and readable live answers — `completed` (PR #76)

Following physical feedback that U7 still feels dense, replace simultaneous dashboards with one foreground activity. The implementation on `feat/mission-focus` provides:

- A Mission → Watch → Improve navigation path and one primary next mission; Start remains visible on a 390×844 phone.
- Watch beside the mission instead of buried in detailed test records. Starting a trial brings the active question, received answer text, progress, and Stop together; competing panels leave the foreground during a test.
- Reading responses displayed as readable answer/quote text. Original response bytes remain inspectable and are unchanged for scoring; malformed responses still receive their actual format-error receipts.
- A brief last-challenge result as each receipt arrives, with the full receipt list available on request. Reconnection reports stale progress rather than claiming continued live output.
- Skill ladder, full map, examples, setup, model catalog and test records progressively disclosed. Links reveal their closed destination; review dialogs remain reachable independently of collapsed sections.
- Empty result panels omitted; saved evidence and future curriculum boundaries preserved. No new scores, suite changes, model upgrades or agent capabilities.

Acceptance: `scripts/smoke-mission-focus.mjs` exercises first mission, live answer, completed result, setup navigation, unique control IDs and 320/390/1280px bounds. It writes clearly labeled simulated previews to `output/playwright/mission-focus/` (ignored). Existing mission, dashboard and journey regressions remain required. Production-JS answer presentation regressions run in Tests. Real-model/shipped Firefox and physical Toronado acceptance remain separate from fixture Chromium; this change does not build or write a USB image.

### U9 Improve: one evidence-based experiment, approved, retested and decided — `completed` (PR #77; live on Toronado 2026-10-10)

Following review of U8, the Improve step became the end of the loop instead of a menu. On `feat/improve-focus`:

- Improve leads with the measured result in plain words ("23 of 24 correct", qualified or what is missing) and explains counts: the document trial produces 32 responses, 24 scored questions plus 8 summaries left for the owner that are never scored. Scoring and criteria are unchanged; the report now carries the unscored count and the run's lab recipe preset.
- One next experiment is chosen from measured evidence and from experiments that exist: format misses propose strict format instructions; wrong answers without format misses propose comparing a different model; a clean result proposes an unchanged retest. Each shows why, what changes and how the result will be judged. Nothing runs until the owner approves in the review dialog.
- The matched retest's before/after and Keep/Restore decision appear in Improve (not in collapsed test records). Labels name the action ("Keep strict format instructions", "Restore standard instructions"); wording says one matched retest, not a guarantee.
- The local-model debrief is shown only when the model actually wrote one for the displayed runs, labeled as its opinion with the producing model. Its prompt now lists only experiments the product can run. No frontend-authored first-person text.
- Watch shows the passage beside the question on wide screens and one tap away on phones, highlights a returned quotation only when it matches the passage exactly, and reduces the HUD to plain status, progress and Stop with model/recipe/elapsed under Run details. Fixed polled snapshots duplicating streamed answer text; a stopped run retries with its own settings instead of silently adding an instruction.

Acceptance: `scripts/smoke-mission-focus.mjs` drives mission → watch → result → review (no start) → approve (one start) → matched retest → before/after → Keep → Restore with API verification, and writes labeled simulated previews to `output/playwright/mission-focus/`. Existing journey, mission, dashboard and arena regressions updated for the new labels. Real-model debrief quality, shipped Firefox and Toronado acceptance remain separate.

### U9a Toronado Firefox acceptance of PR77 — `completed`

Installed b8e09ce's four changed runtime files over the exact PR75 runtime (all 62 installed files matched ac850bb first) with per-file before/after SHA-256, root-only rollback copies and idle/identity gates; settings hash and results list unchanged across the graceful restart. Verified in the shipped Firefox ESR with the real qwen3:4b model: Improve showed the saved real experiment (strict format 20→19 of 24, Restore suggested) with lab-only wording; reviewing and "Not now" started nothing; an approved retest started exactly one run, paired the new run with the newest standard baseline, and produced a real local-model opinion labeled as such; Keep set the lab recipe to concise and Restore returned it to standard, both confirmed by the API; Watch showed the real passage beside its question and 32/24/8 counts; model switch review and storage views worked. Firefox-only findings fixed in a follow-up: the previous run's passage stayed visible during the next speed check, the unstyled progress track looked full at 0%, and the model rollback bar said "Current model" instead of the name. Not yet shown on real hardware: a quote highlight mid-stream (real answers stream in under a second), phone layout, and reboot persistence of the patch.

### U9b Toronado Firefox acceptance of PR78 — `completed`

Installed a84538d's two changed files over the exact b8e09ce runtime (all 62 files matched first) with the same hash, rollback, idle and settings gates; settings hash unchanged and rollback copies verified against the baseline. In the shipped Firefox with qwen3:4b: the progress bar is an empty dark track at "Starting…"; after a run left its last passage on screen, the next run's speed check showed no previous passage; the rollback bar names `qwen3:4b-instruct-2507-q4_K_M`. Model switching: the review dialog opened and was dismissed; no switch occurred. Found: with the passage hidden the speed-check challenge fell into the narrow passage column (fixed in the next PR); an already-decided experiment comparison is re-paired with a newer standard run and still shown above the current proposal; a real debrief claimed it "quotes correctly" and mentioned format errors when quotations scored 4/8 and format errors were 0. Still unverified: quote highlight mid-stream on real hardware, physical phone layout, and reboot persistence of the live patch (to be checked in a reboot coordinated with the owner before any ISO build).

### U11 Persistent challenge replay — `completed` (PR #79; live on Toronado 2026-10-10)

Implemented on `fix/speed-check-layout` (with the speed-check layout fix): `GET /api/benchmarks/replay/<run>` (read-only, document trials only) returns all 32 responses in suite order with the saved verdicts, plain reasons computed with the scorer's own parsing (for example "the answer was right, but the quote isn't copied exactly from the passage"), the fixed accepted answers, and whether a returned quote appears in the passage; scores are never recomputed. Improve shows "Step through every answer" after the result: one row per passage with Fact/Quote/Missing/Summary chips colored by verdict, opening on the first miss, with ←/→, "Next miss" and arrow keys; the detail shows the passage with an exact quote highlighted, the question, the readable answer, the verdict, accepted answers on a miss, and the original output. It persists across reloads until the next result. A pending before/after decision sits above the replay; in an experiment, changed answers are ringed and show the answer from before. The measured facts appear under the model's opinion. A comparison is shown only while its candidate is newer than its baseline and not yet kept or restored in this browser. The old "See example answers" section is removed; quick-suite (non-document) runs show their result without a replay.

Original proposal:

Real inference answers all 32 responses in about 15 seconds, so live Watch shows each answer for under a second. Make the finished run the thing you actually play with:

- After a run, Watch becomes a replay of that exact run: a strip of 32 chips (8 passages × find the fact, quote, notice what's missing, summary), colored by verdict, with arrows/keys to step through. Selecting one shows the passage with the returned quote highlighted only on an exact match, the question, the readable answer, the original output, and the verdict with its plain reason. Summaries are marked "for you, not scored".
- Default to the first miss, so the most useful item is one tap away; "Next miss" skips correct answers.
- Data: the run's saved items already hold item id, category, outcome and output; questions and passages resolve from the exact suite version. Add one read-only endpoint that returns a run's replay items (or extend the receipt) rather than relying on the 100-receipt live buffer; never alter scores.
- Live Watch stays as is during a run; the replay replaces it when the run ends and persists across reloads until the next run starts.
- Pair with the experiment card: in a before/after comparison, the chip strip shows which items changed, and selecting one shows both answers side by side.
- Put the measured facts next to the model's opinion ("it says it quotes correctly; quotes scored 4/8") so a debrief that contradicts the evidence is visible without suppressing it.
- Show only an undecided comparison whose candidate is newer than its baseline; a decided or stale comparison moves to history.
- Accept: fixture smoke steps through all 32 items at 390 and 1280 px; shipped Firefox on Toronado shows a real run's replay after completion and after reload.


### U12 Real misses are answer wording, not evidence — `audited; next experiment proposed`

Audit: `docs/DOCUMENT-MISS-AUDIT.md`. Across seven qwen3:4b runs all 30 miss instances are answer-field misses with valid quotes (16 right meaning rejected for wording, 14 full sentences where a short answer is required); none are wrong facts or unsupported quotes. Older qwen3:0.6b misses are mostly genuinely wrong. The replay now shows answer acceptance and quote validity as separate checks with new, clearly marked diagnostic labels; the combined check is displayed as "Correct answers with a supporting quote" (saved labels unchanged). Proposed next experiment, not implemented: one generic lab instruction restating the short-answer contract, judged by a matched retest and reported as suite-format compliance only. Accepted answers, suite version and thresholds unchanged pending an owner decision.

Earlier finding:

The U11 replay on Toronado (qwen3:4b, six document runs: four standard at 20/24 and two strict-format at 19/24) showed every miss had an exactly copied, supporting quote. The answers missed the exact accepted forms: "to protect nesting birds" (accepts "nesting birds", "protect nesting birds"), "Markdown export" (accepts "markdown"), and the full supporting sentence given as the short answer twice; strict format added "Android 10 or newer" on one fact question. So "Show the evidence 4/8" mostly measures answer wording, and the strict-format instruction does not target it. Options, none applied:

1. Experiment, no scorer change: add a reviewed lab instruction such as "Answer with the shortest phrase from the passage" as a second recipe, proposed only when replayed misses show exact quotes with mismatched answers, and judged by the usual matched retest with Keep/Restore. Lab-only, like strict format.
2. Suite revision, owner-approved: accept reviewed answer variants (for example a leading "to", or the accepted phrase contained in a short answer) as a new suite version with its own criteria. Results under different versions are never compared or used to claim improvement.
3. Leave the scorer strict and say so: the replay now explains these misses as "the quote was copied exactly, but the answer … is not one of the accepted answers".

### U9c Toronado acceptance of PR79 (U11 replay) — `completed`

Installed 4d467ae over the exact a84538d runtime (62 files matched; five replaced, `replay.py` added and checked absent first) with hash, rollback (new file removed on rollback), idle and settings gates; settings hash unchanged. In shipped Firefox with qwen3:4b: the replay of a real run showed 32 chips in 8 passage rows, opened on the first miss with the exact quote highlighted in the passage, Next miss moved to the next miss, it persisted after reload, and after a new run it switched to that run; the speed check used the full width with no previous passage; measured facts appeared under a real opinion; the decided strict-format comparison no longer appeared. Still unverified: physical phone layout and reboot persistence.

### U10 One approved, reversible everyday-assistant experiment — `in review`

U9 keeps a winning instruction for lab tests only. The everyday assistant (OpenClaw chat) does not use it, so a kept lab experiment is not evidence that the assistant improved, and the UI says so. Close this gap deliberately:

- Offer a separately approved assistant experiment that records the previous assistant configuration and exact instruction. No lab result automatically promotes a change or proves it helps the assistant.
- Verify the assistant actually uses it (through the assistant path, not the lab path) with a matched before/after on the same fixed questions, then Keep/Restore for the assistant separately.
- Never change model weights, personality files, credentials or conversations; never treat the lab result alone as proof for the assistant.

Implementation on `feat/u10-assistant-trial` adds one reviewed grounded-answer block to operating instructions (`AGENTS.md`), independent eight-task before/after through scoped gateway sessions, per-check evidence and Keep/Restore. See [U10-ASSISTANT-TRIAL.md](U10-ASSISTANT-TRIAL.md) for exact scope, limits and fault recovery. Persona/config files are fingerprinted; owner edits block recovery without overwrites. Instructions, task identity and model are recorded. Local fixture Chromium and unit evidence do not establish real assistant improvement. Toronado deployment, a real approved trial, reboot and physical-phone checks are not performed in this slice.

The same change makes answer-wording-only diagnostics recommend reviewing misses rather than a larger model. Unscored summaries are excluded from advice, and quotation failures remain separate from wording diagnoses. No lab scores, suite rules or qualification thresholds change.
