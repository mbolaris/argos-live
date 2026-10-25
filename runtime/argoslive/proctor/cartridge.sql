PRAGMA user_version = 2;
CREATE TABLE manifest (
    cartridge_id TEXT PRIMARY KEY NOT NULL,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    content_origin TEXT NOT NULL CHECK(content_origin IN ('argos_original', 'published_practice_form', 'imported_open_dataset')),
    calibration_status TEXT NOT NULL CHECK(calibration_status = 'uncalibrated'),
    start_window_ms INTEGER NOT NULL CHECK(start_window_ms BETWEEN 1 AND 3600000),
    abort_on_timeout INTEGER NOT NULL CHECK(abort_on_timeout IN (0, 1))
) STRICT;
CREATE TABLE forms (
    form_id TEXT PRIMARY KEY NOT NULL,
    entry_module_id TEXT NOT NULL,
    FOREIGN KEY(form_id, entry_module_id) REFERENCES modules(form_id, module_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE modules (
    module_id TEXT PRIMARY KEY NOT NULL,
    form_id TEXT NOT NULL REFERENCES forms(form_id),
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    duration_ms INTEGER NOT NULL CHECK(duration_ms BETWEEN 1 AND 3600000),
    break_ms INTEGER NOT NULL CHECK(break_ms BETWEEN 0 AND 3600000),
    aids_json TEXT NOT NULL,
    UNIQUE(form_id, module_id),
    UNIQUE(form_id, ordinal)
) STRICT;
CREATE TABLE items (
    item_id TEXT PRIMARY KEY NOT NULL,
    module_id TEXT NOT NULL REFERENCES modules(module_id),
    position INTEGER NOT NULL CHECK(position > 0),
    domain TEXT NOT NULL,
    prompt TEXT NOT NULL,
    response_type TEXT NOT NULL CHECK(response_type IN ('mcq_single', 'numeric_grid', 'json_object')),
    choices_json TEXT NOT NULL,
    schema_json TEXT NOT NULL DEFAULT '{}',
    correct TEXT NOT NULL,
    UNIQUE(module_id, position)
) STRICT;
CREATE TABLE routes (
    module_id TEXT NOT NULL,
    form_id TEXT NOT NULL,
    minimum INTEGER NOT NULL CHECK(minimum >= 0),
    maximum INTEGER NOT NULL CHECK(maximum >= minimum),
    next_module_id TEXT,
    PRIMARY KEY(module_id, minimum),
    FOREIGN KEY(form_id, module_id) REFERENCES modules(form_id, module_id),
    FOREIGN KEY(form_id, next_module_id) REFERENCES modules(form_id, module_id) DEFERRABLE INITIALLY DEFERRED,
    CHECK(next_module_id IS NULL OR next_module_id != module_id)
) STRICT;
