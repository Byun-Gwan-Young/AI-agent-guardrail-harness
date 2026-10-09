-- LEGACY/OFFLINE FIXTURE ONLY.
-- PostgreSQL is owned by storage/schema.sql after DB unification.
-- This file remains for tests/test_service_demo_db.py SQLite compatibility.

-- C-19-6 (DM-89) : demo records in PostgreSQL (database guardrail_demo). Read by service/api.py (read only).
--
-- Every value is copied from committed record files; nothing is recomputed here (STOP sentences and judgement values
-- are stored as recorded). No narrative, reasoning text or key goes into any table.
-- Types are kept to TEXT · INTEGER · DOUBLE PRECISION · BOOLEAN · JSONB · TIMESTAMPTZ so that the offline tests can
-- run the same statements on SQLite after a plain type substitution (service/store.py SQLITE_TYPES).
-- Re-running this file is safe (IF NOT EXISTS). service/load_demo.py replaces the rows in one transaction.

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id      TEXT PRIMARY KEY,
    korean_name      TEXT,                 -- scenarios/README.md (C-19-5 map); NULL when the map has none
    task             TEXT NOT NULL,        -- DEMO-CL · DEMO-CT · DEMO-CT-N · DEMO-CS · DEMO-MR · DEMO-LR · A-1
    task_type        TEXT NOT NULL,        -- T1 · T2 · T3 (demo, DM-3) or dataset
    variant          TEXT NOT NULL,        -- normal · stall · natural (CT-N) · dataset
    pair_scenario_id TEXT,                 -- the other variant of the same task (DM-5); NULL without a pair
    status           TEXT,                 -- the map's status column (데모 최종 동결 · 데이터셋 · 이전 버전)
    frozen           BOOLEAN NOT NULL,     -- listed in docs/criteria/demo-final-freeze.json scenario_ids
    title            TEXT                  -- task title of the sessions' replay.json
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id              TEXT PRIMARY KEY,
    scenario_id             TEXT NOT NULL REFERENCES scenarios (scenario_id),
    task                    TEXT NOT NULL,
    task_type               TEXT NOT NULL,
    variant                 TEXT NOT NULL,
    mode                    TEXT NOT NULL,   -- observe · block
    plan_id                 TEXT,            -- batch plan; NULL for sessions run without the batch runner
    plan_kind               TEXT NOT NULL,   -- main (demo-main-*) · trial (demo-trial-*) · none
    batch_item              TEXT,            -- <scenario>:<mode>:<repeat>
    lane                    INTEGER,
    repeat_index            INTEGER,
    rerun_of                TEXT,
    account_label           TEXT,            -- label the lane recorded (no key anywhere)
    account_corrected       TEXT,            -- reports/c18-8/account-corrections.json (PM statement, DM-81 ②)
    git_commit              TEXT,
    git_dirty               BOOLEAN,
    condition_group         TEXT,
    final_freeze_sha256     TEXT,
    model                   TEXT,
    reasoning_effort        TEXT,
    termination_reason      TEXT,
    class                   TEXT,            -- success · stalled · escalated · other (aggregate); NULL when not counted
    escalated_by            TEXT,
    role_labels             JSONB,           -- role ID -> Korean display name (replay.json, scenario registration)
    steps                   INTEGER,
    max_steps               INTEGER,
    tokens_prompt           INTEGER,
    tokens_cached_prompt    INTEGER,
    tokens_completion       INTEGER,
    tokens_reasoning        INTEGER,         -- a count only
    tokens_total            INTEGER,         -- prompt + completion (the aggregate's "tokens")
    usage_missing_turns     INTEGER,
    credits_measured        DOUBLE PRECISION,
    credits_estimated       DOUBLE PRECISION,
    first_stop_step         INTEGER,
    first_stop_template     TEXT,
    first_stop_text         TEXT,            -- explain-v1 sentence as recorded
    stop_steps              JSONB,
    blocked_step            INTEGER,
    if_stopped_token_ratio  DOUBLE PRECISION,
    if_stopped_tokens_after INTEGER,
    if_stopped_credits_after DOUBLE PRECISION,
    stall_start             INTEGER,         -- aggregate (S-27); NULL when not counted or not computable
    detection_delay         INTEGER,         -- aggregate (first STOP - stall start); negative = late progress (DM-71)
    validity                TEXT NOT NULL,   -- valid · excluded · not_counted (trial or sessions outside the plans)
    exclusion_code          TEXT,            -- reports/c18-8/exclusions.json reason code
    replaced_by             TEXT,
    counted                 BOOLEAN NOT NULL, -- a row of the aggregate (session_rows)
    started_at              TIMESTAMPTZ,
    ended_at                TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS steps (
    session_id          TEXT NOT NULL REFERENCES sessions (session_id),
    step_id             INTEGER NOT NULL,
    agent               TEXT,
    role                TEXT,                -- Korean display name (scenario registration)
    step_status         TEXT,
    failure_reasons     JSONB,
    state               TEXT,                -- baseline · progress · stagnant · oscillating · unmeasured
    state_label         TEXT,                -- 기준 · 진전 · 정체 · 되돌림 · 측정 안 됨
    decision            TEXT,                -- continue · deadlock · termination_failure
    criteria_reason     TEXT,                -- judgements.json criteria.reason
    consecutive_steps   INTEGER,
    stop_template       TEXT,
    stop_text           TEXT,                -- explain-v1 sentence on the STOP step, as recorded
    blocked             BOOLEAN,
    tests_passed        INTEGER,
    tests_total         INTEGER,
    changed_paths       JSONB,
    tokens_prompt       INTEGER,
    tokens_cached_prompt INTEGER,
    tokens_completion   INTEGER,
    tokens_reasoning    INTEGER,             -- a count only
    step_tokens         INTEGER,             -- prompt + completion
    cumulative_tokens   INTEGER,
    credits_estimated   DOUBLE PRECISION,
    cumulative_credits  DOUBLE PRECISION,
    judgement_ns        INTEGER,             -- judgements.json (S-5); NULL when the step has no judgement
    facts               JSONB NOT NULL,      -- the replay.json step as recorded (structured values only)
    PRIMARY KEY (session_id, step_id)
);

CREATE TABLE IF NOT EXISTS aggregates (
    aggregate_id      TEXT PRIMARY KEY,      -- plan IDs joined with '+'
    aggregate_version TEXT,
    plans             JSONB NOT NULL,
    scope             TEXT,
    input_sha256      TEXT NOT NULL,         -- sha256 of the aggregate JSON file
    inputs            JSONB NOT NULL,        -- path -> sha256 of every input file read by the loader
    loaded_at         TIMESTAMPTZ NOT NULL,
    body              JSONB NOT NULL         -- the aggregate JSON as recorded
);

CREATE INDEX IF NOT EXISTS sessions_scenario ON sessions (scenario_id);
CREATE INDEX IF NOT EXISTS sessions_validity ON sessions (validity, mode);
