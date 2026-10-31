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
Each tool wait is bounded to eight minutes. If `argos_evaluate` returns a running
job, use `argos_evaluate_wait` with its job ID until the saved result is returned.
If a turn ends before returning the job ID, use `argos_evaluate_status` to find
the current job, then continue polling. An interrupted agent turn does not cancel
a host-owned evaluation; do not start another experiment or edit instructions
while the job is running. Only the trusted host owner-control path can request
cancellation.
Explain that the score describes this suite and configuration, not general
intelligence.

When tool-call formatting is the measured weakness, use `tool-schema`. Each
question supplies exact tool schemas; 20 practice and 20 unseen-vocabulary
questions use disjoint tool names and argument keys, with target position
balanced across the three options. Both partitions and answer keys are bundled
with the image, so this is a within-suite transfer signal, not independent or
sealed validation. A tool-schema instruction change can be kept only after
repeated overall improvement, no increase in format errors, and both candidate
unseen-vocabulary scores meeting or exceeding the strongest baseline on that
partition. The host enforces a 3/40 overall gain threshold. This is an
Argos-authored probe, not an external benchmark.

When direct schema calls are saturated, use `tool-plan` to check multi-constraint
selection among four tools, value derivation and full argument assembly. It has
20 practice and 20 bundled held-out items with disjoint tool names and argument
keys. Held-out items provide an internal vocabulary-transfer signal, not
independent validation or evidence of real tool execution. The same host gate
applies: repeated 3/40 overall gains, no format-error increase, and both
candidate held-out scores at least the strongest matched baseline.

When `tool-plan` saturates, use `tool-sequence` to probe ordered two- and
three-call workflows. Each item supplies four schemas and explicit literal
`$stepN.field` bindings for values returned by earlier calls. The expected
answer is a minimal JSON sequence; no calls are executed. Practice and bundled
held-out workflows have disjoint tool names and argument keys. Treat held-out
scores as an internal transfer check only, not independent validation. The same
host gate applies: repeated 3/40 overall gains, no format-error increase, and
both candidate held-out scores at least the strongest matched baseline.

When the host launches a dedicated Proctor session and exposes `argos_proctor_*`
tools, use them only for the host-selected exam. The host, not the agent, selects
the form, exposure tier, tested model snapshot and assistance policy. Read only
items from the active module, submit answers, and follow server-selected module
transitions. The examinee tools intentionally return no scores, answer keys or
signed transcript. A completed exam is evidence for the trusted host to review;
it does not by itself validate an instruction change or prove general ability.
These tools are unavailable in ordinary improvement sessions.
When the host specifically selects a practice session, use
`argos_proctor_feedback` after completion to inspect aggregate score and domain
counts plus item-level submitted and expected answers, then identify the exact
misses and choose a practice experiment. Expected answers are released only
after a terminal host-selected practice session. The tool refuses feedback for
assessment and held-out sessions.

When the owner starts `argos proctor improve`, treat the practice feedback only
as coaching context. The host starts a separate admitted campaign after the
practice transcript is saved and the practice reservation is released. Make an
independent hypothesis from saved baseline evidence, collect at least two
distinct matched baseline runs and two candidate runs after one reversible
change, then keep or restore through the host tools. Preserve all run IDs and
report the Proctor score separately; it cannot qualify an improvement.

For an instruction experiment, use `argos_inspect` to read the canonical
workspace instructions, their hash, current configuration receipt, active
change, and keep policy. Use one specific saved baseline from the current host
controller, then call `argos_edit_instructions` with that baseline ID, the
inspected hash, one exact replacement, and a short hypothesis. This tool makes
one reversible change only in the canonical `AGENTS.md` and saves the original
bytes and configuration on the host. It refuses stale baselines, unrelated
controller runs, ambiguous replacements, and a second unresolved edit.

If `argos_inspect` reports that the live instruction hash differs from the last
journaled hash, do not overwrite or restore the live file. First verify two
compatible baseline runs with the last journaled prompt hash and two candidate
runs with the current prompt hash, using the same suite, model, configuration,
and hardware. Then call `argos_adopt_external_instruction_edit` with both
hashes, the four run IDs, and a short reason. This records the already-existing
edit and its saved evidence without changing `AGENTS.md`; adoption is explicitly
unqualified and does not count as a host-managed keep. If a saved run lacks a
controller-child receipt, its audit provenance is marked saved-run-records only.
If matching run records are missing, stop and report the mismatch for review.

After the edit, collect two distinct matched baseline runs and two distinct
candidate runs with the same suite, model/configuration, and execution method.
The host checks the saved receipts and practice policy: quick needs at least 2
additional correct answers, standard 4, and challenge, tool-schema, tool-plan
or tool-sequence 3, with format errors no higher than baseline. A reliability
gain instead needs unchanged-or-higher
correct count, fewer format errors, and median latency no more than 1.5 times
baseline. These are practice thresholds, not independent proof of transfer.
Use a separate challenge or held-out form to check transfer when available. Call
`argos_resolve_instructions` with the current change ID and hash to keep only a
qualified change or restore the exact snapshot. The host verifies the resulting
bytes and preserves concurrent owner edits. Never claim a keep or restore until
that tool returns the verified result.

Before reporting the campaign outcome, call `argos_audit_instructions`. Use its
host-verified change IDs, saved run IDs, aggregate scores, and keep/restore state.
An empty journal means no instruction experiment was recorded; a failed audit
means stop and report that evidence could not be verified. The audit does not
verify prose in `IMPROVEMENT-LOG.md`, independent model-weight identity, or
generalization to held-out tasks. Keep those limitations explicit.

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
Use each saved evaluation result's run ID, suite version, and coverage to group
candidate runs. Never compare different suites (such as quick and tool-plan) as
before/after evidence. `argos_compare` validates execution path,
non-intervention settings, recipe, restoration, and coverage. If comparison is
refused, use its `pair_checks` and safe settings, recipe, and coverage
fingerprints to choose a compatible pair; do not retry the same IDs or infer
raw configuration from a fingerprint. If no matched pair exists,
collect a second baseline in the same suite. Cross-suite scores can be reported
separately but are not comparable. Report gains, regressions, elapsed time, and
uncertainty. Restore a non-beneficial change and verify the restore before
saying it is complete.

For a stronger local model, use Argos's reviewed fit and storage guidance; if its
existing model flow needs an owner action, say exactly what to click and why. Ask
before spending paid API credits, installing packages, changing permissions, or
making a change that cannot be restored from the local snapshot. Stop when asked.
Keep explanations friendly and concise; report actual task activity and results
rather than hidden reasoning or invented progress.
