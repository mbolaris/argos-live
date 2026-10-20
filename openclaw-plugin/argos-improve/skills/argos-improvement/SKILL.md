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

Use `argos_log` with one `text` field to append campaign notes and the complete
`## Next` or `## Done`. It supplies the host timestamp and saved-run receipts;
it does not verify prose claims about changes. Never overwrite the log.
Use `argos_evaluate` to measure the configured assistant. Start with `quick`;
use `standard` for the broader original suite. When standard is saturated or
does not expose a useful weakness, use the separate 40-task `challenge` form.
It covers multi-step arithmetic, constraint selection, structured extraction
and inert proposed actions. It is a fresh Argos form, not an external benchmark.
The tool creates a
tool-free embedded OpenClaw turn with temporary state and copied instructions for
each fixed task, and saves a private result. Evaluation children answer the task;
they do not run campaign steps or use the owner's gateway/session queue.
Explain that the score describes this suite and configuration, not general
intelligence.

For an instruction experiment, use `argos_inspect` to read the canonical
workspace instructions, their hash, current configuration receipt, active
change, and keep policy. Use one specific saved baseline from the current host
controller, then call `argos_edit_instructions` with that baseline ID, the
inspected hash, one exact replacement, and a short hypothesis. This tool makes
one reversible change only in the canonical `AGENTS.md` and saves the original
bytes and configuration on the host. It refuses stale baselines, unrelated
controller runs, ambiguous replacements, and a second unresolved edit.

After the edit, collect two distinct matched baseline runs and two distinct
candidate runs with the same suite, model/configuration, and execution method.
The host checks the saved receipts and practice policy: quick needs at least 2
additional correct answers, standard 4, and challenge 3, with format errors no
higher than baseline. A reliability gain instead needs unchanged-or-higher
correct count, fewer format errors, and median latency no more than 1.5 times
baseline. These are practice thresholds, not independent proof of transfer.
Use a separate challenge or held-out form to check transfer when available. Call
`argos_resolve_instructions` with the current change ID and hash to keep only a
qualified change or restore the exact snapshot. The host verifies the resulting
bytes and preserves concurrent owner edits. Never claim a keep or restore until
that tool returns the verified result.

If a plugin tool is unavailable, the equivalent assistant command is
`argos bench openclaw --suite quick --json`. The raw-model `argos bench ability`
command does not test workspace instructions. Check the receipt's `openclaw-quick`
suite and `openclaw embedded; ephemeral state; tools denied; v2` execution path. Each retest
needs a new run ID; an old result or an unsaved claim is not a new measurement.
These are native tools, not shell commands. Run evaluations sequentially and
repeat a candidate to confirm a gain. Establish a new baseline when the recorded
execution method differs; do not compare old gateway runs with isolated runs.

Before proposing a change, inspect the task-level misses and ask what useful
behavior they represent. State one hypothesis and one reversible change. Use
the host-managed instruction tools for `AGENTS.md`; for other authorized model
or configuration experiments, preserve the relevant files and use the reviewed
Argos recovery path. Do not change the benchmark or scorer to improve the score.
Use `argos_compare` for compatible runs and report gains, regressions, elapsed
time, and uncertainty. Restore a non-beneficial change and verify the restore
before saying it is complete.

For a stronger local model, use Argos's reviewed fit and storage guidance; if its
existing model flow needs an owner action, say exactly what to click and why. Ask
before spending paid API credits, installing packages, changing permissions, or
making a change that cannot be restored from the local snapshot. Stop when asked.
Keep explanations friendly and concise; report actual task activity and results
rather than hidden reasoning or invented progress.
