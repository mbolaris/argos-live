# Evaluation execution boundary

The fixed assistant suites measure text answers and proposed tool-call JSON.
They do not require shell, filesystem, browser, model-control or plugin tools.
The everyday campaign controller retains its own normal capabilities; evaluation
children must not inherit those capabilities or its durable session queue.

Each evaluation turn now uses the pinned OpenClaw embedded runtime (`--local`)
with a new temporary HOME, state directory, configuration and working directory.
Only bounded copies of AGENTS, SOUL, IDENTITY, USER and TOOLS instructions are
provided. Campaign journals, workspace tool scripts, skills, owner credentials,
plugins, gateway configuration and existing sessions are not copied. All tools
are denied by OpenClaw policy. Only the pinned bundled Ollama provider plugin
is allowed (2026.10.4 needs it for inference), memory plugins are disabled, and the model runtime is
explicitly OpenClaw with the configured model served by localhost Ollama.
Interrupted embedded work cannot enter the owner's gateway database and therefore
cannot resume there on gateway restart. The temporary state is removed after the
CLI exits. This is an OpenClaw capability boundary, not an operating-system sandbox
for arbitrary hostile host software.

Concurrent changes to the owner's workspace invalidate a benchmark. The harness
preserves those edits and additions rather than rolling them back or moving them
away. Saved results identify the new execution path; the comparison tool rejects
comparisons with the older gateway/tool-enabled execution path. Establish a fresh
baseline after migration. A gain on one quick run remains inconclusive.

## Existing persistence

The new runner prevents future gateway evaluation sessions. It does not erase
old ones. Before launching a gateway, Argos checks its existing agent databases
for pending legacy `argos-trial-*` sessions and refuses startup if any remain.
Unreadable session metadata also requires review. Completed legacy sessions are
preserved. Disabling future heartbeats does not cancel pending sessions or tools.

Recovery must snapshot configuration, workspace and consistent databases, identify
pending work, and use a reviewed recovery procedure before restarting. Do not
manually mark a running session complete, delete its evidence, or assume that a
quiet process list means its durable work cannot resume.

## Model selection

The CLI refuses to select missing managed weights before prompting or writing
configuration. The bundled starter is checked at its read-only image location.
Downloading remains a separate agent-owned step. This preflight does not replace
the model acquisition workflow's integrity checks.

## Validation scope

Tests cover policy/configuration separation, unique temporary state, local CLI
routing, cleanup, preservation of owner files, rejection of nonlocal providers,
missing-model selection and pending legacy session startup refusal. Real pinned
OpenClaw execution must additionally be tested in a disposable VM, including an
attempt to execute a tool and write outside the evaluation workspace. A source
overlay smoke test is not acceptance of a newly built ISO or physical hardware.
Do not resume unattended trials on the previous image merely because unit tests
or configuration validation pass.
