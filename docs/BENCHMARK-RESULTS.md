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
Quick and standard are different suites. Ability accuracy and format-error counts
are recomputed from item evidence. Speed medians are recomputed from measured
runs; all three generation-rate measurements must be known to rank a prompt size.
Unknown or skipped values stay unknown. Each prompt size has its own rows.

Hardware and Ollama/Argos versions may differ between selected runs; inspect the
saved originals before interpreting a difference as model quality or performance.
The table carries model tag, manifest digest, timestamp and run ID. Tool-format
scores do not establish that real tools work. Code execution is still excluded.

Reads are bounded to 1 MiB, schema/version/identity and nonfinite values are
checked, and linked paths are refused. Invalid listing entries are counted and
excluded rather than silently accepted. New results never overwrite an existing
run ID. CSV quotes fields normally and prefixes formula-bearing labels for
spreadsheet safety. JSON retains the original label.
