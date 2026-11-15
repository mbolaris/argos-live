# Saved benchmark results

Speed and ability commands save private `argos-bench/1` JSON files in
`~/.local/share/argos-live/results/`. With mounted encrypted persistence this
location survives reboot; RAM-backed try mode does not. `--results-dir` chooses
another directory explicitly. Owner model names and hardware details can identify
a personal machine; do not publish result files automatically.

`argos bench results` lists runs with IDs. Use `--load ID` to inspect full JSON,
`--compare ID ID` for a readable comparison, or `--compare ID ID --csv` to export
CSV on stdout. `--json` exposes structured listing/comparison and rejected-file
names. `--delete ID` removes only that run, without touching models or profiles.

Comparison requires identical kind, suite version, settings and item/prompt
coverage. Cancelled/incomplete ability runs and failed restoration are refused.
Quick, standard, challenge, tool-schema, tool-plan and tool-sequence are distinct suites.
Tool-schema, tool-plan and tool-sequence comparisons report practice and held-out deltas separately. Ability accuracy
and format-error counts are recomputed from item evidence. Speed medians are recomputed from measured
runs; all three generation-rate measurements must be known to rank a prompt size.
Unknown or skipped values stay unknown. Each prompt size has its own rows.

Hardware and Ollama/Argos versions may differ between selected runs; inspect the
saved originals before interpreting a difference as model quality or performance.
The table carries model tag, manifest digest, timestamp and run ID. Tool-format
scores do not establish that real tools work. Tool-sequence scores describe
ordered call planning with literal result references, not call execution. Code
execution is still excluded.

Reads are bounded to 1 MiB, schema/version/identity and nonfinite values are
checked, and linked paths are refused. Invalid listing entries are counted and
excluded rather than silently accepted. New results never overwrite an existing
run ID. CSV quotes fields normally and prefixes formula-bearing labels for
spreadsheet safety. JSON retains the original label.

## Headroom report

`argos headroom` answers one question from saved runs: on which forms can the
deployed build still show a gain? A form it already maxes out cannot show an
improvement. The command runs no model and changes nothing. `--json` prints the
same data, and the dashboard serves it read-only at `GET /api/headroom` with the
session token.

Each row is one form: the ability suites, `documents-short`,
`owner-recovery-decision` and the three Auto Climb practice tiers. A row shows
the suite version, the last three matched scores (newest first, raw counts) and
one status:

| Status | Meaning |
|---|---|
| `saturated` | The three most recent matched runs each scored at least 90 percent. |
| `has room` | Three or more matched runs, and at least one of the last three is under 90 percent. |
| `too few runs` | One or two matched runs. Run it again before deciding. |
| `never run` | No matched run of the current form version for this build. |

What "matched" means here:

- The build is the model in the assistant configuration. Where there is none
  (for example on a development machine) the model of the newest saved run is
  used, and the first line of the report says so. `--model TAG` picks another.
- A row holds only complete, full-form runs of the current suite version for
  that model. The newest such run sets the row; older runs join it only with the
  same model digest, settings, recipe and item coverage. Runs of other versions,
  models or settings, and partial, cancelled or lap-slice runs, are never
  scored. They are counted under `left_out`.
- Forms with a practice and a held-out half get one row per half. The halves
  are never added together.
- Runs through the assistant (the deployed build) and runs of the bare model
  (`argos bench ability`, `argos bench documents`) are separate rows. Bare-model
  rows appear only when the model has such runs.
- Runs made with different `AGENTS.md` instructions may share a row, because
  instructions are what the improvement loop changes. Such a row is marked
  (`instructions_varied`, `*` in the table).

Limits. Hardware and runtime versions are not part of the match. Auto Climb rows
read the current Auto Climb session file only, count its kept-build practice
runs, and do not report its held-out validation partitions, which are used once.
Auto Climb itself moves up a tier only after three perfect runs; this report's
90 percent line is a separate, looser flag. A status is a reading of three
scores, not a statistical test.
