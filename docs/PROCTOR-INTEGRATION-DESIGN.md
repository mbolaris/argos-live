# Proctor integration and exclusive Toronado slots

Draft design, October 17, 2026. Codex owns coordination after the Claude handoff.
This is a proposal; the merged proctor core does not implement this host lease.

## Immediate operating agreement

Toronado is reserved for the owner-authorized 27B controller transition and
campaign. No proctor inference is authorized in that reservation. The isolated
heartbeat is temporarily set to 0m during the active takeover controller session,
so it cannot launch a second evaluation. Restore its original 3m interval only
after the active session and any benchmark have finished; snapshot before that
config change. A future proctor window needs an explicit recorded slot agreement,
heartbeat gating, checks for active gateway runs as well as OS processes, and a
worker-exit check before release. GPU idleness alone does not establish a slot.

## One admission authority

Introduce a host service that owns admission for campaign controller turns,
campaign evaluations, proctor exams, model operations and instruction maintenance.
All entry points must participate: dashboard, CLI, plugin evaluation tool,
heartbeat dispatch and proctor adapter. A check inside the proctor alone cannot
prevent the campaign from starting during an exam. Native direct Ollama access or
arbitrary shell access remains a bypass unless OS access is separately enforced.
Initial integration must report that limitation and retain declared enforcement.

Use a single durable SQLite admission transaction for the host. Each reservation
has an unguessable id, monotonically increasing generation/fencing token, workload
kind, controller UTC observation time, local monotonic lifetime, boot id, process
identity including start time, worker/cgroup identity, snapshot hash, and eventual
saved result/transcript id. Separate reservation admission from execution: a
reserved but unstarted worker can be canceled without representing a test run.
The already merged answer-transaction/idempotency machinery remains authoritative
for exam answers; do not couple long-running inference to an open SQLite write
transaction.

A campaign controller owns a parent reservation while using tools. It may hand
exclusive inference to exactly one child evaluation, await its saved result and
then resume. The evaluator must not deadlock by independently acquiring its
parent's reservation. Child authorization is minted by the service, not supplied
as an arbitrary agent-chosen identifier. No controller inference or workspace
mutation is allowed while that child is running. Concurrent evaluation calls get
a structured busy response before creating a run or changing workspace state.

Proctor admission requires no campaign parent reservation and no outstanding
child. Maintenance likewise requires quiescence. Model changes/downloads that
could affect measurement are exclusive. Keep campaign and proctor result stores
and attribution separate; include the reservation and generation in both kinds
of evidence.

## Recovery must fail closed

States: reserved, starting, running, draining, completed/failed, released; mark
uncertain ownership quarantined. Persist worker identity before it may execute.
A lease timeout means investigate, not permission to start competing work. After
service or worker failure, reconcile process start identity, boot id, cgroup and
saved artifacts. Reclaim only after the old worker and descendants are confirmed
exited, with its final result saved or an interrupted record created. On Linux,
a different validated kernel boot ID is a sufficient boundary for old local
processes and inference requests; write a per-generation recovery receipt before
releasing admission. Same-boot PID absence, timeout, or wall-clock age is not
enough. Fence all writes to service-owned run state by generation. Fencing tokens
cannot stop an uncontrolled old Ollama request; quarantine until that request
has exited, been independently confirmed canceled, or the kernel has rebooted.
Restore heartbeat from its saved prior value only after the reservation is
drained, without overwriting newer unrelated configuration.

Toronado's wall clock currently labels Pacific time UTC. Use monotonic time for
live timeouts and retain both host times and controller UTC evidence; never infer
expiry across a reboot from the bad wall clock.

The takeover demonstrated a separate failure boundary: the coordinating CLI
expired its waiting deadline after the gateway accepted a turn. Its error warned
that execution could continue. Later read-only inspection found the exact session
marked timeout and no benchmark child, while the liveboard still reported running
with partial coverage and no saved result. Client timeout, gateway turn timeout,
worker exit, and saved result finalization must be separate recorded events.
Neither a CLI failure nor stale progress grants admission to replacement work.
Require a service-owned interrupted record when a drained child has no final
artifact; retain its partial evidence without ranking it. The parent must be able
to observe a durable child outcome after reconnecting, without repeating the
experiment or relying on a continuously open CLI connection.

## Proctor boundary

The service owns cartridges, answer keys, exposure history, signing keys and
immutable transcript finalization. The agent gets only scoped operations for its
own exam: start/status, allowed question navigation, submit with idempotency key,
request permitted aid, and finish. It cannot select hidden items, read keys,
rewrite history or sign its own outcome. Aid inference holds the same exam
reservation and follows the cartridge's recorded aid policy. Keep the existing
isolated evaluation context for answer-only model tests; do not substitute it for
an interactive tool-enabled agent exam without labeling the different scope.

Same-UID files are not an independent security boundary against an agent with
shell access. A protected service identity and transport authorization require a
reviewed deployment plan and owner approval before any root-level installation.
Until then, label the integration declared and do not claim tamper resistance.

### Scoped agent adapter implementation

`runtime/argoslive/proctor/agent_session.py` wraps the core with one immutable
host-selected profile. Its public methods do not accept form, tier, subject,
policy, answer revision, session capability or transcript choices. The plugin
registers optional `argos_proctor_*` tools; its managed bridge routes them only
when `owned(..., exam_session=...)` holds a `proctor` workload reservation.
Campaign, compare, log, and instruction tools are rejected in that mode. The
host bridge writes the signed terminal transcript before releasing admission;
incomplete or uncertain sessions remain quarantined. The Proctor session ID is
bound as the workload result ID, and its signed payload hash is journaled before
release. The agent tools return questions and state but no score, answer key or
transcript.

`argos_proctor_feedback` returns aggregate score and domain counts only when the
host preselected the practice tier and the session is terminal. This lets the
agent choose a follow-up practice experiment. In the bundled practice form only,
the profile also exposes `argos_evaluate_wait`; the bridge intercepts it during
the designated item, records its actual function name and arguments as the
host-scored response, and returns a synthetic no-op. It cannot start or resume
a real evaluation. Assessment and held-out sessions refuse feedback and preserve
scores for the trusted host.

This adapter is declared enforcement only and is not active in the default
profile or production gateway. The host must build the exam profile from a
verified model/configuration snapshot and the protected service must own the
cartridge, token secret, signing key and workload store before held-out use.
Reference-aided exams are refused until their bounded aid workers exist. The
fixture tests verify tool scoping and transcript privacy but do not establish
same-UID isolation, backend drainage, model identity attestation, a calibrated
question bank or real-model ability.

## Acceptance evidence before a live proctor slot

1. Simultaneous campaign/proctor admissions yield exactly one winner. A rejected
   request starts no inference and changes no workspace or result record.
2. Nested campaign evaluation cannot deadlock, overlap another child, or allow a
   parent instruction edit until the saved child result exists.
3. Heartbeat ticks and all normal CLI/dashboard/plugin routes respect admission;
   legacy direct inference bypasses are explicitly accounted for.
4. Kill the service and workers at each start/finalization boundary. No stale
   timeout admits a second worker; restart either recovers the saved outcome or
   quarantines safely. Test late callbacks and stale generation writes.
5. Verify snapshot hashes, selected and actual model, original heartbeat recovery,
   failed/void result handling, transcript signature and private-key isolation.
6. After those offline/disposable-host tests pass, agree a Toronado slot. Back up
   records, gate heartbeat, run one explicitly scoped exam, save its run/transcript
   id, drain and verify the worker, then restore campaign availability. Report
   any contention as a measurement limitation; never attribute this exam to an
   instruction change without matched evidence.

## Implementation checkpoint

### Pinned SDK admission boundary inspected

The integrity-checked OpenClaw2026.10.4 package has a before_agent_run gate.
Its global hook runner marks this hook fail-closed; its harness wrapper converts
handler errors into a block before inference. Context contains framework runId,
sessionId/sessionKey and trigger, while the event includes senderIsOwner. These
are candidate host inputs, not model-authored authorization text. The exact
desktop/heartbeat values must still be verified by a native protocol fixture.
Do not derive owner authority from words in the prompt or from an agent-supplied
reservation ID. Admit a parent once by framework run identity, and authorize its
evaluation child through a host-minted capability unavailable as a tool argument.

The embedded agent-end call uses runAgentEndSideEffects, which does not await
plugin completion. Therefore agent_end alone cannot be the authoritative release
boundary. The host must confirm worker/child drainage and saved outcomes before
release; a late callback must match its reservation generation. SDK fail-closed
entry hooks do not themselves implement this durable lifecycle or protect direct
backend/model-operation paths. Removing broad filesystem/runtime tools also
requires bounded host tools for the agent's own model and instruction decisions;
it must not introduce an operator planner in place of those decisions.

Registration itself needs verification: the pinned registry ignores
before_agent_run and agent_end for non-bundled plugins unless their owner
configuration explicitly grants hooks.allowConversationAccess=true. Merely
loading the plugin or listing its tools does not prove an admission gate is
active. The typed decision contract uses exactly {outcome:"pass"} to admit;
{outcome:"block",reason:"..."} denies. An "allow" outcome is invalid.
scripts/smoke-admission-hook.py now exercises the real CLI against a synthetic
local model endpoint: an ungranted negative control, explicit denial, a thrown
handler, a malformed decision, and a valid pass. It records only safe framework
identity fields and request counts. Run39090547783 at source8310dad passed all
five cases and the broader pinned compatibility job. Its saved report is
evidence/admission-hook-8310dad.json. The ungranted control made one request and
emitted no hook event; each granted refusal/error/invalid decision exited1 with
zero model requests; a valid pass exited0 with one request.

All granted local CLI cases reported trigger=user and senderIsOwner=true,
including the refused runs. A generic local CLI invocation can therefore carry
those values: they do not prove a fresh human owner instruction or authorize a
heartbeat/campaign on their own. The host still needs its own owner-started
campaign record and private dispatch capability. agent_end also fired for each
blocked attempt, so an end event is not evidence that a reservation was admitted
or inference drained. Match host-owned identity and generation, then confirm
worker lifecycle. No production controller protection has been deployed by this
fixture. Desktop and heartbeat ingress still require native evidence.

Source inspected: hooks-CM9Qxrxp.mjs, hook-runner-global-BfCvU9TT.mjs,
before-agent-run-Dal6QhAA.mjs, settled-turn-finalization-result-G1tP4IWJ.mjs,
builtin-openclaw-qVsnLx0N.mjs and context-engine-lifecycle-BwtFrh_C.mjs from
the exact package integrity pinned in the checked-in runtime lock.

### Cooperative parent/child lifecycle

The next-image branch contains cooperative reservations for the assistant
benchmark CLI/API, argos_log and a host controller scope. The controller holds
the root OS lock for its entire lifetime. delegate() durably marks it delegated
before returning one operation-specific, one-use child capability. Only its hash is saved.
The child acquires a separate nonblocking lock, verifies parent id/generation,
the live parent lock and Linux boot/process birth, then publishes its identity
before it executes. A second child, mismatched operation, old generation or
replayed capability cannot enter inference. An unused grant can be revoked
under that same child lock; active or uncertain workers cannot be revoked.

The delegated evaluation API and fixed subprocess worker publish the complete or
failed/cancelled saved result before recording their terminal lifecycle. The
ordinary Python evaluation API now also saves before release; previously it
returned an unsaved result after releasing admission. Log workers keep the parent
reservation and reuse the append-only interface. workload_worker accepts only
fixed evaluation/log/maintenance operations, an explicit host home, and a bounded private stdin
request. Capability secrets are excluded from argv, persistent metadata, normal
output and request-error messages. This is an internal host protocol, not a new
model tool argument or permission to invoke arbitrary commands.

resume() requires both a released child and an explicit trusted-host drainage
assertion. That assertion is deliberately not derived from SDK end events or
timeouts. It is not implemented backend/process inspection: the supervising
adapter must establish it before calling resume. A failed/cancelled child,
publication error, killed worker, abandoned controller, or missing live parent
lock leaves admission closed. Root and child finalization are fenced by the
parent identity/generation; neither lease expiry nor a stale active marker
automatically reclaims work. These are short file/OS-lock lifecycle operations,
not the proposed deployed SQLite service or an OS security boundary.

The fixed-worker integration test runs separate evaluation/log processes with
synthetic CLI replies, checks saved result receipts and secret-free output,
confirms worker exit before parent resume, then admits a proctor only after the
parent releases. Other tests cover contention before inference, killed parents
and children, stale callbacks, invalid/replayed capabilities, failed publication
and final-marker failure while the owner's PID remains alive. These tests do not
exercise an actual model or establish backend drainage.

Source697908a passed all14 cases in the guarded Linux gate and the complete
Tests run39092122371:762 Python tests (4skips),28 Node tests and shell syntax.
The machine-checked receipt and focused log are saved under
evidence/workload-delegation-697908a.{json,log}; the receipt binds the source,
hosted run and private full-log hash. Native SDK compatibility is a separate
gate; lifecycle fixtures alone do not prove controller ingress is mediated.
Pinned compatibility run39092126565 also passed at that exact source: browser,
schema/recovery, native gateway cleanup, generation requests and admission entry
hooks. The receipt includes hashes of its locally preserved JSON artifacts.

The native controller/heartbeat dispatch is not yet connected to this lifecycle.
Desktop trials, model operations and direct backend access also need mediation,
and no isolated service identity is deployed. The host must stop the controller's
inference and instruction writes while a child owns the delegated slot; the
cooperative API cannot force a generic SDK or shell client to honor that rule.
Acceptance remains governed by UNATTENDED-ACCEPTANCE.md.

### Managed SDK bridge (opt-in; production routing remains open)

controller_bridge.owned holds the root controller reservation and a private
AF_UNIX endpoint. The host chooses the allowed session key and trigger before
launch. The plugin's hostAdmission mode binds before_agent_run framework identity
to a private turn token. before_tool_call binds the framework run/tool-call IDs
to execution; neither identity nor the capability is a model tool argument.
The SDK tool factory itself has no runId in this pin, so a factory/global-current
run guess is not used. End hooks record metadata and cannot release admission.

In this managed scope, the tool hook admits only Argos host operations. The
original tools are argos_evaluate, argos_compare and argos_log; optional bounded
instruction tools are described below. Evaluations/logs use the fixed delegated workers;
comparisons load checked saved results. Failed/cancelled saved evaluations remain
visible with their full IDs while the host stays quarantined. Admission tokens
are absent from persistent metadata, child environments and tool output.

The host-only launch/finish interface owns an actual embedded SDK process in a
new session. It preflights explicit plugin enablement/allowlisting, conversation
hook access and skills.workshop.autonomous.mode=off. The exact pinned source
otherwise defaults autonomous skill review to auto, allowing post-turn review
inference. finish verifies successful CLI output/session identity and absence of
live process-group members, then saves a host worker receipt before marking the
parent drained. A client-provided worker_exited claim or agent_end callback is
not a completion path. A missing end callback/ack alone cannot negate confirmed
worker completion. Unexpected transport/workers/results remain quarantined.

Sourcea1d2247 passed native compatibility run39093712268, including this opt-in
interface against the real pinned SDK with synthetic responses. Four controller
requests and20 isolated evaluation requests completed. A generic exec call was
denied by the hook without creating its marker; evaluation and log calls reached
the fixed host workers. Saved synthetic result258e61073d48642bbf38a3cdf3a50198
has20/20 coverage (not a model-quality claim). A proctor reservation was rejected
while the host context remained open, then admitted after the SDK process group
and host context exited. The report, saved result, worker receipt and checked
hash manifest are in evidence/controller-bridge-a1d2247/. Full Tests
run39093712269 passed768 Python tests (4skips),29 Node tests and shell syntax.

This is not installed or enabled in Toronado's running gateway. The
production UI/heartbeat dispatcher still needs its supervised adapter and durable
owner-started campaign authorization. The managed tool set also needs bounded
configuration changes and model operations before it can carry
the full self-improvement loop; enabling it as the default now would prevent the
agent from making its experiments. Proctor/evaluator service identity and actual
backend admission/drainage remain independent requirements.

Native fixture attempt6597e35/run39093471588 stopped before controller launch
with EADDRINUSE binding11434 immediately after another synthetic fixture.
The revised synthetic HTTP helper uses SO_REUSEADDR for stopped TCP TIME_WAIT
and explicitly disables SO_REUSEPORT. Linux kernel preflight tests require an
existing listener to reject a competitor and remain usable, while allowing a
stopped fixture's successor to bind. No process/listener is killed or adopted.
This addresses fixture socket lifecycle; it is not evidence of model exclusion
or proof of the historical kernel socket state on the discarded first runner.

### Bounded instruction experiments

The optional managed-only tools argos_inspect, argos_edit_instructions and
argos_resolve_instructions use fixed delegated maintenance workers. No tool
argument selects a path or command. Inspection returns canonical AGENTS.md,
its hash, a private-safe configuration receipt and the practice keep policy.
Edits require that hash, one unique literal replacement, a hypothesis and a
completed matching baseline admitted by this same host controller reservation.
Only the canonical .openclaw/workspace/AGENTS.md may change. Other workspaces,
ambiguous patches, stale hashes and borrowed result IDs are refused.

Before replacing bytes, the host saves private before/after/config snapshots,
the baseline and its admission record, and an immutable intent. It then records
the applied hash. Resolution either restores those exact bytes or validates a
keep. Every keep needs at least two baseline and two candidate runs with matching
configuration, model tag and hardware. The conservative practice policy requires
the worst candidate to beat the best baseline by two correct quick tasks or four
standard tasks without more format errors; alternatively, correct answers must
be maintained with strictly fewer format errors and median latency at most 1.5
times baseline. These are practice thresholds, not statistical significance or
independent generalization evidence. Installed weight identity remains unproven.
The current receipt also binds the copied personality/context inputs across
runs. `workspace_context_receipt` hashes missing-versus-present states and the
bytes of each non-AGENTS `WORKSPACE_FILES` input. Evaluation records that hash,
checks for context changes before turns and final publication, and refuses to
compare runs with different context hashes. Instruction-change admission and
audit require the recorded non-AGENTS context hash to match. Tests include a
newly created SOUL.md invalidating the run, not only changes to existing files.
This covers those fixed copied inputs; it does not establish protected service
ownership, backend-wide mediation, or a complete audit of free-form claims.

Restoration does not require a successful exam. An unmeasured restoration is
explicitly marked as such and does not count as a completed experiment. Unknown
write outcomes or failed journal publication stay quarantined. Expected hashes
preserve an observed owner edit; protected ownership is still required to exclude
arbitrary same-UID races or journal tampering.

instruction_changes.audit replays the patch, checks snapshot/config hashes,
event ordering, evidence and admission receipts, policy calculations, journal
continuity and the final live guide. Its report covers only this host instruction
journal. It explicitly does not certify free-form log claims or independent gain.
The optional tools are not enabled in the default conversation profile. No live
gateway or Toronado deployment is implied by adding them.

Source67fa777 passed native compatibility run39106875111 and Tests
run39106875110 (779 Python tests,4skips;29 Node tests;seven guarded groups and
shell syntax). The pinned SDK exercised inspect, evaluate, edit, restore and log;
the host audit confirmed exact restoration and proctor exclusion through context
release. Saved synthetic resulta69d6a762035ec1a2576c107625c394a covers20 tasks.
The native fixture restores without a candidate exam, explicitly counts zero
qualified experiments and claims no independent gain. Repeated measured keep/
restore is covered by unit tests. Evidence and verified artifact hashes are in
evidence/instruction-tools-67fa777/.
