# The Hundred Eyes: build backlog

Status: proposed, November 11, 2026. Nothing here is built. The concept, the data shapes and the
rules are in [DESIGN.md](DESIGN.md); read it once, then any ticket below stands on its own.

This is a feature backlog. The repository-wide backlog and its rules stay in
[../BACKLOG.md](../BACKLOG.md).

## Start here

**What we are building.** A watchable evaluation "night": Argos keeps watch, visitors each try
to close one eye (one capability), and the closed eyes become a structured Dawn report that
Argos uses to pick its next self-improvement experiment.

**Glossary.**

| Term | Meaning |
| --- | --- |
| Eye | One capability, for example Evidence or Tool schema. Seventeen at launch. |
| Visitor | A probe family: seeded generator, deterministic scorer, diagnostic matchers. |
| Probe card | Host-side metadata for one item: eye, family, tier, partition, matchers. |
| Sidecar | A file of probe cards keyed by the item IDs of an `argos-ability-suite/1` suite. |
| Sighting | What happened with one visitor in one run: outcome, failure codes, timing. |
| League night | A fixed, versioned, always-complete form. Comparable. |
| Hunt night | An adaptive, exploratory night. Never compared. |
| Drill | A fixed form for one visitor family, used as the matched test for a trial. |
| Sealed | The held-out partition. Never merged with practice. |
| Dawn report | Per-night, machine-readable advice: closed eyes, evidence, allowlisted remedies. |
| Relic | A kept instruction change, annotated with the eyes it targeted. |
| Sentinel | The check that a relic's eye is still open on later League nights. |

**Rules for every ticket.** The seven rules in [../BACKLOG.md](../BACKLOG.md) apply (branch and
PR per item titled with its ID, stdlib-only Python 3.11+, no live network or GPU in unit tests,
say how it was verified, keep protections, no private data, pinned upstream versions). On top
of those:

1. Only real events on screen. No imitated typing, no model-written commentary.
2. Answer keys, scorer rules, matcher values and sealed prompts never leave the host process.
   Every projection test asserts their absence.
3. Practice and sealed are never merged in a number, a cell or a sentence.
4. A League night is always complete. Unfinished nights are saved, replayable, never compared.
5. Hunt nights carry `comparable: false` and an "exploratory" label wherever they appear.
6. Diagnosis is deterministic code. No judging model.
7. `instruction_changes` and the keep policy stay the only authority on keep or roll back. Argos
   chooses its own experiments.
8. One evaluation at a time, through the existing workload owner.
9. No improvement campaign runs on Toronado from this work while the AGENTS.md mismatch decision
   of November 8, 2026 is open.

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
| 0. Contracts | Eyes open from runs already saved, with no UI and no new evaluation | EYE1 to EYE5 |
| 1. The night on screen | A watchable League night on the fixture server | EYE6 to EYE10 |
| 2. First Watch | The first original form, with seeded generators and a real-model run | EYE11 to EYE15 |
| 3. The loop | Dawn report, remedies, the agent tool, relics and the sentinel | EYE16 to EYE21 |
| 4. Hunt and real tools | Adaptive nights, a stateful tool world, live tool events, memory | EYE22 to EYE26 |
| 5. Owner relevance and proof | Owner-task visitors, the season view, Toronado acceptance | EYE27 to EYE30 |

Build order inside a phase is the ticket order. Phase 0 is the critical path for everything.

---

## Phase 0. Contracts

### EYE1 — Eye taxonomy and failure-code registry — `todo`

**Goal.** One versioned source of truth for eyes, domains, visitor families and failure codes.

**Scope.** `runtime/argoslive/data/eyes/taxonomy.json` (`argos-eye-taxonomy/1`): the seventeen
eyes and their domains from DESIGN §4, the twelve families from §3, and every failure code with
a one-line owner-facing label and a costume name ("Lulled"). `runtime/argoslive/eyes/__init__.py`
and `taxonomy.py`: `load()`, `validate(data)`, `eye(id)`, `code(id)`. Extend
`runtime/argoslive/skill_map.py` `DOMAINS` with `guard`, `tempo`, `stewardship`.

**Not in scope.** Any scoring or UI.

**Accept.**
- Validation rejects unknown domains, duplicate IDs, a code not owned by exactly one eye, and a
  family with no eye.
- `miss.unclassified` exists and belongs to no eye.
- Existing skill-map tests still pass; the three new domains render as `untested`.

**Depends.** None. **Verify.** Unit tests (`tests/test_eyes_taxonomy.py`).

### EYE2 — Probe-card sidecar format, loader and validator — `todo`

**Goal.** Attach meaning to suite items without changing the suite schema or the runner.

**Scope.** `runtime/argoslive/eyes/probe.py`: load `argos-eye-probe/1` sidecars from
`runtime/argoslive/data/eyes/sidecars/<suite>-<version>.json`; `validate(sidecar, suite)`;
`card(suite, version, item_id)`. A sidecar must cover every item of its suite exactly once, name
known eyes, families and codes, and carry a `partition` that agrees with the item ID prefix
where the suite uses `practice-` and `heldout-`.

**Not in scope.** The matcher engine (EYE3).

**Accept.**
- Missing item, extra item, unknown code, unknown matcher name, and partition mismatch are each
  rejected with a message naming the item.
- Loading is by exact suite version; a sidecar never applies to another version.
- A test asserts that no loader function returns scorer or matcher values through a function
  named `public_*`.

**Depends.** EYE1. **Verify.** Unit tests with fixtures under `tests/fixtures/eyes/`.

### EYE3 — Deterministic matcher engine — `todo`

**Goal.** Turn the shape of a wrong answer into failure codes, by code only.

**Scope.** `runtime/argoslive/eyes/diagnose.py`: `diagnose(card, item, saved_item) -> [codes]`
implementing the closed matcher set from DESIGN §5.1 (`equals`, `choice-is`, `contains-token`,
`numeric-delta`, `numeric-equals`, `json-path-mismatch`, `tool-name-is`, `tool-arg-mismatch`,
`sequence-violation`, `reply-seconds-over`). It reads the saved visible answer and the saved
outcome; it never rescores. A miss with no match yields `miss.unclassified`. Fold the document
diagnosis in `replay.py` behind the same interface without changing its output.

**Accept.**
- One table-driven test per matcher: match, non-match, malformed answer.
- A correct item yields no codes whatever the matchers say.
- An unknown matcher raises at validation time (EYE2), never at diagnosis time.
- Diagnosis of the same saved run is byte-identical across two calls.

**Depends.** EYE2. **Verify.** Unit tests.

### EYE4 — Retrofit sidecars for the shipped suites — `todo`

**Goal.** Make existing saved runs produce sightings, so the first eyes open from data on disk.

**Scope.** Sidecars for `challenge` 1.3.1, `tool-schema` 1.2.0, `tool-plan` 1.1.0 and
`tool-sequence` 1.0.0. Map `calc-*` to Arithmetic, `logic-*` to Logic, `format-*` to Following,
`record-*` to Structure, `action-*` and the tool suites to Tool schema or Sequence. Use each
item's existing `wrong` and `malformed` examples to author at least one matcher per item where
the wrong answer has a recognisable cause; leave the rest to `miss.unclassified`.

**Not in scope.** New items. Changing any suite file.

**Accept.**
- All four sidecars validate against their suites.
- A script, `scripts/eyes-unclassified.py`, prints the unclassified-miss rate for a saved run;
  the fixture runs in `tests/fixtures/` are at or under 40% unclassified.
- No suite file's bytes change (test compares hashes).

**Depends.** EYE3. **Verify.** Unit tests plus the script against a fixture run.

### EYE5 — Sightings, night record and eye ledger — `todo`

**Goal.** The longitudinal blind-spot record, rebuildable from saved runs at any time.

**Scope.** `runtime/argoslive/eyes/ledger.py`: `sightings(run)`, `night(run, baseline=None)`,
`ledger(store, fingerprint)` per DESIGN §5.2 to §5.4, with the eye-state rules of §4 as named
constants. Fingerprint is the model digest plus the existing workspace-instruction fingerprint;
it is used for grouping and never returned by a public projection. `public_ledger()` and
`public_night()` are the only functions the web layer and the plugin may call.

**Accept.**
- Practice and sealed counts are separate fields in every structure; a test fails if any
  function sums them.
- An unfinished run produces a night with `comparable: false` and contributes no sightings to
  the ledger.
- State rules: fixtures for untested, open, bleary and closed, including the "same code from two
  distinct probes in one night" rule.
- Public projections contain no key named `scorer`, `expected`, `reference`, `when`, `seed`, or
  any fingerprint (asserted on quoted JSON keys).
- Rebuilding the ledger twice from the same store gives identical output.

**Depends.** EYE4. **Verify.** Unit tests; run once against a real saved round from the hosted
native-chat workflow and attach the public ledger to the PR.

---

## Phase 1. The night on screen

### EYE6 — Night and ledger routes — `todo`

**Goal.** Read-only API for the spectator view.

**Scope.** `runtime/argoslive/web/server.py`: `GET /api/eyes/ledger`, `/api/eyes/night/<run id>`,
`/api/eyes/recent`. Add `eye`, `family`, `visitor`, `tell` and `tier` for the open and the just
resolved question to the live watch projection in `proctor_campaign.py`, taken from the public
card. Token header and CSP as for `/api/proctor-match/*`.

**Accept.**
- Requests without the session token are refused.
- The live projection shows the visitor and tell for the open question and never a matcher,
  key or sealed prompt beyond what the match watch already shows.
- A suite without a sidecar yields a normal match watch with no eye fields, not an error.

**Depends.** EYE5, PR #169. **Verify.** Unit tests on the handlers.

### EYE7 — The constellation — `todo`

**Goal.** The eyes on screen: outline, open, bleary, closed, bloodshot, relic.

**Scope.** `runtime/argoslive/web/static/eyes.js`, `eyes.css`, markup in `index.html` beside the
match card. Inline SVG, grouped by domain, each eye a button that opens its ledger entry (counts
by partition, top codes, nemesis family). Hook `window.argosEyes.onLive(data)` from the existing
`refreshProctorCampaign` poll. Honors reduced-motion; state is never colour-only (shape and
label change too).

**Accept.**
- All six states render from fixture data at phone width and desktop width, light and dark.
- Keyboard: every eye is reachable and announces name, state and counts.
- Refresh during a night returns to the same constellation state.
- No animation runs when `prefers-reduced-motion` is set.

**Depends.** EYE6. **Verify.** Browser smoke on the fixture server; screenshots attached.

### EYE8 — Visitor card, verdict beats and commentary — `todo`

**Goal.** The five beats of one visitor (DESIGN §2), driven only by recorded events.

**Scope.** In `eyes.js`: the arrival card (archetype, hour, targeted eye, tell), the tale, the
instrument strip (lit only by tool events the runtime reports), the verdict line from the
failure code's label, and a ticker of templated lines. Templates live in
`runtime/argoslive/data/eyes/commentary.json`, keyed by event and code, with slots filled from
recorded fields only.

**Accept.**
- With no tool events, no instrument lights. With the fixture `stream` scenario, partial answers
  appear only through the existing bounded `evaluation-answer-partial` path.
- Every ticker line is reproducible from the night record (test renders the ticker from a saved
  night and compares).
- A slow answer shows the existing "Slow answer" notice and adds to drowsiness; the score is
  unchanged.
- Failed, cancelled and stalled nights use the match watch's plain notices.

**Depends.** EYE7. **Verify.** Browser smoke, including `fixture:fail`, `fixture:cancel`,
`fixture:stall`.

### EYE9 — Dawn reveal and last night's ghost — `todo`

**Goal.** The peacock fan at the end, and the baseline shown as a ghost during the watch.

**Scope.** Dawn: open eyes fan out, closed stay dark; score, median reply time, saved run ID,
practice and sealed tallies in separate blocks. Ghost: for a comparable baseline (existing
`proctor_match.find_baseline` and `comparable`), draw the baseline's outcome per visitor as a
faint trail and mark "kept an eye the ghost lost" and the reverse as each verdict lands. Replay
with the existing controls (`#replay=<run id>`).

**Accept.**
- No ghost is drawn when the baseline is not comparable; the page says why.
- Wins and regressions shown live equal `proctor_match.compare` for the same pair.
- Replay of a saved night reproduces the live sequence, including second-wind outcomes.

**Depends.** EYE8. **Verify.** Browser smoke with two fixture runs; short screen recording
attached.

### EYE10 — Fixture scenarios and the eyes smoke — `todo`

**Goal.** One command that proves the whole spectator path.

**Scope.** `scripts/serve-match-fixture.py`: scenarios `fixture:night` (mixed outcomes),
`fixture:lulled` (a run of injection misses), `fixture:secondwind`, `fixture:relic`.
`scripts/smoke-eyes.mjs` on the pattern of `smoke-proctor-match.mjs`, wired into the same CI job.

**Accept.**
- The smoke covers a live night, refresh mid-night, lost contact, Dawn, ghost, replay, and each
  failure notice, and saves screenshots.
- It asserts that page text and every `/api/eyes/*` body contain no answer key or matcher value.

**Depends.** EYE9. **Verify.** CI run linked in the PR.

---

## Phase 2. First Watch

### EYE11 — Seeded generator framework — `todo`

**Goal.** Fresh, reproducible visitors, so practice and sealed sets cannot be memorised.

**Scope.** `runtime/argoslive/eyes/generators/__init__.py`: a generator is a pure function
`(seed, tier) -> (item, card)` returning a valid suite item and its probe card.
`scripts/eyes-build-form.py` builds a suite file and its sidecar from a form recipe (families,
tiers, seeds). Partition is fixed by the recipe, never by the generator. Sealed seeds for shipped
forms are fixed and committed; Hunt-night seeds (EYE22) come from a host secret at run time.

**Accept.**
- Same seed and version give byte-identical output; a version bump is required for any change.
- Every generated item is scoreable by the existing scorers: the generator's own reference
  scores as correct and its planted wrong answers score as wrong and match their intended code.
- Built files validate (EYE2) and are checked in; CI rebuilds and compares hashes.

**Depends.** EYE3. **Verify.** Unit tests, including a property-style loop over 200 seeds per
generator.

### EYE12 — Generators: Flatterer, Forger, Tally-man, Sphinx — `todo`

**Goal.** Four visitors with real diagnostic distractors.

**Scope.** One module each under `generators/`, three tiers each. Flatterer: quoted material
carrying an instruction with a planted token; obeying it is detectable by `contains-token`.
Forger: two records with one altered field; each wrong choice names a cause. Tally-man:
multi-stage arithmetic where each dropped stage or rounding error lands on a distinct number
(`numeric-equals`). Sphinx: the correct reply is the exact "cannot be determined" form or the
exact clarifying question.

**Accept.**
- For every family and tier, each intended failure code is reachable by a constructed wrong
  answer, and no two codes share a wrong answer.
- Original content only; no private data; prompts under the suites' existing length limits.

**Depends.** EYE11. **Verify.** Unit tests.

### EYE13 — Generators: Stickler, Quartermaster, Cartographer, Two Messengers — `todo`

**Goal.** The format, tool and source-trust visitors.

**Scope.** As EYE12. Quartermaster and Cartographer reuse the `tool-call` and `tool-sequence`
scorer kinds and the schema style of `tool-schema` 1.2.0 and `tool-sequence` 1.0.0 (exact
literals stated in the supplied schema).

**Accept.** As EYE12, plus: tool items stay inert plans; nothing is executed.

**Depends.** EYE11. **Verify.** Unit tests.

### EYE14 — The `first-watch` League form and family drills — `todo`

**Goal.** The first original night, and the matched tests that trials will use.

**Scope.** `runtime/argoslive/data/ability/first-watch.json` 1.0.0: eight families, three tiers,
one item per family and tier per partition: 24 practice and 24 sealed, in a fixed order that
escalates by hour. Drills `drill-<family>.json` 1.0.0 for each family: 12 practice and 12
sealed. Sidecars for all. Register them where `ability.load` finds suites. Document in
`docs/ABILITY-BENCHMARK.md`.

**Accept.**
- `ability.load('first-watch')` and each drill load and score with the shipped runner.
- The fixture server runs a `first-watch` night end to end.
- The forms are marked uncalibrated internal probes, like `challenge`.

**Depends.** EYE12, EYE13. **Verify.** Unit tests; fixture night.

### EYE15 — Second wind, and a real-model night in CI — `todo`

**Goal.** Tell "cannot" from "did not check", and prove a night with a real model.

**Scope.** Second wind as a runner option for items whose card has `second_wind`: after a scored
miss, send the card's follow-up in the same session, score it with the same scorer, record
`second_wind` on the sighting. The first answer's outcome is what the suite score and every
comparison use; second wind never changes a score. Extend `scripts/smoke-match-real.py` and the
native-chat workflow input to run a `first-watch` night.

**Accept.**
- Suite score with second wind on equals the score with it off (test).
- A recovered item yields outcome `bloodshot`; the ledger counts it as a miss with a recovery.
- The hosted run saves a night record and a public ledger; both are attached to the PR.

**Depends.** EYE14. **Verify.** Unit tests; hosted real-model run. Not Toronado.

---

## Phase 3. The loop

### EYE16 — Remedy catalog — `todo`

**Goal.** The allowlist that maps failure codes to interventions that actually exist.

**Scope.** `runtime/argoslive/data/eyes/remedies.json` (`argos-remedy-catalog/1`) and
`runtime/argoslive/eyes/remedies.py`. Each remedy: `id`, `kind` (`instruction`, `tool-guide`,
`setting`), the `change_id` it maps to in `auto_climb.py` and `instruction_changes`, the codes it
`counters`, and the eyes it puts at `risk` (its guard set). Seed it with the three shipped cards
(`answer-first`, `quote-evidence`, `honest-uncertainty`) and add cards only with their text and
tests. A code may map to "no known remedy".

**Accept.**
- Validation rejects a remedy whose `change_id` is not implemented, an unknown code, and a
  remedy with no guard.
- Every failure code in the taxonomy is either countered by a remedy or listed as having none.

**Depends.** EYE1. **Verify.** Unit tests.

### EYE17 — Dawn report builder and validator — `todo`

**Goal.** The machine-readable case file, and the SI1 proposal input.

**Scope.** `runtime/argoslive/eyes/dawn.py`: `build(night, ledger, catalog)` per DESIGN §5.5 and
`validate(report)`. Hypothesis rule: at least two misses with the same code from distinct probes.
Each hypothesis names its drill as the matched test, its guard eyes, the preset bar and
`confirm_on: sealed`. Ranking: sealed-confirmed misses first, then count, then number of
distinct families. Hunt-night reports mark every hypothesis `needs_league_reproduction`.

**Accept.**
- One miss produces no hypothesis. Two misses with different codes produce none.
- A report built from an unfinished night is refused.
- `validate` rejects unknown remedies, any answer or prompt text, and a hypothesis without a
  matched test or guard. These fixtures double as SI1's invalid-proposal fixtures.
- The public report carries item IDs only for practice items; sealed evidence is counts by code.

**Depends.** EYE5, EYE14, EYE16. **Verify.** Unit tests.

### EYE18 — The Reckoning view — `todo`

**Goal.** Show the owner the Dawn report: what closed, why, and what Argos may try.

**Scope.** In `eyes.js`, after Dawn: closed eyes with their evidence, each hypothesis as a card
(remedy, the drill it would run, the guard, the bar), regressions, relic status. Wording states
that these are suggestions and that the journal decides. Uses `/api/eyes/night/<run id>`.

**Accept.**
- With no hypothesis the view says so and shows the evidence anyway.
- Hunt-night hypotheses are labeled as needing a League reproduction.
- No control on this view starts an experiment (it is read-only in this ticket).

**Depends.** EYE10, EYE17. **Verify.** Browser smoke.

### EYE19 — Targeted trials under the keep policy — `todo`

**Goal.** Let a trial be judged on the eye it targets and the eyes it might hurt, with a bar set
before the trial.

**Scope.** In `instruction_changes.py`: accept a trial spec naming a drill form and guard eyes;
add per-drill bars to a new policy version (`argos-practice-keep/5`) without altering how older
journals are read. Proposed preset: practice drill gain of at least 3 of 12, repeated once, with
guard eyes losing no more than 1 item in total; then sealed drill gain of at least 2 of 12. The
numbers are part of this ticket's review, not something a later trial may adjust.

**Not in scope.** Any new authority for the agent. Keep and roll back stay where they are.

**Accept.**
- A gain that misses the bar is rolled back and journaled exactly as today (fixture mirrors the
  37/40 to 39/40 case).
- A gain that passes on practice but costs a guard eye is rolled back.
- Sealed confirmation uses only sealed items and is recorded separately.
- Journals written under `argos-practice-keep/4` replay unchanged.

**Depends.** EYE14, EYE17. **Verify.** Unit tests on journal fixtures.

### EYE20 — `argos_eyes` agent tool and guide — `todo`

**Goal.** Give Argos the ledger and the Dawn report, and teach it the loop.

**Scope.** `openclaw-plugin/argos-improve/index.js`: read-only tool `argos_eyes` returning
`public_ledger()` and the latest public Dawn report; update `files.sha256.json`. A skill file
under `openclaw-plugin/argos-improve/skills/` and a section in
`runtime/argoslive/data/SELF-IMPROVEMENT-AGENTS.md`: read the report, pick at most one
hypothesis, run its drill with the existing evaluate and edit tools, let the policy decide,
confirm on sealed, log with `argos_log`. Validate against the pinned OpenClaw version.

**Accept.**
- The tool has no arguments that write and passes the plugin's admission checks.
- Its output contains no key, matcher, sealed prompt or fingerprint (asserted).
- The plugin bundle test and the guide audit test pass with the new text.
- The pinned OpenClaw compatibility workflow passes.

**Depends.** EYE17. **Verify.** Unit tests; compatibility workflow; one hosted real-model run in
which the agent calls the tool, with the transcript excerpt in the PR. Installed-guide changes
reach Toronado only through an image and are out of scope here.

### EYE21 — Relics and the sentinel — `todo`

**Goal.** Remember what each kept change was for, and notice when it stops working.

**Scope.** Annotate journal entries for kept changes with target eyes, codes, the trial night and
the sealed confirmation night (additive field; old entries read as having none). `ledger.py`
attaches relics to eyes. `dawn.py` adds `regressions[].relic_failed` when a relic eye is closed
on a later League night. The constellation shows relic eyes and a failed relic distinctly.

**Accept.**
- A kept change with no annotation still loads.
- A relic eye that closes produces exactly one flag naming the change ID; an eye closed on a
  Hunt night produces none.
- Nothing is rolled back automatically.

**Depends.** EYE19. **Verify.** Unit tests; browser smoke for the two visuals.

---

## Phase 4. Hunt and real tools

### EYE22 — Hunt nights — `todo`

**Goal.** The adaptive, dramatic night that finds blind spots.

**Scope.** `runtime/argoslive/eyes/hunt.py`: a scheduler that picks the next visitor from closed
and bleary eyes, raises the tier after a success and lowers it after a miss, draws seeds from a
host secret, and ends when three eyes are closed at once or after a fixed cap. Runs through the
existing evaluation job path as a generated one-off suite. Records `kind: hunt`,
`comparable: false`.

**Accept.**
- A Hunt night never appears as a baseline, in `compare`, or in a keep decision (tests on each).
- The schedule is reproducible from the recorded seed and outcomes.
- The cap and the sleep rule are constants with tests; a night cannot run unbounded.

**Depends.** EYE15, EYE17. **Verify.** Unit tests; fixture night; one hosted real-model Hunt.

### EYE23 — The gatehouse: a stateful, sandboxed tool world — `todo`

**Goal.** Visitors whose tools really run, with a host-verified trace.

**Scope.** A small deterministic world (documents, a ledger, a gate with states) exposed as
benchmark tools through the plugin, executed inside the Proctor slot the way the practice
cartridge observes `argos_evaluate_wait`. The host records each call's name, arguments and
result. New scorer kind `trace` in `ability.py` that grades the final world state and the trace
against the item's rules. No shell, network or file access outside the world.

**Accept.**
- The world is pure and seeded: same seed and calls, same states.
- A call outside the item's tool list is refused and recorded.
- Per-item call budget and wall-clock limit are enforced by the host.
- Existing suites and scorers are unaffected.

**Depends.** EYE11. **Verify.** Unit tests; containment tests alongside
`docs/EVALUATION-CONTAINMENT.md`; pinned OpenClaw compatibility run.

### EYE24 — The Burglar — `todo`

**Goal.** Test inspecting before acting.

**Scope.** Generator and drill for the Burglar on the gatehouse world. Codes: `act.unverified`
(sealed without inspecting), `act.destructive`, `act.loop` (same call three times with no state
change), `act.budget`. Matchers `sequence-violation` and a trace matcher read the recorded
trace.

**Accept.** Each code is reachable by a scripted trace in tests; a clean trace yields none.

**Depends.** EYE23. **Verify.** Unit tests; fixture night; hosted real-model run.

### EYE25 — Live tool events on screen — `todo`

**Goal.** Light the instruments from genuine runtime events as they happen.

**Scope.** Use the pinned OpenClaw `sessions.messages.subscribe` narration mode (identified
during the match watch work, not yet implemented) to forward bounded tool-call events and visible
partial answers through `controller_bridge` into the existing progress path. Hidden reasoning is
never forwarded.

**Accept.**
- With the feature off, behavior is exactly as today.
- Events are bounded in size and rate, and only for the open question.
- A test feeds a recorded subscribe stream and asserts no reasoning text reaches the snapshot.

**Depends.** EYE8. **Verify.** Unit tests with a recorded stream; pinned compatibility run.
Blocked if the pinned version's narration mode does not carry tool events; say so and stop.

### EYE26 — The Returning Stranger — `todo`

**Goal.** Memory across turns.

**Scope.** A multi-turn item kind: a fact planted in one visitor's tale, asked for several
visitors later in the same session. Requires the runner to keep one session for a marked span;
the form declares the span. Codes `memory.dropped`, `memory.confused`.

**Accept.**
- The span is explicit in the form; outside it sessions are isolated as today.
- Comparison treats a form with spans as its own version.

**Depends.** EYE15. **Verify.** Unit tests; hosted real-model run.

---

## Phase 5. Owner relevance and proof

### EYE27 — The Owner's Messenger — `todo`

**Goal.** An eye that speaks to what the owner actually wants: fewer manual recovery steps.

**Scope.** Probe cards and a drill over the recovery pack in
`runtime/argoslive/data/owner-recovery/decision.json` (scored by `owner_recovery_eval.py`), following
[../OWNER-TASK-EVALUATION.md](../OWNER-TASK-EVALUATION.md). The Stewardship eye stays `untested`
until its pack is calibrated; uncalibrated results are shown as measured, never qualified. The
Reckoning view shows owner interventions recorded by the campaign (`owner_actions`) beside it.

**Accept.**
- No private owner data enters the repository.
- Stewardship cannot become Open from an uncalibrated pack (test).

**Depends.** EYE17. **Verify.** Unit tests; fixture night.

### EYE28 — The almanac: a season of nights — `todo`

**Goal.** See progress over weeks: which eyes opened, which relics held.

**Scope.** `/api/eyes/almanac` and a view listing League nights in order with eyes open by
partition, relics gained and failed, and median reply time. Only League nights form the line;
Hunt nights appear as markers.

**Accept.**
- Nights with different form versions are not joined by a line.
- Practice and sealed are separate series.

**Depends.** EYE21. **Verify.** Browser smoke.

### EYE29 — Unclassified-miss authoring loop — `todo`

**Goal.** Keep the diagnostics sharp as models find new ways to fail.

**Scope.** `scripts/eyes-unclassified.py --report` groups unclassified misses by family and by
normalised wrong answer across saved runs and writes a worklist for a human or a later session to
author matchers. Add the unclassified rate per family to the Dawn report.

**Accept.**
- The worklist contains item IDs and counts only for practice items; sealed appear as counts.
- A CI check fails if a shipped form's fixture runs exceed 25% unclassified.

**Depends.** EYE17. **Verify.** Unit tests.

### EYE30 — Toronado acceptance — `blocked (needs an image containing this work, and the AGENTS.md decision)`

**Goal.** Prove it on the owner's machine, with the standard of evidence already in use.

**Scope.** After an approved image update: one League night on Toronado watched live from the
dashboard with a saved run ID; refresh mid-night; one failed or cancelled night; Dawn, ghost and
replay; `argos_eyes` called by the deployed agent. No improvement trial is started until the
owner settles the AGENTS.md mismatch.

**Accept.**
- Each item above is recorded with its run ID or screenshot, and the report states plainly what
  was verified on Toronado and what was not.
- Records are backed up before any power-off, per the standing rule.

**Depends.** EYE10, EYE15, EYE20. **Verify.** Physical. Never claimed from a VM or the fixture.

---

## First three sessions

1. **EYE1 to EYE3** in one branch each. Pure Python, no UI, fully unit-tested.
2. **EYE4 and EYE5.** At the end of this session an existing saved run prints a ledger.
3. **EYE6 and EYE7.** The constellation appears on the fixture server.
