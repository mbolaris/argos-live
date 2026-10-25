# Evaluation job lifecycle and long-tool recovery

The immediate blocker is reliable measurement, before changing the question bank.
An agent-turn timeout must not destroy the only saved evidence of a long test.

`argoslive.evaluation_jobs.Jobs` implements the host-side lifetime primitive:

- One host thread holds both job exclusion and workload admission until saved
  publication and reservation settlement. An abandoned job never expires.
- `start()` admits one fixed quick, standard, challenge, or tool-schema evaluation and returns a job ID.
- `wait()` lasts at most eight minutes. Aborting the wait does not cancel work.
- A different host reader can inspect the saved run without the original waiter.
- `cancel_owner()` is a separate host-owner control. Cancellation after inference
  dispatch preserves the saved partial run and quarantines admission unless an
  independent owner can prove backend drainage. Cancellation before any dispatch
  can safely release admission, without claiming the cancelled test passed.
- Status/progress metadata is synchronized across readers and writers, including
  Windows atomic replacement. Terminal status is returned only after admission's
  release/quarantine record has been published.

The current agent-tools PR exposes bounded start/wait/status operations in both
managed host admission and the direct plugin path. Each wait is capped at eight
minutes. The bridge keeps its delegated child and controller reservation while
the agent polls; the direct plugin leaves the benchmark process independent of
the tool's AbortSignal. A status operation recovers the job ID after a lost
reply. A second evaluation is refused until the first result is consumed. A
separate trusted-host cancellation method requests cancellation; no agent cancel
tool is registered.

This still is not a supervisor that survives a host/gateway process kill, and
the owner control remains cooperative within the Argos account.
Direct job IDs live in the plugin process; if that process dies, the benchmark
can still save its result, but polling by job ID is unavailable and the workload
reservation may require recovery. Saved metadata alone never proves that a
former process/backend has stopped.

## Pinned runtime liveness integration

The observed failure was an OpenClaw tool call with regular Argos progress,
while the host diagnostic owner continued to report only
`tool:argos_evaluate:started`. The pinned runtime patch in
`scripts/patch-openclaw-liveness.mjs` wires `argos_evaluate` updates to the
existing owner-fenced semantic progress event, at most once every 30 seconds.
It keeps the tool call pending until the saved result returns, so controller
inference stays suspended and the delegated workload exclusion remains active.
The plugin forwards the worker's bounded `asking` and `scored` events through
host admission as well as in direct mode. A disconnected progress client does
not cancel a delegated evaluation.

The patch runs only after npm verifies the upstream package against the checked
in `package-lock.json`; it records hashes of the two modified runtime files.
It refuses unrecognized source layouts. This addresses the observed no-progress
watchdog path in addition to the bounded start/wait protocol now exposed by both
adapters. Returning `running` does not release workload admission: the managed
bridge retains its delegated child and parent reservation, and the direct path
retains the evaluator's admission. Host-process survival is not established.
Explicit cancellation methods exist for trusted host callers. The owner CLI below
requests cancellation through the evaluator; a tool-wait abort is never owner cancellation.

The pinned compatibility gate now runs the patched 2026.10.4 activity tracker,
not only a mock: it lets the tracker age 16 minutes, emits an owner-fenced
`argos_evaluate` semantic progress event, drains the runtime's queued event, and
asserts `lastProgressAgeMs` returns to zero. A saved report records the old and
new ages. The same actual-runtime smoke also passes against OpenClaw 2026.10.5;
CI fetches that package only after checking both npm's integrity metadata and
the downloaded tarball against the checked-in SHA-512 pin. The image remains
pinned to 2026.10.4. This verifies the liveness behavior that the earlier
callback-only test could not establish.

## Integration gates before exposing start/wait tools

The direct plugin rejects an already-aborted request before spawning any command.
Its progress parser bounds unterminated stderr lines and discards oversized or
malformed progress without cancelling evaluation work. Only asking/scored events
with integer counts within the fixed 20/70 task bounds reach diagnostic liveness.
Subprocess tests cover no launch before dispatch, oversized-line resynchronizing,
and invalid progress followed by a valid saved-result response. Active cancellation
first sends SIGTERM to the dedicated process group, allowing the CLI's existing
handler to save a cancelled partial run. If the process group still holds pipes
after five seconds, SIGKILL drains it before the tool settles. A regression
fixture ignores SIGTERM in both parent and descendant and verifies group exit.
An unresponsive process may still fail to save a run; the plugin reports that as
an error rather than inventing a result ID.

Both hostAdmission and direct runArgos adapters now keep evaluation lifetime
outside the individual tool wait. Tool abort cancels only the bounded wait.
Owner cancellation is also available through the identity-fenced CLI below. The benchmark itself saves the run without polling.

Returning `running` must not resume controller inference while the delegated
evaluation still owns inference resources. Existing bridge delegation explicitly
requires child drainage before controller resume. Enforce suspension/resource
mediation at the host layer; prompt instructions or a hook that times out and
fails open are insufficient. Likewise, block instruction/configuration/log writes
throughout an active evaluation. Do not merely weaken parent.resume(), detach a
child, or release admission to let the controller ask for status.

The bridge's outer context now stops its controller worker first and retains the
parent reservation while waiting for an already admitted tool to finish saving.
A socket disconnect or exception leaving that context does not itself terminate
the evaluation. The existing worker deadline still bounds a stuck child; its
deadline plus pipe-drain allowance bounds teardown. The aborted controller remains
uncertain and quarantined even if its evaluation saves a completed result. This
preserves evidence while the Python host remains alive, not across a host kill.
The regression uses the real Unix socket and delegated evaluator subprocess with
a gated synthetic CLI, disconnects the client, aborts the outer context, verifies
exclusion during teardown and checks the saved result and retained quarantine.
It does not substitute for actual SDK abort/resource-mediation acceptance.
Unknown cancellation drainage remains quarantined, never reclaimed by age.
On Linux, a later workload may recover an orphan only when the persisted
reservation contains a valid boot ID different from the current kernel's boot
ID. That reboot boundary proves old processes and inference requests cannot
survive; recovery first writes a per-generation receipt retaining the prior
state and saved result ID. Missing, malformed or same-boot identities still
leave admission quarantined.

The latest native SDK gate exposed a cross-thread SQLite failure: Proctor state
was opened on setup but first accessed by the SDK socket-handler thread. The
engine now serializes its shared connection and permits that host thread handoff.
A regression covers the thread boundary; the revised SDK smoke and the full
Linux bridge/transport suite must pass before this is accepted. Release still
requires CI, a checksum-pinned ISO, strict VM acceptance, and owner coordination
before changing the production card.

## Evidence policy

A terminal job is not necessarily a completed ability test. Use the saved run's
state and complete coverage for ability claims. Partial 67/70 correctness cannot
establish a 70-item result. Keep practice feedback separate from private held-out
verification; an agent's chosen change needs matched baseline/candidate evidence
before an unseen form can establish transfer. Quick 20/20 is a smoke check, not
evidence of further gain from a saturated test.

## Owner cancellation command

Run `argos bench control status` to read the recorded evaluation target. The
receipt explicitly does not establish process liveness. To request Stop, copy
its exact `id`, `generation`, and (for a delegated evaluation) `child_id`:

```sh
argos bench control stop --id ID --generation GENERATION
argos bench control stop --id ID --generation GENERATION --child-id CHILD_ID
```

Stop writes a cancellation marker fenced to that reservation and child. The
shared evaluator polls it through its existing cancellation path, including
while waiting for a model turn. This covers direct CLI/plugin evaluations and
managed delegated evaluations. A stale target, non-evaluation workload, or
quarantine is refused. A request for an old child cannot stop its successor.
`cancel_requested` proves only publication of the request: inspect the saved
partial run and reservation afterward. This command never releases quarantine
or claims backend drainage. Like the rest of this cooperative service, it is
not protected against arbitrary same-UID filesystem access. Actual SDK and
exact-image acceptance of this command remain required.
