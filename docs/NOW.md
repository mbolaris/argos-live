# Now: what Argos Live is working on

Written November 14, 2026. This page is the single source of current priority. Where it disagrees
with the priority or "next" sections of [BACKLOG.md](BACKLOG.md), [PROJECT-GOALS.md](PROJECT-GOALS.md),
[STATUS.md](STATUS.md) or a handoff file, this page wins. Ticket text still lives in
[shakedown/BACKLOG.md](shakedown/BACKLOG.md); this page only says which tickets get worker time and
in what order.

## The one goal

**Argos gets measurably better at real tasks, by its own experiments, while the owner watches.**

Everything a worker does should move one of these four numbers:

| Number | Today | Why it is the constraint |
| --- | --- | --- |
| Scored items Argos can be tested on | about 330, hand-written | Too few to find weaknesses or to hold a sealed half back |
| Forms where the deployed build has room to gain | 2 or 3 | A build that scores 20/20 cannot show an improvement |
| Changes kept on matched evidence | a handful, all answer-format rules | The loop works but has little to chew on |
| Owner actions needed per improvement session | several | The owner wants to start it and watch |

## Where it honestly stands

- **The loop is real.** Campaigns, the keep policy, the instruction journal, byte-exact restore,
  unattended runtime updates without rebuilding the drive, and a watch mirror on Yugo all work.
- **The loop is starved.** `quick` is 20/20 on every run. Auto Climb tiers 1 and 2 are saturated and
  tier 3 swings between 5 and 8 of 8. The only gain measured this week was a summary-format rule on
  `documents-short` (24-25/32 to 28/32). Nearly every miss found so far is the same one: right value,
  wrong format.
- **Most recent work was plumbing.** Since mid October the bulk of merged PRs went to boot, SSD, SSH
  recovery, containment and deployment records. That work was needed and is done enough.
- **The watch is thin.** The Proctor match watch and the Shakedown bench (Phase 1) exist. The
  console board, fault cards and go/no-go poll are designed but not built.

## Three lanes

Only these three get worker time. Each has one owner-visible outcome.

### Lane A. Exam board: many more, much harder, more interesting tests

Outcome: thousands of scorable items across families the current build fails a useful share of, each
with a practice half and a sealed half.

| Order | Ticket | What it adds | Needs |
| --- | --- | --- | --- |
| A1 | **EV1** (new) Headroom report. Status: built, in review (PR "EV1: headroom report"). | `argos headroom`: per form, the deployed build's last three scores, flagged saturated, has room, too few runs, or never run. Tells Lane A what to write next and tells Argos where to aim. | nothing |
| A2 | **EV2** (new) Hard forms in the shipped format | `challenge-hard` and `documents-long`: about 120 items aimed at a 40 to 70 percent pass rate for the deployed model, calibrated on the hosted real-model workflow before merge. Immediate headroom while generators are built. | nothing |
| A3 | SIM44, SIM45 | Benchmark pack format and the first packs (MMLU and GSM8K subsets): numbers people recognise. | nothing |
| A4 | SIM11, SIM12, SIM13 | Seeded generators for eight fault families. This is what makes the test set effectively unlimited and keeps a sealed half fresh. | SIM3 |
| A5 | SIM46, SIM47 | Function-calling and instruction-following packs. | SIM44 |
| A6 | SIM31, SIM32, SIM33 | Original exam-style forms modelled on formats people know; raw scores only. | SIM2 |
| A7 | SIM23, SIM24 | The rig: stateful, sandboxed tasks where Argos has to actually operate something. | SIM11 |

New families to write tickets for once A4 lands (grounded, deterministic, no judging model):

- **Called shot.** Before each item Argos states whether it expects to pass. Scored as calibration.
  It is honest by construction and it is the best thing to watch.
- **Long procedure.** A 30 to 60 step checklist with one changed step part way through.
- **Shift handover.** Facts given early in a session, needed many turns later, with one superseded.
- **Conflicting orders.** Two sources disagree; the right answer is to say which is authoritative
  and why, or to ask.
- **Degraded mode.** The same form under a smaller context window or a token budget.

Every new form ships with: a version, a practice and sealed split, a passing, wrong and malformed
reference per item, and a proposed keep rule (see Owner decisions).

### Lane B. The loop: Argos uses the tests to pick and prove its own experiments

Outcome: a session that goes weakness, experiment, matched retest, keep or restore with no owner
action after Start.

| Order | Ticket | What it adds | Needs |
| --- | --- | --- | --- |
| B1 | SIM1, SIM2, SIM3 | Consoles, fault cards, deterministic matchers. **Critical path: Lanes A and C both wait on SIM3.** | nothing |
| B2 | SIM4, SIM5 | Sidecars for the shipped suites and the readiness ledger, so consoles light from runs already saved. | SIM3 |
| B3 | SIM16, SIM17 | Corrective-action catalog and the debrief report Argos reads to choose an experiment. | SIM1, SIM5, SIM14 |
| B4 | SIM19, SIM20, SIM21 | Targeted trials under the keep policy, the `argos_readiness` tool, fixes on record and the regression watch. | SIM17 |
| B5 | **LOOP1** (new) Chained session | One Start runs: headroom report, pick the weakest form with room, campaign, verdict, next form, inside the standing-orders envelope. Removes the "owner picks a task and pastes run IDs" step. | EV1 |

### Lane C. The watch: live, honest, entertaining

Outcome: the owner opens one page and sees every test as it happens, and can trust every word on it.

| Order | Ticket | What it adds | Needs |
| --- | --- | --- | --- |
| C1 | **WATCH1** (new) Live feed | One always-on page for whatever is running (lap, campaign, Auto Climb, sim): current item, running score, clock, last five results, streaks and personal bests. Works on the Yugo mirror. Built on the match watch. | nothing |
| C2 | **WATCH2** (new) Morning debrief | One screen for "what happened while I was away": sessions run, verdicts, what was kept or restored and why, the best and worst moment. Generated by code from the journal. | nothing |
| C3 | SIM6 to SIM10 | Console board, fault cards, mission clock, go/no-go poll, reference trace. | SIM5 |
| C4 | SIM18, SIM25 | Debrief view and live tool events. | SIM10, SIM17 |

House rules for anything on screen (these are what make it honest, and they are not negotiable):

1. Only real events. No imitated typing and no model-written commentary. Colour comes from
   templated lines chosen by code from real outcomes.
2. Misses are shown as plainly as passes. "Too close to call" is a normal verdict.
3. Practice and sealed scores never share a number. Exploratory runs are labelled exploratory.
4. The tension is real: the clock, the injected fault, the call before the answer, the streak.
5. Real-world sci-fi only: consoles, polls, debriefs. No fantasy or myth, no named real missions.

## Frozen

No worker time on these unless one blocks a lane, and then only the smallest fix:

- Boot, SSD, image builds, SSH recovery, containment, time sync, QEMU diagnostics.
- Personality packs, model catalog, guided downloads, release packaging.
- The older dashboard pages and the pre-Shakedown mission and play-session designs.
- Open PRs #93, #122, #135, #144, #167 and #168: close or park (owner decision below).

## Rules for workers

1. One ticket, one branch, one PR titled with the ticket ID. Work in a worktree, never in the main
   checkout. Remove the worktree when the PR merges.
2. Take a ticket by changing its status line in the same PR that starts it. Do not start a ticket
   whose "Needs" is not on `main`.
3. Build against the fixture server (`scripts/serve-match-fixture.py`). Real-model checks run on the
   hosted workflow. Workers do not touch Toronado; the operator does, under the
   [standing orders](HANDS-OFF-STANDING-ORDERS.md).
4. Standard library only. No judging model. Answer keys and sealed prompts never leave the host
   process.
5. Say how it was verified, and say plainly what was not.
6. A PR that changes priority changes this page. Nothing else states priority.

Shakedown rule 14 (no campaign while the November 8 `AGENTS.md` mismatch is open) no longer blocks:
the edit was adopted into the journal on November 13.

## First wave

Five workers can start today without touching each other's files:

| Worker | Tickets | Lane |
| --- | --- | --- |
| 1 | SIM1, then SIM2, then SIM3 | B (critical path) |
| 2 | EV1 headroom report | A |
| 3 | EV2 hard forms | A |
| 4 | SIM44, then SIM45 | A |
| 5 | WATCH1 live feed | C |

Second wave, when SIM3 merges: SIM11 to SIM13 (generators), SIM4 and SIM5, SIM16, SIM31, WATCH2.

## Owner decisions

1. **Keep rules for new forms.** Each new form needs a minimum gain before a change measured on it
   can be kept. Proposed default so workers do not wait on each one: both candidate runs beat the
   best baseline by at least 5 percent of the form's items (minimum 3), no more format errors, and
   no regression on the sealed half.
2. **What Argos may change.** Today only `AGENTS.md` instructions. Adding inference settings
   (context size, temperature, thinking) as reversible, journaled changes would give it far more to
   try. This widens its reach, so it is the owner's call.
3. **Stale work.** Whether to close the six open PRs above and remove the merged worktrees and
   branches.
