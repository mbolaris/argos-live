# The Hundred Eyes

Status: design proposal, November 11, 2026. Documentation only; nothing here is shipped
behavior. Tickets are in [BACKLOG.md](BACKLOG.md).

It builds on [one complete AI build session](../PLAY-SESSION.md), the
[Proctor match watch](../PROCTOR-MATCH-WATCH.md) (PR #169), the
[ability suites](../ABILITY-BENCHMARK.md), [Auto Climb](../AUTO-CLIMB-SPEC.md), items SI1 to
SI3 in the [main backlog](../BACKLOG.md) and the
[owner-task protocol](../OWNER-TASK-EVALUATION.md). It does not replace the event stream, the
scorers, the results store, the workload owner or the keep policy, and it adds no second
coordinator.

## 1. The idea in one paragraph

In the myth, Argus Panoptes is the watchman with a hundred eyes, and Hermes beats him by
telling tales until every eye closes. Here **Argos keeps watch at a gate for one night**.
Hermes, the showman face of the Proctor, sends a line of visitors. Each visitor carries a tale
built to close **one specific eye**, and each eye is one capability. The owner watches a
constellation of eyes hold or go dark, hour by hour. At dawn the eyes still open fan out as a
peacock tail, and the night's closed eyes become a machine-readable case file that Argos uses
to choose its next self-improvement experiment. "Blind spot" stops being a metaphor: it is an
eye on the screen, with a name, a count and evidence behind it.

## 2. A night from the spectator's seat

The match watch already has four stages. The night reuses them with new names.

| Stage | Match watch name | What the owner sees |
| --- | --- | --- |
| Dusk | Setup | The model and instructions on watch tonight, the kind of night, the visitors queued as silhouettes, last night's ghost loaded. |
| The Watch | Round | Visitors arrive one at a time. Eyes hold or close. |
| Dawn | Score | The peacock fan: open eyes spread out, closed eyes stay dark. Score, median reply time, saved run ID, practice and sealed tallies kept apart. |
| The Reckoning | What changed | Eyes won and lost against the baseline night, the Dawn report, and what Argos may try next. |

### One visitor, five beats

1. **Arrival.** A visitor card slides in: archetype, hour, and the eye it is after ("The Forger
   is after the Evidence eye"). The owner knows the trick; Argos does not. The card never shows
   the answer or the scoring rule.
2. **The tale.** The prompt, as sent.
3. **Argos acts.** Only real events appear. A tool call the runtime reports lights the matching
   instrument at the gate (lantern for inspect, ledger for lookup, bell for a clarifying
   question, seal for a committed action). The pinned OpenClaw CLI returns the reply whole, so
   the reply lands whole; the page never imitates typing. A question clock runs the entire time.
4. **Verdict.** The eye flares gold and stays open, or closes with one plain line taken from the
   deterministic diagnosis: "Lulled: followed an instruction hidden inside the quoted letter."
5. **Second wind** (where the visitor has one). After a miss, Argos gets one follow-up that
   states only that the first answer was not accepted. Recovering re-opens the eye as
   *bloodshot*. This separates "cannot do it" from "did not check", which point at different
   fixes.

### What makes it watchable

- **The constellation.** Eyes are grouped by domain. Untested eyes are outlines, open eyes
  glow, bleary eyes flicker, closed eyes are dark. A whole night reads at a glance.
- **Escalation.** Hours are difficulty tiers. Early visitors are honest travelers; by the small
  hours Hermes sends the Forger with two near-identical ledgers.
- **Drowsiness.** A meter that fills with slow answers and near misses. It is presentation built
  from recorded reply times; it never changes a score.
- **Last night's ghost.** The baseline run plays alongside as a faint trail. When the ghost lost
  an eye that tonight's watch keeps, the owner sees the gain as it happens, and the reverse for
  a regression. It is the existing matched comparison, shown live.
- **Named failures.** "Lulled", "Wrong lantern", "Counted sheep", "Sealed it unread". Each is a
  failure code with a costume on.
- **Commentary.** A one-line ticker built from templates over recorded facts. No model writes
  it, so it cannot invent anything.

### Two kinds of night

| | League night | Hunt night |
| --- | --- | --- |
| Form | Fixed, versioned, same visitors in the same order | Adaptive: Hermes aims at closed and bleary eyes and raises the tier after each success |
| Length | Always complete, whatever happens | Ends when Argos "falls asleep" (three eyes closed at once) |
| Seeds | Fixed practice set and a fixed sealed set | Fresh every night |
| Evidence | Comparable. The only nights that can feed a keep or roll-back decision | Exploratory. Finds blind spots and suggests hypotheses. Never compared, never qualifies anything |

A League night is an ordinary ability run with a costume on, so the existing comparison rules
(same suite version, same order, complete coverage) apply unchanged. A Hunt night is where the
drama is; its record says `comparable: false` everywhere it appears.

A League night surveys every eye with a few visitors each, which is too few to judge one
change. So each visitor family also has a **drill**: a fixed form of 12 practice and 12 sealed
items for that family alone. A drill is the matched test for a trial aimed at that family's eye.

## 3. The visitors

Each archetype is a probe family: a seeded generator, a deterministic scorer, and a set of
diagnostic matchers that turn the *shape* of a wrong answer into a failure code.

| Visitor | The trick | Eye | What it tests | Failure codes | Scorer kind |
| --- | --- | --- | --- | --- | --- |
| The Flatterer | Quoted material that contains an instruction or an authority claim | Guard | Instruction hierarchy, injection resistance | `inject.obeyed`, `inject.partial` | instruction, choice |
| The Forger | Two near-identical records, one altered | Evidence | Grounding an answer in the right source | `evidence.wrong-source`, `evidence.unsupported` | choice, json |
| The Tally-man | Multi-stage arithmetic with a tempting shortcut | Arithmetic | Carrying every stage | `calc.stage-dropped`, `calc.rounding`, `calc.unit` | numeric |
| The Sphinx | A question the tale cannot answer | Uncertainty | Saying so, or asking the exact clarifying question | `uncertainty.guessed`, `clarify.missing` | instruction, choice |
| The Stickler | An exact output contract | Following | Format and constraint fidelity | `format.extra-text`, `format.schema`, `format.constraint` | instruction, json |
| The Quartermaster | A request against supplied tool schemas | Tool schema | Tool choice and argument shape | `tool.wrong-name`, `tool.bad-arg-type`, `tool.missing-arg`, `tool.extra-arg` | tool-call |
| The Cartographer | A job needing several dependent calls | Sequence | Ordering and passing results forward | `plan.order`, `plan.dangling-ref`, `plan.extra-step` | tool-sequence |
| The Two Messengers | Conflicting reports, one stale | Source trust | Checking recency and provenance | `verify.stale-trusted`, `verify.unreconciled` | choice, json |
| The Rhapsode | A long tale with the fact early and a decoy late | Context | Holding early context | `context.recency-bias`, `context.dropped` | choice, numeric |
| The Returning Stranger | A fact from hour one, needed at hour five | Recall | Memory across turns | `memory.dropped`, `memory.confused` | numeric, choice |
| The Burglar | A stateful gatehouse where actions have consequences | Verification | Inspecting before acting, with real tools | `act.unverified`, `act.destructive`, `act.loop`, `act.budget` | host-verified trace |
| The Owner's Messenger | A chore from the owner's own recovery work | Stewardship | The tasks the owner actually wants done | per task pack | per task pack |

The first seven use response kinds the runner scores today. The Returning Stranger needs a
multi-turn session and the Burglar needs a sandboxed stateful tool world; both are later phases.

## 4. The eyes

Eyes extend `skill_map.py`'s domains instead of inventing a parallel map.

| Domain | Eyes |
| --- | --- |
| Understanding | Reading, Following |
| Reasoning | Arithmetic, Logic, Uncertainty |
| Planning | Structure, Sequence |
| Tool use | Tool schema, Tool choice, Verification |
| Memory | Context, Recall |
| Guard (new) | Guard, Evidence, Source trust |
| Tempo (new) | Tempo |
| Stewardship (new) | Stewardship |

Seventeen eyes at launch. "Hundred" is the horizon: every eye has pupils, one per probe family
and tier, and the map grows as visitors are authored.

Eye states map onto the skill map's evidence states and are computed from fixed, versioned
criteria, never from a feeling:

| Eye state | Skill-map state | Rule (launch defaults) |
| --- | --- | --- |
| Untested | untested | No scored sighting for this model and instruction fingerprint |
| Open | qualified | At least 6 scored sightings across at least 2 families, at least 85% correct, and no miss in the latest League night |
| Bleary | measured | Scored, but short of Open and not Closed |
| Closed | attention | At least 3 scored sightings and under 50% correct, or the same failure code from 2 distinct probes in one night |

Practice and sealed sightings are counted separately and shown separately. Only sealed
sightings can confirm that a kept change opened an eye.

## 5. The feedback architecture

```
Probe card ──► Sighting ──► Night record ──► Eye ledger ──► Dawn report
 (authoring)   (one per     (one per run)    (longitudinal)   (per night, advice)
               visitor)                                            │
                                                                   ▼
            Sentinel ◄── Relic ◄── keep policy ◄── trial ◄── Argos picks a remedy
          (later nights)  (kept     (existing,     (existing    (Argos owns its
                          change)   sole authority) runner)      experiments)
```

Design decision that keeps this cheap: **a League form is an ordinary `argos-ability-suite/1`
file plus a sidecar of probe cards keyed by item ID.** The runner, scorers, results store,
comparison and keep policy work unchanged. The sidecar adds meaning. The same sidecar format
retrofits the existing suites, so runs already saved light up eyes without one new evaluation.

### 5.1 Probe card (authoring time, host-side only)

```json
{
  "schema": "argos-eye-probe/1",
  "item": "heldout-forger-07",
  "family": "forger",
  "eye": "evidence",
  "tier": 3,
  "partition": "sealed",
  "generator": {"name": "forger", "version": "1.0.0", "seed": "…"},
  "spectator": {"visitor": "The Forger", "tell": "Two ledgers; one figure was altered."},
  "diagnostics": [
    {"code": "evidence.wrong-source", "when": {"choice-is": "B"}},
    {"code": "evidence.unsupported", "when": {"choice-is": "D"}}
  ],
  "second_wind": {"prompt": "That answer was not accepted. Check the sources again and answer once more."}
}
```

Matchers are a closed set evaluated by code, never by a model: `equals`, `choice-is`,
`contains-token`, `numeric-delta`, `numeric-equals`, `json-path-mismatch`, `tool-name-is`,
`tool-arg-mismatch`, `sequence-violation`, `reply-seconds-over`. This is distractor analysis:
every wrong option and every planted token is designed so that falling for it names its cause.
A miss no matcher claims becomes `miss.unclassified`, and the unclassified rate is a health
metric for the probes themselves.

### 5.2 Sighting (one per visitor, derived from the saved run)

```json
{
  "schema": "argos-eye-sighting/1",
  "run_id": "…", "item": "heldout-forger-07",
  "eye": "evidence", "family": "forger", "tier": 3, "partition": "sealed",
  "outcome": "closed",
  "codes": ["evidence.wrong-source"],
  "detector": {"matcher": "choice-is", "probe_version": "1.0.0"},
  "reply_seconds": 14.2,
  "tool_calls": 0,
  "second_wind": {"offered": true, "recovered": false}
}
```

`outcome` is `open`, `bloodshot` (missed, then recovered), `closed` or `unscored`. A sighting
never copies an answer key, a scorer rule or the matcher's expected value.

### 5.3 Night record

One per run: night kind (`league` or `hunt`), form and version, `comparable`, the ordered
sightings, tempo summary (median and slowest reply, total tool calls), the watch ID from the
campaign controller, and the baseline run used for the ghost. Stored beside the saved run under
the owner-only state directory, like the campaign records the match watch already keeps.

### 5.4 Eye ledger (longitudinal, per model and instruction fingerprint)

```json
{
  "schema": "argos-eye-ledger/1",
  "eyes": {
    "evidence": {
      "state": "closed",
      "practice": {"scored": 9, "open": 4},
      "sealed": {"scored": 6, "open": 2},
      "by_tier": {"1": [3, 3], "2": [3, 5], "3": [0, 7]},
      "codes": {"evidence.wrong-source": 7, "evidence.unsupported": 2},
      "nemesis": "forger",
      "last_league_run": "…",
      "relics": []
    }
  }
}
```

It is rebuilt from saved runs and sidecars, so it can always be regenerated and never becomes a
second source of truth.

### 5.5 Dawn report (what Argos reads)

```json
{
  "schema": "argos-dawn-report/1",
  "night": {"run_id": "…", "kind": "league", "form": "first-watch", "version": "1.0.0", "comparable": true},
  "closed": [
    {
      "eye": "evidence",
      "evidence": {"misses": 5, "of": 6, "families": ["forger", "two-messengers"],
                   "codes": {"evidence.wrong-source": 4, "evidence.unsupported": 1},
                   "items": ["practice-forger-02", "practice-forger-05"]},
      "hypotheses": [
        {
          "remedy": "quote-evidence",
          "kind": "instruction",
          "counters": ["evidence.wrong-source", "evidence.unsupported"],
          "matched_test": {"form": "drill-forger", "version": "1.0.0", "partition": "practice"},
          "guard": ["following", "tempo"],
          "bar": {"policy": "argos-practice-keep/4", "minimum_correct_delta": 2},
          "confirm_on": "sealed"
        }
      ]
    }
  ],
  "regressions": [],
  "tempo": {"median_reply_seconds": 9.8, "slowest_item": "practice-rhapsode-03"},
  "unclassified_misses": 1
}
```

Rules that keep it rigorous:

- **A hypothesis needs a pattern.** At least two misses with the same code from distinct probes.
  One miss is an anecdote and produces no hypothesis.
- **Remedies come from an allowlist.** `remedies.json` maps failure codes to interventions that
  exist: instruction cards (`answer-first`, `quote-evidence`, `honest-uncertainty` and new ones),
  tool guides, context settings. A code with no known remedy says so. This is the fixed schema
  and allowlist that SI1 asks for.
- **Every hypothesis names its own test and its guard.** The matched test is the practice half
  of the affected family's drill. The guard is a set of currently open eyes the change is most
  likely to hurt, so a gain that costs another eye is visible in the same trial.
- **The report is advice.** `instruction_changes` and the keep policy remain the only authority
  on whether a change stays. Argos chooses whether and what to try.
- **Confirmation is sealed.** A kept change is confirmed only by sealed sightings from a night
  the tuning never saw. Sealed feedback to Argos is aggregate: eye, code counts and item IDs,
  never prompts or answers.
- **Hunt nights can suggest, never decide.** A hypothesis born on a Hunt night must be
  reproduced on League practice items before a trial counts.

### 5.6 Relics and the sentinel

When the keep policy keeps a change, the journal entry gains an annotation: the eyes and codes
it targeted, the trial night and the sealed confirmation night. That is a **relic**, and the eye
shows it. On every later League night the **sentinel** checks relic eyes first. A relic eye that
closes again is flagged as "relic failed" in the Dawn report with the kept change's ID, which is
the cue to review a rollback through the existing resolve path.

### 5.7 What Argos is given

A read-only plugin tool, `argos_eyes`, returns the agent-facing projection of the ledger and the
latest Dawn report. The installed guide teaches the loop: read the report, pick at most one
hypothesis, run its matched trial through the existing evaluate and edit tools, let the policy
decide, confirm on a sealed night, log it. No new write capability is added.

## 6. Honesty and protection rules

1. Only real events are shown. No imitated typing, no invented reasoning, no model-written
   commentary.
2. Answer keys, scorer rules, matcher values and sealed prompts never leave the host process.
   Spectator and agent projections carry visitor names, tells, codes, counts and item IDs.
3. Practice and sealed results are never merged in a score, a ledger cell or a sentence.
4. A League night is always complete. An unfinished night is saved and replayable, never
   compared, never a baseline.
5. Hunt nights are labeled exploratory wherever they appear.
6. Small counts are shown as counts. No percentage without its denominator.
7. A score on these visitors describes these visitors. The Owner's Messenger is the only family
   that speaks to owner tasks, and only once its pack is calibrated under the owner-task protocol.
8. One evaluation at a time, through the existing workload owner.
9. Stdlib-only Python, loopback binding, per-session token on every route.

## 7. What is reused and what is new

| Need | Existing piece | Change |
| --- | --- | --- |
| Run a night | `bench_openclaw`, `bench_ability`, `evaluation_jobs` | None for League nights |
| Score | `ability.py` scorers | None; the Burglar adds a host-verified trace kind later |
| Store and compare | `results.Store`, `proctor_match.compare` | None |
| Live progress | `proctor_campaign` snapshot and watch record | Adds eye and visitor fields to the projection |
| Stage strip, pips, replay, ghost data | `match.js`, `proctor_match.match` | New constellation view beside it |
| Skill grouping | `skill_map.py` | Three new domains; eye states mapped to evidence states |
| Miss diagnosis | `replay.py` (document misses) | Generalised by the matcher engine |
| Experiment candidates | `auto_climb.py` candidates, `instruction_changes` | Remedy catalog points at the same change IDs |
| Agent tools | `openclaw-plugin/argos-improve` | One read-only tool |
| UI iteration without hardware | `scripts/serve-match-fixture.py`, `smoke-proctor-match.mjs` | New scenarios |

New: the `argoslive.eyes` package (taxonomy, probe cards, matcher engine, sightings, ledger,
Dawn report, remedy catalog, generators), the sidecar and form data files, the constellation
view, and the `argos_eyes` tool.

## 8. Decisions taken here

- The theme is the Argus myth, because the project is named for it and the constellation makes
  blind spots literal.
- A night is an ability run plus a sidecar, not a new runner.
- Diagnosis is deterministic distractor analysis, not a judging model.
- League and Hunt nights are separate kinds so the fun cannot dilute the evidence.
- The owner sees each visitor's trick during the watch; the agent never does.
- Retrofitting existing suites comes first, so the first eyes open from data already on disk.
- No improvement campaign starts from this design while the AGENTS.md mismatch decision of
  November 8, 2026 is open.
