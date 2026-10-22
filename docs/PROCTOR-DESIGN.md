# Proctor core and scoped examinee adapter (P1)

Argos Proctor administers versioned assessments under recorded conditions and
preserves evidence about the tested configuration. P1 implements the local core
and a narrow managed-agent adapter. It is not yet a protected agent-facing daemon.

## Scope and trust

The host administrator, examiner, signing keys, caller registry and supervisor
are trusted. Examinees must eventually run in a separate process with no access
to cartridges, state, host launch credentials or private keys. Filesystem modes
do not protect these secrets from root. The signature establishes that the holder
of a particular installation key issued the record; it does not attest hardware
or defend against the machine owner.

P1 supports `mcq_single` and `numeric_grid` with deterministic grading. Cartridges
are uncalibrated: scaled scores and scoring bases are null. Coding, arbitrary
JSON schemas, in-process tests and imported executable graders are rejected.
There is no SAT/MCAT/IQ equivalence or claimed general intelligence measurement.
Grader `choice-numeric/2` accepts exact decimal values and simple exact fractions
for numeric-grid responses; it does not evaluate arithmetic expressions or round.

The engine accepts only `declared` enforcement and closed-book/reference-aided
policies. A subject can describe a model driver, booth agent or deployed profile;
that description does not establish that a booth exists or its isolation works.
The host launch adapter must independently establish model/configuration identity,
memory lineage and permissions before it can claim stronger enforcement.

The optional OpenClaw bridge now exposes `argos_proctor_*` operations only inside
a dedicated host-started Proctor workload. The host preselects the cartridge,
form, exposure tier, subject/configuration snapshot and closed-book policy. The
agent can start, inspect status, read active-module items, submit answers, advance
server-selected modules and submit a module. Tool outputs exclude the examinee
capability, keys, scores and signed transcript. A host-side terminal transcript
must be issued before the workload releases. The adapter refuses reference-aided
sessions until bounded aid workers are implemented.

For host-selected practice sessions only, `argos_proctor_feedback` returns
aggregate score and domain counts after terminal signing, giving the agent a
learning signal without revealing answer keys. Assessment and held-out feedback
remains host-only.

This is still a cooperative same-UID bridge. There is no installed service
identity or OS-enforced backend exclusion, the model identity is host-declared
rather than attested, and a managed context is not wired into the production
gateway/heartbeat dispatcher. Do not call this tamper-resistant or use the
four-item regression fixture as a meaningful ability exam. Existing benchmark
commands/results are unchanged; protected service deployment and real model
acceptance remain separate milestones.

## Content and storage

`cartridge.sql` defines content; `state.sql` defines private mutable state.
Both use schema version 1 and SQLite STRICT tables (SQLite 3.37+). Runtime Python
is stdlib-only, Python 3.11+, including SQLite serialize/deserialize support.

Compile trusted JSON using the public four-item regression fixture as an example:

```sh
python3 scripts/compile-proctor-cartridge.py \
  tests/fixtures/proctor/fixed.json /private/path/example.exam.db
```

The fixture is test data, not an assessment of meaningful model ability. A
20-item original assessment is follow-up work. Definitions declare a manifest,
forms, modules, response choices/keys and routing intervals. The compiler checks
foreign keys, score coverage, forward routing, reachability, contiguous item
positions, aids and answer contracts. Publication is atomic without overwrite
on filesystems supporting hard links. Invalid content is rejected before output
publication. Definitions/databases are bounded to 4 MiB and 1,024 items total.

The engine reads a cartridge into a validated byte snapshot and hashes those exact
bytes. Replacing its path cannot change an active engine's questions. Examinee
item responses explicitly project public fields and never return answer keys or
routing rules. No item explanations or solutions are released in P1, including
practice sessions. Feedback exposure is reserved for a later explicit API.

`open_state` enables foreign keys, WAL, FULL synchronization and a bounded busy
timeout on each connection. On POSIX it requires a private directory and private
database; the directory protects WAL/SHM sidecars. Windows privacy relies on
host ACLs. Use encrypted persistence for sensitive state and signing keys.
The core does not mount storage or establish encryption. A worker owns its own
SQLite connection; it must not share that connection concurrently.

## Host and examinee contracts

`Proctor` receives a pinned `Cartridge`, state connection, caller registry, a
random persistent token secret of at least 32 bytes, boot identity, signer and
optional test clock. It never accepts a timestamp as an examinee method argument.
Linux uses `CLOCK_BOOTTIME` so suspend consumes exam time; the fallback is a
monotonic clock. Clock values are meaningful only within their recorded boot.

The host-facing methods are:

- `enroll`: authenticated host selects subject/configuration snapshot, policy,
  form and practice/assessment/held-out tier. Never expose those selections as
  unrestricted examinee privileges.
- `complete_aid`: authenticated owning host worker supplies a bounded aid result.
- `tick`: supervisor periodically advances deadlines and issues pending transcripts.
- `recover`: once at exclusive daemon startup, invalidates unfinished sessions
  and marks running aids uncertain. Constructing another worker does not recover
  global state. The supervisor must terminate orphan workers and prevent multiple
  daemon owners; those process controls are not implemented by this library.
- `issue_transcripts`: signs already-frozen payloads outside SQLite transactions.

The examinee-facing methods require a separate session capability:

- `begin_module(session_id, token, module_id, key)`
- `record_answer(session_id, token, module_id, item_id, answer, revision, key)`
- `submit_module(session_id, token, module_id, key)`
- `reserve_aid(session_id, token, module_id, name, input, key)`
- `get_item`, `status`, `aid_status`, `get_transcript`

These are Python boundaries for future authenticated adapters, not MCP tools
registered in OpenClaw. Tokens are never written to response logs. Enrollment
replays derive the same session token from the host token secret and stored
nonce; the database stores only its hash. Persist that secret privately across
restarts. A changed secret fails explicitly rather than replaying unusable tokens.
Signing and session token keys are separate.

Each mutating call authenticates before replay lookup. Request hashes use
structured JSON, not delimiter concatenation. Identical retries replay the original
result; changed payloads conflict. Module IDs are explicit, so a stale begin or
submit cannot apply to a subsequent module. Expected rejections commit their
evidence and replay result before an exception is returned. Unexpected failures
roll back the entire write transaction. Oversized or incorrectly typed method
arguments fail before submission logging; future adapters must report their own
transport failures separately. Missing client telemetry remains null.

## Timing and grading

The session states are READY, ACTIVE, BREAK, COMPLETED, ABANDONED, TIMED_OUT and
INVALIDATED. The initial start window is bounded. Modules can be submitted early;
next-module breaks can end early when explicitly begun. At a break's expiration,
the next module automatically starts at the scheduled break deadline.

Answer acceptance samples the host clock after acquiring `BEGIN IMMEDIATE` and
requires acceptance strictly before the module deadline. State, deadline,
revision, validation, answer mutation, audit and replay result share one transaction.
Rejected answers preserve earlier accepted revisions. Reads do not move a cursor
or grade anything, and item/aid reads refuse expired modules even before a tick.

The scheduler catches up through every overdue transition, with module starts
anchored to scheduled break deadlines and breaks anchored to module closure.
Silence, a delayed worker or a late begin never grants a fresh duration. Timeout
normally advances to the next module; `abort_on_timeout` ends the assessment.
Only bounded deterministic grading runs inside the write transaction. External
grading is not supported and must not be added inside that lock.

Aids are durable asynchronous jobs. Reservation authenticates and checks active
module, deadline, assistance policy and cartridge allowlist in a short transaction.
The host does actual work outside SQLite, then completes that job. Repeating a
reservation returns its original job identity; `aid_status` reports current state.
Identical completion is idempotent and a changed completion conflicts. Closure
discards running jobs; restart marks them uncertain. Late results are not exposed.
Concrete calculator/reference workers are still to be implemented; arbitrary
shell/Python execution is never an aid in this slice.

## Exposure and transcripts

Held-out eligibility checks both stable lineage and known memory-store identity.
`memory_id: null` means no known persistent store, not a shared dummy memory.
Exposure keys use stable cartridge/form IDs across content rebuilds; each session
also pins its exact cartridge digest for reproducibility. Renaming content or
unknown shared/training-data exposure cannot be detected by this ledger.

Enrollment serializes reservations across independent connections. A held-out
reservation blocks overlapping launches, including a concurrent practice launch.
A new held-out launch also refuses any existing overlapping live reservation.
Reservations are distinct from exposure: questions are conservatively marked
released on module activation. An expired unstarted reservation does not consume
a form. Seeing any module prevents a later clean held-out attempt for that
lineage or memory, even after abort, prompt edits or a known memory reset.

Terminal transitions freeze transcript payloads in the same transaction as final
state. Transcripts include actual configuration/policy snapshots, content digest,
route/module timing, boot identities, accepted answer revisions, domain counts, unanswered items and a
server-observed discipline ledger. First-attempt acceptance counts the earliest
logged submission per item; identical retries add no attempts. Late attempts
after terminal closure do not rewrite the issued results. Transcript payload and
audit triggers reject updates/deletes. Root remains trusted and can alter the DB.

`Ed25519Signer` uses system OpenSSL, explicitly included in the image package list.
`generate_key` provisions a private installation key without overwrite. Export
`signer.public_key_der` through a trusted channel and retain it independently.
The envelope contains `payload_json`, the exact UTF-8 string that was signed,
plus algorithm, public-key digest and base64 signature. This avoids pretending
Python JSON serialization implements RFC 8785. Verify the original bytes with
`verify_envelope(envelope, trusted_public_key_der)` before decoding the payload.

Signing runs outside write locks. A signing failure leaves the frozen payload
available for retry without regrading. Stored issued envelopes are immutable;
retrieval never recomputes results. Private key access or missing OpenSSL is a
host provisioning failure, never a reason to fall back to an unsigned transcript.

## Verification and follow-up

```sh
python3 -m unittest discover -s tests -p 'test_proctor*.py' -v
bash scripts/check.sh
```

Focused tests cover malformed/stale retries and rollback, authentication before
replay, exact deadlines, zero/expired breaks, complete silent catch-up, branching,
timeout policy, aid denial/completion/restart, exposure and reservation races,
real independent-connection writer contention, invalid cartridges, compiler
publication, immutable evidence, signing retry and real OpenSSL verification with
tampering/wrong-key rejection. The actual signature round trip is not mocked.
OpenSSL tests skip explicitly if unavailable; CI's Linux system provides it.

October 17, 2026 validation: 32 focused Windows tests pass with actual OpenSSL.
Linux CI passes 699 Python tests (four skips), 25 Node tests and shell checks,
including the real signature round trip and packaged SQL-resource check. Full
Windows discovery ran 714 tests with 38 skips and three journey/reboot failures;
all three reproduce on unchanged main (path separators and POSIX permissions).

Remaining: protected daemon ownership and scheduler, production gateway/heartbeat
dispatch, model loading/GPU leases, real model runner, concrete aid workers,
held-out bank governance, calibrated scoring, coding sandbox grader, dashboard
integration, image build and physical Toronado acceptance. P1 unit and signature
evidence does not establish any of those deployment properties.
