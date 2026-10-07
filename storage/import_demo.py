"""GitHub demo record를 최종 PostgreSQL 스키마에 저장한다."""

import argparse

from storage.db import get_connection, get_project_id
from storage.import_utils import (
    PROJECT_ROOT,
    dumps_json,
    load_json,
    require_files,
    resolve_run_dir,
    scenario_payload,
    upsert_scenario,
    verify_project,
)


def demo_session_payload(run_dir):
    """demo 폴더의 여러 파생 파일을 sessions/judgements 형태로 정리한다."""
    require_files(
        run_dir,
        (
            "scenario.yaml",
            "conditions.json",
            "summary.json",
            "record/manifest.json",
            "record/demo-summary.json",
            "record/judgements.json",
        ),
    )

    conditions = load_json(run_dir / "conditions.json")
    summary = load_json(run_dir / "summary.json")
    manifest = load_json(run_dir / "record/manifest.json")
    demo_summary = load_json(run_dir / "record/demo-summary.json")
    judgements = load_json(run_dir / "record/judgements.json")
    replay_path = run_dir / "record/replay.json"
    replay = load_json(replay_path) if replay_path.is_file() else None

    session_id = demo_summary.get("session_id")
    if not session_id:
        raise ValueError(f"{run_dir.name}: demo-summary에 session_id가 없습니다.")

    # 같은 run에서 나온 파일인지 session_id를 교차 확인한다.
    ids = {
        "summary": summary.get("session_id"),
        "manifest": manifest.get("session_id"),
        "judgements": judgements.get("session_id"),
        "conditions": conditions.get("session_id"),
    }
    mismatched = {
        name: value
        for name, value in ids.items()
        if value is not None and value != session_id
    }
    if mismatched:
        raise ValueError(f"{run_dir.name}: session_id 불일치: {mismatched}")

    scenario_info = scenario_payload(run_dir, conditions)
    manifest_scenario = manifest.get("scenario") or {}
    manifest_hash = manifest_scenario.get("hash")
    if manifest_hash and manifest_hash != scenario_info["scenario_hash"]:
        raise ValueError(f"{run_dir.name}: scenario hash가 manifest와 다릅니다.")

    if manifest_scenario.get("id") not in (None, scenario_info["scenario_key"]):
        raise ValueError(f"{run_dir.name}: scenario id가 manifest와 다릅니다.")

    run_meta = manifest.get("run") or {}
    condition_meta = manifest.get("condition") or {}
    code_meta = manifest.get("code") or {}
    token_meta = manifest.get("tokens") or {}
    session_times = demo_summary.get("session_times") or {}

    total_tokens = summary.get("total_tokens")
    if total_tokens is None and token_meta.get("total_status") == "measured":
        total_tokens = token_meta.get("total")

    execution_config = {
        "temperature": condition_meta.get("temperature"),
        "criteria_version": code_meta.get("criteria_version") or judgements.get("criteria_version"),
        "criteria_sha256": judgements.get("criteria_sha256")
        or ((condition_meta.get("group") or {}).get("fields") or {}).get("criteria_sha256"),
        "progress_version": code_meta.get("progress_version"),
        "metrics_version": code_meta.get("metrics_version"),
        "max_steps": condition_meta.get("max_steps"),
        "max_llm_calls_per_step": condition_meta.get("max_llm_calls_per_step"),
        "max_tokens": condition_meta.get("max_tokens"),
        "context_buffer_messages": condition_meta.get("context_buffer_messages"),
        "reasoning_effort": condition_meta.get("reasoning_effort"),
        "runner_protocol": condition_meta.get("runner_protocol"),
        "collection_policy": ((condition_meta.get("group") or {}).get("fields") or {}).get("collection_policy"),
        "output_contract_version": ((condition_meta.get("group") or {}).get("fields") or {}).get("output_contract_version"),
        "requested_seed": ((condition_meta.get("group") or {}).get("fields") or {}).get("requested_seed"),
        "git_commit": code_meta.get("git_commit"),
        "manifest_version": manifest.get("manifest_version"),
    }

    session_data = {
        "import_source": "demo-record",
        "tests_passed": demo_summary.get("tests_passed"),
        "tokens": demo_summary.get("tokens"),
        "credits_estimated": demo_summary.get("credits_estimated"),
        "credits_measured": demo_summary.get("credits_measured"),
        "tool_calls_per_response": demo_summary.get("tool_calls_per_response"),
        "tool_results": demo_summary.get("tool_results"),
        "strict_output": demo_summary.get("strict_output"),
        "condition_group": demo_summary.get("condition_group"),
        "condition_group_missing_fields": demo_summary.get("condition_group_missing_fields"),
        "condition_group_missing_by_class": demo_summary.get("condition_group_missing_by_class"),
        "account_label": demo_summary.get("account_label"),
        "batch": demo_summary.get("batch"),
        "blocked_step": (replay or {}).get("blocked_step"),
        "if_stopped": (replay or {}).get("if_stopped"),
        "key_scan": demo_summary.get("key_scan"),
    }

    session = {
        "id": session_id,
        "status": "ended" if session_times.get("ended_at") or run_meta.get("ended_at") else "active",
        "termination_reason": demo_summary.get("termination_reason") or run_meta.get("termination_reason"),
        "phase": demo_summary.get("phase") or condition_meta.get("phase"),
        "guardrail_mode": demo_summary.get("guardrail_mode") or judgements.get("guardrail_mode"),
        "model": demo_summary.get("model") or (manifest.get("model") or {}).get("name"),
        "steps_reached": demo_summary.get("steps") or run_meta.get("steps_reached"),
        "total_tokens": total_tokens,
        "first_stop_step": judgements.get("first_stop_step"),
        "started_at": session_times.get("started_at") or run_meta.get("started_at"),
        "ended_at": session_times.get("ended_at") or run_meta.get("ended_at"),
        "execution_config": execution_config,
        "session_data": session_data,
    }

    return {
        "scenario": scenario_info,
        "session": session,
        "judgements": judgements.get("steps") or [],
    }


def upsert_demo_session(cursor, scenario_id, session):
    cursor.execute(
        """
        INSERT INTO sessions (
            id, scenario_id, status, termination_reason, phase, guardrail_mode,
            model, steps_reached, total_tokens, first_stop_step,
            started_at, ended_at, execution_config, session_data
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
        )
        ON CONFLICT (id)
        DO UPDATE SET
            scenario_id = EXCLUDED.scenario_id,
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
            session_data = EXCLUDED.session_data;
        """,
        (
            session["id"],
            scenario_id,
            session["status"],
            session["termination_reason"],
            session["phase"],
            session["guardrail_mode"],
            session["model"],
            session["steps_reached"],
            session["total_tokens"],
            session["first_stop_step"],
            session["started_at"],
            session["ended_at"],
            dumps_json(session["execution_config"]),
            dumps_json(session["session_data"]),
        ),
    )


def upsert_demo_judgement(cursor, session_id, row):
    """demo에는 원본 observation이 없으므로 제공된 judgement record만 저장한다."""
    progress = row.get("progress") or {}
    criteria = row.get("criteria") or {}
    decision = criteria.get("decision")
    rule_id = criteria.get("criteria_version")
    if not decision or not rule_id:
        raise ValueError(
            f"{session_id} step {row.get('step_id')}: criteria 식별 정보가 없습니다."
        )

    result_data = {
        "collection": row.get("collection"),
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
            row.get("step_id"),
            row.get("agent_id"),
            row.get("observed_at"),
            decision,
            rule_id,
            criteria.get("criteria_sha256"),
            progress.get("state"),
            progress.get("version"),
            criteria.get("consecutive_steps"),
            criteria.get("reason"),
            row.get("judgement_ns"),
            dumps_json(result_data),
        ),
    )


def import_demo(run_value, project_id):
    """demo run 하나를 저장한다. scenario는 자동 등록된다."""
    run_dir = resolve_run_dir(run_value, demo=True)
    payload = demo_session_payload(run_dir)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            verify_project(cursor, project_id)
            scenario_id = upsert_scenario(cursor, project_id, payload["scenario"])
            upsert_demo_session(cursor, scenario_id, payload["session"])
            for row in payload["judgements"]:
                upsert_demo_judgement(cursor, payload["session"]["id"], row)

    return payload["session"]["id"], len(payload["judgements"])


def demo_folders():
    root = PROJECT_ROOT / "runs" / "demo"
    if not root.is_dir():
        raise FileNotFoundError(f"demo runs 폴더가 없습니다: {root}")
    return sorted(
        folder
        for folder in root.iterdir()
        if folder.is_dir() and (folder / "record/judgements.json").is_file()
    )


def import_all_demos(project_id):
    total_sessions = 0
    total_judgements = 0
    for folder in demo_folders():
        session_id, count = import_demo(str(folder), project_id)
        total_sessions += 1
        total_judgements += count
        print(f"{session_id}: judgements {count}")

    print("demo 전체 PostgreSQL 저장 성공")
    print("sessions:", total_sessions)
    print("judgements:", total_judgements)
    return total_sessions, total_judgements


def main():
    parser = argparse.ArgumentParser(
        description=(
            "GitHub demo record를 PostgreSQL에 저장합니다. "
            "원본이 없는 observation/LLM call은 만들지 않습니다."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("run", nargs="?", help="runs/demo 아래 폴더명/짧은 prefix 또는 경로")
    group.add_argument("--all", action="store_true", help="runs/demo의 모든 record import")
    parser.add_argument("--project-id", type=int)
    args = parser.parse_args()

    project_id = get_project_id(args.project_id)
    if args.all:
        import_all_demos(project_id)
        return

    session_id, count = import_demo(args.run, project_id)
    print("demo PostgreSQL 저장 성공")
    print("session_id:", session_id)
    print("judgements:", count)
    print("observations: 0 (demo record 원본 없음)")
    print("llm_calls: 0 (demo record 원본 없음)")


if __name__ == "__main__":
    main()
