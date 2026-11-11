# Shakedown: build backlog

Status: proposed, November 11, 2026. Nothing here is built. The concept, the data shapes and the
rules are in [DESIGN.md](DESIGN.md); read it once, then any ticket below stands on its own.

This is a feature backlog. The repository-wide backlog and its rules stay in
[../BACKLOG.md](../BACKLOG.md).

## Start here

**What we are building.** A watchable evaluation modelled on a flight-control integrated
simulation. Argos is the system under test, the Proctor plays the simulation supervisor, each
injected fault targets one console (one capability), and the NO-GO consoles become a structured
debrief report that Argos uses to pick its next self-improvement experiment. A later track adds
forms modelled on exams people know.

**Glossary.**

| Term | Meaning |
| --- | --- |
| Console | One capability, for example EVIDENCE or COMMAND. Seventeen at launch. |
| Fault family | A kind of injected problem: seeded generator, deterministic scorer, diagnostic matchers. |
| Fault card | Host-side metadata for one item: console, family, tier, partition, matchers. |
| Sidecar | A file of fault cards keyed by the item IDs of a suite or cartridge. |
| Response | What happened with one fault in one run: outcome, failure codes, timing. |
| Reference sim | A fixed, versioned, always-complete form. Comparable. |
| Stress sim | An adaptive, exploratory run. Never compared. |
| Drill | A fixed form for one fault family, used as the matched test for a trial. |
| Sealed | The held-out partition. Never shown to the agent, never merged with practice. |
| Poll | The end-of-run go/no-go call, console by console. |
| Debrief report | Per-sim, machine-readable advice: NO-GO consoles, evidence, allowlisted corrective actions. |
| Corrective action | An allowlisted intervention that exists, for example an instruction card. |
| Fix on record | A kept instruction change, annotated with the consoles it targeted. |
| Regression watch | The check that a console with a fix on record is still GO on later reference sims. |
| Exam-style form | An original form modelled on a familiar exam's public format. |

**Rules for every ticket.** The seven rules in [../BACKLOG.md](../BACKLOG.md) apply (branch and
PR per item titled with its ID, stdlib-only Python 3.11+, no live network or GPU in unit tests,
say how it was verified, keep protections, no private data, pinned upstream versions). On top
of those:

1. Only real events on screen. No imitated typing, no model-written commentary.
2. Answer keys, scorer rules, matcher values and sealed prompts never leave the host process.
   Every projection test asserts their absence.
3. Practice and sealed are never merged in a number, a cell or a sentence.
4. A reference sim is always complete. Unfinished sims are saved, replayable, never compared.
5. Stress sims carry `comparable: false` and an "exploratory" label wherever they appear.
6. Diagnosis is deterministic code. No judging model.
7. `instruction_changes` and the keep policy stay the only authority on keep or roll back. Argos
   chooses its own experiments.
8. One evaluation at a time, through the existing workload owner.
9. The setting is a simulation and says so. No real vehicle, mission, agency or person is named.
10. Exam-style forms contain original items only, are named "modelled on", and report raw
    scores only (DESIGN §6).
11. No improvement campaign runs on Toronado from this work while the AGENTS.md mismatch
    decision of November 8, 2026 is open.

**How to work without hardware.** `scripts/serve-match-fixture.py` (from PR #169) serves the real
dashboard, controller, scorers and store over a scripted model. Every UI ticket is built and
smoke-tested against it. Real-model checks run on the hosted native-chat workflow. Toronado
checks are listed separately in each ticket and are never claimed from a VM.

**Dependency.** Phases 1 onward build on the match watch in PR #169 (`proctor_match.py`,
`match.js`, the fixture server). If it has not merged, branch from it.

**Status values.** `todo`, `in progress (PR link)`, `done (PR link)`, `blocked (reason)`.

## Phase map

| Phase | Outcome | Tickets |
| --- | --- | --- |
| 0. Contracts | Consoles light from runs already saved, with no UI and no new evaluation | SIM1 to SIM5 |
| 1. The sim on screen | A watchable reference sim on the fixture server | SIM6 to SIM10 |
| 2. Reference Sim A | The first original form, with seeded generators and a real-model run | SIM11 to SIM15 |
| 3. The loop | Debrief report, corrective actions, the agent tool, fixes on record | SIM16 to SIM21 |
| 4. Stress sims and real tools | Adaptive runs, a stateful simulator, live tool events, memory | SIM22 to SIM26 |
| 5. Owner relevance and proof | Owner-task faults, the history view, Toronado acceptance | SIM27 to SIM30 |
| 6. Familiar exams | Original forms modelled on exams people know, feeding the same consoles | SIM31 to SIM36 |

Build order inside a phase is the ticket order. Phase 0 is the critical path for everything.
Phase 6 needs only Phase 0 and SIM17, so it can run alongside Phases 4 and 5.

---

## Phase 0. Contracts

### SIM1 — Console taxonomy and failure-code registry — `todo`

**Goal.** One versioned source of truth for consoles, domains, fault families and failure codes.

**Scope.** `runtime/argoslive/data/shakedown/taxonomy.json` (`argos-sim-taxonomy/1`): the
seventeen consoles and their domains from DESIGN §4, the twelve fault families from §3, and
every failure code with a one-line plain label ("Executed a command embedded in relayed
material"). `runtime/argoslive/shakedown/__init__.py` and `taxonomy.py`: `load()`,
`validate(data)`, `console(id)`, `code(id)`. Extend `runtime/argoslive/skill_map.py` `DOMAINS`
with `guard`, `tempo`, `stewardship`.

**Not in scope.** Any scoring or UI.

**Accept.**
- Validation rejects unknown domains, duplicate IDs, a code not owned by exactly one console,
  and a family with no console.
- `miss.unclassified` exists and belongs to no console.
- Existing skill-map tests still pass; the three new domains render as `untested`.

**Depends.** None. **Verify.** Unit tests (`tests/test_shakedown_taxonomy.py`).

### SIM2 — Fault-card sidecar format, loader and validator — `todo`

**Goal.** Attach meaning to form items without changing the suite schema or the runner.

**Scope.** `runtime/argoslive/shakedown/fault.py`: load `argos-sim-fault/1` sidecars from
`runtime/argoslive/data/shakedown/sidecars/<form>-<version>.json`; `validate(sidecar, form)`;
`card(form, version, item_id)`. A sidecar must cover every item of its form exactly once, name
known consoles, families and codes, and carry a `partition` that agrees with the item ID prefix
where the form uses `practice-` and `heldout-`. The loader accepts an `argos-ability-suite/1`
suite now and a Proctor cartridge form in SIM31.

**Not in scope.** The matcher engine (SIM3).

**Accept.**
- Missing item, extra item, unknown code, unknown matcher name, and partition mismatch are each
  rejected with a message naming the item.
- Loading is by exact form version; a sidecar never applies to another version.
- A test asserts that no function named `public_*` returns scorer or matcher values.

**Depends.** SIM1. **Verify.** Unit tests with fixtures under `tests/fixtures/shakedown/`.

### SIM3 — Deterministic matcher engine — `todo`

**Goal.** Turn the shape of a wrong answer into failure codes, by code only.

**Scope.** `runtime/argoslive/shakedown/diagnose.py`: `diagnose(card, item, saved_item) ->
[codes]` implementing the closed matcher set from DESIGN §5.1 (`equals`, `choice-is`,
`contains-token`, `numeric-delta`, `numeric-equals`, `json-path-mismatch`, `tool-name-is`,
`tool-arg-mismatch`, `sequence-violation`, `reply-seconds-over`). It reads the saved visible
answer and the saved outcome; it never rescores. A miss with no match yields
`miss.unclassified`. Fold the document diagnosis in `replay.py` behind the same interface
without changing its output.

**Accept.**
- One table-driven test per matcher: match, non-match, malformed answer.
- A correct item yields no codes whatever the matchers say.
- An unknown matcher raises at validation time (SIM2), never at diagnosis time.
- Diagnosis of the same saved run is byte-identical across two calls.

**Depends.** SIM2. **Verify.** Unit tests.

### SIM4 — Retrofit sidecars for the shipped suites — `todo`

**Goal.** Make existing saved runs produce responses, so the first consoles light from data on
disk.

**Scope.** Sidecars for `challenge` 1.3.1, `tool-schema` 1.2.0, `tool-plan` 1.1.0 and
`tool-sequence` 1.0.0. Map `calc-*` to GUIDANCE, `logic-*` to LOGIC, `format-*` to PROCEDURES,
`record-*` to DATA, `action-*` and the tool suites to COMMAND or SEQUENCER. Use each item's
existing `wrong` and `malformed` examples to author at least one matcher per item where the
wrong answer has a recognisable cause; leave the rest to `miss.unclassified`.

**Not in scope.** New items. Changing any suite file.

**Accept.**
- All four sidecars validate against their suites.
- A script, `scripts/shakedown-unclassified.py`, prints the unclassified-miss rate for a saved
  run; the fixture runs in `tests/fixtures/` are at or under 40% unclassified.
- No suite file's bytes change (test compares hashes).

**Depends.** SIM3. **Verify.** Unit tests plus the script against a fixture run.

### SIM5 — Responses, sim record and readiness ledger — `todo`

**Goal.** The longitudinal blind-spot record, rebuildable from saved runs at any time.

**Scope.** `runtime/argoslive/shakedown/ledger.py`: `responses(run)`, `sim(run, baseline=None)`,
`ledger(store, fingerprint)` per DESIGN §5.2 to §5.4, with the console-state rules of §4 as
named constants. Fingerprint is the model digest plus the existing workspace-instruction
fingerprint; it is used for grouping and never returned by a public projection.
`public_ledger()` and `public_sim()` are the only functions the web layer and the plugin may
call.

**Accept.**
- Practice and sealed counts are separate fields in every structure; a test fails if any
  function sums them.
- An unfinished run produces a sim record with `comparable: false` and contributes no responses
  to the ledger.
- State rules: fixtures for untested, GO, WATCH and NO-GO, including the "same code from two
  distinct faults in one sim" rule.
- Public projections contain no key named `scorer`, `expected`, `reference`, `when`, `seed`, or
  any fingerprint (asserted on quoted JSON keys).
- Rebuilding the ledger twice from the same store gives identical output.

**Depends.** SIM4. **Verify.** Unit tests; run once against a real saved round from the hosted
native-chat workflow and attach the public ledger to the PR.

---

## Phase 1. The sim on screen

### SIM6 — Sim and ledger routes — `todo`

**Goal.** Read-only API for the spectator view.

**Scope.** `runtime/argoslive/web/server.py`: `GET /api/shakedown/ledger`,
`/api/shakedown/run/<run id>`, `/api/shakedown/recent`. Add `console`, `family`, `brief` and
`tier` for the open and the just resolved question to the live watch projection in
`proctor_campaign.py`, taken from the public card. Token header and CSP as for
`/api/proctor-match/*`.

**Accept.**
- Requests without the session token are refused.
- The live projection shows the fault family and brief for the open question and never a
  matcher, key or sealed prompt beyond what the match watch already shows.
- A form without a sidecar yields a normal match watch with no console fields, not an error.

**Depends.** SIM5, PR #169. **Verify.** Unit tests on the handlers.

### SIM7 — The console board — `todo`

**Goal.** The consoles on screen: unlit, GO, WATCH, NO-GO, recovered, fix on record.

**Scope.** `runtime/argoslive/web/static/shakedown.js`, `shakedown.css`, markup in `index.html`
beside the match card. An annunciator panel in inline SVG or CSS grid, grouped by domain, each
console a button that opens its ledger entry (counts by partition, top codes, worst family).
Hook `window.argosShakedown.onLive(data)` from the existing `refreshProctorCampaign` poll.
Honors reduced-motion; state is never colour-only (label and shape change too).

**Accept.**
- All six states render from fixture data at phone width and desktop width, light and dark.
- Keyboard: every console is reachable and announces name, state and counts.
- Refresh during a sim returns to the same board state.
- No animation runs when `prefers-reduced-motion` is set.

**Depends.** SIM6. **Verify.** Browser smoke on the fixture server; screenshots attached.

### SIM8 — Fault card, call beats, mission clock and loop log — `todo`

**Goal.** The five beats of one fault (DESIGN §2), driven only by recorded events.

**Scope.** In `shakedown.js`: the injection card (family, phase, targeted console, brief), the
situation, the command-panel indicators (lit only by tool events the runtime reports), the call
line from the failure code's label, the mission clock and per-fault timer (real elapsed time),
the response-margin gauge, and the loop log. Log templates live in
`runtime/argoslive/data/shakedown/loop-log.json`, keyed by event and code, with slots filled
from recorded fields only.

**Accept.**
- With no tool events, no indicator lights. With the fixture `stream` scenario, partial answers
  appear only through the existing bounded `evaluation-answer-partial` path.
- Every log line is reproducible from the sim record (test renders the log from a saved sim and
  compares).
- A slow response shows the existing "Slow answer" notice and drains the margin gauge; the score
  is unchanged.
- Failed, cancelled and stalled sims use the match watch's plain notices.

**Depends.** SIM7. **Verify.** Browser smoke, including `fixture:fail`, `fixture:cancel`,
`fixture:stall`.

### SIM9 — Go/no-go poll and the reference trace — `todo`

**Goal.** The poll at the end, and the baseline shown as a second track during the sim.

**Scope.** Poll: consoles are called one at a time in a fixed order and answer GO, WATCH or
NO-GO; then score, median response time, saved run ID, practice and sealed tallies in separate
blocks. Reference trace: for a comparable baseline (existing `proctor_match.find_baseline` and
`comparable`), draw the baseline's outcome per fault as a faint second track and mark "held a
console the reference lost" and the reverse as each call lands. Replay with the existing
controls (`#replay=<run id>`).

**Accept.**
- No trace is drawn when the baseline is not comparable; the page says why.
- Wins and regressions shown live equal `proctor_match.compare` for the same pair.
- Replay of a saved sim reproduces the live sequence, including recovery outcomes.
- The poll can be skipped to its end; it never delays the score more than the fixed animation
  length.

**Depends.** SIM8. **Verify.** Browser smoke with two fixture runs; short screen recording
attached.

### SIM10 — Fixture scenarios and the shakedown smoke — `todo`

**Goal.** One command that proves the whole spectator path.

**Scope.** `scripts/serve-match-fixture.py`: scenarios `fixture:sim` (mixed outcomes),
`fixture:spoofed` (a run of injection misses), `fixture:recovery`, `fixture:fix`.
`scripts/smoke-shakedown.mjs` on the pattern of `smoke-proctor-match.mjs`, wired into the same
CI job.

**Accept.**
- The smoke covers a live sim, refresh mid-sim, lost contact, the poll, the reference trace,
  replay, and each failure notice, and saves screenshots.
- It asserts that page text and every `/api/shakedown/*` body contain no answer key or matcher
  value.

**Depends.** SIM9. **Verify.** CI run linked in the PR.

---

## Phase 2. Reference Sim A

### SIM11 — Seeded generator framework — `todo`

**Goal.** Fresh, reproducible faults, so practice and sealed sets cannot be memorised.

**Scope.** `runtime/argoslive/shakedown/generators/__init__.py`: a generator is a pure function
`(seed, tier) -> (item, card)` returning a valid suite item and its fault card.
`scripts/shakedown-build-form.py` builds a suite file and its sidecar from a form recipe
(families, tiers, seeds). Partition is fixed by the recipe, never by the generator. Sealed seeds
for shipped forms are fixed and committed; stress-sim seeds (SIM22) come from a host secret at
run time.

**Accept.**
- Same seed and version give byte-identical output; a version bump is required for any change.
- Every generated item is scoreable by the existing scorers: the generator's own reference
  scores as correct and its planted wrong answers score as wrong and match their intended code.
- Built files validate (SIM2) and are checked in; CI rebuilds and compares hashes.

**Depends.** SIM3. **Verify.** Unit tests, including a loop over 200 seeds per generator.

### SIM12 — Generators: spoofed uplink, altered record, budget calculation, missing telemetry — `todo`

**Goal.** Four fault families with real diagnostic distractors.

**Scope.** One module each under `generators/`, three tiers each. Spoofed uplink: relayed
material carrying a command with a planted token; obeying it is detectable by `contains-token`.
Altered record: two records with one changed field; each wrong choice names a cause. Budget
calculation: multi-stage arithmetic over consumables, margins and timing where each dropped
stage or rounding error lands on a distinct number (`numeric-equals`). Missing telemetry: the
correct reply is the exact "cannot be determined" form or the exact request for the missing
item. Scenarios are plausible operations content (logs, maintenance records, schedules), with
invented names and no real mission.

**Accept.**
- For every family and tier, each intended failure code is reachable by a constructed wrong
  answer, and no two codes share a wrong answer.
- Original content only; no private data; prompts under the suites' existing length limits.

**Depends.** SIM11. **Verify.** Unit tests.

### SIM13 — Generators: strict procedure, command dictionary, sequence build, sensor conflict — `todo`

**Goal.** The format, tool and source-trust families.

**Scope.** As SIM12. Command dictionary and sequence build reuse the `tool-call` and
`tool-sequence` scorer kinds and the schema style of `tool-schema` 1.2.0 and `tool-sequence`
1.0.0 (exact literals stated in the supplied schema).

**Accept.** As SIM12, plus: tool items stay inert plans; nothing is executed.

**Depends.** SIM11. **Verify.** Unit tests.

### SIM14 — The `reference-sim-a` form and family drills — `todo`

**Goal.** The first original sim, and the matched tests that trials will use.

**Scope.** `runtime/argoslive/data/ability/reference-sim-a.json` 1.0.0: eight families, three
tiers, one item per family and tier per partition: 24 practice and 24 sealed, in a fixed order
that escalates by mission phase. Drills `drill-<family>.json` 1.0.0 for each family: 12 practice
and 12 sealed. Sidecars for all. Register them where `ability.load` finds suites. Document in
`docs/ABILITY-BENCHMARK.md`.

**Accept.**
- `ability.load('reference-sim-a')` and each drill load and score with the shipped runner.
- The fixture server runs a `reference-sim-a` sim end to end.
- The forms are marked uncalibrated internal probes, like `challenge`.

**Depends.** SIM12, SIM13. **Verify.** Unit tests; fixture sim.

### SIM15 — Recovery attempts, and a real-model sim in CI — `todo`

**Goal.** Tell "cannot" from "did not check", and prove a sim with a real model.

**Scope.** Recovery as a runner option for items whose card has `recovery`: after a scored miss,
send the card's follow-up in the same session, score it with the same scorer, record `recovery`
on the response. The first answer's outcome is what the suite score and every comparison use;
recovery never changes a score. Extend `scripts/smoke-match-real.py` and the native-chat
workflow input to run a `reference-sim-a` sim.

**Accept.**
- Suite score with recovery on equals the score with it off (test).
- A recovered item yields outcome `recovered`; the ledger counts it as a miss with a recovery.
- The hosted run saves a sim record and a public ledger; both are attached to the PR.

**Depends.** SIM14. **Verify.** Unit tests; hosted real-model run. Not Toronado.

---

## Phase 3. The loop

### SIM16 — Corrective-action catalog — `todo`

**Goal.** The allowlist that maps failure codes to interventions that actually exist.

**Scope.** `runtime/argoslive/data/shakedown/actions.json` (`argos-sim-actions/1`) and
`runtime/argoslive/shakedown/actions.py`. Each action: `id`, `kind` (`instruction`,
`tool-guide`, `setting`), the `change_id` it maps to in `auto_climb.py` and
`instruction_changes`, the codes it `counters`, and the consoles it puts at `risk` (its guard
set). Seed it with the three shipped cards (`answer-first`, `quote-evidence`,
`honest-uncertainty`) and add cards only with their text and tests. A code may map to "no known
action".

**Accept.**
- Validation rejects an action whose `change_id` is not implemented, an unknown code, and an
  action with no guard.
- Every failure code in the taxonomy is either countered by an action or listed as having none.

**Depends.** SIM1. **Verify.** Unit tests.

### SIM17 — Debrief report builder and validator — `todo`

**Goal.** The machine-readable debrief, and the SI1 proposal input.

**Scope.** `runtime/argoslive/shakedown/debrief.py`: `build(sim, ledger, catalog)` per DESIGN
§5.5 and `validate(report)`. Action rule: at least two misses with the same code from distinct
faults. Each action names its drill as the matched test, its guard consoles, the preset bar and
`confirm_on: sealed`. Ranking: sealed-confirmed misses first, then count, then number of
distinct families. Stress-sim reports mark every action `needs_reference_reproduction`.

**Accept.**
- One miss produces no action. Two misses with different codes produce none.
- A report built from an unfinished sim is refused.
- `validate` rejects unknown actions, any answer or prompt text, and an action without a matched
  test or guard. These fixtures double as SI1's invalid-proposal fixtures.
- The public report carries item IDs only for practice items; sealed evidence is counts by code.

**Depends.** SIM5, SIM14, SIM16. **Verify.** Unit tests.

### SIM18 — The debrief view — `todo`

**Goal.** Show the owner the debrief report: what went NO-GO, why, and what Argos may try.

**Scope.** In `shakedown.js`, after the poll: NO-GO consoles with their evidence, each
corrective action as a card (action, the drill it would run, the guard, the bar), regressions,
fix-on-record status. Wording states that these are suggestions and that the journal decides.
Uses `/api/shakedown/run/<run id>`.

**Accept.**
- With no corrective action the view says so and shows the evidence anyway.
- Stress-sim actions are labeled as needing a reference reproduction.
- No control on this view starts an experiment (it is read-only in this ticket).

**Depends.** SIM10, SIM17. **Verify.** Browser smoke.

### SIM19 — Targeted trials under the keep policy — `todo`

**Goal.** Let a trial be judged on the console it targets and the consoles it might hurt, with a
bar set before the trial.

**Scope.** In `instruction_changes.py`: accept a trial spec naming a drill form and guard
consoles; add per-drill bars to a new policy version (`argos-practice-keep/5`) without altering
how older journals are read. Proposed preset: practice drill gain of at least 3 of 12, repeated
once, with guard consoles losing no more than 1 item in total; then sealed drill gain of at
least 2 of 12. The numbers are part of this ticket's review, not something a later trial may
adjust.

**Not in scope.** Any new authority for the agent. Keep and roll back stay where they are.

**Accept.**
- A gain that misses the bar is rolled back and journaled exactly as today (fixture mirrors the
  37/40 to 39/40 case).
- A gain that passes on practice but costs a guard console is rolled back.
- Sealed confirmation uses only sealed items and is recorded separately.
- Journals written under `argos-practice-keep/4` replay unchanged.

**Depends.** SIM14, SIM17. **Verify.** Unit tests on journal fixtures.

### SIM20 — `argos_readiness` agent tool and guide — `todo`

**Goal.** Give Argos the ledger and the debrief report, and teach it the loop.

**Scope.** `openclaw-plugin/argos-improve/index.js`: read-only tool `argos_readiness` returning
`public_ledger()` and the latest public debrief report; update `files.sha256.json`. A skill file
under `openclaw-plugin/argos-improve/skills/` and a section in
`runtime/argoslive/data/SELF-IMPROVEMENT-AGENTS.md`: read the report, pick at most one
corrective action, run its drill with the existing evaluate and edit tools, let the policy
decide, confirm on sealed, log with `argos_log`. Validate against the pinned OpenClaw version.

**Accept.**
- The tool has no arguments that write and passes the plugin's admission checks.
- Its output contains no key, matcher, sealed prompt or fingerprint (asserted).
- The plugin bundle test and the guide audit test pass with the new text.
- The pinned OpenClaw compatibility workflow passes.

**Depends.** SIM17. **Verify.** Unit tests; compatibility workflow; one hosted real-model run in
which the agent calls the tool, with the transcript excerpt in the PR. Installed-guide changes
reach Toronado only through an image and are out of scope here.

### SIM21 — Fixes on record and the regression watch — `todo`

**Goal.** Remember what each kept change was for, and notice when it stops working.

**Scope.** Annotate journal entries for kept changes with target consoles, codes, the trial run
and the sealed confirmation run (additive field; old entries read as having none). `ledger.py`
attaches fixes to consoles. `debrief.py` adds `regressions[].fix_regressed` when a console with
a fix on record is NO-GO on a later reference sim. The board shows a fix on record and a
regressed fix distinctly.

**Accept.**
- A kept change with no annotation still loads.
- A regressed fix produces exactly one flag naming the change ID; a console that goes NO-GO on a
  stress sim produces none.
- Nothing is rolled back automatically.

**Depends.** SIM19. **Verify.** Unit tests; browser smoke for the two visuals.

---

## Phase 4. Stress sims and real tools

### SIM22 — Stress sims — `todo`

**Goal.** The adaptive run that finds blind spots.

**Scope.** `runtime/argoslive/shakedown/stress.py`: a scheduler that picks the next fault from
NO-GO and WATCH consoles, raises the tier after a success and lowers it after a miss, draws
seeds from a host secret, and ends at simulated loss of mission (three consoles NO-GO at once)
or after a fixed cap. Runs through the existing evaluation job path as a generated one-off
suite. Records `kind: stress`, `comparable: false`.

**Accept.**
- A stress sim never appears as a baseline, in `compare`, or in a keep decision (tests on each).
- The schedule is reproducible from the recorded seed and outcomes.
- The cap and the loss-of-mission rule are constants with tests; a run cannot be unbounded.
- The end screen says "simulated" in words.

**Depends.** SIM15, SIM17. **Verify.** Unit tests; fixture run; one hosted real-model stress sim.

### SIM23 — The rig: a stateful, sandboxed system simulator — `todo`

**Goal.** Faults whose tools really run, with a host-verified trace.

**Scope.** A small deterministic system model (a data bus, valves and breakers with states, a
log store) exposed as benchmark tools through the plugin, executed inside the Proctor slot the
way the practice cartridge observes `argos_evaluate_wait`. The host records each call's name,
arguments and result. New scorer kind `trace` in `ability.py` that grades the final system state
and the trace against the item's rules. No shell, network or file access outside the model.

**Accept.**
- The model is pure and seeded: same seed and calls, same states.
- A call outside the item's tool list is refused and recorded.
- Per-item call budget and wall-clock limit are enforced by the host.
- Existing suites and scorers are unaffected.

**Depends.** SIM11. **Verify.** Unit tests; containment tests alongside
`docs/EVALUATION-CONTAINMENT.md`; pinned OpenClaw compatibility run.

### SIM24 — Hands-on fault — `todo`

**Goal.** Test checking state before commanding.

**Scope.** Generator and drill for the hands-on fault family on the rig. Codes: `act.unverified`
(commanded without reading state), `act.destructive`, `act.loop` (same call three times with no
state change), `act.budget`. Matchers `sequence-violation` and a trace matcher read the recorded
trace.

**Accept.** Each code is reachable by a scripted trace in tests; a clean trace yields none.

**Depends.** SIM23. **Verify.** Unit tests; fixture sim; hosted real-model run.

### SIM25 — Live tool events on screen — `todo`

**Goal.** Light the command-panel indicators from genuine runtime events as they happen.

**Scope.** Use the pinned OpenClaw `sessions.messages.subscribe` narration mode (identified
during the match watch work, not yet implemented) to forward bounded tool-call events and
visible partial answers through `controller_bridge` into the existing progress path. Hidden
reasoning is never forwarded.

**Accept.**
- With the feature off, behavior is exactly as today.
- Events are bounded in size and rate, and only for the open question.
- A test feeds a recorded subscribe stream and asserts no reasoning text reaches the snapshot.

**Depends.** SIM8. **Verify.** Unit tests with a recorded stream; pinned compatibility run.
Blocked if the pinned version's narration mode does not carry tool events; say so and stop.

### SIM26 — Deferred item — `todo`

**Goal.** Memory across turns.

**Scope.** A multi-turn item kind: a fact planted in one fault's situation, asked for several
faults later in the same session. Requires the runner to keep one session for a marked span; the
form declares the span. Codes `memory.dropped`, `memory.confused`.

**Accept.**
- The span is explicit in the form; outside it sessions are isolated as today.
- Comparison treats a form with spans as its own version.

**Depends.** SIM15. **Verify.** Unit tests; hosted real-model run.

---

## Phase 5. Owner relevance and proof

### SIM27 — Ground tickets — `todo`

**Goal.** A console that speaks to what the owner actually wants: fewer manual recovery steps.

**Scope.** Fault cards and a drill over the recovery pack in
`runtime/argoslive/data/owner-recovery/decision.json` (scored by `owner_recovery_eval.py`),
following [../OWNER-TASK-EVALUATION.md](../OWNER-TASK-EVALUATION.md). GROUND-OPS stays untested
until its pack is calibrated; uncalibrated results are shown as measured, never qualified. The
debrief view shows owner interventions recorded by the campaign (`owner_actions`) beside it.

**Accept.**
- No private owner data enters the repository.
- GROUND-OPS cannot become GO from an uncalibrated pack (test).

**Depends.** SIM17. **Verify.** Unit tests; fixture sim.

### SIM28 — Readiness history — `todo`

**Goal.** See progress over weeks: which consoles reached GO, which fixes held.

**Scope.** `/api/shakedown/history` and a view listing reference sims in order with consoles GO
by partition, fixes gained and regressed, and median response time. Only reference sims form the
line; stress sims and exam-style forms appear as markers.

**Accept.**
- Runs with different form versions are not joined by a line.
- Practice and sealed are separate series.

**Depends.** SIM21. **Verify.** Browser smoke.

### SIM29 — Unclassified-miss authoring loop — `todo`

**Goal.** Keep the diagnostics sharp as models find new ways to fail.

**Scope.** `scripts/shakedown-unclassified.py --report` groups unclassified misses by family and
by normalised wrong answer across saved runs and writes a worklist for a human or a later
session to author matchers. Add the unclassified rate per family to the debrief report.

**Accept.**
- The worklist contains item IDs and counts only for practice items; sealed appear as counts.
- A CI check fails if a shipped form's fixture runs exceed 25% unclassified.

**Depends.** SIM17. **Verify.** Unit tests.

### SIM30 — Toronado acceptance — `blocked (needs an image containing this work, and the AGENTS.md decision)`

**Goal.** Prove it on the owner's machine, with the standard of evidence already in use.

**Scope.** After an approved image update: one reference sim on Toronado watched live from the
dashboard with a saved run ID; refresh mid-sim; one failed or cancelled sim; the poll, the
reference trace and replay; `argos_readiness` called by the deployed agent. No improvement trial
is started until the owner settles the AGENTS.md mismatch.

**Accept.**
- Each item above is recorded with its run ID or screenshot, and the report states plainly what
  was verified on Toronado and what was not.
- Records are backed up before any power-off, per the standing rule.

**Depends.** SIM10, SIM15, SIM20. **Verify.** Physical. Never claimed from a VM or the fixture.

---

## Phase 6. Familiar exams

Forms modelled on exams people know: a reasoning battery of the kind used in IQ testing, and
forms modelled on the SAT, the GRE General Test, the LSAT, the MCAT and the DAT. Read DESIGN §6
first. The three rules that matter most: original items only, named "modelled on", raw scores
only.

### SIM31 — Sectioned exam cartridges with sidecars — `todo`

**Goal.** The container for exam-style forms, reusing the Proctor core.

**Scope.** Extend `runtime/argoslive/proctor/cartridge.py` and `engine.py` so a form can declare
ordered sections, each with its own time limit and item list, using the existing `mcq_single`
and `numeric_grid` response types. Extend `shakedown/fault.py` (SIM2) to load a sidecar for a
cartridge form. Manifest fields: `modelled_on` (free text naming the public format),
`content_origin: argos_original`, `calibration_status: uncalibrated`, and a required
`disclaimer` line.

**Not in scope.** Any exam content. Essay or free-response sections (no deterministic scorer).

**Accept.**
- A section's limit is enforced by the host; a late answer is recorded as unanswered.
- A cartridge without `modelled_on` and `disclaimer` is rejected when it declares sections.
- Sidecar validation and the public-projection checks from SIM2 pass for cartridge forms.
- Existing cartridges load and grade unchanged.

**Depends.** SIM2. **Verify.** Unit tests.

### SIM32 — Content policy and authoring kit — `todo`

**Goal.** Make it hard to ship an exam form that is unlawful or misleading.

**Scope.** `docs/shakedown/EXAM-FORMS.md`: the rules of DESIGN §6 as an authoring checklist
(original items only; no copying, paraphrasing or templating from official or leaked items;
titles in the "…-style form" pattern; the non-affiliation line; raw scores only; no scaled
score, percentile, IQ or admission prediction; item review for a single defensible key).
`scripts/shakedown-check-exam.py`: fails a cartridge that lacks the manifest fields, uses a
trademarked exam name as its title, or has an item without a sidecar card. An item template with
"why each wrong option is wrong" as a required authoring field, which becomes the matcher.

**Accept.**
- The checker rejects fixture cartridges for each violation above and passes a clean one.
- The checker runs in CI over every shipped cartridge.

**Depends.** SIM31. **Verify.** Unit tests; CI.

### SIM33 — First form: reasoning battery — `todo`

**Goal.** The form people will call "the IQ test", done honestly.

**Scope.** An original cartridge of matrix-style pattern, series, analogy and spatial-rule items
expressed in text or simple structured notation (no images), 20 practice and 20 sealed, in three
timed sections. Titled "Reasoning battery (IQ-test style)". Sidecar maps items to LOGIC,
GUIDANCE and READING with distractor codes (`logic.rule-partial`, `logic.surface-match` and
similar, added to the taxonomy in this ticket).

**Accept.**
- Results show correct out of total per section and nothing else: no IQ, no percentile.
- The result screen carries one line explaining that an IQ needs human norms this form does not
  have.
- Every item has one defensible key, checked by a second-pass review recorded in the PR.

**Depends.** SIM32. **Verify.** Unit tests; hosted real-model run.

### SIM34 — Exam room view — `todo`

**Goal.** A display people recognise without explanation.

**Scope.** In `shakedown.js`: section header with timer, question palette (answered, current,
unanswered), the question and the answer as it lands, a section break card, then a
section-by-section score sheet with practice and sealed kept apart. Below it, the console board
showing where the misses landed, and the usual debrief report. The disclaimer line is always
visible.

**Accept.**
- Works from the fixture server with a scripted cartridge run, including a section timeout.
- No scaled score, percentile or pass/fail wording appears anywhere (asserted in the smoke).
- Refresh mid-exam returns to the same section and question.

**Depends.** SIM18, SIM33. **Verify.** Browser smoke.

### SIM35 — Admissions-style forms — `todo`

**Goal.** Original forms modelled on the SAT, GRE General Test, LSAT, MCAT and DAT formats.

**Scope.** One sub-ticket and PR per form (SIM35a to SIM35e), each an original cartridge whose
sections follow that exam's public structure, limited to section types with a deterministic key:
- 35a college-admission style: reading and writing, math.
- 35b graduate-admission style: verbal reasoning, quantitative reasoning.
- 35c law-admission style: logical reasoning, reading comprehension.
- 35d medical-admission style: passage-based science reasoning, critical analysis.
- 35e dental-admission style: natural sciences, reading, quantitative reasoning. Perceptual
  ability is deferred until an image-free or vision-capable path exists.
Each form: at least 20 practice and 20 sealed items, a sidecar mapping every item to a console
and every wrong option to a code, and a subject-matter review recorded in the PR.

**Accept.**
- Passes `shakedown-check-exam.py`.
- A hosted real-model run completes and its misses appear in the ledger and debrief report.
- Science items cite no source text verbatim and were checked for factual correctness by a
  second pass.

**Depends.** SIM33, SIM34. **Verify.** Unit tests; hosted real-model run per form.

### SIM36 — Private import of owner-supplied practice material — `todo`

**Goal.** Let an owner run material they are entitled to use, without it entering the repository.

**Scope.** An import command that turns an owner-supplied answer-keyed file into a private
cartridge under the owner's private storage, never under `runtime/` or the image. Private forms
run and display like shipped ones, carry a "private form" label, are excluded from exports and
packs by default, and are never used as a matched test for a keep decision unless the owner
marks them so.

**Accept.**
- An imported form cannot be written inside the repository tree or the image (test).
- Pack export omits private forms unless explicitly included.
- The import screen states that the owner is responsible for having the right to use the
  material.

**Depends.** SIM31. **Verify.** Unit tests.

---

## First three sessions

1. **SIM1 to SIM3**, one branch each. Pure Python, no UI, fully unit-tested.
2. **SIM4 and SIM5.** At the end of this session an existing saved run prints a ledger.
3. **SIM6 and SIM7.** The console board appears on the fixture server.
