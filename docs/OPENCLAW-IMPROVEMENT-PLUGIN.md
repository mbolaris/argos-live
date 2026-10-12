# Argos Live: a lightweight OpenClaw improvement plugin

Product direction agreed October 12, 2026. This supersedes the Auto Climb
coordinator as the next development target. Progress belongs in
[BACKLOG.md](BACKLOG.md).

## Implementation status — October 12, 2026

A first working prototype is installed on Toronado as OpenClaw plugin
`argos-improve` version `0.1.3`. It registers
`argos_evaluate` (fixed 20-task quick or 70-task standard Argos ability suite)
and `argos_compare` (compatible saved-run comparison). The runner creates fresh
ordinary OpenClaw sessions per task, records provider/model identity, outputs,
scorer receipts, elapsed time and suite version in private `argos-bench/1`
results. The bundled skill explains how to use the tools and make one reversible
change. The owner prompt has a removable Argos improvement block.

This is a first live prototype, not the complete experience described below:
there is no one-button continuing session, experiment journal, automatic or
verified restore, task-level watch UI, or accepted standard external benchmark.
The current suite is Argos' own fixed ability suite, not IFEval and not a
general measure of intelligence. Initial Toronado quick runs on the same model
scored 18/20 and 19/20 without configuration changes; one experimental prompt
change scored 16/20. This is enough to demonstrate the tool path and a useful
regression signal, but not enough repetitions to estimate noise or claim a
general ability change. The agent incorrectly reported that an instruction
restore was complete; the host detected the mismatch and restored from a private
pre-trial copy. Restore verification must be host-owned before agent-led changes
are trusted.

The historical 52/70 (74.3%) standard baseline was superseded by later 70-task
model comparisons. On the same suite and prompt, qwen3:4b scored 54/70 in 151.37s
and qwen3:14b scored 57/70 in 187.71s. The larger model gained three items but
was about 36 seconds slower; category changes were mixed, so this is a modest
suite-specific signal, not a broad quality claim. The suite's
`tool-call` category checks a JSON-shaped proposed call; it does **not** execute
or verify a real tool action. Its `instruction` category checks constrained text
formatting, not completion of external actions. These are measured suite scores,
not standard benchmark results or general capability claims.

Do not describe the plugin as self-improvement completed. Current Toronado
configuration allows OpenClaw file tools and the two benchmark tools while
denying shell, browser/web, gateway and runtime controls. Preserve that file access;
startup validation now accepts the reviewed policy instead of incorrectly
requiring `group:fs` to be denied. The clean-image bootstrap, recommended model
choice and plugin packaging are being validated in this branch; no new ISO has
been built from these changes yet. On Toronado's measured RTX 3090, qwen3:14b
fits the current 32K estimate with headroom and qwen3:30b is tight; the existing
model flow can make that candidate easy to try. The plugin does not download or
switch models itself: the owner uses the reviewed Argos model flow, then the
agent can compare matched runs. Paid spending and permission changes remain
explicit owner decisions.

## The experience

Boot the Argos Live image on native hardware or in a VM. OpenClaw is already
configured with a local starter model, benchmark tools, a shared improvement
guide and operating instructions. Press **Start improving** and watch the agent
evaluate its setup, explain a useful experiment, make a reversible change, and
compare the results. Ordinary OpenClaw chat lets the owner coach it along the way.

The game is customizing and optimizing the owner's OpenClaw installation.
OpenClaw does the improving. Argos makes its actual work and evidence visible.
A loyal agent serves the owner's goals, protects their information, respects
Stop and corrections, and admits failure or uncertainty. It does not pursue
scores, more permissions, spending or continued operation as goals of its own.

## Keep the harness small

Ship one pinned OpenClaw extension with benchmark tool entry points, a bundled
skill/guide and a small results adapter. Use the supported plugin and workspace
instruction mechanisms in the pinned host release; inspect the actual SDK before
selecting registration APIs. Do not invent a global system-prompt config key.
The proposed operating text is in [the improvement guide](SELF-IMPROVEMENT-GUIDE.md).

- **OpenClaw owns:** hypotheses, experiment order, tool use, model selection,
  configuration/skill changes, explanations and requests for owner support.
- **Benchmark tools own:** fixed task delivery, scoring, identities, measured
  timings and durable run evidence. The agent's opinion is not the score.
- **Argos owns:** boot/runtime provisioning, existing authenticated access,
  visible progress/results, Start/Stop and a reviewed recovery entry point.

No second planner, candidate allowlist of prompt experiments, mandatory countdown,
automatic promotion policy, new model downloader or additional tool framework.
Reuse existing download, storage and recovery primitives when needed, without
making their old UI workflows mandatory. Do not add general-purpose frameworks
merely to wrap a few benchmark commands.

## Benchmark tools

Minimum interface, names illustrative until SDK implementation:

1. **Evaluate:** run a named, versioned suite through the configured OpenClaw
   assistant in fresh evaluation sessions; return measured results and run ID.
2. **Compare:** compare compatible runs, identifying gains, regressions, timing
   and resource use. Explain incompatible suite/configuration conditions.
3. **Record experiment:** link a hypothesis and change/snapshot identity to
   before/after runs, with the agent's keep/restore decision and explanation.

The runner must not recursively ask the evaluation agent to launch itself.
Use the pinned host's supported session execution from a separate runner context;
verify that plugin calls do not deadlock the gateway or consume a competing
legacy workload. Benchmark sessions retain the actual model, prompts, tools and
skills under test; prevent answer-key access and result contamination separately.

The first prototype currently uses Argos' fixed ability suite. That is useful
for exercising the plugin and showing concrete misses, but it is not an
established external benchmark. Before adding a standard scorer, compare the
maintenance and license costs of a small IFEval subset with the value it adds;
SQuAD 2.0 reading/abstention and MBPP+/EvalPlus coding are later possibilities.
Verify licenses, dependencies, scoring parity and local execution before
bundling. Keep external scorer dependencies isolated from the stdlib-only Argos
runtime. Use original task/scorer definitions and label subsets as quick checks,
not official full-benchmark scores.

Record suite/scorer revisions and hashes, task IDs, exact model/digest and
redacted configuration identity, answers/artifacts, checks, failures and timings.
Record tokens/cost only when actually supplied by the backend; unknown is unknown.
Separate infrastructure errors from wrong answers. A changed benchmark starts a
new comparison series. Keep a trusted reference outside the agent's editable
workspace and identify the actual trust boundary; hashes in that same workspace
alone cannot establish integrity against an agent with full permissions.

Public benchmarks may be in model training data. Repeated tuning on a fixed
subset establishes improvement on that subset. Confirm useful gains on separate
tasks before describing broader improvement; no elaborate rotation coordinator
is required. Show capability scores separately, not an invented IQ or school grade.

## Watch the work

One main view shows what the agent is trying, the current task, actual tool events
and answer, the measured verdict and before/after result. A compact timeline holds
completed experiments, changes kept/restored and requests for help. Details hold
technical settings. Normal chat remains separate from Start/Stop.

Use actual OpenClaw events where available. Whole-turn output is labelled as such;
never manufacture streaming or expose hidden reasoning. Agent narration, user
guidance and scorer events have distinct authors. The agent cannot rewrite a
scorer verdict by writing an explanatory log entry. Keep records durable and
detect truncation/modification; do not claim a file is immutable when the agent's
effective permissions can rewrite it. Logs are local by default, with redacted,
explicitly selected exports rather than automatic leaderboard uploads.

## Owner control and recovery

Broad owner-authorized OpenClaw tool access is supported; the plugin does not
grant itself permissions or alter the host's authentication. Full permissions
inside a VM/live environment are not permission to modify host/internal disks,
firmware or security settings. Paid APIs, downloads and sustained compute use
follow the owner's configured allowance. Minimal resource enforcement and Stop
remain; a system prompt is not an enforcement mechanism.

Before changing settings or workspace instructions, preserve a private snapshot
and a precise restoration recipe. Model selection, package upgrades and storage
changes have different recovery needs; config Git alone cannot undo all of them.
Keep keys and private conversations out of source control and public receipts.
Initially demonstrate one reversible prompt/config change, with no package or
storage migration. Do not overwrite owner edits when restoring.

Start must actually launch a continuing OpenClaw task, not merely display a guide.
Prove continuation, Stop and interrupted-run behavior on the pinned runtime.
Stop prevents further experiments and attempts safe cancellation of current work;
if rollback is needed or cancellation is incomplete, show that plainly.

## Small implementation sequence

- **LP1 — prototype implemented; acceptance in progress:** thin OpenClaw adapter
  for fixed quick/standard Argos ability suites, private durable results and
  compatible-run comparison. Verify known pass/fail fixtures and real local-model
  runs. Decide whether an upstream scorer adds enough value to justify its
  dependencies. No new coordinator.
- **LP2 — agent-led experiment:** install the guide/instruction block without
  replacing owner persona files. One Start executes baseline, one agent-selected
  reversible change, retest and evidence-backed keep/restore within an allowance.
  Verify actual files/configuration and readiness afterward, including interruption.
- **LP3 — watch and boot integration:** show actual task/answer/verdict and agent
  commentary in the existing view, with working Stop/chat and reconnect. Pin and
  bundle the extension/assets; prove a clean VM boot and native Toronado run.
  Offline readiness, phone usability and reboot persistence are separate checks.

Pause expansion of the old Auto Climb policy. Keep its recovery and evidence code
until replacements pass; do not delete working paths or leave pending journals.
An explicit Start chooses one workload owner, so old and new loops cannot run
concurrently. Existing installed sessions and saved results remain readable.
PR106's live reliability fixes are reusable transition work, not proof of this
plugin. No new ISO/USB or live permission changes occur merely from this document.

References: [pinned OpenClaw plugins](https://github.com/openclaw/openclaw/blob/v2026.10.1/docs/tools/plugin.md),
[IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval),
[SQuAD 2.0](https://rajpurkar.github.io/SQuAD-explorer/),
[EvalPlus](https://github.com/evalplus/evalplus).
