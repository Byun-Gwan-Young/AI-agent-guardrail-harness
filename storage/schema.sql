-- =========================================================
-- AI Agent Guardrail - PostgreSQL Schema
-- =========================================================


-- ---------------------------------------------------------
-- 1. projects
-- 가드레일 프로젝트 정보
-- ---------------------------------------------------------

CREATE TABLE projects (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    mode VARCHAR(20) NOT NULL DEFAULT 'observe',
    rule_id VARCHAR(100) NOT NULL,
    upstream_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ---------------------------------------------------------
-- 2. api_keys
-- 프로젝트별 가드레일 API Key 정보
-- 실제 키 원문이 아니라 hash를 저장
-- ---------------------------------------------------------

CREATE TABLE api_keys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL,
    key_hash TEXT NOT NULL,
    revoked_at TIMESTAMPTZ,

    FOREIGN KEY (project_id)
        REFERENCES projects(id)
);


-- ---------------------------------------------------------
-- 3. scenarios
-- 에이전트에게 시킬 과제와 실행 조건
-- ---------------------------------------------------------

CREATE TABLE scenarios (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL,
    scenario_key VARCHAR(100) NOT NULL,
    scenario_revision INTEGER NOT NULL,
    name TEXT NOT NULL,
    config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (project_id)
        REFERENCES projects(id),

    UNIQUE (project_id, scenario_key, scenario_revision)
);


-- ---------------------------------------------------------
-- 4. sessions
-- 시나리오를 실제로 실행한 한 번의 실행 기록
-- ---------------------------------------------------------

CREATE TABLE sessions (
    id VARCHAR(200) PRIMARY KEY,
    scenario_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL,
    outcome VARCHAR(30),
    termination_reason VARCHAR(50),
    total_tokens BIGINT,
    first_stop_step INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    execution_config JSONB,

    FOREIGN KEY (scenario_id)
        REFERENCES scenarios(id)
);


-- ---------------------------------------------------------
-- 5. llm_calls
-- 세션 중 발생한 각각의 LLM 호출
-- 한 step에서 여러 LLM 호출이 발생할 수 있음
-- ---------------------------------------------------------

CREATE TABLE llm_calls (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    call_index INTEGER NOT NULL,
    step INTEGER,
    role VARCHAR(50),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    reasoning_tokens INTEGER,
    tool_calls JSONB,
    latency_ms DOUBLE PRECISION,

    FOREIGN KEY (session_id)
        REFERENCES sessions(id),

    UNIQUE (session_id, call_index)
);


-- ---------------------------------------------------------
-- 6. observations
-- 각 step에서 관측한 상태와 progress 결과
-- ---------------------------------------------------------

CREATE TABLE observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    step INTEGER NOT NULL,
    role VARCHAR(50),
    artifact_changed BOOLEAN,
    tests_passed INTEGER,
    tests_total INTEGER,
    new_issue_ids JSONB,
    progress_state VARCHAR(30) NOT NULL,
    observation_data JSONB,
    unmeasured_reason TEXT,
    progress_version VARCHAR(50),

    FOREIGN KEY (session_id)
        REFERENCES sessions(id),

    UNIQUE (session_id, step)
);


-- ---------------------------------------------------------
-- 7. judgements
-- observation을 기준으로 가드레일이 내린 판정
-- 같은 step도 서로 다른 rule로 다시 판정할 수 있음
-- ---------------------------------------------------------

CREATE TABLE judgements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    step INTEGER NOT NULL,
    decision VARCHAR(50) NOT NULL,
    rule_id VARCHAR(100) NOT NULL,
    stagnant_run INTEGER,
    reason TEXT,
    judgement_ns BIGINT,

    FOREIGN KEY (session_id)
        REFERENCES sessions(id),

    UNIQUE (session_id, step, rule_id)
);