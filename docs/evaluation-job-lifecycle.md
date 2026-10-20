# Evaluation job lifecycle and long-tool recovery

The immediate blocker is reliable measurement, before changing the question bank.
An agent-turn timeout must not destroy the only saved evidence of a long test.

`argoslive.evaluation_jobs.Jobs` implements the host-side lifetime primitive:

- One host thread holds both job exclusion and workload admission until saved
  publication and reservation settlement. An abandoned job never expires.
- `start()` admits one fixed quick/standard evaluation and returns a job ID.
- `wait()` lasts at most eight minutes. Aborting the wait does not cancel work.
- A different host reader can inspect the saved run without the original waiter.
- `cancel_owner()` is a separate host-owner control. Cancellation after inference
  dispatch preserves the saved partial run and quarantines admission unless an
  independent owner can prove backend drainage. Cancellation before any dispatch
  can safely release admission, without claiming the cancelled test passed.
- Status/progress metadata is synchronized across readers and writers, including
  Windows atomic replacement. Terminal status is returned only after admission's
  release/quarantine record has been published.

This is **not** a detached process service, automatic quarantine recovery, or an
enabled agent-facing protocol. A killed host process does not survive merely
because its Python evaluation thread was non-daemon. The actual application host
must outlive agent turns, preserve the job, and own shutdown/cancellation. Saved
metadata alone never proves that a former process/backend has stopped.

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
watchdog path without exposing an asynchronous poll protocol. The asynchronous
`Jobs` primitive above remains unexposed because returning `running` would let
OpenClaw resume model generation while evaluation owns the same inference
resources. Process-wide host survival and explicit cancellation still require a
separately supervised host service before claiming that an aborted SDK turn can
always be recovered.

## Integration gates before exposing start/wait tools

The direct plugin rejects an already-aborted request before spawning any command.
Its progress parser bounds unterminated stderr lines and discards oversized or
malformed progress without cancelling evaluation work. Only asking/scored events
with integer counts within the fixed 20/70 task bounds reach diagnostic liveness.
Subprocess tests cover no launch before dispatch, oversized-line resynchronizing,
and invalid progress followed by a valid saved-result response. Active cancellation
still signals the direct child; this is not direct-path aborted-turn survival.

Both hostAdmission and direct runArgos adapters must use the same host service,
not an agent-owned child. Tool abort cancels only the bounded wait. Owner cancel
requests actual job cancellation. The host must save a run without polling and
retain a failed/interrupted result ID for inspection.

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

Tests must cover the real SDK/transport cancellation path, both adapters, bounded
polling, persisted completion without polling, rejection of a second evaluation,
and controller/resource exclusion. The CPU primitive tests do not substitute for
those integration tests. Release still requires CI, a checksum-pinned ISO, strict
VM acceptance, and owner coordination before changing the production card.

## Evidence policy

A terminal job is not necessarily a completed ability test. Use the saved run's
state and complete coverage for ability claims. Partial 67/70 correctness cannot
establish a 70-item result. Keep practice feedback separate from private held-out
verification; an agent's chosen change needs matched baseline/candidate evidence
before an unseen form can establish transfer. Quick 20/20 is a smoke check, not
evidence of further gain from a saturated test.
