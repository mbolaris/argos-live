# Evaluation job lifecycle: host primitive, not yet exposed to agent tools

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

## Integration gates before exposing start/wait tools

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

The existing bridge teardown terminates pending children. It must instead retain
host ownership across an aborted agent turn and settle each child independently.
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
