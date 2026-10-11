# Auto Climb: stable product and acceptance contract

October 11, 2026. This is the target, not a completion claim. Status/evidence lives in
[BACKLOG.md](BACKLOG.md); current fixes/testing in [AUTO-CLIMB-WORKER.md](AUTO-CLIMB-WORKER.md).
This supersedes the original handoff's proposed defaults where clarified below.

## Experience

One **Start Auto Climb** button after boot: assess the AI, try an eligible better model,
reassess, improve its configuration and continue until a scoped plateau or budget limit.
Shared supported foundations first, specialization later. The agent plays; the owner
watches and coaches. Keep Open chat separate from Start. Do not use “Ready to prove I
can do better.” Model fit is an estimate, not proof of quality.

Before each experiment show what changes, why, cost and checks, with a **30-second
countdown**, Try now, Skip this idea, Pause and Stop. Silence permits execution only
inside the session's disclosed approval. Details pauses the shared session for every
viewer; closing it requires Resume. Browser closure does not stop an approved session.

Three sparse views: Start, Watch, Next move/result. Show the task/source, actual answer
or tool activity, immediate receipts, before/after and starting/current capability
markers. Whole-turn updates are not token streaming. No fake tokens, hidden reasoning,
IQ or literal school-grade claims. Commentary is opinion, separate from evidence.
Final report: gains/regressions, changes kept/restored, cost, stop reason, one next action.

## Coordinator and authority

Reuse OpenClaw execution, assistant transactions, downloads, model selection, storage
and scoring. No second agent/tool framework. Server owns timers, session/action IDs,
approved policy, exact model/config identities, exposure ledger, budgets and transactions.
Use safe atomic persistence and a single workload owner through delegated child jobs.
Public snapshots omit secrets, raw owner files and private conversations.

Reuse map: `assistant_trial.py` for reviewed OpenClaw turns and instruction transactions;
`model_selection.py` for switch/Keep/Restore; `model_controls.py` and `pull_jobs.py` for
verified acquisition; `catalog.py`, `hw.py`, `storage_view.py` for fit/storage; `results.py`
and `skill_map.py` for scoped receipts; `desktop.py` and `web/server.py` for actual wiring.
Inspect their contracts before adding adapters; do not assume fake callbacks match them.

Material change means a different model digest, instruction/config/resource hash,
affected scope, permission, test plan, required budget or changed hardware/storage fit
invalidating the proposal. Invalidate its ID and restart the full preview; changes outside
approval need explicit approval. Pause/Skip/Stop race atomically with action commitment.
Stale commands cannot execute. All authenticated viewers control the same shared session.

One worker only. Resume waits for old execution and cleanup to finish. Restart resolves
journaled mutations before pausing and never resumes a stale countdown. Owner edits block
restore instead of being overwritten. Failed/unknown cleanup stays blocked with evidence.

## Budget/stopping policy v1

Defaults to validate: 60 minutes active time, six attempted experiments, one new download
attempt, 8 GiB transferred new bytes, no permission expansion. Strictly validate supported
values before approval; unsupported/invalid limits fail before work. Settings stay secondary.

Reserve an experiment slot durably immediately before acquisition/staging; failed, cancelled
and blocked attempts consume it. Skip before commitment does not. Count partial/failed
transfer and retry bytes. Baseline, warmup, countdown, inference, acquisition and cleanup
consume time. Explicit paused intervals may be excluded; Resume/reboot never reset consumed
budgets. Account conservatively after interruption. Reserve cleanup time and enforce
deadlines inside child work, not just between experiments. Cleanup remains bounded.

Plateau: three distinct completed non-improving experiments since the last validated gain
**and** no remaining eligible untried candidate within approval. Say “Plateau within this
session's tested options.” Errors, missing storage and skipped ideas are not measured
non-improvement. Fewer than three usable options: options exhausted. Remaining options plus
spent budget: budget exhausted. Fresh validation unavailable: blocked/validation unavailable.

## Evidence/promotion policy v1

First implement one assistant document-answer domain, not the whole ladder. The lab's
32 attempts (24 scored, eight unscored summaries) and assistant's eight prompts are
different instruments. Future map regions remain unavailable until scored tasks exist.

Suites/scorers/thresholds/keys stay outside agent write authority. Bind receipts to exact
model digest, instructions/settings/resources, suite version and tool policy. Actual
turns use the everyday OpenClaw path and verify selected-model identity. Missing runner,
wrong-model, empty/error replies and partial coverage are execution failures, not scores.

For the first accuracy-focused domain:

1. Matched complete practice: at least two newly passing challenges, no regressions.
2. Matched validation on a fresh versioned partition of at least eight tasks: at least
   one newly passing challenge, no regressions.
3. Confirm with a second disjoint fresh partition of at least eight tasks under the
   same validation rule. This is bounded repeatability, not statistical significance.
4. Keep only with complete verified evidence and transaction/model/config checks;
   otherwise restore exactly and verify readiness. Missing evidence blocks promotion.

Compare current kept build and candidate on the same fresh tasks in isolated sessions.
Reserve partition IDs before first exposure; consume on any exposure, including failure,
cancellation and crash. No reuse across later experiments/sessions under a held-out label.
Reviewed generators require recorded versions/seeds and enforced non-overlap; cosmetic
rewording is not independence. Exhausted inventory stops automatic promotion honestly.

The assistant necessarily sees its assigned questions/passages. Keys, future partitions
and detailed validation feedback stay out of planning/reflection, retrieval and writable
workspace. Enforce the runner/tool/file boundary; another JSON filename is not isolation.
Owner-facing evidence is separate from planner input. After every Keep, rebase all
comparisons on the verified kept build. Preserve original starting evidence for reporting.
Durable verified Undo survives completion/reboot. Do not relax criteria to produce a win;
saturated accuracy or speed-only gains require a separately specified policy.

## Models and later adapters

Use a small reviewed catalog and actual tested-context memory overhead. Filter all eligible
candidates for fit, availability, storage and budget before ranking. Unknown fit is not
automatic eligibility. Larger weights do not establish usefulness. One explained suggestion,
at most three alternatives, with the working fallback preserved.

Downloads require a confirmed eligible store. Otherwise assess and offer one Choose model
storage action. No silent internal-disk choice, adoption, formatting, moving or deletion.
Verify full artifact identity/readiness, not file existence. Use existing journaled model
switch/Keep/Restore with deadlines and error propagation; no direct-config fallback.

Later: supported Ollama options, approved reference libraries, reviewed skills/tools.
Options must affect real assistant execution. Libraries record provenance/hash/citations;
documents are untrusted data. Aided/unaided results are distinct. No answer contamination,
hidden web access or tool permissions; real tools wait for sandbox acceptance.

## Numbered acceptance gates

| Gate | Required evidence |
|---|---|
| AC1-1 | Real desktop composition invokes verified OpenClaw runner; absent runner fails closed; cold start works. |
| AC1-2 | Durable IDs/envelope, server countdown, atomic overrides, reconnect and shared two-viewer Pause. |
| AC1-3 | Single worker/workload owner, bounded cancellable children, cumulative budgets across Resume/reboot. |
| AC1-4 | Journal-before-write, owner-edit protection, exception/crash/Stop cleanup and durable verified Undo. |
| AC2-1 | Fresh validation exposure/confirmation policy enforced, including exhaustion and incomplete coverage. |
| AC2-2 | Rebased current-kept comparisons and exact build identities; later regression cannot inherit earlier gains. |
| AC2-3 | Actual unattended assistant session reaches verified Keep or Restore and truthful stop reason/results. |
| AC2-4 | Real watch activity and readable before/after at desktop/390px; shipped Firefox/physical phone checked separately. |
| AC3-1 | All eligible curated models filtered at actual context; confirmed store action and explained fit/quality uncertainty. |
| AC3-2 | Verified bounded download, partial/failed bytes, cancellation/deadlines and no unbounded joins. |
| AC3-3 | Journaled switch, selected-model reply, requalification and verified Keep/Restore/Undo without raw-config fallback. |
| AC3-4 | Actual supported model upgrade and failure/regression restoration exercised; GPU claims require measurements. |
| AC4-1 | Execution-path and independent evidence tests before runtime/reference/tool adapters become runnable. |

Finish/review AC1/AC2 before promoting stacked AC3. Keep existing work; don't restart it.
No ISO/USB deployment substitutes for these gates. Media update requires separate fresh
device/backup/image verification and a reviewed persistence-preserving plan.
