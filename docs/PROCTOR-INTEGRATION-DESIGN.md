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
exited, with its final result saved or an interrupted record created. Fence all
writes to service-owned run state by generation. Fencing tokens cannot stop an
uncontrolled old Ollama request; quarantine until that request has exited or been
confirmed canceled. Restore heartbeat from its saved prior value only after the
reservation is drained, without overwriting newer unrelated configuration.

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

Source inspected: hooks-CM9Qxrxp.mjs, hook-runner-global-BfCvU9TT.mjs,
before-agent-run-Dal6QhAA.mjs, settled-turn-finalization-result-G1tP4IWJ.mjs,
builtin-openclaw-qVsnLx0N.mjs and context-engine-lifecycle-BwtFrh_C.mjs from
the exact package integrity pinned in the checked-in runtime lock.

The next-image branch now contains initial cooperative admission for the assistant
benchmark CLI/API and argos_log. It does not implement the complete service above.
The controller/heartbeat, desktop trials, model operations and direct backend
access still need mediation, and no isolated service identity is deployed.
Acceptance remains governed by UNATTENDED-ACCEPTANCE.md.
