# Auto Climb review and next worker work order

## Follow-up review: PR95 fe6d4e4 / PR96 550931e

This follow-up supersedes the original findings below where fixes are acknowledged.
Both PRs remain open. Independently reran all 24 focused unit/API tests on Windows:
PASS (38.5 seconds), with resource warnings. Default runner wiring, empty-reply rejection,
readiness checks, rebased instruction comparisons, partition confirmation scaffolding,
some owner-edit guards, and removal of direct model-config fallback are real progress.
They do not establish the blanket “all gates Pass” scorecard in the worker report.

Remaining work, prioritized:

1. **Fix Linux Pause/Resume CI and lifecycle, not just the test.** PR95 run 38165593388
   and PR96 run 38166506834 fail `test_single_worker_and_cumulative_duration_across_resume`:
   `Refused: Previous Auto Climb worker is still terminating`. Pause/Resume join the
   worker while holding coordinator locks the worker needs for cleanup/finalization.
   Signal under lock, wait outside locks, then verify ownership atomically. Bound real
   cancellation and test blocked turns/concurrent viewers. Do not increase waits blindly.

2. **Restore/Keep must propagate failures and prove completion.** AC3 still catches and
   discards exceptions in `_run_model_restore`, `_run_model_keep` and recovery. An isolated
   reproduction with `model_restorer` raising RuntimeError returned successfully. A
   `join(timeout=300)` does not terminate a child; check liveness, cancel and settle it
   before another operation or releasing ownership. Never infer restored from returning.
   The coordinator's main exception path still records blocked without guaranteed staged
   instruction cleanup. Stop clears the mutation record without fully verifying cleanup.
   Undo restores instruction text only; model Undo and verified readiness still need gates.

3. **Persist exposure globally before baseline exposure.** The ledger is reset in every
   Start. Partition 1 is evaluated in initial assessment before any reservation; per-candidate
   clean-build validation baselines are also evaluated before consumption is recorded.
   Consumption currently begins only before candidate validation. Crash/failure or a new
   session can therefore reuse exposed partitions. Persist an installation-wide inventory,
   reserve both matched partitions before their first baseline turn, keep them consumed on
   all exits, and fail honestly on exhaustion. Prevent future keys/feedback entering the
   planner. Test failed-practice followed by another candidate and a new session/reboot.

4. **Enforce actual deadlines/partial-byte accounting.** Budget checking remains between
   experiments; a long baseline or inference can overrun. AC3 records bytes only after
   successful acquisition and still releases `lab_active` around child start. Failed/partial
   transfers are not charged by those helpers. Use real progress to charge/reserve bytes
   and remaining deadline/cancel propagation; retain one ownership token through delegation.
   An unavailable downloader must not return a successful synthetic acquisition.

5. **Verify model identity and artifact fit, not labels.** The default OpenClaw runner now
   exists, but Auto Climb never sets its `expected_model`; digest remains unset after Keep.
   Set/update and verify expected exact model identity at every relevant transition. AC3
   still recognizes installed models by manifest parsing/layer existence rather than
   full `model_verify.verify`. Catalog maximum `context_tokens` is not necessarily actual
   execution context. Restrict recommendations to supported curated identities and tested
   context; no claim of passing artifact verification from files merely existing.

6. **Correct evidence labels before live acceptance.** AC2-3/4 and AC3-4 require actual
   assistant/Firefox/model/phone evidence, not fake callbacks or fixture screenshots.
   Change those to pending. Completed-turn updates remain distinct from token streaming.
   Do not induce a regression by changing production scorers/accepted answers; use a
   separately authorized reversible candidate or deterministic fault-injection acceptance
   harness, labeled as such. Keep private logs/configuration out of public results.

Next worker instruction: preserve the fixes, resolve items 1–5 with regressions on PR95
first and rebase PR96. Require green exact-head Linux and focused tests. Report item 6
as pending until actually exercised; do not merge/deploy/build media yet. Original
R1–R6 below supply context and broader acceptance tests, not a request to redo fixed work.

October 11, 2026. Contract: [AUTO-CLIMB-SPEC.md](AUTO-CLIMB-SPEC.md).
Status: [BACKLOG.md](BACKLOG.md). Findings refer to these exact inspected heads:

- PR95 `edc1db53b53706bd681c3634db4f3ec63165c74a`: coordinator, validation fixtures,
  API, UI and tests. Open; implemented scaffolding, not accepted AC1/AC2.
- PR96 `e16b655b198ddfffd5696a6935f1b2a4fc482783`: recommendation, acquisition and
  switching, stacked on PR95. Open; not accepted AC3.
- Main `904fb2c` contains the plan. PR93's LAN/browser-origin fix is separately open.

## Evidence reviewed

Independently reran all 20 `test_auto_climb*.py` tests on Windows: PASS, with socket
resource warnings. They use injected fake runners/controllers. Worker reports fixture
browser passes and unit tests in a separate checkout on Toronado. That is portability
evidence, not live OpenClaw, shipped Firefox, real download/switch or physical GPU acceptance.
Review reproductions used disposable local homes; no SSH/live patch/ISO/USB or owner-data
mutation was performed. “All milestones complete and verified on Toronado hardware”
overstates the evidence. Correct status/PR descriptions before proceeding.

## Required fixes, in order

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

## Work sequence

1. Fetch current heads, retain existing work and correct completion claims. Reproduce
   R1/R2, add regressions and fix them on PR95; then fix R3/R4 and exact-head checks.
2. Rebase stacked PR96 on the corrected parent, finish R5/R6 and all numbered AC3 gates.
   Update PR descriptions with gate IDs and actual evidence, not blanket milestone claims.
3. After code review/tests, prepare controlled owner-authorized live acceptance: idle
   first, full installed baseline/upload hash checks, rollback and unchanged durable
   settings/results. Never patch a running trial or treat a separate test checkout as
   a deployed assistant. Report precise remaining gates before requesting a merge/deploy.
4. Observe actual OpenClaw replies, countdown override, unattended transition, verified
   promotion/restoration and stop reason in shipped Firefox. Phone acceptance is separate.
   An induced regression safely restored is valid; no guaranteed artificial improvement.

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

Continue PR95 and stacked PR96; do not start a feature rewrite or merge/deploy yet.
Read AUTO-CLIMB-SPEC.md and this work order from the updated plan PR. Fix R1–R4 with
regressions on PR95 first: review reproduced a missing production runner scoring empty
replies and recovery overwriting an owner edit. Then rebase PR96 and finish its adapter
gates. Preserve existing code/UI and owner data; fake green tests do not establish a
live assistant loop. Cite numbered gates and exact-head evidence in the PRs. Deliver
reviewable fixes and precise remaining live acceptance. Keep one-button, sparse Watch
and the 30-second preview. Ask for private connection notes only when live tests need
them. Do not touch USB media, credentials, owner short.json or unrelated changes.
