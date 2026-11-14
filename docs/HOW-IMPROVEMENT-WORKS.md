# How Argos improves itself

Argos can change its own instructions to get better at your work, and you can watch it happen. This page
explains how that works, what each verdict means and what you decide. It describes the system as of
November 2026. The design and acceptance details are in [AUTO-CLIMB-SPEC.md](AUTO-CLIMB-SPEC.md),
[OWNER-TASK-EVALUATION.md](OWNER-TASK-EVALUATION.md) and [SELF-IMPROVEMENT-GUIDE.md](SELF-IMPROVEMENT-GUIDE.md).

## The loop

1. **Find a weakness.** Run a fixed set of questions with known answers and see what the assistant gets wrong.
2. **Try one change.** Make one reversible change, such as a short reviewed rule added to `AGENTS.md`.
3. **Measure again.** Run the same questions again, plus fresh questions the change was never tuned on.
4. **Keep or restore.** Keep the change only if the evidence clears a fixed bar set in advance. Otherwise
   restore the original file, byte for byte.

Every step is recorded: run IDs, scores, the instruction file's hash before and after, and the decision.
A change is never kept because a score "looks better".

## Two ways to run it

| | Auto Climb | Task-focused campaign |
|---|---|---|
| Dashboard | **Self-improvement → Start Auto Climb** | **Improve a useful task → Start task-focused campaign** |
| What it measures | Short built-in practice tasks in curriculum tiers | A recurring task you describe, measured by a suite you pick |
| Who changes instructions | The controller, from a reviewed list of rules | Argos itself, through its managed tools |
| Can it keep a change? | **No.** Gains are reported, then restored ("practice-only") | Yes, if the keep policy passes on matched runs |
| Good for | Finding weaknesses cheaply; trying candidate rules | Making a lasting improvement to work you care about |

### Auto Climb

Auto Climb starts at the easiest practice tier that the current setup does not already pass. There are
three tiers:

- `argos-foundation/1`: grounded answers with quotes.
- `argos-foundation/2`: near-miss details.
- `argos-foundation/3`: exact answer formats, such as one letter, yes or no, a number or an ISO date.

Each tier has eight practice challenges and a set of held-out validation partitions. A partition is used
once, then retired.

- **Saturation needs three perfect runs.** A tier counts as saturated only after its practice set comes
  out perfect three runs in a row. One perfect run can be luck: in November 2026 the production model
  scored 8/8 on tier 3 once, then 7, 6 and 5 of 8 on repeats.
- **Keep bar.** A candidate rule must gain at least 2 practice challenges with no regressions. It must
  then gain at least 1 on a fresh validation partition, and at least 1 on a second, different partition,
  each with no regressions.
- **Why it never keeps.** These are synthetic practice tasks, not your work. A candidate that clears the
  bar is reported as **practice-only** and restored. The evidence is still useful: you can add a
  practice-only rule yourself (see [Owner edits](#owner-edits)).
- **Limits.** Each session runs inside an approved envelope: maximum duration, maximum number of
  experiments and zero model downloads unless you allow them.

### Task-focused campaign

You give the campaign three things:

- **Recurring task:** what you want Argos to do better, in your own words.
- **What counts as success?:** an observable result.
- **Measurement suite:** the suite that tests that task. Choose "None fits" if no suite tests it. In that
  case Argos reports the gap and changes nothing.

Everyday chat pauses while the campaign runs, and restarts and is re-verified afterwards. Inside the
campaign, Argos:

1. inspects its instructions;
2. saves at least two baseline runs;
3. makes one reversible change;
4. saves at least two candidate runs;
5. compares them;
6. keeps or restores the change and audits its own journal.

Its notes appear in `IMPROVEMENT-LOG.md` on the dashboard.

A campaign gives Argos four turns. A thorough experiment can need more than one campaign. When you start a
follow-up campaign, put the earlier run IDs in the task text, because Argos does not search old results
on its own.

**Keep policy.** Every candidate run must beat the best baseline run by a fixed number of correct
answers, with no more format errors than the cleanest baseline run:

| Suite | Minimum gain |
|---|---|
| quick | 2 |
| standard | 4 |
| challenge | 3 |
| tool-schema | 3 |
| tool-plan | 3 |
| tool-sequence | 3 |

Tool suites must also not regress on their held-out half. A change can also be kept for reliability: the
same or better score, fewer format errors and no more than 1.5 times slower. A few items in some suite
versions are excluded from these counts because their prompts left the expected answer ambiguous.

`documents-short` ("Read this brief") and `owner-recovery-decision` can be measured in a campaign but
cannot keep a change yet, because the keep policy has no minimum gain for them.

## Verdicts

| You see | Meaning |
|---|---|
| **Kept** | The change cleared the keep policy on matched runs and stays in `AGENTS.md`. |
| **Restored** | The evidence fell short. `AGENTS.md` is back to its exact previous bytes. |
| **Practice-only** | Auto Climb only: the change cleared the practice and validation bar, but synthetic tasks cannot keep a change. It was restored. |
| **Practice saturated** | Auto Climb: three perfect runs at the hardest tier, so no change can show a gain. Nothing was changed. |
| **Options exhausted** | Auto Climb tried every candidate that fits the observed misses. |
| **Incomplete** (campaign) | The campaign stopped before all required evidence existed. Read the missing list and Argos's report. |
| **Task not measured** | No suite tests the task you described. Argos reports what checks are missing instead of guessing. |

## Owner edits

You can edit `AGENTS.md` yourself, for example to add a rule Auto Climb reported as practice-only. Argos
then sees an *untracked owner edit*. Its instruction audit fails, and its own experiments refuse to
start, until the edit is adopted into its journal.

To adopt the edit:

1. Start a task-focused campaign on a suite that has saved runs from before your edit.
2. Name the edit in the task text, with at least two before-edit run IDs and two after-edit run IDs from
   the same suite, model and settings.
3. Argos makes the adopt call itself. Adoption records the edit; it does not claim a gain.

## Reading results honestly

- **Compare like with like.** Only compare runs with the same suite version, model, hardware and question
  order. The results view refuses other comparisons.
- **One run is a clue, not a result.** Scores move between identical runs. Repeat before you conclude
  anything.
- **A miss can be the test's fault.** If a question never stated the allowed values (for example
  lowercase `pdf`), a "wrong" answer shows a gap in the question, not a weakness in the model. Check the
  exact prompt and scorer before blaming the model.
- **A maxed-out suite can't show improvement.** When a setup already scores 20/20 or 70/70, pick a
  harder suite or describe a harder task.

## What you decide

Argos chooses its experiments. You decide:

- which tasks matter;
- what counts as success;
- the budget: time, experiments and downloads;
- whether to loosen any keep rule.

Anything that touches boot media, model downloads, SSH or permissions always asks first. For running the
loop unattended on a dedicated machine, see [HANDS-OFF-STANDING-ORDERS.md](HANDS-OFF-STANDING-ORDERS.md)
and [HANDS-OFF-RUNBOOK.md](HANDS-OFF-RUNBOOK.md).
