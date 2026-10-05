import json
import sys
from pathlib import Path

from storage.db import get_connection


# 프로젝트 루트
project_root = Path(__file__).resolve().parent.parent

# 실행할 run 폴더 이름을 명령어에서 받음
if len(sys.argv) < 2:
    print("사용법: python -m storage.import_run <run_folder_name>")
    sys.exit(1)

run_name = sys.argv[1]

# 실험 결과 폴더
run_dir = project_root / "runs" / run_name

# 입력한 run 폴더가 실제로 존재하는지 확인
if not run_dir.exists():
    raise FileNotFoundError(f"run 폴더를 찾을 수 없습니다: {run_dir}")

summary_path = run_dir / "summary.json"
session_path = run_dir / "session.json"
conditions_path = run_dir / "conditions.json"


# JSON 읽기
with open(summary_path, "r", encoding="utf-8") as f:
    summary = json.load(f)

with open(session_path, "r", encoding="utf-8") as f:
    session_data = json.load(f)

with open(conditions_path, "r", encoding="utf-8") as f:
    conditions_data = json.load(f)


# 필요한 값 가져오기
session_id = summary["session_id"]
scenario_key = session_data["meta"]["scenario_id"]
scenario_revision = conditions_data["scenario"]["scenario_revision"]


# summary.json과 session.json이 같은 실행인지 확인
session_json_id = session_data.get("session_id")

if session_json_id != session_id:
    raise ValueError(
        f"session_id가 서로 다릅니다: "
        f"summary={session_id}, session={session_json_id}"
    )


status = session_data["status"]
outcome = summary["actual_outcome"]
termination_reason = summary["termination_reason"]
total_tokens = summary["total_tokens"]

criteria_latest = summary.get("criteria_latest") or {}

stop_candidates = [
    criteria_latest.get("first_deadlock_step"),
    criteria_latest.get("first_termination_failure_step"),
]

first_stop_step = min(
    (step for step in stop_candidates if step is not None),
    default=None,
)

started_at = session_data["meta"]["started_at"]
ended_at = session_data["meta"]["ended_at"]


# 실행 당시 설정 저장
session_meta = session_data.get("meta") or {}
scenario_config = conditions_data.get("scenario") or {}

execution_config = {
    "temperature": session_meta.get("temperature"),
    "criteria_version": session_meta.get("criteria_version"),
    "criteria_parameters": session_meta.get("criteria_parameters"),
    "criteria_sha256": session_meta.get("criteria_sha256"),
    "model": scenario_config.get("model"),
    "max_tokens": scenario_config.get("max_tokens"),
    "scenario_revision": scenario_revision,
    "runner_protocol": conditions_data.get("runner_protocol"),
    "collection_policy": conditions_data.get("collection_policy"),
}

# PostgreSQL 연결
conn = get_connection()
cursor = conn.cursor()


# 실제 실행 당시 scenario revision과 정확히 일치하는 DB scenario 찾기
cursor.execute(
    """
    SELECT id
    FROM scenarios
    WHERE scenario_key = %s
      AND scenario_revision = %s;
    """,
    (scenario_key, scenario_revision),
)

rows = cursor.fetchall()

if len(rows) == 0:
    raise ValueError(
        f"시나리오를 찾을 수 없습니다: "
        f"{scenario_key} revision {scenario_revision}"
    )

if len(rows) > 1:
    raise ValueError(
        f"같은 시나리오가 여러 개 있습니다: "
        f"{scenario_key} revision {scenario_revision}"
    )

scenario_id = rows[0][0]


# -------------------------------------------------
# 1. sessions 저장
# -------------------------------------------------

cursor.execute(
    """
    INSERT INTO sessions (
        id,
        scenario_id,
        status,
        outcome,
        termination_reason,
        total_tokens,
        first_stop_step,
        started_at,
        ended_at,
        execution_config
    )
    VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s::JSONB
    )
    ON CONFLICT (id)
    DO UPDATE SET
        status = EXCLUDED.status,
        outcome = EXCLUDED.outcome,
        termination_reason = EXCLUDED.termination_reason,
        total_tokens = EXCLUDED.total_tokens,
        first_stop_step = EXCLUDED.first_stop_step,
        started_at = EXCLUDED.started_at,
        ended_at = EXCLUDED.ended_at,
        execution_config = EXCLUDED.execution_config;
    """,
    (
        session_id,
        scenario_id,
        status,
        outcome,
        termination_reason,
        total_tokens,
        first_stop_step,
        started_at,
        ended_at,
        json.dumps(execution_config),
    ),
)


# -------------------------------------------------
# 2. observations + judgements 저장
# -------------------------------------------------

observations_dir = run_dir / "observations"

# 1.ack.json, 2.ack.json ... 숫자 순서로 정렬
ack_files = sorted(
    observations_dir.glob("*.ack.json"),
    key=lambda path: int(path.name.split(".")[0]),
)


# session.json의 관측 수와 실제 ack.json 수가 같은지 확인
expected_observations = session_data.get("observations") or []

if len(ack_files) != len(expected_observations):
    raise ValueError(
        f"observation 파일이 누락되었습니다: "
        f"예상 {len(expected_observations)}개, "
        f"ack.json {len(ack_files)}개"
    )



# 예상 step 번호와 실제 ack.json의 step 번호가 같은지 확인
expected_steps = {
    observation["step_id"]
    for observation in expected_observations
}

ack_steps = {
    int(path.name.split(".")[0])
    for path in ack_files
}

if expected_steps != ack_steps:
    raise ValueError(
        f"observation step이 일치하지 않습니다: "
        f"예상={sorted(expected_steps)}, "
        f"ack={sorted(ack_steps)}"
    )





for ack_path in ack_files:

    with open(ack_path, "r", encoding="utf-8") as f:
        ack_data = json.load(f)

    observation = ack_data["observation"]

    step = observation["step_id"]
    role = observation["agent_id"]

    # artifact가 없는 시나리오도 안전하게 처리
    artifact = observation.get("artifact") or {}
    progress = observation.get("progress") or {}

    tests_passed = artifact.get("test_pass_count")
    tests_total = artifact.get("test_total_count")

    progress_state = progress.get("state", "unmeasured")
    progress_version = progress.get("version")

    # metrics가 없는 경우도 안전하게 처리
    metrics = progress.get("metrics") or {}

    # 파일 변경 여부 확인
    files_changed_metric = metrics.get(
        "artifact.files_changed"
    )

    if (
        files_changed_metric is not None
        and files_changed_metric.get("status") == "measured"
    ):
        artifact_changed = bool(files_changed_metric.get("value"))
    else:
        artifact_changed = None


    # 현재 JSON에는 "새로 생긴 issue"가 따로 없으므로 NULL
    new_issue_ids = None


    # observation 원본 전체를 JSONB로 저장
    observation_data = observation


    # progress를 측정할 수 없었던 경우
    unmeasured_reason = None

    if progress_state == "unmeasured":
        unmeasured_reason = progress.get(
            "reason",
            "progress could not be measured"
        )


    # -------------------------------------------------
    # observations 저장
    # -------------------------------------------------

    cursor.execute(
        """
        INSERT INTO observations (
            session_id,
            step,
            role,
            artifact_changed,
            tests_passed,
            tests_total,
            new_issue_ids,
            progress_state,
            observation_data,
            unmeasured_reason,
            progress_version
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s::JSONB, %s, %s
        )
        ON CONFLICT (session_id, step)
        DO UPDATE SET
            role = EXCLUDED.role,
            artifact_changed = EXCLUDED.artifact_changed,
            tests_passed = EXCLUDED.tests_passed,
            tests_total = EXCLUDED.tests_total,
            new_issue_ids = EXCLUDED.new_issue_ids,
            progress_state = EXCLUDED.progress_state,
            observation_data = EXCLUDED.observation_data,
            unmeasured_reason = EXCLUDED.unmeasured_reason,
            progress_version = EXCLUDED.progress_version;
        """,
        (
            session_id,
            step,
            role,
            artifact_changed,
            tests_passed,
            tests_total,
            new_issue_ids,
            progress_state,
            json.dumps(observation_data),
            unmeasured_reason,
            progress_version,
        ),
    )


    # -------------------------------------------------
    # judgements 저장
    # -------------------------------------------------

    criteria = observation["criteria"]

    decision = criteria["decision"]
    rule_id = criteria["criteria_version"]
    stagnant_run = criteria.get("consecutive_steps")
    reason = criteria.get("reason")

    # 현재 ack.json에는 판정 시간(ns)이 없으므로 NULL
    judgement_ns = None


    cursor.execute(
        """
        INSERT INTO judgements (
            session_id,
            step,
            decision,
            rule_id,
            stagnant_run,
            reason,
            judgement_ns
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (session_id, step, rule_id)
        DO UPDATE SET
            decision = EXCLUDED.decision,
            stagnant_run = EXCLUDED.stagnant_run,
            reason = EXCLUDED.reason,
            judgement_ns = EXCLUDED.judgement_ns;
        """,
        (
            session_id,
            step,
            decision,
            rule_id,
            stagnant_run,
            reason,
            judgement_ns,
        ),
    )


# -------------------------------------------------
# 3. llm_calls 저장
# -------------------------------------------------

# LLM turn 번호 -> step / role 연결표 만들기
turn_map = {}

for ack_path in ack_files:

    with open(ack_path, "r", encoding="utf-8") as f:
        ack_data = json.load(f)

    observation = ack_data["observation"]

    step = observation["step_id"]
    role = observation["agent_id"]

    for turn_number in observation.get("llm_turns", []):

        # 같은 LLM turn이 여러 step에 중복 연결되는지 확인
        if turn_number in turn_map:
            raise ValueError(
                f"LLM turn {turn_number}이 여러 step에 중복 연결되어 있습니다."
            )

        turn_map[turn_number] = {
            "step": step,
            "role": role,
        }


# session.json의 모든 LLM 호출
turns = session_data["turns"]


for turn_data in turns:

    call_index = turn_data["turn"]

    mapping = turn_map.get(call_index)

    if mapping is None:
        raise ValueError(
            f"LLM turn {call_index}을 연결할 observation step을 찾을 수 없습니다."
        )

    step = mapping["step"]
    role = mapping["role"]


    # 토큰 정보
    response_body = turn_data.get("response_body") or {}
    usage = response_body.get("usage") or {}

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")

    completion_details = usage.get("completion_tokens_details") or {}
    reasoning_tokens = completion_details.get("reasoning_tokens")


    # tool_calls 실제 내용 가져오기
    choices = response_body.get("choices")

    # 오류 응답 등으로 확인할 수 없는 경우 SQL NULL
    tool_calls = None

    # 정상적인 LLM 응답이 존재하는 경우
    if choices:
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls")

        # 정상 응답이지만 tool call이 없으면 빈 목록
        if tool_calls is None:
            tool_calls = []


    # 전체 처리 시간
    latency_ms = turn_data.get("total_ms")


    cursor.execute(
        """
        INSERT INTO llm_calls (
            session_id,
            call_index,
            step,
            role,
            prompt_tokens,
            completion_tokens,
            reasoning_tokens,
            tool_calls,
            latency_ms
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s::JSONB, %s
        )
        ON CONFLICT (session_id, call_index)
        DO UPDATE SET
            step = EXCLUDED.step,
            role = EXCLUDED.role,
            prompt_tokens = EXCLUDED.prompt_tokens,
            completion_tokens = EXCLUDED.completion_tokens,
            reasoning_tokens = EXCLUDED.reasoning_tokens,
            tool_calls = EXCLUDED.tool_calls,
            latency_ms = EXCLUDED.latency_ms;
        """,
        (
            session_id,
            call_index,
            step,
            role,
            prompt_tokens,
            completion_tokens,
            reasoning_tokens,
            json.dumps(tool_calls) if tool_calls is not None else None,
            latency_ms,
        ),
    )

print(
    f"observations + judgements 자동 저장 준비 완료: "
    f"{len(ack_files)}개"
)

print(f"llm_calls 자동 저장 준비 완료: {len(turns)}개")


# -------------------------------------------------
# 실제 DB에 저장 확정
# -------------------------------------------------

conn.commit()

cursor.close()
conn.close()


print("sessions + observations + judgements + llm_calls 자동 저장 성공!")
print("session_id:", session_id)
print("scenario_key:", scenario_key)