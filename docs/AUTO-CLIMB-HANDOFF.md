# Auto Climb: implementation handoff

Owner-approved product direction, October 11, 2026. This is a plan, not a claim
that Auto Climb or a full foundation ladder is implemented.

## The experience

After boot, one **Start Auto Climb** button starts a bounded session:

**Find my AI's level → try the best eligible model for this machine → climb
again → improve its configuration → stop with an understandable result.**

The owner watches useful work rather than administering suites. Early curriculum
is shared; do not ask for a profession or make the owner assemble a test plan.
Specialization comes later. The agent should be interested and candid, without
the rejected slogan “Ready to prove I can do better.” Keep **Open chat** visually
separate from Start; it must not read as “Go talk to Argos.”

Before each new experiment, show a short suggestion and a **30-second countdown**:
what changes, why it might help, likely cost, and what will be checked. Controls:
**Try now**, **Skip this idea**, **Pause Auto Climb**. Opening details pauses the
countdown. Silence permits the next move only inside the already-approved session.
Automatic measured Keep/Restore is part of that session, with an undo/history.
Stop remains visible throughout. Do not ask for approval on every routine retry.

## Decisions that supersede older plans

Older U13 describes a fixed instruction campaign with manual Keep/Restore and no
model-authored selection. Preserve that safe implementation as a reusable primitive;
the new coordinator adds session-level approval and automatic decisions within a
reviewed action envelope. The agent may explain and rank valid candidates. It cannot
execute arbitrary model-authored commands or instructions.

Model selection should be easy: one recommended candidate, at most three alternatives,
clear fit/cost, and **Download and test**. With Auto Climb enabled, eligible acquisition
and switching can proceed within the disclosed session budget. “Best for this hardware”
means best locally demonstrated among evaluated candidates, not a universal ranking.
A larger model, download, or repeated attempt never earns a rung by itself.

The kept changes must apply to the everyday OpenClaw assistant and be tested through
that path. A better direct-Ollama lab result is not enough. Do not rewrite the agent,
replace OpenClaw, or build a second tool-execution framework.

## Inspect and reuse first

At authoring, main is `86a148da85a9d71d5d797c37dfb1872ec6fa03e9` (PR92).
Re-fetch and inspect current main and open PRs; do not assume this remains current.
PR93 adds optional paired LAN dashboard access and its browser-origin fix; it is
separate from this plan. Do not discard or duplicate it.

Read `PROJECT-GOALS.md`, `FOUNDATION-CURRICULUM.md`, `U10-ASSISTANT-TRIAL.md`,
`CURATED-MODEL-JOURNEY.md`, and the current backlog. Historical status paragraphs
are not implementation evidence. Reuse:

| Existing component | Responsibility |
|---|---|
| `runtime/argoslive/assistant_trial.py` | Scoped real OpenClaw turns, reviewed instruction ideas, comparison, transactions and recovery |
| `runtime/argoslive/model_selection.py` | Reversible model switching, verified readiness and owner-edit protections |
| `runtime/argoslive/pull_jobs.py`, `catalog.py`, `hw.py` | Durable downloads, pinned model identities and hardware evidence |
| `runtime/argoslive/storage.py`, `web/models.py` | Storage eligibility and model guidance; inspect current API before extending |
| `runtime/argoslive/lab.py`, `doc_trial.py`, `results.py`, `skill_map.py` | Existing test execution, receipts, comparison integrity and scoped qualification |
| `runtime/argoslive/web/server.py`, `web/static/*` | Authenticated API and responsive UI |

The current document mission has eight passages, 24 scored checks and eight unscored
summaries: 32 attempted items, not 32 scored questions. Current assistant campaigns
use eight prompts per round. These are different instruments; never combine their
counts or equate the assistant campaign with the whole skill ladder.

## Architecture: a small durable coordinator

Add a server-side Auto Climb controller around existing primitives. The browser renders
state and sends explicit commands; it does not own timers or execute the schedule.
Reuse the existing workload exclusion mechanism so chat recovery, trials, switches and
downloads cannot accidentally compete. Inventory code before introducing another lock.

Persist a versioned session: session ID, approved envelope, active model digest and
configuration identity, curriculum version, current phase, action IDs, deadlines,
budgets used, receipt/result IDs, decision reasons, failure and recovery state.
Use atomic writes and existing safe-path rules. Never put credentials or private raw
conversations in the public event stream.

Suggested phases: preflight, assess, propose, countdown, acquire, stage, retest,
validate, keep-or-restore, reassess, paused, plateau, budget-exhausted, blocked, stopped.
Each action is idempotent with a durable ID. Reconnect must not start another action.
Keep and restore failures block progress. Restart recovery resolves pending mutations
first and then pauses; it must not silently continue a stale countdown after reboot.

Countdown semantics: start only while ready; show a server deadline; Pause/Skip/Stop
invalidate its action ID atomically. Details opens a server-side pause, including from
a phone. Closing details offers Resume. Closing a browser does not stop an approved
session; explicitly say it continues. New material changes require a fresh suggestion
and full countdown. No delayed request may execute a cancelled action.

## Session envelope and recommendations

Start with one compact disclosure and editable Settings, not a setup wizard. Proposed
initial defaults: 60 minutes, six completed experiments, at most one new model download,
8 GiB of new download bytes, and no permission expansion. These are engineering defaults
to validate on the bundled model, not measured promises. Baseline/validation time and
failed downloads count toward budgets. Reserve time for cleanup before starting work.

Automatic downloads require an explicitly confirmed existing eligible model store.
If absent, assessment still runs and the upgrade step offers one obvious **Choose model
storage** action. Never silently select an internal disk, format, adopt data, move a
store, or delete installed weights. Explain needed/free space and persistent versus
temporary storage in plain language. Offline sessions can use installed models.

Fit uses fresh hardware evidence, verified artifact sizes and runtime/cache/context
overhead. Unknown or insufficient fit is ineligible for automatic acquisition. CPU
fallback, speed and memory estimates must be labeled estimates until measured. Do not
refresh mutable tags or invent model identities during a session. Catalog updates use
the existing review/checksum/license process. Keep the known working model available.

The planner selects from structured, supported interventions, one variable at a time:
model identity/quantization, supported Ollama options, reviewed assistant instructions,
approved reference collections, and later reviewed skills/tools. “Think,” context and
other options must be supported and actually propagated through the assistant path;
do not expose a control that only changes a recorded recipe or bypasses OpenClaw.

## Measurement and stopping

Keep suites, scorers, thresholds and fixed validation rules outside the agent's write
authority. Record exact model/config/resource/tool identities for each result. Existing
comparison invariants and restoration checks remain mandatory.

Practice identifies a possible improvement; fresh independent checks establish whether
it generalizes within the tested scope. Add versioned held-out checks before enabling
automatic promotion. Held-out answer keys stay out of prompts, libraries and reflection.
Never tune on those checks after a failed promotion and keep calling them held-out;
track exposure and rotate according to a fixed policy. Local storage alone cannot
guarantee isolation from an agent with broad file access: enforce the boundary.

Use a reviewed deterministic decision policy. Agent opinion cannot choose the scorer,
override regressions or declare qualification. Preserve the existing assistant-trial
win rule where applicable; define domain-specific promotion criteria and validation
budgets before adding new domains. Do not invent a universal noise percentage.

Proposed plateau rule: three distinct completed eligible experiments since the last
validated gain, no validated improvement, and no remaining eligible untried candidate
within the current envelope. If candidates remain but the budget runs out, report
budget-exhausted. Readiness failure, cancellation, unavailable tests, network errors,
owner edits and unsupported options are blockers, not a plateau. Say **Plateau within
this session's tested options**, not “this AI cannot improve.” Never retry the same
failed idea indefinitely. Freeze initial scope before implementation; revisions get
new policy identities.

Only implemented, independently scored domains are runnable. Mark future map regions
unavailable. The K–12 metaphor is not an IQ measure or literal school-grade claim.

## Make it watchable

Three views, one continuous story:

1. **Start:** your AI, current model, demonstrated ladder, one Start Auto Climb button.
2. **Watch:** large current task/source, actual answer or permitted tool activity,
   immediate scored receipts, completed-task timeline, starting/current ladder markers,
   and Pause/Stop. Avoid a wall of raw JSON, configuration names or counters.
3. **Next move/result:** agent's short evidence-grounded suggestion and countdown;
   after retest, show the same failed task before/after, gains, regressions and tradeoffs.

Model commentary is labeled opinion. Use real observable activity, never fabricated
thoughts or hidden chain of thought. If the runner only emits completed turns, say so;
adding real streaming is a separate verified transport change. Don't animate fake tokens.
Final report: starting level, verified ending level, changes kept/restored, time/download
cost, why it stopped, and one recommended next action. No competing Go/chat buttons.

## References and skills: later adapters

A Library can hold owner-provided manuals, academic aids and approved article snapshots.
Record source URL/title/retrieval date/content hash where applicable; do not make arbitrary
web fetching a hidden permission. Treat documents as untrusted data, not executable
instructions. Show consulted passages and citations. Measure unaided and resource-assisted
capabilities separately, with fresh tasks and no test-answer contamination. A Library
adapter requires ingestion/retrieval evidence; copying documents into a folder is not
evidence the assistant used them. Tool/skill work waits for the existing sandbox and
permission acceptance; this plan never authorizes expanding access automatically.

## Deliver in reviewable slices

**AC1 — durable loop and consent.** Add coordinator/state API, one-button approved
envelope, 30-second countdown and Pause/Skip/Stop. Reuse current model and reviewed
instruction candidates. No automatic promotion until AC2 validation exists. Exercise
reconnect, duplicate commands, restart recovery, owner edits and rollback failures.

**AC2 — first complete Auto Climb.** One real assistant domain, versioned independent
validation, deterministic automatic Keep/Restore, bounded plateau policy, coherent
watch/result UI at desktop and phone widths. This is the first usable product milestone.
It must complete an unattended bounded session and truthfully explain its stopping reason.

**AC3 — hardware-aware model upgrade.** Integrate fit/store/download/switch/requalify,
same-domain comparisons and fallback. Test failed pulls, changed storage, model load
failure, resource pressure and recovery. This delivers the owner's full minimum loop.

**AC4 — supported inference options and reference collections.** Add adapters only
after execution-path support and independent validation exist. Expand curriculum and
real tool missions separately. Do not fake a broad ladder to meet a visual target.

Each slice gets code, scoped meaningful tests, documentation and a PR. Update backlog
status with evidence. Do not mark “fun” complete from fixture screenshots: the owner
must be able to start and understand the real live session without coaching.

## Testing and live acceptance

Local repository commands (Windows uses `py`, or an installed Python executable):

```powershell
$env:PYTHONPATH='runtime;tests'
py -m unittest discover -s tests -p 'test_assistant_trial.py'
py -m unittest discover -s tests -p 'test_model_selection.py'
node --check runtime/argoslive/web/static/app.js
node scripts/smoke-assistant-trial.mjs
node scripts/smoke-mission-first.mjs
node scripts/smoke-journey-browser.mjs
```

Read scripts first. Browser scripts resolve Playwright via
`work/compatibility-runtime/package.json` or `ARGOS_BROWSER_RUNTIME`; point it to an
existing installed runtime, and set `ARGOS_PYTHON` to the actual Python executable
when `py` is unsuitable. Add dedicated coordinator tests with a controllable clock
and fake adapters, plus browser tests driving the real production JS. Run relevant
integration/CI checks for every touched backend; existing green checks are not evidence
for new code. Full Windows discovery has historically included POSIX/storage fixture
failures: diagnose/report them and use Linux CI, never silently weaken tests.

Test at 390px and desktop, including phone reconnect, countdown override races, offline
downloads, budget exhaustion, plateau, interrupted mutation and opinion failure. Assert
an opinion failure cannot erase measured results. Simulated captures must be watermarked.

Toronado is currently `192.168.1.46`. The paired LAN dashboard is
`http://192.168.1.46:44429`; it is a temporary current-session relay with a code displayed
on Toronado, not exposed chat or guaranteed boot persistence. The browser pairing bug
was fixed in PR93; verify that version before debugging Auto Climb over LAN.

For the established owner's Windows host, SSH uses `mbolaris@192.168.1.46`, the owner's
existing `~/.ssh/id_ed25519`, `IdentitiesOnly=yes`, `BatchMode=yes`,
`StrictHostKeyChecking=yes`, and `HostKeyAlias=192.168.1.30` (the enrolled host alias).
Use existing authorized credentials; never disable host checks or put passwords in
the repository. Another agent with only the repo may not have this access: do useful
local/CI work and request connection details only when live testing actually needs them.

Managed desktop user is `argos`; private session metadata is under
`~/.local/state/argos-live/desktop-session.json`. Never print its token or publish
profile/log contents. Installed code is `/usr/local/lib/argos-live`; persistent overlays
have previously made it differ from the ISO. Verify actual full runtime hashes against
the intended revision before patching or drawing conclusions.

For live acceptance, take a rollback copy, wait for all workloads to be idle, verify
uploaded hashes and unchanged durable owner settings/results, then patch only the
reviewed files. Do not interrupt a running session. Observe shipped Firefox, actual
OpenClaw replies, live receipts, a countdown override, an unattended next action and
verified restoration. Test phone separately. A real gain is not guaranteed; correctly
restoring a regressing candidate is a successful functional test. Report real streaming,
physical GPU use, reboot persistence and model upgrades only when each was exercised.

No USB write, ISO dispatch, internal-disk change, firmware/security change, or publication
of private data is part of this implementation handoff. Preserve the owner's
`runtime/argoslive/data/documents/short.json` edit. An eventual USB update needs its own
current verified image, fresh exact-device inventory/full backup and reviewed preserving
plan; never reuse historical geometry or backups as proof.

## Prompt for the next implementation agent

Implement Auto Climb following `docs/AUTO-CLIMB-HANDOFF.md`. First inspect current main,
open PRs and existing controllers, then deliver AC1 and AC2 as a coherent vertical slice
before adding AC3. The product goal is one button after boot: assess the AI, show real
work, announce the next reversible experiment for 30 seconds, automatically try and
keep verified improvements within the approved envelope, and stop honestly at a scoped
plateau or budget limit. Model upgrades that fit the hardware are the next required
slice, not an enormous catalog. Reuse OpenClaw, existing transactions and scoring.
Keep the UI sparse and observable, preserve owner data, and do not mistake lab gains
or model opinions for assistant improvement. Include race/recovery tests and phone-width
browser evidence. Do not deploy or build USB media as a substitute for proving the loop.
Read the handoff's local and Toronado testing sections, report precisely what was actually
tested, and leave a reviewable PR plus the next slice's concrete remaining work.
