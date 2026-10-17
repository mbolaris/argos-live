PRAGMA user_version = 1;
CREATE TABLE host_settings (
    name TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
) STRICT;
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY NOT NULL,
    caller_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    token_nonce TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('READY', 'ACTIVE', 'BREAK', 'COMPLETED', 'ABANDONED', 'TIMED_OUT', 'INVALIDATED')),
    reason TEXT,
    cartridge_digest TEXT NOT NULL,
    form_id TEXT NOT NULL,
    tier TEXT NOT NULL CHECK(tier IN ('practice', 'assessment', 'held_out')),
    subject_json TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    lineage_id TEXT NOT NULL,
    memory_id TEXT,
    prior_lineage INTEGER NOT NULL CHECK(prior_lineage >= 0),
    prior_memory INTEGER NOT NULL CHECK(prior_memory >= 0),
    created_ns INTEGER NOT NULL,
    start_deadline_ns INTEGER NOT NULL,
    active_module TEXT
) STRICT;
CREATE TABLE session_modules (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    module_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('PENDING', 'ACTIVE', 'BREAK', 'SUBMITTED', 'EXPIRED', 'INVALIDATED')),
    break_deadline_ns INTEGER,
    started_ns INTEGER,
    deadline_ns INTEGER,
    locked_ns INTEGER,
    PRIMARY KEY(session_id, module_id)
) STRICT;
CREATE TABLE answers (
    session_id TEXT NOT NULL,
    module_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    answer TEXT NOT NULL,
    accepted_ns INTEGER NOT NULL,
    PRIMARY KEY(session_id, item_id),
    FOREIGN KEY(session_id, module_id) REFERENCES session_modules(session_id, module_id)
) STRICT;
CREATE TABLE attempts (
    attempt_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    module_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    requested_revision INTEGER NOT NULL,
    answer TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('ACCEPTED', 'MODULE_NOT_ACTIVE', 'INVALID_ANSWER_FORMAT', 'STALE_REVISION')),
    at_ns INTEGER NOT NULL,
    FOREIGN KEY(session_id, module_id) REFERENCES session_modules(session_id, module_id)
) STRICT;
CREATE TABLE operations (
    caller_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    operation TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state = 'COMPLETED'),
    status INTEGER,
    response_json TEXT,
    PRIMARY KEY(caller_id, scope, operation, operation_key)
) STRICT;
CREATE TABLE aids (
    aid_id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    module_id TEXT NOT NULL,
    caller_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('RUNNING', 'COMPLETED', 'UNCERTAIN', 'DISCARDED')),
    output_json TEXT,
    started_ns INTEGER NOT NULL,
    completed_ns INTEGER,
    FOREIGN KEY(session_id, module_id) REFERENCES session_modules(session_id, module_id)
) STRICT;
CREATE TABLE exposures (
    session_id TEXT PRIMARY KEY NOT NULL REFERENCES sessions(session_id),
    cartridge_id TEXT NOT NULL,
    form_id TEXT NOT NULL,
    lineage_id TEXT NOT NULL,
    memory_id TEXT,
    questions_released INTEGER NOT NULL DEFAULT 0 CHECK(questions_released IN (0,1)),
    feedback_released INTEGER NOT NULL DEFAULT 0 CHECK(feedback_released IN (0,1))
) STRICT;
CREATE INDEX exposure_lineage ON exposures(cartridge_id, form_id, lineage_id);
CREATE INDEX exposure_memory ON exposures(cartridge_id, form_id, memory_id);
CREATE TABLE transcript_payloads (
    session_id TEXT PRIMARY KEY NOT NULL REFERENCES sessions(session_id),
    payload_json TEXT NOT NULL
) STRICT;
CREATE TABLE transcripts (
    session_id TEXT PRIMARY KEY NOT NULL REFERENCES transcript_payloads(session_id),
    envelope_json TEXT NOT NULL
) STRICT;
CREATE TRIGGER attempts_no_update BEFORE UPDATE ON attempts BEGIN SELECT RAISE(ABORT, 'append-only evidence'); END;
CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT, 'append-only evidence'); END;
CREATE TRIGGER exposure_no_delete BEFORE DELETE ON exposures BEGIN SELECT RAISE(ABORT, 'persistent exposure'); END;
CREATE TRIGGER exposure_monotonic BEFORE UPDATE ON exposures
WHEN NEW.session_id IS NOT OLD.session_id OR NEW.cartridge_id IS NOT OLD.cartridge_id
 OR NEW.form_id IS NOT OLD.form_id OR NEW.lineage_id IS NOT OLD.lineage_id OR NEW.memory_id IS NOT OLD.memory_id
 OR NEW.questions_released < OLD.questions_released OR NEW.feedback_released < OLD.feedback_released
BEGIN SELECT RAISE(ABORT, 'immutable identity and monotonic exposure'); END;
CREATE TRIGGER payload_no_update BEFORE UPDATE ON transcript_payloads BEGIN SELECT RAISE(ABORT, 'immutable transcript'); END;
CREATE TRIGGER payload_no_delete BEFORE DELETE ON transcript_payloads BEGIN SELECT RAISE(ABORT, 'immutable transcript'); END;
CREATE TRIGGER transcript_no_update BEFORE UPDATE ON transcripts BEGIN SELECT RAISE(ABORT, 'immutable transcript'); END;
CREATE TRIGGER transcript_no_delete BEFORE DELETE ON transcripts BEGIN SELECT RAISE(ABORT, 'immutable transcript'); END;
