# Proctor match watch

The Proctor campaign card shows one evaluation round as something the owner can
follow: setup, the question on the clock, the answer and verdict, a score
reveal, a comparison against a baseline, and a replay that can be reopened
later. It builds on the live watch from PRs #164 and #165 and changes nothing
about how a round is run, scored, or kept.

## What the owner sees

- **Stage strip**: Setup, Round, Score, What changed.
- **Clock**: time on the current question, ticking between status polls, with
  the campaign time beside it.
- **Question pips**: one per question; correct, miss, not scored, not asked yet.
- **Answer**: shown when it lands, with the saved verdict and a one-line reason.
  The pinned OpenClaw CLI returns an answer only when the turn finishes, so the
  page says so and does not imitate typing. The controller accepts bounded
  visible-answer snapshots (`evaluation-answer-partial`, 8,192 characters, only
  for the question on the clock); nothing in the shipped runner sends them yet.
- **Score reveal**: the saved score, median reply time, the saved run ID, and
  separate practice and held-out tallies when the suite has partitions. The two
  are never merged.
- **What changed**: baseline score to round score, the questions won and lost,
  median reply time before and after, and whether the model and instructions
  were the same.
- **Kept or rolled back**: the host instruction journal's own record for the
  trial that names this run, the runs it used, and the preset bar for the suite.
- **Your steps**: clicks this dashboard accepted during the campaign (Start,
  Retry recovery, SSH recovery approval) with their times. Physical steps and
  anything typed elsewhere are not observed and are not counted.
- **Replays**: any saved ability round by run ID (`#replay=<run id>` in the
  address, so a refresh or a saved link returns to it), and campaigns watched
  from this dashboard, including ones that failed before saving a round.

## Notices

Stalls, failures and cancellations are stated in words, not implied:

| Notice | Meaning |
| --- | --- |
| Slow answer | The open question has run past `SLOW_ANSWER_SECONDS` (120 s). |
| Quiet | No event for `QUIET_SECONDS` (300 s) with no question open. |
| Round cancelled / failed | The saved run's state. Shown, replayable, never compared. |
| Campaign stopped | The bounded failure code. Nothing from it counts. |
| Recovery needed | Argos did not come back; the retry button is the next step. |
| Lost contact | The page cannot reach the dashboard. It keeps retrying and rejoins the same watch ID. |

The thresholds only label what the owner sees. Host timeouts still decide when
work stops.

## Evidence rules

- Verdicts are the outcomes saved when the run was scored. Nothing here rescores.
- A comparison needs the same suite version, the same question order, and two
  fully covered rounds. An unfinished round is saved and replayable, and is
  never compared or used as a baseline.
- The baseline is the one the host journal recorded for the trial when there is
  one; otherwise the latest earlier complete round of the same test.
- The comparison is descriptive. `instruction_changes` and its keep policy
  remain the only authority on whether a change stays, and Argos owns its model
  and instruction experiments.
- A fixed-suite score describes those questions. It is not evidence that an
  owner task got easier.

## Privacy

`/api/proctor-match/*` is read-only and uses the dashboard session token. Its
projections carry the question, the visible saved answer, the verdict and the
reply time. They never carry answer keys, scorer rules, hidden reasoning,
session IDs, hardware details, instruction hashes or private paths. Campaign
records under `~/.local/state/argos-live/proctor-watch/` hold only what the
live watch already showed, in an owner-only directory.

## Working on it

`scripts/serve-match-fixture.py` serves the real dashboard, campaign controller,
scoring, results store and match module over a scripted model, so UI changes
need no Toronado access, SSD move or reboot:

```sh
python3 scripts/serve-match-fixture.py --suite challenge --pace 1.2
```

Start a campaign from the page; the first word of the task picks the scenario
(`fixture:round`, `fixture:fail`, `fixture:cancel`, `fixture:stall`,
`fixture:crash`, `fixture:stream`). `scripts/smoke-proctor-match.mjs` drives all
of them in Chromium, including refresh and lost contact, and saves screenshots.

`scripts/smoke-match-real.py` follows a real model's round through the same
controller and routes on a disposable hosted VM (the `match_watch_rounds` input
of the native-chat workflow). The host runs the evaluation directly there; it
does not exercise the agent-led campaign, Toronado, or the deployed model.
