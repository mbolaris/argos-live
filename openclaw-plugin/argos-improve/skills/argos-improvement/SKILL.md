---
name: argos-improvement
description: Measure the configured OpenClaw assistant with Argos benchmarks and compare saved runs before recommending an improvement.
---

# Improve with evidence

When the owner says go, run a baseline and pursue useful reversible local
experiments. Use the workspace AGENTS.md for the installed operating guide.
Prefer a comfortably fitting stronger model early; inspect `argos hw --json`,
`argos catalog --json`, and `argos storage --json` first. Use ordinary OpenClaw
tools and Argos's existing managed download/switch flow, without a second planner.
Keep a private workspace journal linking snapshots and before/after run IDs.

Use `argos_evaluate` to measure the configured assistant. Start with `quick`;
use `standard` when the owner wants the longer evaluation. The tool creates a
fresh ordinary OpenClaw session for each fixed task and saves a private result.
Explain that the score describes this suite and configuration, not general
intelligence.

If a plugin tool is unavailable, the equivalent assistant command is
`argos bench openclaw --suite quick --json`. The raw-model `argos bench ability`
command does not test workspace instructions. Check the receipt's `openclaw-quick`
suite and `openclaw gateway; fresh session per task` execution path. Each retest
needs a new run ID; an old result or an unsaved claim is not a new measurement.

Before proposing a change, inspect the task-level misses and ask what useful
behavior they represent. State one hypothesis and one reversible change. Preserve
the current settings and owner instructions before editing. Do not change the
benchmark or scorer to improve the score. After the change, run the same suite
and use `argos_compare` on the two run IDs. Report gains, regressions, elapsed
time, and uncertainty; restore the previous settings if the change does not help
or causes a regression. Verify the restore before saying it is complete.

For a stronger local model, use Argos's reviewed fit and storage guidance; if its
existing model flow needs an owner action, say exactly what to click and why. Ask
before spending paid API credits, installing packages, changing permissions, or
making a change that cannot be restored from the local snapshot. Stop when asked.
Keep explanations friendly and concise; report actual task activity and results
rather than hidden reasoning or invented progress.
