"""Import one real/raw run into the canonical PostgreSQL Storage schema.

This is a writable-project ingestion path, not a demo loader.  The importer
reads the persisted run artifacts, derives ``scenario_hash`` from the exact
``scenario.yaml`` bytes, separates observation input from judgement results,
and rejects forbidden secrets/model text before opening the write path.

Do not use this importer to write into the read-only canonical demo project and
do not invent missing source data.  Re-import of the same identity is designed
to be idempotent through upsert behavior.

See ``storage/README.md`` for the Storage invariants and ownership boundaries.
"""

import argparse

from storage.db import get_connection, get_project_id
from storage.safety import assert_no_secrets, assert_safe_storage_json
from storage.import_utils import (
    build_execution_config,
    build_session_data,
    count_tool_calls,
    dumps_json,
    first_stop_step,
    load_json,
    observation_input,
    require_files,
    resolve_run_dir,
    scenario_payload,
    token_usage,
    upsert_scenario,
    verify_project,
)


def load_persisted_observations(run_dir, session_data):
    """session.json의 observation 목록과 실제 ack.json을 서로 검증해 읽는다."""
    expected = session_data.get("observations") or []
    expected_steps = {
        item.get("step_id") for item in expected if item.get("step_id") is not None
    }
    if len(expected_steps) != len(expected):
        raise ValueError("session.json observation step_id가 없거나 중복되어 있습니다.")

    observations_dir = run_dir / "observations"
    ack_files = []
    if observations_dir.is_dir():
        ack_files = sorted(
            observations_dir.glob("*.ack.json"),
            key=lambda path: int(path.name.split(".")[0]),
        )

    if expected and not ack_files:
        raise ValueError(
            "session.json에는 observation이 있지만 ack.json이 없습니다. "
            "원본 누락 여부를 먼저 확인하세요."
        )

    if len(ack_files) != len(expected):
        raise ValueError(
            f"observation 수가 일치하지 않습니다: "
            f"session.json={len(expected)}, ack.json={len(ack_files)}"
        )

    loaded = []
    for path in ack_files:
        ack = load_json(path)
        if ack.get("persisted") is not True:
            raise ValueError(f"persisted=true가 아닌 ack입니다: {path.name}")

        observation = ack.get("observation")
        if not isinstance(observation, dict):
            raise ValueError(f"observation 객체가 없습니다: {path.name}")

        file_step = int(path.name.split(".")[0])
        if observation.get("step_id") != file_step:
            raise ValueError(
                f"ack 파일명과 step_id가 다릅니다: {path.name}, "
                f"step_id={observation.get('step_id')}"
            )
        loaded.append(observation)

    actual_steps = {item.get("step_id") for item in loaded}
    if expected_steps != actual_steps:
        raise ValueError(
            f"observation step이 일치하지 않습니다: "
            f"session.json={sorted(expected_steps)}, ack={sorted(actual_steps)}"
        )

    expected_by_step = {item["step_id"]: item for item in expected}
    loaded_by_step = {item["step_id"]: item for item in loaded}
    mismatched_steps = [
        step for step in sorted(expected_steps)
        if expected_by_step[step] != loaded_by_step[step]
    ]
    if mismatched_steps:
        raise ValueError(
            "session.json과 ack.json observation 내용이 다릅니다: "
            f"steps={mismatched_steps}"
        )

    return loaded


def _model_name(value):
    """Return a stable TEXT model identifier from string/object source forms."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "model", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    raise ValueError("model must be a string or an object containing name/model/id")


def session_values(summary, session_data, conditions_data, scenario, observations):
    """여러 raw 파일의 값을 sessions 한 행 형태로 정리한다."""
    meta = session_data.get("meta") or {}
    status = session_data.get("status")
    if status == "done":
        status = "ended"

    return {
        "status": status or ("ended" if meta.get("ended_at") else "active"),
        "termination_reason": summary.get("termination_reason") or meta.get("termination_reason"),
        "phase": conditions_data.get("phase"),
        "guardrail_mode": conditions_data.get("guardrail_mode") or meta.get("guardrail_mode"),
        "model": _model_name(
            conditions_data.get("model") or scenario.get("model") or meta.get("model")
        ),
        "steps_reached": summary.get("steps") or len(observations),
        # 알려진 부분합을 전체 토큰으로 둔갑시키지 않는다.
        "total_tokens": summary.get("total_tokens"),
        "first_stop_step": first_stop_step(observations, summary),
        "started_at": meta.get("started_at"),
        "ended_at": meta.get("ended_at"),
        "execution_config": build_execution_config(session_data, conditions_data, scenario),
        "session_data": build_session_data(summary, conditions_data, "raw-run"),
    }


def upsert_session(cursor, session_id, scenario_id, values):
    """Insert/update a raw-run session without changing its historical identity."""
    cursor.execute(
        """
        SELECT source, scenario_id
        FROM sessions
        WHERE id = %s
        FOR UPDATE;
        """,
        (session_id,),
    )
    existing = cursor.fetchone()
    if existing is not None and (existing[0] != "raw-run" or existing[1] != scenario_id):
        raise ValueError(
            f"session_id={session_id!r}는 기존 source/project/scenario identity와 다릅니다."
        )

    cursor.execute(
        """
        INSERT INTO sessions (
            id, scenario_id, status, termination_reason, phase, guardrail_mode,
            model, steps_reached, total_tokens, first_stop_step,
            started_at, ended_at, execution_config, session_data, validity, source
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
            'not_counted', 'raw-run'
        )
        ON CONFLICT (id)
        DO UPDATE SET
            status = EXCLUDED.status,
            termination_reason = EXCLUDED.termination_reason,
            phase = EXCLUDED.phase,
            guardrail_mode = EXCLUDED.guardrail_mode,
            model = EXCLUDED.model,
            steps_reached = EXCLUDED.steps_reached,
            total_tokens = EXCLUDED.total_tokens,
            first_stop_step = EXCLUDED.first_stop_step,
            started_at = EXCLUDED.started_at,
            ended_at = EXCLUDED.ended_at,
            execution_config = EXCLUDED.execution_config,
            session_data = EXCLUDED.session_data,
            validity = EXCLUDED.validity
        WHERE sessions.source = EXCLUDED.source
          AND sessions.scenario_id = EXCLUDED.scenario_id
        RETURNING id;
        """,
        (
            session_id,
            scenario_id,
            values["status"],
            values["termination_reason"],
            values["phase"],
            values["guardrail_mode"],
            values["model"],
            values["steps_reached"],
            values["total_tokens"],
            values["first_stop_step"],
            values["started_at"],
            values["ended_at"],
            dumps_json(values["execution_config"]),
            dumps_json(values["session_data"]),
        ),
    )

    if cursor.fetchone() is None:
        raise ValueError(
            f"session_id={session_id!r}는 기존 source/project/scenario identity와 다릅니다."
        )


def upsert_observation(cursor, session_id, observation):
    """계산 결과를 제외한 observation 입력만 저장한다."""
    cursor.execute(
        """
        INSERT INTO observations (
            session_id, step, agent_id, observed_at, observation_data
        )
        VALUES (%s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (session_id, step)
        DO UPDATE SET
            agent_id = EXCLUDED.agent_id,
            observed_at = EXCLUDED.observed_at,
            observation_data = EXCLUDED.observation_data;
        """,
        (
            session_id,
            observation["step_id"],
            observation.get("agent_id"),
            observation.get("observed_at"),
            dumps_json(observation_input(observation)),
        ),
    )


def upsert_judgement(cursor, session_id, observation):
    """progress + criteria 계산 결과를 judgements에 저장한다."""
    criteria = observation.get("criteria") or {}
    progress = observation.get("progress") or {}

    decision = criteria.get("decision")
    rule_id = criteria.get("criteria_version")
    if not decision or not rule_id:
        return False

    result_data = {
        "collection": observation.get("collection"),
        "progress": progress,
        "criteria": criteria,
    }

    cursor.execute(
        """
        INSERT INTO judgements (
            session_id, step, agent_id, observed_at,
            decision, rule_id, rule_hash,
            progress_state, progress_version,
            stagnant_run, reason, judgement_ns, result_data
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s::jsonb
        )
        ON CONFLICT (session_id, step, rule_id)
        DO UPDATE SET
            agent_id = EXCLUDED.agent_id,
            observed_at = EXCLUDED.observed_at,
            decision = EXCLUDED.decision,
            rule_hash = EXCLUDED.rule_hash,
            progress_state = EXCLUDED.progress_state,
            progress_version = EXCLUDED.progress_version,
            stagnant_run = EXCLUDED.stagnant_run,
            reason = EXCLUDED.reason,
            judgement_ns = EXCLUDED.judgement_ns,
            result_data = EXCLUDED.result_data;
        """,
        (
            session_id,
            observation["step_id"],
            observation.get("agent_id"),
            observation.get("observed_at"),
            decision,
            rule_id,
            criteria.get("criteria_sha256"),
            progress.get("state"),
            progress.get("version"),
            criteria.get("consecutive_steps"),
            criteria.get("reason"),
            observation.get("judgement_ns"),
            dumps_json(result_data),
        ),
    )
    return True


def upsert_llm_call(cursor, session_id, turn_data, mapping):
    """LLM 원문은 제외하고 토큰/지연/상태 같은 메타데이터만 저장한다."""
    prompt_tokens, completion_tokens, reasoning_tokens = token_usage(turn_data)
    agent_id = mapping.get("agent_id") if mapping else None
    step = mapping.get("step") if mapping else None

    cursor.execute(
        """
        INSERT INTO llm_calls (
            session_id, call_index, step, agent_id,
            prompt_tokens, completion_tokens, reasoning_tokens,
            latency_ms, status_code, retry_count, tool_call_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id, call_index)
        DO UPDATE SET
            step = EXCLUDED.step,
            agent_id = EXCLUDED.agent_id,
            prompt_tokens = EXCLUDED.prompt_tokens,
            completion_tokens = EXCLUDED.completion_tokens,
            reasoning_tokens = EXCLUDED.reasoning_tokens,
            latency_ms = EXCLUDED.latency_ms,
            status_code = EXCLUDED.status_code,
            retry_count = EXCLUDED.retry_count,
            tool_call_count = EXCLUDED.tool_call_count;
        """,
        (
            session_id,
            turn_data["turn"],
            step,
            agent_id,
            prompt_tokens,
            completion_tokens,
            reasoning_tokens,
            turn_data.get("total_ms"),
            turn_data.get("status_code"),
            turn_data.get("retry_count"),
            count_tool_calls(turn_data),
        ),
    )


def import_run(run_value, project_id):
    """raw run 하나를 PostgreSQL에 저장한다. scenario는 자동 등록된다."""
    run_dir = resolve_run_dir(run_value, demo=False)
    require_files(
        run_dir,
        ("summary.json", "session.json", "conditions.json", "scenario.yaml"),
    )

    summary = load_json(run_dir / "summary.json")
    session_data = load_json(run_dir / "session.json")
    conditions_data = load_json(run_dir / "conditions.json")

    session_id = summary.get("session_id")
    if not session_id:
        raise ValueError("summary.json에 session_id가 없습니다.")

    # 서로 다른 실행 파일을 실수로 섞어 넣는 일을 막는다.
    for label, value in (
        ("session.json", session_data.get("session_id")),
        ("conditions.json", conditions_data.get("session_id")),
    ):
        if value is not None and value != session_id:
            raise ValueError(
                f"session_id가 서로 다릅니다: summary={session_id}, {label}={value}"
            )

    observations = load_persisted_observations(run_dir, session_data)
    scenario_info = scenario_payload(run_dir, conditions_data)
    scenario = scenario_info["config"]
    values = session_values(summary, session_data, conditions_data, scenario, observations)

    # Raw-run files are trusted experiment artifacts, but the DB is still a
    # persistence boundary. Reject accidental credentials/model traffic before
    # opening a transaction. scenario config may legitimately contain task text,
    # so it receives the secret-only check; persisted session/observation facts
    # receive the stricter storage-shape check.
    assert_no_secrets(scenario_info["config"], "scenario config")
    assert_no_secrets(values["model"], "model")
    assert_safe_storage_json(values["execution_config"], "execution_config")
    assert_safe_storage_json(values["session_data"], "session_data")
    for observation in observations:
        assert_no_secrets(observation.get("agent_id"), "observation agent_id")
        assert_safe_storage_json(observation_input(observation), "observation_data")
        criteria = observation.get("criteria") or {}
        progress = observation.get("progress") or {}
        assert_safe_storage_json(
            {"collection": observation.get("collection"), "progress": progress, "criteria": criteria},
            "judgement result_data",
        )

    with get_connection() as conn:
        with conn.cursor() as cursor:
            verify_project(cursor, project_id)
            scenario_id = upsert_scenario(cursor, project_id, scenario_info)
            upsert_session(cursor, session_id, scenario_id, values)

            judgement_count = 0
            turn_map = {}

            for observation in observations:
                upsert_observation(cursor, session_id, observation)
                if upsert_judgement(cursor, session_id, observation):
                    judgement_count += 1

                # LLM turn 번호를 실제 step/agent에 연결한다.
                for turn_number in observation.get("llm_turns") or []:
                    if turn_number in turn_map:
                        raise ValueError(
                            f"LLM turn {turn_number}이 여러 step에 연결되어 있습니다."
                        )
                    turn_map[turn_number] = {
                        "step": observation.get("step_id"),
                        "agent_id": observation.get("agent_id"),
                    }

            turns = session_data.get("turns") or []
            seen_turns = set()
            for turn_data in turns:
                call_index = turn_data.get("turn")
                if call_index in seen_turns:
                    raise ValueError(f"LLM turn {call_index}이 중복되어 있습니다.")
                seen_turns.add(call_index)
                upsert_llm_call(cursor, session_id, turn_data, turn_map.get(call_index))

    result = {
        "session_id": session_id,
        "scenario_key": scenario_info["scenario_key"],
        "observations": len(observations),
        "judgements": judgement_count,
        "llm_calls": len(session_data.get("turns") or []),
    }

    print("raw run PostgreSQL 저장 성공")
    print("session_id:", result["session_id"])
    print("scenario_key:", result["scenario_key"])
    print("observations:", result["observations"])
    print("judgements:", result["judgements"])
    print("llm_calls:", result["llm_calls"])
    return result


def main():
    parser = argparse.ArgumentParser(
        description="raw run(session.json + ack.json + LLM call)을 PostgreSQL에 저장합니다."
    )
    parser.add_argument("run", help="runs/ 아래 폴더명/짧은 prefix 또는 run 폴더 경로")
    parser.add_argument("--project-id", type=int)
    args = parser.parse_args()

    import_run(args.run, get_project_id(args.project_id))


if __name__ == "__main__":
    main()
