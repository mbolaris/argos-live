# Mission 1 implementation handoff: Read this brief

Agreed product direction, October 8, 2026. This is an implementation specification,
not shipped functionality. It is self-contained for an agent with only this repo.
Read the repository rules in [BACKLOG.md](BACKLOG.md) first. This document replaces
the old instruction to start by building J1 again.

## Outcome and first mission

Make improving a private AI a satisfying activity:

**Follow the recommended mission → watch → understand → change one thing → retest
→ keep or restore → use it on real material.**

The shared foundation curriculum is now the product direction:
[Shared foundations](FOUNDATION-CURRICULUM.md). New owners follow the same early
ladder with one recommended next action, rather than choosing a profession or
designing their own tests. Specialization comes after demonstrated foundations.
Future AI-generated proposals must become validated, owner-approved experiment
plans; the current bounded model debrief is only an opinion. This clarification
does not expand J6a's implementation scope or replace its acceptance criteria.

The first mission is **Read this brief**. Reuse the existing short-document suite:
eight original passages, 24 code-scored answer/quotation/not-stated questions,
and eight summaries for owner judgment. Fixed qualification criteria remain fixed;
summaries are not automatic scores. The mission tests short-document reading, not
file access, long documents, general intelligence or actual tool execution.

Start with the existing suite rather than inventing a new benchmark or expanding
the catalog. Offer the existing owner-pasted-document task after a completed run.
Do not retain owner text or answers beyond that task's existing memory-only lifetime.

The fast improvement loop must work with the bundled model. Model downloads are
an optional slower route, not a prerequisite for getting started or experimenting.
No guaranteed two-minute duration: estimate from applicable measured history,
otherwise show named phases, elapsed time and an unknown duration honestly.

## Current foundation: extend it

Reviewed baseline is main `dc0cb44437ab2119f3b4f45fb8810e9e52311e81`, including
merged PR58/59. J1 live events and J2 task map/replay exist. On the same built image,
local offline WHPX ran actual shipped Firefox with a real model: streamed answers,
incremental receipts, reload retaining the run, cancellation retaining partial
receipts, completed baseline saving speed/ability and assistant resumption. Map
and replay were visually reviewed. Hosted acceptance failed after readiness with
an unresolved ValueError; never describe it as passed. These are distinct checks.

Observed problems:

- Map precedes the recommended mission. In a 390px simulated-layout preview,
  the recommendation began about 2,090px down; installed static file hashes matched.
- Both upgrade buttons just call `focusSection('models-title')`, losing the skill
  and result context. Practice repeats the same suite without changing anything.
- Cancellation can leave `Generating response…` on the unfinished challenge.
- Storage leads with technical location cards before the actual destination choice.
- The current runners have no explicit instruction-recipe input and select fixed
  deterministic settings. `OllamaClient.generate` has no system argument today;
  it is not enough to add a UI control or edit an agent personality file.

Evidence caveat: phone/desktop previews use simulated model/storage data; actual
Firefox captures are from the same-image local VM. Neither establishes what the
owner's active physical browser tab shows or a physical GPU inference result.

## The six screens/states

### 1. Home: one useful next action

Show the chosen AI name (generic fallback: "your AI"), selected model, last result
or "Not yet tested", one recommended mission and **Start: Read this brief**.
Explain briefly that chat pauses for the test and resumes afterward. Put the start
action above the fold at 390×844. While startup is busy, show its named phase and
a disabled reason; never start another workload or silently queue duplicates.

From a ready workspace, one tap starts the existing document plan. Storage choice
and model acquisition must not gate a bundled-model trial. Keep the skill map as
an accessible compact overview leading to its full view; move inventory and raw
records to Details. Resolve duplicate document ladder/map/navigation emphasis.

### 2. Watch: visible work and visible control

Use a focused page/view, not mandatory browser fullscreen. Keep completed/total,
elapsed time, named phase and Stop visible. Show the actual current question,
streamed answer and latest scored result. Older receipts expand on demand.
On phone, prioritize one current challenge instead of nested long cards.

Reuse the existing bounded journal, run identity, cursor and gap handling.
Reload/reconnect must retain the running job. Speed/setup/restoration use phase
progress, not invented item counts. Completed, failed and cancelled states clear
all working indicators. Cancellation ends in **Stopped · incomplete** with retained
partial evidence and the actual cleanup/resumption status. No finished badge or
qualification for partial runs. Preserve existing ownership, timeouts and budgets.

### 3. Debrief: what happened and why

Lead with one measured sentence, then distinguish wrong answers, format failures
and unassessed responses. Show one representative question/actual answer and its
failure reason before advanced records. A numerically correct answer in the wrong
required format is a response-contract failure; do not silently loosen the scorer,
invent a partial pass or claim the model cannot do arithmetic from that example.

Show generation tokens/s, first-visible-answer wait and input processing separately.
State exactly what each existing measurement means; do not relabel a backend's
first thinking token as a first visible answer. A local-model opinion is labeled
opinion, uses only bounded public metrics, never changes qualification, and never
executes its suggested next action. No opinion failure invalidates completed scores.

Offer **Retest unchanged**, **Try one change**, and later **Try a different model**.
Remove the suggestion that merely repeating a test trains the model.

### 4. Change one thing: the new inexpensive experiment path

First release: response instructions, with a small reviewed public preset such as
"Follow the requested output format; omit extra prose." Preview the exact change.
Keep the suite's item prompts, references, scorers and qualification bars untouched.
Instructions must not contain answers, item IDs or a lookup of visible exercises.

Introduce a versioned, canonical trial recipe recording instruction identity/hash,
actual context, thinking mode, seed, temperature, output cap and request format.
Record model tag plus manifest digest, suite/version/coverage, hardware and runtime
identity. Pass the recipe to the actual backend; verify the pinned Ollama API before
adding a bounded system-instruction parameter or using its existing chat method.
Default benchmark invocation must retain its existing requests and settings.

Separate standard calibration runs from instructed experiment runs. Support legacy
results for their old standard path; missing recipe fields must not match a new
experiment or inherit qualification. Bound and validate input server-side.

Start with public presets. Owner-written instructions/persona editing are a later
slice requiring private storage and explicit scope. Public preset text can be
reviewed in the repo; private instruction content must not enter event streams,
diagnostic exports, shared CSV or unencrypted model DATA. Hashing does not make
private content anonymous. Guest recipes are session-only. Never implicitly import
an owner's personality, memory, credentials or history into benchmark prompts.

Thinking/context experiments follow instructions. Offer only options verified for
the selected model and pinned backend, with advisory fit and unchanged bounded
workloads. Change one variable at a time. Do not raise budgets to accommodate a
setting. Count thinking time/work honestly without displaying hidden reasoning.
Quantization is a separate manifest-digest model candidate, often a download, not
a free configuration knob.

### 5. Retest and decide: two distinct comparison paths

Keep `results.compare` and existing upgrade claims strict. Standard comparisons
still require compatible suite/version/settings/coverage and current hardware
rules. Do not add a broad "ignore settings" switch to make experiments compare.

Add an explicit controlled-experiment validator: baseline/candidate, declared
changed field and old/new values. Require the same suite/version/item coverage,
hardware/runtime, budgets, and every non-intervention recipe field. Instructions
experiments require the same model digest; model interventions require the same
recipe and an explicitly recorded old/new digest. Reject multiple unannounced
changes, partial runs, missing identity, failed restoration and stale evidence.

Label observed differences, not causal proof. A +1 result is an observed change;
say **One additional answer; improvement not yet confirmed** unless a predefined
repeat/validation protocol supports a stronger claim. Do not label a difference
"within noise" without repeated measurements establishing that range. Speed
comparisons need compatible speed runs; an ability pair cannot establish speedup.

Bind task qualification and selected skill-map evidence to model files AND the
tested recipe, suite and applicable runtime/settings. Old recipes remain history,
not evidence for the selected configuration. Do not reuse exact-context criteria
for a different context or suite silently; version the supported qualification
scope. Small task probes still cannot qualify an entire domain.

Keep/Restore initially changes the selected **Lab recipe only**, with a durable
local recipe-selection rollback and a clear notice. It does not alter the active
OpenClaw personality or prove improved agent behavior. Promotion into the assistant
requires a separate reviewed profile transaction, pinned schema validation and
an actual OpenClaw-path test, preserving internal IDs, credentials and history.

To claim general improvement, use original held-out exercises not shown during
tuning and record repeat/validation coverage. Repeated visible items are practice
evidence; they are not evidence of training, learning or generalization.

### 6. Use it

Offer the existing **Paste your own brief** action. Label this owner-judged task
separately from scored suite qualification. Show a supported quotation and leave
the owner in control of accepting the answer. The next useful activity should be
specific, previewable and reversible; a model's suggestion is not authorization.

## Guided model/storage route: J3

Carry mission, skill, source run, failed criterion and selected recipe through
candidate choice → storage → verified download → explicit switch → matched retest
→ Keep/Restore. Reuse existing catalog/download/store/switch controllers and their
guards. Candidate rationale is a hypothesis, not a promised benchmark improvement.

Lead with named eligible destinations, needed/free space and persistence/encryption.
Offer one eligible recommendation with a factual reason. Put paths and complete
profile/history/results inventory behind Details. Preview the folder being created,
confirm with **Use this location**, and explain blocked choices. No auto-adoption,
formatting, relocation or silent fallback. Keep the starter usable when acquisition
is refused, offline, cancelled or out of space. Do not add an unverified model tag.

## Visual tone and skill map

Clean futuristic mission control, readable on desktop and phone. Use "your AI"
for generic copy and the selected name for its voice. Keep meaningful controls
visible, strong contrast, keyboard focus, status text alongside color and reduced
motion. No XP, AGI percentage, fabricated intelligence rank, streaks or neglect.
Routine events are plain; qualification names the measured result; commissioning
is rare and tied to real new capability. Sound judgment and rollback deserve respect.

Map useful task progression. JSON output is formatting, not planning; tool-call
formatting is not tool execution; filesystem retention is not conversational memory.
Future skills are discoverable but must not dominate the first mission. Actual
sandboxed agentic workflows remain J4 until allowed tools produce verified artifacts.
Do not rebuild J1/J2 or a new event/scoring/store framework to achieve this redesign.

## Work order and code entry points

Implement one small reviewable PR at a time:

| Item | Deliverable | Reuse / inspect |
|---|---|---|
| J5 | Mission-first home, existing document start, terminal states and clear verdicts | web/static, lab.py, mission_report.py, command_center.py |
| J6a | Versioned Lab recipe and real bounded instruction request; standard runs unchanged | ollama.py, bench_ability.py, doc_trial.py, lab.py, results.py |
| J6b | Preview/select a public instruction preset, run, keep/restore Lab recipe | authenticated web routes, private/session recipe state, web/static |
| J7 | Explicit one-variable experiment comparison and recipe-bound skill evidence | results.py, command_center.py, skill_map.py, mission_report.py |
| J3 | Inline storage/model flow carrying mission context | storage_view.py, model_selection.py, catalog, download controls |
| J8 | Focused watch/debrief phone polish and richer original validation fixtures | existing J1 events/J2 replay, suite data, browser smokes |
| J6c | Verified thinking/context controls after recipe/comparison correctness | pinned backend capabilities, recipe and qualification scope |

J4 actual tool execution and P8 identity/personality editing remain separately
scoped work. The mission should work end to end with instructions before adding
thinking, hardware tuning, personality migration or more model downloads.

## Acceptance and delivery

- At 390×844 and desktop 1280×900, the primary Start action is visible without
  scrolling when ready. Check 320px usability, keyboard/touch targets and overflow.
- One tap starts exactly one document trial from a ready workspace; unavailable
  states explain themselves. No storage configuration required for the starter.
- Reload retains the job and displayed evidence. Cancel/failure never leave
  "Generating" or an active streaming indicator; cleanup remains accurately shown.
- A first-time reviewer can identify what failed, why and the next available action
  from the debrief without opening raw records. Do not invent a usability-study pass.
- Tests prove recipes reach the backend, are bounded, differ only as declared,
  cannot match unidentified/partial/old recipe evidence, and restore without
  touching another workload or the actual assistant profile.
- Adversarial strings render as text. Private inputs/hidden reasoning never leak
  to events, output exports or public logs. Repeating visible tests implies no learning.
- Run the relevant unit tests and existing dashboard/journey browser harnesses;
  `bash scripts/check.sh` and required Linux/native/onboarding/compatibility checks
  apply as specified in BACKLOG. Ensure CI triggers cover newly changed runtime paths.
- Review desktop/phone screenshots. Distinguish fixture Chromium, real pinned
  model requests, actual shipped Firefox, OpenClaw-path behavior and physical boot.
  Do not increase timeouts, silently skip a failed integration or claim green from readiness.

Update item status in each PR, describe the shipped behavior and exact validation
scope, push every commit and open a scoped PR. Merge only with owner authorization;
historical merged PRs are not blanket permission. You may proceed with implementation
PRs; do not dispatch a duplicate ISO or attempt a raw USB write from a repo-only agent.

When the implementation lands, hand the local deployment agent the merged source,
PR/check IDs, exact changed runtime scope and remaining acceptance. One exact-source
ISO must be fully hash/source/package/pins verified and reviewed in actual Firefox
before a separately authorized preserving USB update with fresh identity/backup/geometry.
The owner's next USB rebuild preference is persistent **Argos desktop** by default,
with explicit no-passphrase reset-on-reboot **Argos guest** still available (G2).

The original Yugo chat remains available for consultation on plans, tone and local
deployment. Ask the owner to relay a focused question there; no cross-chat access or
unsolicited messaging is assumed. Preserve any local changes, especially short.json.
Resolve routine choices from this spec rather than repeatedly asking for approval.
