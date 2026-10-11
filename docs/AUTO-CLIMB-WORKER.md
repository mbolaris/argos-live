# Auto Climb review and next worker work order

## Current implementation status — October 11, 2026

AC1–AC3 implementation is merged to `main`; this is code status, not live acceptance.

- [PR95](https://github.com/mbolaris/argos-live/pull/95) merged as
  `3a835d912bac01d78d0918331f37d57fd888444c`, implementing AC1/AC2 and review fixes.
- [PR98](https://github.com/mbolaris/argos-live/pull/98) merged as
  `8f21f5494e4dc343da0a638d1749ce59fe5f06c5`. It contains AC3; all six CI checks passed
  on exact reviewed head `25ff49bc767e8610a01670a8eb485c6770590405` (Tests ×2,
  schema-and-recovery ×2, native-chat, pinned Ollama smoke). PR96 was closed when its
  stacked base branch was deleted; PR98 is the rebased replacement.

The current implementation closes the earlier Linux Resume failure, propagates restore
errors, reserves global validation partitions before exposure and blocks on corrupt
inventory. Delegated download/model selection retains the workload reservation and uses
bounded cancellation. Model recommendations use curated entries and the 32k execution
context; model Undo uses the journaled selector outside the startup lock. Focused local
unit suites and browser smokes passed. Full Windows discovery still has 13 platform-
specific storage/journey/reboot-permission errors or failures; Linux CI passes.

Still pending: confirmation that the installed Toronado runtime matches merged `main`,
real model download and switch, actual OpenClaw requalification and result, shipped
Firefox and physical-phone review, measured physical GPU claims, and reboot persistence.
No live deployment or assistant improvement is claimed by the code merges. CI/fixture
evidence is not a live assistant gain. The recommendation's fit is an estimate, and the
download byte budget reserves the catalog's full expected size before transfer; it is
not a measurement of partial bytes actually transferred.

Next worker instruction: start from merged `main` and read the stable specification plus
this work order. Do not reopen or reimplement PR95/PR96 findings. If live acceptance is
authorized, verify the installed runtime and idle state first, use the existing guarded
transactions, preserve owner data, and report each measured gate separately. Do not
infer deployment, model-switch, reboot, or USB authorization from a code merge. The
historical review below remains useful as rationale and acceptance context.

October 11, 2026. Contract: [AUTO-CLIMB-SPEC.md](AUTO-CLIMB-SPEC.md).
Status: [BACKLOG.md](BACKLOG.md). The historical findings below refer to inspected
pre-fix heads from the initial review; they are rationale, not current implementation tasks:

- PR95 `edc1db53b53706bd681c3634db4f3ec63165c74a`: initial coordinator, validation
  fixtures, API, UI and tests; later corrected and merged as PR95 above.
- PR96 `e16b655b198ddfffd5696a6935f1b2a4fc482783`: initial recommendation, acquisition
  and switching; later rebased, corrected and merged as PR98 above.
- Main `904fb2c` contained the plan at that review point. PR93's LAN/browser-origin
  work was separate from this Auto Climb review.

## Evidence reviewed

Independently reran all 20 `test_auto_climb*.py` tests on Windows: PASS, with socket
resource warnings. They use injected fake runners/controllers. Worker reports fixture
browser passes and unit tests in a separate checkout on Toronado. That is portability
evidence, not live OpenClaw, shipped Firefox, real download/switch or physical GPU acceptance.
Review reproductions used disposable local homes; no SSH/live patch/ISO/USB or owner-data
mutation was performed. “All milestones complete and verified on Toronado hardware”
overstates the evidence. Correct status/PR descriptions before proceeding.

## Historical review findings and resolution context

The following R1–R6 findings were raised against the initial PR95/PR96 heads. The
coordinator, recovery, concurrency, validation, model-switch and watch changes were
subsequently implemented and merged in PR95/PR98. Keep these notes for review context;
use AUTO-CLIMB-SPEC.md and the current backlog for present acceptance status.

### R1: production runner and verified readiness — AC1-1, AC2-3

Both heads default `self.runner` to `startup.runner`; real startup has no such attribute
and desktop passes no runner. `_run_task_suite` silently scores empty replies. A local
production-style construction reproduced `runner=None` and eight empty scored attempts
without calling a model. Wire `assistant_trial.OpenClawRunner` with existing reviewed
setup/profile/session/model/cancel behavior, rather than a looser substitute.

`_restart_assistant` accepts `snapshot.active`; real startup uses this for an active
worker, not verified readiness. Require ready phase, model-reply verification and gateway
readiness; timeout raises. Add production composition tests (no injected Auto Climb runner),
cold-start, missing runner, wrong model and failed warmup. Empty execution must fail closed.

### R2: guarded mutation, recovery and Undo — AC1-4

AGENTS.md is written directly; restart recovery overwrites differing contents with session
`raw_before` without checking owner edits. A disposable-home reproduction overwrote a later
owner edit and reported paused. Fingerprint-check helpers are imported but not enforced.
The main exception path marks blocked without restoring an already-staged instruction.
AC3 Keep/Restore helpers swallow errors; direct config fallback has no proper journal.

Reuse guarded transactions. Persist before/expected-after identity before each write,
including absent versus empty file. Restore only matching staged contents; preserve owner
edits and unrelated pending transactions. Failure/unknown cleanup stays blocked, never
“kept/restored.” Add exceptions, crash, cancellation and edit tests at every mutation
boundary, and verified Undo after session completion/reboot. Remove raw-config fallbacks.

### R3: lifecycle, ownership and budgets — AC1-2/3, AC3-2

Pause immediately changes phase; Resume can spawn another worker before the previous
one exits and clears their shared pause flag. Countdown releases `lab_active`, permitting
competing workloads. Model helpers release ownership and join children without bounded
wait/cancel propagation. `_run_session` resets elapsed-time origin after Resume; budget
checks occur between experiments rather than during long work. Envelope values lack strict
validation; failed/partial download bytes are not charged.

Enforce one worker and atomic child delegation. Implement spec budget policy v1. Test
Pause/Resume during a blocked turn, override/expiry races, competing manual workload,
two viewers, restart, interrupted transfer, exhausted budget during inference/acquisition,
and failed cleanup. Assert no duplicate turn/mutation and no budget reset.

### R4: comparisons, fresh validation and stopping — AC2-1/2

The same validation JSON is reused at baseline and across candidates without exposure
tracking/rotation/confirmation. Questions necessarily enter model context; the claim they
stay outside it is false. Protect keys/future partitions and separate planner feedback.
Static-file separation does not establish that boundary.

Instruction Keep leaves comparisons based on the original weaker assistant; AC3 only
rebases after model Keep. A later regression can therefore appear improved. Model digest
is unset. Plateau is declared on option exhaustion or three unsuccessful experiments,
not both contract conditions; skipped/blocked options can produce false plateau.

Implement spec promotion/stopping policy v1. Add sequential Keep→regression tests,
consumed exposure across failure/reboot/session, unavailable fresh checks, complete
coverage, exact build identity and distinct stop reasons. If fresh validation isn't
available, disable automatic promotion honestly; do not weaken the gate to ship.

### R5: actual model adapter — AC3-1/3

Recommendation selects a larger-weight model before some budget/store filtering, so a
viable alternative can be hidden. It hardcodes 32k context, allows noncurated fallback
and treats existing layer files as installed without full identity verification. Weight
size/fit is not quality evidence. Test all eligible installed models even with download
quota spent; filter at actual execution context before ranking.

Use verified inventory and existing journaled model transactions only. Test corrupted
blobs, unavailable hardware evidence, viable smaller alternatives, unconfirmed storage,
failed switch/restore and stale fit/budget proposals. Fake callbacks are not real model
acceptance. Preserve known working fallback and verify selected-model identity after switch.

### R6: watch experience — AC2-4

Actual execution uses complete `runner.turn()` responses; call this completed-turn
progress unless real incremental transport is implemented and tested. Show one main
action and real question/source/answer/receipts, with before/after and scoped progress.
Details pauses everyone. Opinion is separate from evidence and cannot erase results.

## Remaining acceptance sequence

1. Confirm the installed runtime and package on Toronado against merged `main`. Check
   that no trial or model transaction is active; preserve rollback and durable settings/
   results before any authorized live test. A source checkout is not a deployed assistant.
2. In shipped Firefox, exercise the real OpenClaw path: baseline assessment, fit-aware
   recommendation, storage confirmation and bounded model acquisition only within the
   approved session envelope, then actual switch and same-ladder requalification. Record
   selected-model identity, real replies, receipts, cost and stop reason. Fit is not quality.
3. Exercise the 30-second preview, owner override, Pause/Resume/Stop, unattended
   transition, and guarded Keep/Restore. Confirm fresh validation is disjoint and that
   the transaction survives restart before claiming verified promotion or restoration.
   A safely restored induced regression is valid; no improvement is guaranteed.
4. Review phone layout, physical GPU use and reboot persistence as separate gates. Keep
   completed-turn updates distinct from actual token streaming. Do not infer these from
   CI or fixture screenshots.
5. Treat ISO/USB release as a separate, explicitly authorized task with fresh media
   identity, backup and reviewed preservation plan. No media write is implied here.

## Local testing

Read current scripts; Windows entry points:

```powershell
$env:PYTHONPATH='runtime;tests'
py -m unittest discover -s tests -p 'test_auto_climb*.py' -v
py -m unittest discover -s tests -p 'test_assistant_trial.py'
py -m unittest discover -s tests -p 'test_model_selection.py'
node --check runtime/argoslive/web/static/app.js
node scripts/smoke-auto-climb.mjs
node scripts/smoke-assistant-trial.mjs
node scripts/smoke-mission-first.mjs
node scripts/smoke-journey-browser.mjs
```

Set `ARGOS_PYTHON` to available Python. Browser scripts resolve Playwright through
`work/compatibility-runtime/package.json` or `ARGOS_BROWSER_RUNTIME`. Use an installed
runtime. Add production composition/real adapter-contract tests, not only fakes. Keep
fixture screenshots labeled simulated. Diagnose/report Windows POSIX fixture failures
and use Linux CI; don't weaken checks. Resource warnings should be cleaned up.

## Private live-testing runbook

Owner-local notes identify the Windows source machine, Linux Toronado destination and
enrolled key alias separately. Request them only when needed; use authorized keys with
strict host verification. Never guess a host, disable host checks, or search unrelated
agent transcripts for credentials. Do not publish tokens, codes, private profiles/logs.

Persistent overlays can differ from the ISO: verify installed runtime hashes. LAN access
does not expose OpenClaw chat. Real GPU, shipped Firefox, actual streaming, physical
phone and reboot persistence require individually scoped evidence. Preserve owner
short.json. No USB/ISO/internal-disk/security work is part of this work order.

## Prompt to the worker

Continue from `main` at `8f21f5494e4dc343da0a638d1749ce59fe5f06c5`. AC1–AC3 code is
merged in PR95 and PR98; do not recreate those PRs or claim live acceptance from CI.
Read AUTO-CLIMB-SPEC.md, BACKLOG.md and this work order. If the owner authorizes live
acceptance, verify the installed package and idle state, preserve rollback and owner data,
then report the real OpenClaw model/requalification and Keep/Restore gates with exact
evidence. Keep fit, quality, completed-turn progress, streaming, physical GPU, phone and
reboot claims separate. Request owner-local connection notes only when needed; never
search unrelated transcripts or commit private details. Do not touch USB media,
credentials, `runtime/argoslive/data/documents/short.json`, or unrelated changes.
