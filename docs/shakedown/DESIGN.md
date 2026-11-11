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

## In brief

Shakedown is a workbench for people who tune a local model and agent framework for fun. They
change something, run a lap, and get an honest verdict on a scorecard of their own builds
(§1 to §3). Its showpiece is a watchable simulation that also diagnoses *why* a build is weak
(§4 to §7). Public benchmarks (§8) and exam-style forms (§9) add numbers people recognise.

The simulation frame, in one paragraph:

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

## 1. Who this is for

The typical user is an enthusiast who runs a local model and an agent framework for the fun of
making it better. They swap a quantization, raise the context, edit the system prompt, add a
tool, and want to know one thing: **did that help?** They are not running a lab. They have one
GPU, limited patience for a 40-minute run, and a real appetite for numbers they can understand,
compare and show to someone.

What that person wants, in order:

1. **A fast answer.** Change something, press one button, get a verdict in a few minutes.
2. **Numbers that mean something to them.** Tokens per second, and scores on tests whose names
   they already know.
3. **An honest verdict.** "Better", "worse" or "too close to call", so they stop chasing noise.
4. **A reason and a next move.** Where it got better or worse, and one thing worth trying next.
5. **Something to watch** when they feel like watching, and nothing in the way when they don't.
6. **A record.** Every build they tried, side by side, and their best on this hardware.
7. **Something to share**, without anything leaving the machine unless they send it.

Everything else in this design serves that loop. The sim in §4 is the showpiece, and the
diagnostics in §7 are what make the advice trustworthy, but the product is the bench.

## 2. The bench

The home screen is a workbench with four parts.

### 2.1 The loadout

A **loadout** is everything the user can tune, captured automatically at the start of every
run: the model and its quantization, context size, output cap, sampler settings, thinking mode,
which instruction cards are on, the tool profile, the agent framework version, and the hardware
it ran on. The user can name one ("Q5 at 16k context"). Nothing is typed in to make a run
comparable; the snapshot is the record.

Any two loadouts can be diffed in plain words: "Quantization Q4_K_M to Q5_K_M. Context 8,192 to
16,384. Instruction card quote-evidence turned on." This is the first thing shown beside any
comparison, because a score change means nothing until you know what changed.

Loadouts on the bench are trials. They run in the existing Lab staging and never alter the
deployed assistant; applying one for real goes through the existing paths.

### 2.2 The lap

One button, three sizes, each with an estimate made from this machine's measured speed:

| Size | Roughly | What it runs |
| --- | --- | --- |
| Quick lap | 3 minutes | Speed, plus a small fixed slice of every selected form |
| Standard | 15 minutes | Speed, plus the standard slice |
| Full | An hour or more | Every item of every selected form |

The slices are nested and fixed (quick is inside standard, standard inside full), so a quick lap
on one loadout is comparable with a quick lap on another. A lap can be cancelled at any moment;
a partial lap is saved and never compared. Several loadouts can be queued to run one after
another while the user is away, one evaluation at a time.

### 2.3 The scorecard

A spec sheet in the style every enthusiast already reads: **rows are tests, columns are the
user's own loadouts** (up to four pinned, plus the current one).

```
                          Q4 8k      Q5 8k      Q5 16k     Q5 16k + cards
Speed  tokens/s           41.2       33.8       33.1       32.9
       first token        0.41 s     0.48 s     0.52 s     0.55 s
MMLU   100-question set   61 ±9      66 ±9      66 ±9      67 ±9
GSM8K  100-question set   48 ±10     55 ±10     57 ±10     63 ±10
Function calling subset   52 ±10     58 ±10     71 ±9      74 ±9
Reference Sim A  practice 14/24      15/24      18/24      20/24
                 sealed   13/24      15/24      17/24      19/24
```

(The numbers above are invented to show the layout.)

- Each cell shows the score, how many questions it rests on, and its uncertainty.
- The best cell in a row is highlighted only when it is distinguishable from the others.
- Every third-party row says "subset" and carries a footnote that it is not the official score.
- Speed rows sit beside quality rows on purpose: the question is usually a trade-off.
- Tapping a cell opens that run: the questions, the answers, the replay, and the sim if it had
  one.

### 2.4 The verdict and the next move

After a lap, one screen answers the user's question:

- **Headline.** "Better than Q5 8k on function calling. Too close to call on MMLU and GSM8K.
  5% slower."
- **What changed.** The loadout diff.
- **Where.** Which consoles moved, with the failure codes behind them (§7).
- **Next move.** At most one suggestion, taken from the corrective-action allowlist or from a
  plain configuration fact ("12 of 100 prompts were truncated at this context size"), with a
  button that queues a lap to test it.

The verdict is computed on the questions both loadouts answered, pair by pair. When the
difference could easily be chance, it says "too close to call" and estimates how many more
questions would settle it, with a button to run them. This is the same discipline the keep
policy applies to Argos's own experiments, offered to the human as help, not as a gate: the
owner may keep whatever they like on their own bench.

### 2.5 Sharing and records

- **Share card.** The scorecard exported as an image and a JSON file to local storage: loadout
  summary, hardware, the subset labels and footnotes. Nothing is uploaded. Instruction text and
  private data are never in it.
- **Personal bests.** Per test, per hardware, with the loadout that set them.
- **History.** Laps over time (§7 adds consoles and fixes on record to it).

## 3. What gets measured

Four tracks feed the scorecard. The user picks which are in a lap; the default is a sensible mix.

| Track | What it is | Why the user cares | Section |
| --- | --- | --- | --- |
| Speed | Tokens per second, time to first token, memory | The trade-off against every quality number | existing `bench_speed` |
| Standard benchmarks | Small fixed subsets of public benchmarks | Names they know; rough comparability with numbers they read online | §8 |
| Shakedown sims | Original fault scripts that diagnose capabilities | Says *why*, and is the one to watch | §4 to §7 |
| Familiar exams | Original forms modelled on exams people have taken | The relatable question: how would it do on a test I took? | §9 |

Only the Shakedown track is diagnostic by design, because its wrong answers were authored to
name their cause. The other tracks say how much; Shakedown says what to fix.

## 4. A sim from the spectator's seat

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

## 5. Fault families

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

## 6. Consoles

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

## 7. The feedback architecture

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
evaluation, and it attaches to Proctor cartridges for the familiar exams in §9.

### 7.1 Fault card (authoring time, host-side only)

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

### 7.2 Response (one per fault, derived from the saved run)

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

### 7.3 Sim record

One per run: sim kind (`reference` or `stress`), form and version, `comparable`, the ordered
responses, timing summary (median and slowest response, total tool calls), the watch ID from the
campaign controller, and the baseline run used as the reference trace. Stored beside the saved
run under the owner-only state directory, like the campaign records the match watch already
keeps.

### 7.4 Readiness ledger (longitudinal, per model and instruction fingerprint)

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

### 7.5 Debrief report (what Argos reads)

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

### 7.6 Fixes on record and the regression watch

When the keep policy keeps a change, the journal entry gains an annotation: the consoles and
codes it targeted, the trial run and the sealed confirmation run. That is a **fix on record**,
and the console shows it. On every later reference sim the **regression watch** checks those
consoles first. A console with a fix on record that goes NO-GO again is flagged "fix regressed"
in the debrief report with the kept change's ID, which is the cue to review a rollback through
the existing resolve path.

### 7.7 What Argos is given

A read-only plugin tool, `argos_readiness`, returns the agent-facing projection of the ledger
and the latest debrief report. The installed guide teaches the loop: read the report, pick at
most one corrective action, run its drill through the existing evaluate and edit tools, let the
policy decide, confirm on a sealed run, log it. No new write capability is added.

## 8. Standard benchmarks

Enthusiasts read benchmark tables, so the scorecard should speak that language where it honestly
can. The Proctor can administer any benchmark whose answers a program can grade. That rules a
lot in and a lot out.

### 8.1 What is practical

| Tier | Benchmarks | What it needs | Status |
| --- | --- | --- | --- |
| 1. Drop-in | MMLU, GSM8K, ARC (AI2), HellaSwag, TruthfulQA (multiple choice), WinoGrande, MMLU-Pro, BIG-Bench Hard | Nothing new: multiple choice and numeric answers are graded today | First |
| 2. Small checker | IFEval (instruction following), Berkeley Function Calling Leaderboard (BFCL) | A stdlib port of a deterministic checker | Second. BFCL is the most relevant public benchmark for an agent framework |
| 3. Code sandbox | HumanEval, MBPP | The enforced execution sandbox (main backlog items B4b2 and B5b, still open) | Blocked on the sandbox |
| 4. Agent harness | SWE-bench and its variants, Terminal-Bench, tau-bench, GAIA | Containers, repositories, long multi-step runs, sometimes a simulated user | Not now. Slow on one GPU, near the floor for most local models, and a large containment job |
| 5. Not practical | Computer-use suites (OSWorld), robotics simulators, cybersecurity ranges, protein design, chart and other vision benchmarks, rubric- or human-judged knowledge work (Remote Labor Index and similar), Humanity's Last Exam | A desktop VM with vision, a physics simulator, specialised tooling, a judging model or human graders | Out of scope. No deterministic grader, or hardware and risk far beyond a hobby rig |

Most of the rows in a frontier model's release table belong to tiers 4 and 5. What carries over
from those tables is the format, which §2.3 adopts, not the tests.

### 8.2 A small subset, done properly

- **Use published small sets where they exist.** The tinyBenchmarks project publishes
  100-question selections of MMLU and GSM8K, among others, and reports that about 100 curated
  questions estimate the full MMLU score within roughly two points on average. Using the same
  100 questions as everyone else is worth more than choosing our own.
- **Otherwise a fixed, stratified, published list.** The list of item IDs is versioned and never
  changes without a version bump, so two users running "MMLU 100 v1" ran the same questions.
- **Sizes follow the lap.** Quick lap uses a fixed 25 of the 100; standard and full use all 100.

### 8.3 Packs, not bundled data

The repository's fixtures are original on purpose, and that stays true. Standard benchmarks ship
as **benchmark packs**:

- The repository contains the adapter (how to prompt and grade), the item-ID list, the pinned
  source revision with its SHA-256, and the licence record. It contains **no benchmark
  questions**.
- The user downloads a pack from its original source with one click, through the existing
  guided-download path. Gated datasets stay behind the user's own acceptance: GPQA, for
  example, asks users to accept terms and not to post its questions online.
- A pack is verified by hash before use and stored with the owner's data, not in the image.

Each pack's licence is read from the source repository's own licence file and recorded before
the pack ships. Current understanding, to be confirmed in the ticket: IFEval and BFCL are tagged
Apache 2.0 on their dataset cards; MMLU and GSM8K are reported as MIT by secondary sources; GPQA's
data is CC BY 4.0 and gated; the tinyBenchmarks code is MIT but its dataset cards show no licence
field; the rest are not yet checked.

### 8.4 Saying only what is true

1. **"Subset", always.** A cell reads "MMLU, 100-question set: 66 ±9", never "MMLU: 66".
2. **Not the official score.** Different prompting, a different harness and a subset mean the
   number is comparable between this user's loadouts first, and with published numbers only
   roughly.
3. **Public tests leak.** These questions are on the internet and may be in a model's training
   data. The row says so. Sealed Shakedown items are the counterweight.
4. **Diagnosis is limited.** Third-party wrong options were not written to name a cause, so
   most misses are `miss.unclassified`. IFEval and BFCL are the exception: their failures are
   structural (wrong tool, wrong argument, constraint broken) and map straight to failure codes.
5. **Never a matched test for a keep decision.** Public benchmarks inform the owner. Argos's
   trials use drills.

## 9. Familiar exams (future track)

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

## 10. Honesty and protection rules

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
11. A third-party benchmark row is labeled as a subset and as not the official score, notes that
    public questions may be in a model's training data, and is never the matched test for a keep
    decision.
12. Nothing is uploaded. Sharing is an export to the owner's own storage.
13. The bench verdict is help for the owner, not a gate. The keep policy governs only Argos's own
    instruction experiments.

## 11. What is reused and what is new

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
| Loadout | `recipe.py` (`argos-recipe/1`) and saved-run metadata | Adds quantization, card names and tool profile; a plain-words diff |
| Speed rows | `bench_speed.py` | None |
| Laps and queue | `evaluation_jobs`, `workload`, `lab.py` staging | A plan of existing jobs, one at a time |
| Benchmark packs | `pull_jobs.py` and the guided-download path | Pack manifests, hash verification, adapters |

New: the `argoslive.shakedown` package (taxonomy, fault cards, matcher engine, responses,
ledger, debrief report, action catalog, generators), the sidecar and form data files, the
console board, and the `argos_readiness` tool.

## 12. Decisions taken here

- The bench is the home screen and the sim is the showpiece: the user's loop is change, lap,
  verdict, and everything else serves it.
- The scorecard is the user's own loadouts side by side, in the format of a model release table.
- Verdicts say "too close to call" when they should, and say how many more questions would settle it.
- Standard benchmarks ship as packs the user downloads: adapters and item lists in the repository,
  never the questions.
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
