---
name: argos-improvement
description: Improve the configured assistant on owner-selected tasks using relevant, matched evidence.
---

# Improve with evidence

When the owner asks for self-improvement, start with a recurring task the owner
cares about and an observable definition of success. Use relevant saved task
examples or outcomes when available, and keep owner effort, reliability, latency,
and quality visible as separate measures. Use the workspace AGENTS.md for the
installed operating guide. Do not recommend or trial a larger model based on fit,
parameter count, or an Argos-authored score. Consider model changes only when
repeated evidence on the owner task points to model capability as the limiting
factor and other causes have been checked. Use ordinary OpenClaw tools and
Argos's reviewed reversible flows. Keep a private journal linking snapshots and
before/after run IDs.

Use `argos_log` with one `text` field to append campaign notes and the complete
`## Next` or `## Done`. It supplies the host timestamp and saved-run receipts;
it does not verify prose claims about changes. Never overwrite the log.
Use `argos_evaluate` only when an available suite measures a behavior relevant
to the owner task. If no suite does, do not fill the campaign with generic
probes or make a change from unrelated scores. Report that task-specific
measurement is missing and propose what repeatable examples and independent
success checks would be needed. Fixed quick, standard, challenge, tool-schema,
tool-plan, and tool-sequence suites are Argos-authored diagnostics, not external
benchmarks. A score describes only its suite and configuration; it does not
establish owner-task improvement or general ability. The tool creates a
tool-free embedded OpenClaw turn with temporary state and copied instructions
for each fixed task, and saves a private result. Evaluation children answer the
task; they do not run campaign steps or use the owner's gateway/session queue.
Each tool wait is bounded to eight minutes. If `argos_evaluate` returns a running
job, use `argos_evaluate_wait` with its job ID until the saved result is returned.
If a turn ends before returning the job ID, use `argos_evaluate_status` to find
the current job, then continue polling. An interrupted agent turn does not cancel
a host-owned evaluation; do not start another experiment or edit instructions
while the job is running. Only the trusted host owner-control path can request
cancellation.
If a suite is relevant to the owner task, inspect its exact tasks and scoring
rules before using it. Tool-schema, tool-plan, and tool-sequence can diagnose
structured tool-call behavior when that behavior is part of the task. They do
not execute tools. Their bundled held-out partitions are internal transfer
signals because the items and answer keys ship with the image; they are not
sealed or independent validation. Do not move to another suite just because a
score is saturated. Keep suite scores separate and never present their built-in
keep thresholds as proof of owner-task success.

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

When the owner starts `argos proctor improve`, work directly from the supplied
owner task and success criteria. The fixed Proctor quiz is a separate optional
coaching check; it is not a campaign prerequisite or owner-task evidence. Make
an experiment only when relevant baseline evidence supports it. Collect at
least two distinct matched baselines and two candidate runs after one reversible
change, then keep or restore through the host tools. Preserve all run IDs and
report any practice result separately; it cannot qualify task improvement.

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
candidate runs with the same relevant task, suite version, model/configuration,
and execution method. Host score thresholds are gates for the diagnostic suite;
they are not proof that the owner task improved unless its success measure is
directly represented and scored. A reliability gain instead needs
unchanged-or-higher correct count, fewer format errors, and median latency no
more than 1.5 times baseline. Use a genuinely separate task sample or outcome
to check transfer when available. Bundled held-out items are not independent
validation. Call
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

If a plugin tool is unavailable and a relevant suite exists, the equivalent
assistant command is `argos bench openclaw --suite SUITE --json`, using the
matching suite name. The raw-model `argos bench ability`
command does not test workspace instructions. Check the receipt's matching
`openclaw-SUITE` name and the `openclaw embedded; ephemeral state; tools denied; v2` execution path. Each retest
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
