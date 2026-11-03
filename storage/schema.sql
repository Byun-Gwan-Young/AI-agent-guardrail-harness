-- =========================================================
-- AI Agent Guardrail - PostgreSQL 최종 스키마
--
-- 관계:
-- users
--  ├─ projects
--  │   ├─ api_keys
--  │   └─ scenarios
--  │       └─ sessions
--  │           ├─ observations
--  │           ├─ judgements
--  │           └─ llm_calls
--  └─ auth_events
-- allowed_emails (로그인 allow-list)
--
-- 원칙:
-- 1) observations = 판정기에 들어간 입력
-- 2) judgements   = progress/criteria 계산 결과
-- 3) llm_calls    = 요청/응답 원문이 아닌 호출 메타데이터
-- 4) scenario-v2는 scenario_hash로 정확한 YAML 정의를 구분
-- =========================================================

-- MAINTAINER / AI CONTRACT:
-- - 이 파일이 통합 Storage 스키마의 canonical source다. service 쪽 legacy
--   schema/writer를 다시 별도 진실원천으로 만들지 않는다.
-- - 현재 구조는 10개 테이블이며 별도 steps 테이블을 추가하지 않는다.
-- - canonical demo는 read_only이고 raw/live writer의 대상이 아니다.
-- - model/user 원문, reasoning 본문, request/response body, Provider key,
--   Guardrail raw key, DB password를 새 컬럼/JSON에 저장하지 않는다.
-- - schema 변경으로 기존 데이터를 자동 삭제하지 않는다. destructive
--   migration은 preview + 명시적 confirmation이 있는 별도 도구로 분리한다.
-- 자세한 의도/한계/팀 handoff는 storage/README.md를 먼저 읽는다.
--

-- ---------------------------------------------------------
-- 0-1. users
-- Google 로그인으로 확인된 서비스 사용자.
-- google_sub는 Google이 사용자마다 제공하는 고유 식별자다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 계정 탈퇴 유예 상태.
    -- active: 정상 계정
    -- pending_deletion: 탈퇴 요청 후 30일 유예 중
    account_status TEXT NOT NULL DEFAULT 'active',
    deletion_requested_at TIMESTAMPTZ,
    deletion_due_at TIMESTAMPTZ
);

-- 기존 DB에도 계정 탈퇴 상태 컬럼을 안전하게 추가한다.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deletion_due_at TIMESTAMPTZ;

-- schema.sql을 여러 번 실행해도 같은 제약을 다시 만들 수 있도록
-- 기존 제약을 제거한 뒤 현재 계약으로 다시 생성한다.
ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_account_status_check;

ALTER TABLE users
    ADD CONSTRAINT users_account_status_check
    CHECK (account_status IN ('active', 'pending_deletion'));

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_deletion_state_check;

ALTER TABLE users
    ADD CONSTRAINT users_deletion_state_check
    CHECK (
        (
            account_status = 'active'
            AND deletion_requested_at IS NULL
            AND deletion_due_at IS NULL
        )
        OR
        (
            account_status = 'pending_deletion'
            AND deletion_requested_at IS NOT NULL
            AND deletion_due_at IS NOT NULL
            AND deletion_due_at > deletion_requested_at
        )
    );


-- ---------------------------------------------------------
-- 0-2. allowed_emails
-- 서비스 로그인을 허용한 이메일 목록.
-- 사용자가 아직 로그인하지 않았어도 미리 등록할 수 있다.
-- 이메일 비교는 대소문자를 구분하지 않는다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS allowed_emails (
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_allowed_emails_email_ci
    ON allowed_emails (LOWER(email));


-- ---------------------------------------------------------
-- 0-3. auth_events
-- 로그인, 로그인 거절, API 키 발급/폐기 등
-- 인증과 관련된 사건을 기록하는 감사 로그.
-- 로그인 거절처럼 아직 users 행이 없는 경우가 있으므로 user_id는 NULL 가능하다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind VARCHAR(50) NOT NULL,
    user_id BIGINT,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE SET NULL
);



-- ---------------------------------------------------------
-- 1. projects
-- 서비스의 상위 작업 공간.
-- provider      = 사용자가 선택하는 의미 단위(kmu/groq/openai/custom 등)
-- upstream_url  = 프록시가 실제 요청을 보낼 "해결된" endpoint
-- 두 값을 함께 두는 이유: 사용자에게 URL 입력을 강요하지 않으면서도 기존
-- proxy의 upstream_url 계약을 깨지 않고 custom/OpenAI-compatible endpoint도 지원한다.
-- Provider API Key/credential 원문은 이 테이블에 절대 저장하지 않는다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    mode VARCHAR(20) NOT NULL DEFAULT 'observe'
        CONSTRAINT chk_projects_mode_observe_block
        CHECK (mode IN ('observe', 'block')),
    rule_id VARCHAR(100) NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'custom',
    upstream_url TEXT NOT NULL,
    owner_user_id BIGINT REFERENCES users(id),
    read_only BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32),
    ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS read_only BOOLEAN NOT NULL DEFAULT FALSE;

-- Existing rows predate provider.  Infer only providers whose public endpoint is
-- unambiguous; deployment-specific URLs (including KMU) remain 'custom' until
-- the owner/server explicitly assigns a provider.  This migration is idempotent
-- and never deletes project/session data.
UPDATE projects
SET provider = CASE
    WHEN LOWER(upstream_url) LIKE '%api.groq.com%' THEN 'groq'
    WHEN LOWER(upstream_url) LIKE '%api.openai.com%' THEN 'openai'
    ELSE 'custom'
END
WHERE provider IS NULL OR BTRIM(provider) = '';

ALTER TABLE projects
    ALTER COLUMN provider SET DEFAULT 'custom',
    ALTER COLUMN provider SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_projects_provider
    ON projects (provider);

COMMENT ON COLUMN projects.provider IS
    'User-facing provider identifier; credentials are never stored here.';
COMMENT ON COLUMN projects.upstream_url IS
    'Resolved routing endpoint used by the proxy; normally derived from provider, explicit only for custom providers.';

-- Runtime code currently exposes only observe/block. `warn` remains a roadmap item,
-- so enabling it later requires an explicit schema + service contract change rather than
-- silently accepting a mode that the current account/live functions do not implement.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_projects_mode_observe_block'
          AND conrelid = 'projects'::regclass
    ) THEN
        ALTER TABLE projects
            ADD CONSTRAINT chk_projects_mode_observe_block
            CHECK (mode IN ('observe', 'block'));
    END IF;
END
$$;

-- ---------------------------------------------------------
-- 2. api_keys
-- 우리 Guardrail 서비스용 API Key의 원문은 저장하지 않고 hash만 저장한다.
-- Groq/OpenAI/Tavily 같은 외부 Provider Key와는 별개다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_keys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    name TEXT,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (project_id)
        REFERENCES projects(id)
);

ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS key_prefix TEXT,
    ADD COLUMN IF NOT EXISTS name TEXT,
    ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;

-- All current issue_api_key() keys have an 8-character display prefix. Legacy rows
-- without one must be cleaned explicitly before init; do not synthesize a fake prefix.
ALTER TABLE api_keys
    ALTER COLUMN key_prefix SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_key_hash
    ON api_keys (key_hash);

-- API key 검증/프로젝트별 목록 조회 경로.
CREATE INDEX IF NOT EXISTS idx_api_keys_key_prefix
    ON api_keys (key_prefix);

CREATE INDEX IF NOT EXISTS idx_api_keys_project_id
    ON api_keys (project_id);

-- ---------------------------------------------------------
-- 3. scenarios
-- '어떤 실험/과제를 실행했는가'를 저장한다.
-- 같은 scenario_key라도 YAML 내용이 다르면 scenario_hash가 달라 별도 행이 된다.
-- config에는 scenario.yaml의 구조를 JSONB로 보존한다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenarios (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL,
    scenario_key VARCHAR(100) NOT NULL,
    scenario_hash TEXT NOT NULL,
    schema_version VARCHAR(30) NOT NULL,
    name TEXT NOT NULL,
    task_kind VARCHAR(20),
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (project_id)
        REFERENCES projects(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_scenarios_project_key_hash
    ON scenarios (project_id, scenario_key, scenario_hash);

-- ---------------------------------------------------------
-- 4. sessions
-- 하나의 scenario를 실제로 한 번 실행한 기록.
-- execution_config = 어떤 조건으로 실행했는가
-- session_data     = 실행 후 어떤 상세 결과가 남았는가
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(200) PRIMARY KEY,
    scenario_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL,
    termination_reason VARCHAR(50),
    phase VARCHAR(20),
    guardrail_mode VARCHAR(20)
        CONSTRAINT chk_sessions_guardrail_mode_observe_block
        CHECK (guardrail_mode IS NULL OR guardrail_mode IN ('observe', 'block')),
    model TEXT,
    steps_reached INTEGER,
    total_tokens BIGINT,
    first_stop_step INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    execution_config JSONB,
    session_data JSONB,
    validity VARCHAR(20) NOT NULL DEFAULT 'not_counted'
        CHECK (validity IN ('valid', 'excluded', 'not_counted')),
    exclusion_code TEXT,
    rerun_of VARCHAR(200),
    replaced_by VARCHAR(200),
    source VARCHAR(20) NOT NULL
        CHECK (source IN ('demo-record', 'raw-run', 'live')),

    FOREIGN KEY (scenario_id)
        REFERENCES scenarios(id)
);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS guardrail_mode VARCHAR(20),
    ADD COLUMN IF NOT EXISTS validity VARCHAR(20) NOT NULL DEFAULT 'not_counted',
    ADD COLUMN IF NOT EXISTS exclusion_code TEXT,
    ADD COLUMN IF NOT EXISTS rerun_of VARCHAR(200),
    ADD COLUMN IF NOT EXISTS replaced_by VARCHAR(200),
    ADD COLUMN IF NOT EXISTS source VARCHAR(20);

-- guardrail_mode is nullable only for records where no mode was measured/known.
-- Whenever present it must match the modes implemented by accounts.py/live.py.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_sessions_guardrail_mode_observe_block'
          AND conrelid = 'sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT chk_sessions_guardrail_mode_observe_block
            CHECK (guardrail_mode IS NULL OR guardrail_mode IN ('observe', 'block'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_sessions_scenario_id
    ON sessions (scenario_id);

CREATE INDEX IF NOT EXISTS idx_sessions_source_validity
    ON sessions (source, validity);

-- ---------------------------------------------------------
-- 5. llm_calls
-- Proxy가 처리한 개별 LLM 호출의 메타데이터.
-- request/response/reasoning 본문은 저장하지 않는다.
-- step/agent_id는 observation 전에 실행이 끊기면 NULL일 수 있다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_calls (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    call_index INTEGER NOT NULL,
    step INTEGER,
    agent_id TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    reasoning_tokens INTEGER,
    latency_ms DOUBLE PRECISION,
    status_code INTEGER,
    retry_count INTEGER,
    tool_call_count INTEGER,

    FOREIGN KEY (session_id)
        REFERENCES sessions(id),

    UNIQUE (session_id, call_index)
);

-- ---------------------------------------------------------
-- 6. observations
-- 판정기에 실제로 들어간 '입력'만 저장한다.
-- 시나리오마다 형태가 달라질 수 있는 상세 입력은 observation_data(JSONB)에 둔다.
-- progress/criteria 계산 결과는 이 테이블이 아니라 judgements에 저장한다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    step INTEGER NOT NULL,
    agent_id TEXT,
    observed_at TIMESTAMPTZ,
    observation_data JSONB NOT NULL,

    FOREIGN KEY (session_id)
        REFERENCES sessions(id),

    UNIQUE (session_id, step)
);

-- ---------------------------------------------------------
-- 7. judgements
-- observation을 평가한 결과.
-- progress_state/version과 criteria decision을 함께 보존하고,
-- 상세 progress/criteria 결과는 result_data(JSONB)에 저장한다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS judgements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    step INTEGER NOT NULL,
    agent_id TEXT,
    observed_at TIMESTAMPTZ,
    decision VARCHAR(50) NOT NULL,
    rule_id VARCHAR(100) NOT NULL,
    rule_hash TEXT,
    progress_state VARCHAR(30),
    progress_version VARCHAR(50),
    stagnant_run INTEGER,
    reason TEXT,
    judgement_ns BIGINT,
    result_data JSONB NOT NULL,

    FOREIGN KEY (session_id)
        REFERENCES sessions(id),

    -- 현재는 한 session/step/rule_id당 판정 1개를 유지한다.
    UNIQUE (session_id, step, rule_id)
);

-- ---------------------------------------------------------
-- 기존 DB에 대한 데이터 삭제/강제 마이그레이션은 이 파일에서 하지 않는다.
-- 옛 scenario-v1 정리와 NOT NULL 강화는
-- `python -m storage.migrate_current_contract --apply ...`로 명시적으로 수행한다.
-- schema.sql은 신규 DB 생성 + 안전한 additive 변경의 canonical schema다.
-- ---------------------------------------------------------
