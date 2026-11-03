"""Shared parsing/validation helpers for raw and demo importers.

Key semantic contracts:
- ``scenario_hash`` is SHA-256 of the original YAML file bytes, not a hash of
  parsed/re-serialized YAML.
- observation JSON keeps judge *inputs*; computed progress/criteria belong in
  ``judgements.result_data``.
- importer helpers must preserve source identity rather than silently guessing
  missing versions or records.

This module is deliberately small so both ingestion paths use the same meaning
for scenario/session data.  See ``storage/README.md`` for the full handoff.
"""

import hashlib
import json
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOP_DECISIONS = {"deadlock", "termination_failure"}
CURRENT_SCENARIO_SCHEMA_VERSION = "scenario-v2"

# progress_schema.Observation의 '입력' 성격 필드만 보존한다.
# progress / criteria는 계산 결과이므로 judgements로 분리한다.
OBSERVATION_INPUT_FIELDS = {
    "issue_report",
    "collection",
    "agent_id",
    "step_id",
    "llm_turns",
    "progress_source",
    "progress_metric",
    "conversation",
    "artifact",
    "extracted_conversation",
    "termination_context",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_yaml(path):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML 최상위 값이 객체가 아닙니다: {path}")
    return data


def dumps_json(value):
    return json.dumps(value, ensure_ascii=False)


def sha256_file(path):
    """scenario.yaml 파일 바이트 그대로 SHA-256을 계산한다."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_run_dir(value, demo=False):
    """
    run 폴더를 찾는다.

    정확한 폴더명/경로를 우선 사용하고, 못 찾으면 짧은 prefix도 허용한다.
    예: `A-1-v2`가 딱 한 폴더와만 매칭되면 긴 UUID를 생략할 수 있다.
    """
    candidate = Path(value)
    if candidate.is_dir():
        return candidate.resolve()

    base = PROJECT_ROOT / "runs" / ("demo" if demo else "")
    exact = (base / value).resolve()
    if exact.is_dir():
        return exact

    if not base.is_dir():
        raise FileNotFoundError(f"run 기준 폴더가 없습니다: {base}")

    matches = sorted(
        folder for folder in base.iterdir()
        if folder.is_dir() and folder.name.startswith(value)
    )
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        preview = "\n  - ".join(folder.name for folder in matches[:10])
        raise ValueError(
            f"'{value}'로 시작하는 run이 여러 개입니다. 더 길게 입력하세요.\n"
            f"  - {preview}"
        )

    raise FileNotFoundError(f"run 폴더를 찾을 수 없습니다: {exact}")


def require_files(run_dir, relative_paths):
    missing = [name for name in relative_paths if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{run_dir.name}에 필요한 파일이 없습니다: {', '.join(missing)}"
        )


def verify_project(cursor, project_id):
    """raw import 대상이 존재하는 writable project인지 확인한다.

    read_only demo project는 발표 데이터의 canonical boundary이므로 raw run을
    실수로 섞어 넣지 않는다. CLI 자동 선택과 여기서 이중으로 방어한다.
    """
    cursor.execute(
        "SELECT read_only FROM projects WHERE id = %s;",
        (project_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"projects.id={project_id} 프로젝트가 없습니다.")
    if bool(row[0]):
        raise ValueError(f"projects.id={project_id}는 읽기 전용 프로젝트입니다.")


def scenario_payload(run_dir, conditions_data):
    """scenario.yaml을 DB의 scenarios 한 행 형태로 정리한다."""
    scenario_path = run_dir / "scenario.yaml"
    scenario = load_yaml(scenario_path)
    condition_scenario = conditions_data.get("scenario") or {}

    scenario_key = scenario.get("scenario_id") or condition_scenario.get("scenario_id")
    if not scenario_key:
        raise ValueError("scenario_id를 찾을 수 없습니다.")

    yaml_schema_version = scenario.get("schema_version")
    condition_schema_version = condition_scenario.get("schema_version")
    if (
        yaml_schema_version
        and condition_schema_version
        and yaml_schema_version != condition_schema_version
    ):
        raise ValueError(
            "scenario.yaml과 conditions.json의 schema_version이 다릅니다: "
            f"{yaml_schema_version!r} != {condition_schema_version!r}"
        )

    schema_version = yaml_schema_version or condition_schema_version
    if schema_version != CURRENT_SCENARIO_SCHEMA_VERSION:
        raise ValueError(
            "현재 Storage는 scenario-v2만 지원합니다: "
            f"받은 schema_version={schema_version!r}"
        )
    name = scenario.get("title") or condition_scenario.get("title") or scenario_key
    task_kind = scenario.get("task_kind") or condition_scenario.get("task_kind")

    return {
        "scenario_key": scenario_key,
        "scenario_hash": sha256_file(scenario_path),
        "schema_version": schema_version,
        "name": name,
        "task_kind": task_kind,
        # 현재 scenario-v2 원본 구조를 JSONB로 보존한다.
        "config": scenario,
    }


def upsert_scenario(cursor, project_id, payload):
    """
    scenario를 자동 등록/갱신한다.

    사용자가 pgAdmin에서 시나리오 행을 미리 INSERT할 필요가 없다.
    동일 project + key + hash면 기존 행을 갱신하고, hash가 다르면 새 행을 만든다.
    """
    cursor.execute(
        """
        INSERT INTO scenarios (
            project_id,
            scenario_key,
            scenario_hash,
            schema_version,
            name,
            task_kind,
            config
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (project_id, scenario_key, scenario_hash)
        DO UPDATE SET
            schema_version = EXCLUDED.schema_version,
            name = EXCLUDED.name,
            task_kind = EXCLUDED.task_kind,
            config = EXCLUDED.config
        RETURNING id;
        """,
        (
            project_id,
            payload["scenario_key"],
            payload["scenario_hash"],
            payload["schema_version"],
            payload["name"],
            payload["task_kind"],
            dumps_json(payload["config"]),
        ),
    )
    return cursor.fetchone()[0]


def observation_input(observation):
    """재판정에 필요한 입력만 골라 observation_data에 저장한다."""
    return {
        key: observation.get(key)
        for key in OBSERVATION_INPUT_FIELDS
        if key in observation
    }


def first_stop_step(observations, summary=None):
    """deadlock/termination_failure 중 실제 첫 STOP step을 찾는다."""
    for observation in observations:
        criteria = observation.get("criteria") or {}
        if criteria.get("decision") in STOP_DECISIONS:
            return observation.get("step_id")

    criteria_latest = (summary or {}).get("criteria_latest") or {}
    candidates = [
        criteria_latest.get("first_deadlock_step"),
        criteria_latest.get("first_termination_failure_step"),
    ]
    values = [value for value in candidates if value is not None]
    return min(values) if values else None


def count_tool_calls(turn_data):
    """tool call 원문 대신 개수만 계산한다."""
    explicit = turn_data.get("tool_calls")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit

    response = turn_data.get("response_body")
    if not isinstance(response, dict):
        return None

    choices = response.get("choices")
    if not isinstance(choices, list):
        return None

    count = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            count += len(calls)
        elif message.get("function_call") is not None:
            count += 1
    return count


def token_usage(turn_data):
    """Provider 형식 차이를 고려해 토큰 메타데이터를 읽는다."""
    response = turn_data.get("response_body") or {}
    usage = response.get("usage") or {}

    prompt = turn_data.get("prompt_tokens")
    if prompt is None:
        prompt = usage.get("prompt_tokens")

    completion = turn_data.get("completion_tokens")
    if completion is None:
        completion = usage.get("completion_tokens")

    completion_details = usage.get("completion_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    reasoning = completion_details.get("reasoning_tokens")
    if reasoning is None:
        reasoning = output_details.get("reasoning_tokens")

    return prompt, completion, reasoning


def build_execution_config(session_data, conditions_data, scenario):
    """'어떤 조건으로 실행했는가'에 해당하는 값을 모은다."""
    meta = session_data.get("meta") or {}
    termination = scenario.get("termination") or {}
    reasoning = (
        conditions_data.get("final_reasoning_effort")
        or conditions_data.get("reasoning_effort")
        or scenario.get("reasoning_effort")
    )

    return {
        "temperature": conditions_data.get("temperature", meta.get("temperature")),
        "criteria_version": meta.get("criteria_version") or scenario.get("criteria_version"),
        "criteria_parameters": meta.get("criteria_parameters"),
        "criteria_sha256": meta.get("criteria_sha256"),
        "model": conditions_data.get("model") or scenario.get("model") or meta.get("model"),
        "max_tokens": scenario.get("max_tokens", meta.get("max_tokens")),
        "max_steps": termination.get("max_steps"),
        "max_llm_calls_per_step": termination.get("max_llm_calls_per_step"),
        "context_buffer_messages": (
            conditions_data["context_buffer_messages"]
            if "context_buffer_messages" in conditions_data
            else (
                scenario["context_buffer_messages"]
                if "context_buffer_messages" in scenario
                else meta.get("context_buffer_messages")
            )
        ),
        "reasoning_effort": reasoning,
        "runner_protocol": conditions_data.get("runner_protocol"),
        "collection_policy": conditions_data.get("collection_policy"),
        "output_contract_version": conditions_data.get("output_contract_version"),
        "requested_seed": conditions_data.get("requested_seed", meta.get("requested_seed")),
        "registration_sha256": conditions_data.get("registration_sha256"),
    }


def build_session_data(summary, conditions_data, source):
    """'실행 후 어떤 상세 결과가 남았는가'에 해당하는 값을 모은다."""
    return {
        "import_source": source,
        "actual_outcome": summary.get("actual_outcome"),
        "tests_passed_before": summary.get("tests_passed_before"),
        "tests_passed_after": summary.get("tests_passed_after"),
        "known_tokens_subtotal": summary.get("known_tokens_subtotal"),
        "missing_observation_count": summary.get("missing_observation_count"),
        "missing_observation_steps": summary.get("missing_observation_steps"),
        "failed_steps": summary.get("failed_steps"),
        "gateway_usage": summary.get("gateway_usage"),
        "condition_group": conditions_data.get("condition_group"),
        "account_label": conditions_data.get("account_label"),
        "batch": conditions_data.get("batch"),
    }
