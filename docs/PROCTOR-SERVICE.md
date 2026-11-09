# Owner-started Proctor service

`argos proctor practice` starts a host-selected practice session through a fresh,
private OpenClaw gateway profile. The profile preserves the selected local
Ollama model and its reasoning controls, grants `argos_proctor_*` tools plus
`argos_evaluate_wait` for one host-intercepted practice simulation, disables
bundled skills and heartbeat activity, and enables the plugin's host admission
hooks. The host owns the cartridge, caller and token keys,
signing key, subject snapshot, workload reservation, and transcript finalization.
The signed transcript is saved before the Proctor reservation is released.
Before practice, the host verifies the selected catalog manifest and every
declared model blob. The signed subject snapshot includes a digest of the
catalog manifest, the local manifest bytes, and each verified artifact digest,
size, and media type; it does not copy model weights into the transcript.

The command uses the bundled `pilot-a` cartridge unless the owner selects a
different form or supplies a compiled cartridge and form. The host may select
`--form composed-a` for an eight-item original practice form with multi-step
numeric reasoning, constraints, evidence sufficiency, scheduling, uncertainty,
aggregation and one intercepted tool-call simulation. It is bundled practice,
not independent or calibrated assessment, and its score is not directly
comparable with the six-item pilot. The pilot remains the default for now.
The bundled six-item pilot exercises the tool flow
and feedback path, including one `argos_evaluate_wait` call, and adds an
evidence-interpretation item about not diagnosing tool-selection weakness from
challenge items whose available-tool inventories are missing. This is public
practice content, not a held-out assessment. During
that item, the host intercepts the registered wait tool, records its actual
name and arguments in the signed transcript, and returns a labeled synthetic
response without starting an evaluation. Pilot v1.3 allows four minutes per
module for three items and a timing cushion based on native SDK round trips of
roughly twenty to thirty seconds in the recorded CPU test. The previous
one-minute pilot expired before submission. This changes only the public
uncalibrated pilot, not assessment timings. It cannot verify
general ability or establish an improvement. After a terminal practice session,
the host receives aggregate scores and item-level submitted/expected answers to
support coaching. If bounded host continuation ends before submission, the host closes the
session as `ABANDONED`, signs the partial transcript, and reports an incomplete
practice. A clean worker that never starts the exam produces a signed zero-item
ABANDONED receipt without releasing any questions after the bounded start attempts; this is incomplete evidence
and cannot pass image acceptance or start improvement. The launch prompt names
argos_proctor_start({}) as the required first action. Assessment and held-out
exams remain outside this entry point.

The host can continue a practice exam across short agent turns. It verifies
each SDK worker and process group has exited before admitting another turn,
retains the same exclusive workload reservation and exam, and fences off the
previous turn's credentials. For an unanswered item, the host surfaces exactly
that active question in the next bounded turn and records which item was shown.
The answer tool accepts the agent's item identifier and answer; the host binds
it only to an item surfaced in the same active module. The model can also fetch
questions through the item tool. It submits a module after
every item has a recorded agent answer and the worker has drained. It never
fills in an answer. This automatic submission policy is
recorded in the signed administration conditions. Breaks and deadlines remain host-owned.
The signed subject configuration records this administration mode. Sixteen
turns, thirty minutes, or two consecutive turns without progress bound this
coaching procedure; an unfinished exam is signed as ABANDONED. Uncertain
workers still quarantine the workload. Assessment and held-out sessions do not
use this continuation policy.

A practice worker that exits on OpenClaw's `hook_block` may enter the existing
no-answer retry path only when the response is bound to the current session,
the agent-end hook was observed, no host tool was requested or failed, and the
worker process group drained. The blocked turn receives no answer credit. Any
unresolved attempt ends as signed incomplete practice; this recovery rule does
not apply to assessment or held-out sessions.

Start, status, answer, submit and continue responses include a `next_step`
tool name and arguments to help the agent navigate the exam. After fetching an
item, the agent must solve it and supply its own answer. Navigation uses only
the exam state and recorded answer revisions; an incorrect recorded answer
advances the same way as a correct one. It never exposes correctness or chooses
an answer. Practice feedback is suggested only after completion; held-out exams
never offer it. These hints do not force an agent to continue, and the real-model
image test must still prove completion.

The plugin renders the next action in plain text as well as JSON. A question
response explicitly asks the agent to solve it and call the answer tool with
the surfaced item identifier and its own answer; the controller accepts only
items surfaced by the host or retrieved through the item tool. Recording an
answer explicitly asks it to continue or submit. These
directions carry no answer hints and do not turn an incomplete attempt into a
pass.

Fresh image configurations request temperature zero explicitly. Two separate
native fixture runs (39550951768 and 39550954625) completed all four v1.1 pilot items
at that setting, with the actual request temperature observed on the wire.
Each scored 3/4; this is limited workflow repeatability evidence, not an ability
gain. Existing owner configurations remain byte-for-byte unchanged, and the
private Proctor profile still preserves their selected generation controls.

`argos proctor improve --owner-task ... --success-criteria ...` starts a
host-admitted campaign directly from the owner's recurring task and observable
success measure. An optional `--measurement-suite` selects the one fixed suite
the owner has decided measures that task. The dashboard offers the same choice;
“None fits / not sure” is the default. The host rejects evaluations from any
other suite and rejects comparisons and instruction changes without the
owner-selected suite. The optional `owner-recovery-decision/0.5.0` suite is an
uncalibrated eight-case decision-only fixture: it uses simulated receipts and
scores an explicit minimum owner-action category and counts. It does not
execute tools or measure real recovery/owner time, and cannot authorize
instruction edits or keeps. With no suite selected, the service permits inspection and audit,
then reports `task-not-measured` without allowing score-driven changes. Proctor
practice remains a separate coaching check. The dashboard may show Argos's
bounded final report as an unverified suggestion for missing task checks; it is
not evaluation evidence and does not create or select a suite. Host admission
owns one workload reservation at a time, and the controller saves evaluations
even if the campaign agent turn ends. Practice scores never count as evidence
that an ability improved. The campaign follows the installed Argos improvement
skill for matched baseline/candidate runs, keep/restore decisions, and saved run IDs.
For a recovery campaign that obtains `argos_ssh_status`, the host also records a
sanitized `host_observation` from the signature-verified receipt. It shows the
bounded current SSH/persistence state separately from `task-not-measured` and
from benchmark scores. The structured observation omits receipt signatures,
receipt IDs, boot IDs, addresses and raw diagnostics. A ready observation means
SSH was already ready at that check; it does not say that the agent recovered
SSH, reduced owner time, or improved its ability. The agent's prose remains a
separate, unverified report.
The paired-SSH dashboard separately distinguishes an already-ready status from
a recovery job accepted through its one-use approval. It records that accepted
dashboard approval and the host-measured interval to its post-check; if the
service process had to reconcile an interrupted job, the interval is labeled as
time to the later observation. This is not total time from boot or dashboard
opening, and the page cannot count terminal commands outside itself. An already
ready status is never counted as a recovery success.

During an owner-started campaign, the local dashboard's Live test floor shows
the current fixed-suite question while Argos is answering, an elapsed timer,
and each completed response with its host-scored outcome and measured latency.
The live board retains the four most recent runs for the campaign.
The campaign timeline records bounded milestones such as instruction audit,
reversible change, resolution, and saved evaluation result; it omits tool
arguments and free-form campaign notes. A saved partial or failed run is labeled
with its state and is not presented as full coverage.
This is dashboard-only transient progress; it does not expose expected answers
or add the question text to saved evaluation records. The CLI runner returns a
response when the turn completes rather than streaming its tokens, so the live
view shows the question and a working timer until that complete response arrives;
it does not imitate a token stream. Round cards show median end-to-end reply time
and score movement only after complete runs with matching suite versions and
question order; score movement alone is not evidence that the owner's real task
got easier.

There is no automatic progression from quick to standard or challenge when a
score is saturated. A diagnostic suite is selected only when its tasks match the
owner's stated goal; scores remain separate by suite and cannot be compared
across suite types. When no bundled suite measures the task, use the
[owner-task evaluation protocol](OWNER-TASK-EVALUATION.md) to define a reviewed,
repeatable task pack. A draft pack is not a basis for a model or instruction
change until it has appropriate scoring and independent confirmation.
An incomplete practice is retained for review. An exam whose timer reached a
terminal state with unanswered items also remains incomplete; timed completion
does not produce a calibrated ability score.

The everyday agent's fresh local-tool profile includes the read-only
`argos_inspect`, `argos_audit_instructions`, and `argos_ssh_status` tools. On
startup, an existing configuration is migrated only when its local tool
policy matches the reviewed legacy profile; the full prior config is saved in
the private Argos state snapshots before those tools are added. Owner-edited or
otherwise unrecognized policies are left unchanged. This lets the agent inspect
saved evidence, complete the required instruction audit, and report SSH status
without asking the owner to type diagnostic commands. These tools do not grant
shell access or change the selected model.

The service refuses to start if the everyday OpenClaw gateway or Ollama already
occupies its loopback port. Close the everyday assistant first; the Proctor
command then owns and shuts down both its private Ollama process and gateway.

Example:

```sh
argos proctor practice
argos proctor practice --cartridge /path/to/reviewed-cartridge.sqlite3 --form practice-a --json
argos proctor improve --owner-task "use a tool correctly" --success-criteria "select the correct tool and arguments" --measurement-suite tool-schema
```

This is declared/cooperative enforcement within the same Argos user account.
It does not protect keys or files against another process with the same UID,
prove which weights the inference backend actually loaded after startup,
prevent direct access to the local Ollama API, or reserve the GPU against an
unrelated gateway that bypasses Argos workload admission.
The exact-image hosted service smoke requires the owner entry point, scoped
tools, managed gateway lifecycle, a signed completed practice
receipt with all four items answered, bound to the bundled model identity, and assistant recovery. Incomplete
receipts remain saved diagnostic evidence and fail the acceptance gate. Synthetic
integration tests separately verify scoped tool and reservation behavior. The
smoke does not attest which weights Ollama loaded at inference time. A Toronado
exam still requires a reviewed exclusive slot, verified model/config snapshot,
calibrated forms for ability claims, and independent transcript auditing.

The native-chat CI workflow also exercises the real service with the same
verified bundled model, before requiring an ISO rebuild. It uses disposable
storage discovery and the real gateway, exam, model-generated answers and
signer. It requires four recorded answers and signed completion, preserving the
receipt, transcript and public verification key. It is a public-pilot regression
test; it does not establish image acceptance or general ability.
