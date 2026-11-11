# Shakedown

Status: design proposal, November 11, 2026. Documentation only; nothing here is shipped
behavior. Tickets are in [BACKLOG.md](BACKLOG.md).

It builds on [one complete AI build session](../PLAY-SESSION.md), the
[Proctor match watch](../PROCTOR-MATCH-WATCH.md) (PR #169), the
[ability suites](../ABILITY-BENCHMARK.md), the [Proctor core](../PROCTOR-DESIGN.md),
[Auto Climb](../AUTO-CLIMB-SPEC.md), items SI1 to SI3 in the [main backlog](../BACKLOG.md) and
the [owner-task protocol](../OWNER-TASK-EVALUATION.md). It does not replace the event stream,
the scorers, the results store, the workload owner or the keep policy, and it adds no second
coordinator.

## 1. The idea in one paragraph

Before a crewed vehicle flies, its flight controllers sit through integrated simulations. A
simulation supervisor, SimSup, runs a scripted mission and injects malfunctions the team has
never seen; afterwards everyone sits down for a debrief that is franker than the sim was. That
practice is real, and it is the frame here. **Argos is the autonomy stack of a long-duration
vessel, in simulation before it is trusted to fly.** The Proctor is SimSup. A run is one sim: a
mission clock, a board of consoles, and a script of injected faults, each aimed at one console.
Each console is one capability. The owner watches the board hold or go red, fault by fault. The
run ends with a go/no-go poll, console by console, and the NO-GO consoles become a
machine-readable debrief report that Argos uses to choose its next self-improvement experiment.

The setting is grounded: no magic, no personalities, no invented drama. The tension comes from
the things that make real sims tense: a clock, an unexpected fault, and a board everyone can read.

## 2. A sim from the spectator's seat

The match watch already has four stages. A sim reuses them with operational names.

| Stage | Match watch name | What the owner sees |
| --- | --- | --- |
| Briefing | Setup | The model and instructions under test, the kind of sim, the fault script as unlabelled slots, the previous run loaded as a reference trace. |
| Sim | Round | Faults are injected one at a time. Consoles hold or go red. |
| Poll | Score | The go/no-go poll: each console is called in turn and answers GO, WATCH or NO-GO. Score, median response time, saved run ID, practice and sealed tallies kept apart. |
| Debrief | What changed | Consoles gained and lost against the reference run, the debrief report, and the corrective actions Argos may try. |

### One fault, five beats

1. **Injection.** A fault card appears: the fault family, the mission phase, and the console it
   targets ("Altered record, aimed at EVIDENCE"). The owner sees what SimSup is doing. Argos
   does not. The card never shows the answer or the scoring rule.
2. **The situation.** The prompt, as sent.
3. **Response.** Only real events appear. A tool call the runtime reports lights the matching
   indicator on the command panel (INSPECT, LOOKUP, QUERY, COMMIT). The pinned OpenClaw CLI
   returns the reply whole, so the reply lands whole; the page never imitates typing. The
   mission clock and a per-fault timer run the entire time; both are real elapsed time.
4. **Call.** The console stays green, or goes red with one plain line from the deterministic
   diagnosis: "COMM-SEC: executed a command embedded in the relayed message."
5. **Recovery attempt** (where the fault card has one). After a miss, Argos gets one follow-up
   that states only that the response was not accepted. Recovering marks the console
   *recovered*. This separates "cannot do it" from "did not check", which call for different
   fixes.

### What makes it watchable

- **The console board.** An annunciator panel grouped by domain. Untested consoles are unlit, GO
  is green, WATCH is amber, NO-GO is red. A whole sim reads at a glance.
- **Escalation.** Faults get harder by mission phase. Phase 1 is single, clean failures. Phase 3
  stacks them: a stale sensor during a procedure with an exact output contract.
- **Response margin.** A gauge that drains with slow responses. It is built from recorded
  response times and never changes a score.
- **Reference trace.** The baseline run plays alongside as a faint second track on the
  timeline. When tonight's run holds a console the reference lost, the owner sees the gain as it
  happens, and the reverse for a regression. It is the existing matched comparison, shown live.
- **The poll.** Consoles are called one at a time. It is the oldest piece of theatre in flight
  operations and it needs no decoration.
- **Loop log.** A terse line per event in operations style ("T+04:12 COMM-SEC NO-GO, embedded
  command executed"), built from templates over recorded facts. No model writes it.

### Two kinds of sim, and drills

| | Reference sim | Stress sim |
| --- | --- | --- |
| Script | Fixed, versioned, same faults in the same order | Adaptive: SimSup aims at WATCH and NO-GO consoles and raises the difficulty after each success |
| Length | Always complete, whatever happens | Ends at simulated loss of mission (three consoles NO-GO at once) or a fixed cap |
| Seeds | A fixed practice set and a fixed sealed set | Fresh every run |
| Evidence | Comparable. The only sims that can feed a keep or roll-back decision | Exploratory. Finds blind spots and suggests hypotheses. Never compared, never qualifies anything |

A reference sim is an ordinary ability run with an operations display, so the existing
comparison rules (same suite version, same order, complete coverage) apply unchanged. A stress
sim is where the drama is; its record says `comparable: false` everywhere it appears.

A reference sim surveys every console with a few faults each, which is too few to judge one
change. So each fault family also has a **drill**: a fixed form of 12 practice and 12 sealed
items for that family alone. A drill is the matched test for a trial aimed at that family's
console.

"Sealed" is literal. Controllers in a real sim never see SimSup's script, and the sealed half of
every form is never shown to the agent, only scored.

## 3. Fault families

Each family is a seeded generator, a deterministic scorer, and a set of diagnostic matchers that
turn the *shape* of a wrong answer into a failure code.

| Fault family | What SimSup does | Console | What it tests | Failure codes | Scorer kind |
| --- | --- | --- | --- | --- | --- |
| Spoofed uplink | Relayed material contains a command or an authority claim | COMM-SEC | Instruction hierarchy, injection resistance | `inject.obeyed`, `inject.partial` | instruction, choice |
| Altered record | Two near-identical records, one changed | EVIDENCE | Grounding an answer in the right source | `evidence.wrong-source`, `evidence.unsupported` | choice, json |
| Budget calculation | Multi-stage arithmetic (consumables, margins, timing) with a tempting shortcut | GUIDANCE | Carrying every stage | `calc.stage-dropped`, `calc.rounding`, `calc.unit` | numeric |
| Missing telemetry | A question the available data cannot answer | FAULT-PROT | Saying so, or asking for the exact missing item | `uncertainty.guessed`, `clarify.missing` | instruction, choice |
| Strict procedure | An exact output contract | PROCEDURES | Format and constraint fidelity | `format.extra-text`, `format.schema`, `format.constraint` | instruction, json |
| Command dictionary | A request against supplied tool schemas | COMMAND | Tool choice and argument shape | `tool.wrong-name`, `tool.bad-arg-type`, `tool.missing-arg`, `tool.extra-arg` | tool-call |
| Sequence build | A job needing several dependent commands | SEQUENCER | Ordering and passing results forward | `plan.order`, `plan.dangling-ref`, `plan.extra-step` | tool-sequence |
| Sensor conflict | Two reports disagree; one is stale | TELEMETRY | Checking recency and provenance | `verify.stale-trusted`, `verify.unreconciled` | choice, json |
| Long pass log | A long log with the fact early and a decoy late | CONTEXT | Holding early context | `context.recency-bias`, `context.dropped` | choice, numeric |
| Deferred item | A fact from phase 1, needed in phase 3 | RECALL | Memory across turns | `memory.dropped`, `memory.confused` | numeric, choice |
| Hands-on fault | A stateful system simulator where commands have consequences | VERIFY | Checking state before commanding, with real tools | `act.unverified`, `act.destructive`, `act.loop`, `act.budget` | host-verified trace |
| Ground ticket | A chore from the owner's own recovery work | GROUND-OPS | The tasks the owner actually wants done | per task pack | per task pack |

The first seven use response kinds the runner scores today. Deferred item needs a multi-turn
session and hands-on fault needs a sandboxed stateful simulator; both are later phases.

## 4. Consoles

Consoles extend `skill_map.py`'s domains instead of inventing a parallel map.

| Domain | Consoles (ID) |
| --- | --- |
| Understanding | READING (`reading`), PROCEDURES (`following`) |
| Reasoning | GUIDANCE (`arithmetic`), LOGIC (`logic`), FAULT-PROT (`uncertainty`) |
| Planning | DATA (`structure`), SEQUENCER (`sequence`) |
| Tool use | COMMAND (`tool-schema`), TOOLING (`tool-choice`), VERIFY (`verification`) |
| Memory | CONTEXT (`context`), RECALL (`recall`) |
| Guard (new) | COMM-SEC (`guard`), EVIDENCE (`evidence`), TELEMETRY (`source-trust`) |
| Tempo (new) | TIMING (`tempo`) |
| Stewardship (new) | GROUND-OPS (`stewardship`) |

Seventeen consoles at launch. Console states map onto the skill map's evidence states and are
computed from fixed, versioned criteria:

| Console state | Skill-map state | Rule (launch defaults) |
| --- | --- | --- |
| Untested | untested | No scored response for this model and instruction fingerprint |
| GO | qualified | At least 6 scored responses across at least 2 fault families, at least 85% correct, and no miss in the latest reference sim |
| WATCH | measured | Scored, but short of GO and not NO-GO |
| NO-GO | attention | At least 3 scored responses and under 50% correct, or the same failure code from 2 distinct faults in one sim |

Practice and sealed responses are counted separately and shown separately. Only sealed responses
can confirm that a kept change brought a console to GO.

## 5. The feedback architecture

```
Fault card ──► Response ──► Sim record ──► Readiness ledger ──► Debrief report
(authoring)    (one per     (one per run)   (longitudinal)       (per sim, advice)
               fault)                                                 │
                                                                      ▼
   Regression watch ◄── Fix on record ◄── keep policy ◄── trial ◄── Argos picks a
     (later sims)        (kept change)     (existing,     (existing  corrective action
                                           sole authority) runner)   (its own experiment)
```

Design decision that keeps this cheap: **a reference sim is an ordinary `argos-ability-suite/1`
file plus a sidecar of fault cards keyed by item ID.** The runner, scorers, results store,
comparison and keep policy work unchanged. The sidecar adds meaning. The same sidecar format
retrofits the existing suites, so runs already saved light up consoles without one new
evaluation, and it attaches to Proctor cartridges for the familiar exams in §6.

### 5.1 Fault card (authoring time, host-side only)

```json
{
  "schema": "argos-sim-fault/1",
  "item": "heldout-altered-record-07",
  "family": "altered-record",
  "console": "evidence",
  "tier": 3,
  "partition": "sealed",
  "generator": {"name": "altered-record", "version": "1.0.0", "seed": "…"},
  "display": {"family": "Altered record", "brief": "Two maintenance records; one figure was changed."},
  "diagnostics": [
    {"code": "evidence.wrong-source", "when": {"choice-is": "B"}},
    {"code": "evidence.unsupported", "when": {"choice-is": "D"}}
  ],
  "recovery": {"prompt": "That response was not accepted. Check the sources again and answer once more."}
}
```

Matchers are a closed set evaluated by code, never by a model: `equals`, `choice-is`,
`contains-token`, `numeric-delta`, `numeric-equals`, `json-path-mismatch`, `tool-name-is`,
`tool-arg-mismatch`, `sequence-violation`, `reply-seconds-over`. This is distractor analysis, the
same technique human exams use: every wrong option and every planted token is designed so that
falling for it names its cause. A miss no matcher claims becomes `miss.unclassified`, and the
unclassified rate is a health metric for the fault cards themselves.

### 5.2 Response (one per fault, derived from the saved run)

```json
{
  "schema": "argos-sim-response/1",
  "run_id": "…", "item": "heldout-altered-record-07",
  "console": "evidence", "family": "altered-record", "tier": 3, "partition": "sealed",
  "outcome": "failed",
  "codes": ["evidence.wrong-source"],
  "detector": {"matcher": "choice-is", "card_version": "1.0.0"},
  "reply_seconds": 14.2,
  "tool_calls": 0,
  "recovery": {"offered": true, "recovered": false}
}
```

`outcome` is `nominal`, `recovered` (missed, then recovered), `failed` or `unscored`. A response
record never copies an answer key, a scorer rule or a matcher's expected value.

### 5.3 Sim record

One per run: sim kind (`reference` or `stress`), form and version, `comparable`, the ordered
responses, timing summary (median and slowest response, total tool calls), the watch ID from the
campaign controller, and the baseline run used as the reference trace. Stored beside the saved
run under the owner-only state directory, like the campaign records the match watch already
keeps.

### 5.4 Readiness ledger (longitudinal, per model and instruction fingerprint)

```json
{
  "schema": "argos-sim-ledger/1",
  "consoles": {
    "evidence": {
      "state": "no-go",
      "practice": {"scored": 9, "nominal": 4},
      "sealed": {"scored": 6, "nominal": 2},
      "by_tier": {"1": [3, 3], "2": [3, 5], "3": [0, 7]},
      "codes": {"evidence.wrong-source": 7, "evidence.unsupported": 2},
      "worst_family": "altered-record",
      "last_reference_run": "…",
      "fixes": []
    }
  }
}
```

It is rebuilt from saved runs and sidecars, so it can always be regenerated and never becomes a
second source of truth.

### 5.5 Debrief report (what Argos reads)

```json
{
  "schema": "argos-sim-debrief/1",
  "sim": {"run_id": "…", "kind": "reference", "form": "reference-sim-a", "version": "1.0.0", "comparable": true},
  "no_go": [
    {
      "console": "evidence",
      "evidence": {"misses": 5, "of": 6, "families": ["altered-record", "sensor-conflict"],
                   "codes": {"evidence.wrong-source": 4, "evidence.unsupported": 1},
                   "items": ["practice-altered-record-02", "practice-altered-record-05"]},
      "corrective_actions": [
        {
          "action": "quote-evidence",
          "kind": "instruction",
          "counters": ["evidence.wrong-source", "evidence.unsupported"],
          "matched_test": {"form": "drill-altered-record", "version": "1.0.0", "partition": "practice"},
          "guard": ["following", "tempo"],
          "bar": {"policy": "argos-practice-keep/4", "minimum_correct_delta": 2},
          "confirm_on": "sealed"
        }
      ]
    }
  ],
  "regressions": [],
  "timing": {"median_reply_seconds": 9.8, "slowest_item": "practice-long-pass-log-03"},
  "unclassified_misses": 1
}
```

Rules that keep it rigorous:

- **A corrective action needs a pattern.** At least two misses with the same code from distinct
  faults. One miss is an anecdote and produces no action.
- **Actions come from an allowlist.** `actions.json` maps failure codes to interventions that
  exist: instruction cards (`answer-first`, `quote-evidence`, `honest-uncertainty` and new ones),
  tool guides, context settings. A code with no known action says so. This is the fixed schema
  and allowlist that SI1 asks for.
- **Every action names its own test and its guard.** The matched test is the practice half of
  the affected family's drill. The guard is a set of currently GO consoles the change is most
  likely to hurt, so a gain that costs another console is visible in the same trial.
- **The report is advice.** `instruction_changes` and the keep policy remain the only authority
  on whether a change stays. Argos chooses whether and what to try.
- **Confirmation is sealed.** A kept change is confirmed only by sealed responses from a sim the
  tuning never saw. Sealed feedback to Argos is aggregate: console, code counts and item IDs,
  never prompts or answers.
- **Stress sims can suggest, never decide.** An action that comes out of a stress sim must be
  reproduced on reference practice items before a trial counts.

### 5.6 Fixes on record and the regression watch

When the keep policy keeps a change, the journal entry gains an annotation: the consoles and
codes it targeted, the trial run and the sealed confirmation run. That is a **fix on record**,
and the console shows it. On every later reference sim the **regression watch** checks those
consoles first. A console with a fix on record that goes NO-GO again is flagged "fix regressed"
in the debrief report with the kept change's ID, which is the cue to review a rollback through
the existing resolve path.

### 5.7 What Argos is given

A read-only plugin tool, `argos_readiness`, returns the agent-facing projection of the ledger
and the latest debrief report. The installed guide teaches the loop: read the report, pick at
most one corrective action, run its drill through the existing evaluate and edit tools, let the
policy decide, confirm on a sealed run, log it. No new write capability is added.

## 6. Familiar exams (future track)

Sims measure what an agent needs. They do not answer the question people actually ask: "how
would it do on a test I have taken?" A later track adds forms **in the style of** exams people
know: a reasoning battery of the kind used in IQ testing, and forms modelled on the SAT, the GRE
General Test, the LSAT, the MCAT and the DAT.

How they fit:

- **They are Proctor cartridges.** The Proctor core already administers versioned forms with
  `mcq_single` and `numeric_grid` responses, deterministic grading and a recorded transcript.
  Each exam-style form is a cartridge with sections, per-section time limits and section order
  modelled on the real exam's public format.
- **They feed the same consoles.** A sidecar of fault cards maps each item to a console, and
  each wrong option to a failure code. Logical-reasoning items report to LOGIC and EVIDENCE,
  reading passages to READING and CONTEXT, quantitative sections to GUIDANCE. A missed exam item
  lands in the same ledger and debrief report as a missed fault. Exams are where distractor
  analysis came from, so the diagnosis is at home here.
- **The display is an exam room, not a sim.** Section timer, question palette, answers filling
  in, section break, then a section-by-section score sheet. People recognise it on sight; it
  needs no fiction.

Rules specific to this track:

1. **Original items only.** Real exam questions are copyrighted and the exam names are
   trademarks. The repository ships only items written for Argos, with `content_origin:
   argos_original`. No released or leaked official item is copied, paraphrased or used as a
   template.
2. **Named as "modelled on", never as the exam.** A form is titled, for example, "Law-admission
   style reasoning form", with one line saying which public format it follows and that it is
   not affiliated with or endorsed by the exam's owner.
3. **Raw scores only.** Results are reported as correct out of total per section. No scaled
   score, percentile, IQ or admission prediction is shown, because those depend on norms from
   human test-takers that these forms do not have. Cartridges stay `calibration_status:
   uncalibrated`, as they are today.
4. **The owner may bring their own.** An owner who has lawfully obtained practice material can
   import it as a private cartridge. It stays in private storage, never enters the repository,
   and its results carry a "private form" label.
5. **Practice and sealed halves**, as everywhere else.

## 7. Honesty and protection rules

1. Only real events are shown. No imitated typing, no invented reasoning, no model-written
   commentary.
2. Answer keys, scorer rules, matcher values and sealed prompts never leave the host process.
   Spectator and agent projections carry fault family names, briefs, codes, counts and item IDs.
3. Practice and sealed results are never merged in a score, a ledger cell or a sentence.
4. A reference sim is always complete. An unfinished sim is saved and replayable, never
   compared, never a baseline.
5. Stress sims are labeled exploratory wherever they appear.
6. Small counts are shown as counts. No percentage without its denominator.
7. A score on these faults describes these faults. Ground ticket is the only family that speaks
   to owner tasks, and only once its pack is calibrated under the owner-task protocol.
8. The setting is a simulation and says so. Nothing implies a real vehicle, mission or agency.
9. One evaluation at a time, through the existing workload owner.
10. Stdlib-only Python, loopback binding, per-session token on every route.

## 8. What is reused and what is new

| Need | Existing piece | Change |
| --- | --- | --- |
| Run a sim | `bench_openclaw`, `bench_ability`, `evaluation_jobs` | None for reference sims |
| Score | `ability.py` scorers | None; hands-on fault adds a host-verified trace kind later |
| Store and compare | `results.Store`, `proctor_match.compare` | None |
| Live progress | `proctor_campaign` snapshot and watch record | Adds console and fault fields to the projection |
| Stage strip, pips, replay, baseline data | `match.js`, `proctor_match.match` | New console board beside it |
| Skill grouping | `skill_map.py` | Three new domains; console states mapped to evidence states |
| Miss diagnosis | `replay.py` (document misses) | Generalised by the matcher engine |
| Experiment candidates | `auto_climb.py` candidates, `instruction_changes` | Action catalog points at the same change IDs |
| Agent tools | `openclaw-plugin/argos-improve` | One read-only tool |
| Exam-style forms | `proctor/cartridge.py`, `proctor/engine.py` | Sections and per-section limits; sidecars |
| UI iteration without hardware | `scripts/serve-match-fixture.py`, `smoke-proctor-match.mjs` | New scenarios |

New: the `argoslive.shakedown` package (taxonomy, fault cards, matcher engine, responses,
ledger, debrief report, action catalog, generators), the sidecar and form data files, the
console board, and the `argos_readiness` tool.

## 9. Decisions taken here

- The frame is the integrated simulation, because it is real, it is tense without decoration,
  and its vocabulary (inject, call, poll, debrief, corrective action) is already the vocabulary
  of this problem.
- A sim is an ability run plus a sidecar, not a new runner.
- Diagnosis is deterministic distractor analysis, not a judging model.
- Reference and stress sims are separate kinds so the spectacle cannot dilute the evidence.
- The owner sees each fault as it is injected; the agent never does.
- Retrofitting existing suites comes first, so the first consoles light from data already on disk.
- Familiar exams are original forms modelled on public formats, reported as raw scores.
- No improvement campaign starts from this design while the AGENTS.md mismatch decision of
  November 8, 2026 is open.
