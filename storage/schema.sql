-- =========================================================
-- AI Agent Guardrail - PostgreSQL 최종 스키마
--
-- 관계:
-- projects
--  ├─ api_keys
--  └─ scenarios
--      └─ sessions
--          ├─ observations
--          ├─ judgements
--          └─ llm_calls
--
-- 원칙:
-- 1) observations = 판정기에 들어간 입력
-- 2) judgements   = progress/criteria 계산 결과
-- 3) llm_calls    = 요청/응답 원문이 아닌 호출 메타데이터
-- 4) scenario-v2는 scenario_hash로 정확한 YAML 정의를 구분
-- =========================================================

-- ---------------------------------------------------------
-- 1. projects
-- 서비스의 상위 작업 공간. 프로젝트별 기본 모드/규칙/업스트림 설정을 둔다.
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
-- 우리 Guardrail 서비스용 API Key의 원문은 저장하지 않고 hash만 저장한다.
-- Groq/OpenAI/Tavily 같은 외부 Provider Key와는 별개다.
-- ---------------------------------------------------------
CREATE TABLE api_keys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL,
    key_hash TEXT NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (project_id)
        REFERENCES projects(id)
);

CREATE UNIQUE INDEX uq_api_keys_key_hash
    ON api_keys (key_hash);

-- ---------------------------------------------------------
-- 3. scenarios
-- '어떤 실험/과제를 실행했는가'를 저장한다.
-- 같은 scenario_key라도 YAML 내용이 다르면 scenario_hash가 달라 별도 행이 된다.
-- config에는 scenario.yaml의 구조를 JSONB로 보존한다.
-- ---------------------------------------------------------
CREATE TABLE scenarios (
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

CREATE UNIQUE INDEX uq_scenarios_project_key_hash
    ON scenarios (project_id, scenario_key, scenario_hash);

-- ---------------------------------------------------------
-- 4. sessions
-- 하나의 scenario를 실제로 한 번 실행한 기록.
-- execution_config = 어떤 조건으로 실행했는가
-- session_data     = 실행 후 어떤 상세 결과가 남았는가
-- ---------------------------------------------------------
CREATE TABLE sessions (
    id VARCHAR(200) PRIMARY KEY,
    scenario_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL,
    termination_reason VARCHAR(50),
    phase VARCHAR(20),
    guardrail_mode VARCHAR(20),
    model TEXT,
    steps_reached INTEGER,
    total_tokens BIGINT,
    first_stop_step INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    execution_config JSONB,
    session_data JSONB,

    FOREIGN KEY (scenario_id)
        REFERENCES scenarios(id)
);

-- ---------------------------------------------------------
-- 5. llm_calls
-- Proxy가 처리한 개별 LLM 호출의 메타데이터.
-- request/response/reasoning 본문은 저장하지 않는다.
-- step/agent_id는 observation 전에 실행이 끊기면 NULL일 수 있다.
-- ---------------------------------------------------------
CREATE TABLE llm_calls (
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
CREATE TABLE observations (
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
CREATE TABLE judgements (
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
