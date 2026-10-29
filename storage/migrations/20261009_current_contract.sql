-- Guardrail Storage current-contract migration (2026-10-09)
--
-- IMPORTANT:
-- * This is intentionally NOT part of schema.sql.
-- * It removes only the explicitly obsolete `scenario-v1` format.
-- * Unknown/future versions (for example scenario-v3) are NOT deleted.
-- * Run through `python -m storage.migrate_current_contract --apply ...`.

-- 1) Remove only sessions that belong to the explicitly obsolete scenario-v1.
CREATE TEMP TABLE _obsolete_storage_sessions ON COMMIT DROP AS
SELECT s.id
FROM sessions s
JOIN scenarios sc ON sc.id = s.scenario_id
WHERE sc.schema_version = 'scenario-v1';

DELETE FROM llm_calls
WHERE session_id IN (SELECT id FROM _obsolete_storage_sessions);

DELETE FROM judgements
WHERE session_id IN (SELECT id FROM _obsolete_storage_sessions);

DELETE FROM observations
WHERE session_id IN (SELECT id FROM _obsolete_storage_sessions);

DELETE FROM sessions
WHERE id IN (SELECT id FROM _obsolete_storage_sessions);

DELETE FROM scenarios
WHERE schema_version = 'scenario-v1';

-- 2) Recover source only from an explicit importer marker already stored on the row.
UPDATE sessions
SET source = 'raw-run'
WHERE source IS NULL
  AND session_data ->> 'import_source' = 'raw-run';

UPDATE sessions
SET source = 'demo-record'
WHERE source IS NULL
  AND session_data ->> 'import_source' = 'demo-record';

-- 3) Refuse to guess or silently destroy data.  Any unexpected row rolls the
--    transaction back instead of forcing it into the current contract.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM scenarios WHERE scenario_hash IS NULL) THEN
        RAISE EXCEPTION 'current-contract migration: scenario_hash NULL rows remain';
    END IF;

    IF EXISTS (SELECT 1 FROM scenarios WHERE config IS NULL) THEN
        RAISE EXCEPTION 'current-contract migration: scenarios.config NULL rows remain';
    END IF;

    IF EXISTS (SELECT 1 FROM observations WHERE observation_data IS NULL) THEN
        RAISE EXCEPTION 'current-contract migration: observation_data NULL rows remain';
    END IF;

    IF EXISTS (SELECT 1 FROM judgements WHERE result_data IS NULL) THEN
        RAISE EXCEPTION 'current-contract migration: result_data NULL rows remain';
    END IF;

    IF EXISTS (SELECT 1 FROM sessions WHERE source IS NULL) THEN
        RAISE EXCEPTION 'current-contract migration: sessions.source NULL rows remain';
    END IF;

    IF EXISTS (
        SELECT 1 FROM sessions
        WHERE source NOT IN ('demo-record', 'raw-run', 'live')
    ) THEN
        RAISE EXCEPTION 'current-contract migration: unexpected sessions.source value remains';
    END IF;

    IF EXISTS (
        SELECT 1 FROM sessions
        WHERE validity NOT IN ('valid', 'excluded', 'not_counted')
    ) THEN
        RAISE EXCEPTION 'current-contract migration: unexpected sessions.validity value remains';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM scenarios
        WHERE scenario_hash IS NOT NULL
        GROUP BY project_id, scenario_key, scenario_hash
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'current-contract migration: duplicate scenario identities remain';
    END IF;
END
$$;

-- 4) Strengthen columns only after the data checks above succeeded.
ALTER TABLE scenarios
    ALTER COLUMN scenario_hash SET NOT NULL,
    ALTER COLUMN config SET NOT NULL;

ALTER TABLE observations
    ALTER COLUMN observation_data SET NOT NULL;

ALTER TABLE judgements
    ALTER COLUMN result_data SET NOT NULL;

ALTER TABLE sessions
    ALTER COLUMN source SET NOT NULL;

-- 5) Replace the historical partial index with the canonical full identity.
DROP INDEX IF EXISTS uq_scenarios_project_key_hash;
CREATE UNIQUE INDEX uq_scenarios_project_key_hash
    ON scenarios (project_id, scenario_key, scenario_hash);

-- 6) Add DB-level guards for current application vocabularies.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sessions_validity_check'
          AND conrelid = 'sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT sessions_validity_check
            CHECK (validity IN ('valid', 'excluded', 'not_counted'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sessions_source_check'
          AND conrelid = 'sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT sessions_source_check
            CHECK (source IN ('demo-record', 'raw-run', 'live'));
    END IF;
END
$$;

-- 7) Read-path indexes.
CREATE INDEX IF NOT EXISTS idx_api_keys_key_prefix ON api_keys (key_prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_project_id ON api_keys (project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_scenario_id ON sessions (scenario_id);
CREATE INDEX IF NOT EXISTS idx_sessions_source_validity ON sessions (source, validity);
