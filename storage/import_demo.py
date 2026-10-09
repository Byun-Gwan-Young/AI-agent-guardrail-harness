"""Import committed demo records as an exact, read-only PostgreSQL mirror.

The canonical demo is presentation/reproducibility data, not a normal writable
user project.  It is stored under the system-owned ``데모`` project with
``read_only=TRUE``.  Source records are authoritative: missing observations or
LLM-call rows are not synthesized from replay data.

Bulk ``demo-all`` preparation validates every source payload before the write
transaction, replaces demo-owned child rows deterministically, and prunes only
stale rows that belong to the canonical demo import source.  A user-owned
project with the same display name must never be adopted as the demo project.

See ``storage/README.md`` for the demo/live separation contract.
"""

import argparse
import hashlib

from storage.db import get_connection
from storage.safety import assert_no_secrets, assert_safe_storage_json
from storage.import_utils import (
    PROJECT_ROOT,
    dumps_json,
    load_json,
    require_files,
    resolve_run_dir,
    scenario_payload,
    upsert_scenario,
)



DEMO_AGGREGATE = PROJECT_ROOT / "reports" / "c19" / "aggregate-main.json"
DEMO_EXCLUSIONS = PROJECT_ROOT / "reports" / "c18-8" / "exclusions.json"
DEMO_CORRECTIONS = PROJECT_ROOT / "reports" / "c18-8" / "account-corrections.json"
DEMO_PROJECT_NAME = "데모"
DEMO_PROJECT_MODE = "observe"
DEMO_PROJECT_RULE_ID = "deadlock-v0.3"
DEMO_PROJECT_PROVIDER = "custom"
DEMO_PROJECT_UPSTREAM_URL = "https://demo.invalid"

def ensure_demo_project(cursor):
    """읽기 전용 데모 프로젝트를 만들거나 기존 프로젝트를 재사용한다."""
    cursor.execute(
        """
        SELECT id, read_only, owner_user_id
        FROM projects
        WHERE name = %s
          AND owner_user_id IS NULL
        ORDER BY id;
        """,
        (DEMO_PROJECT_NAME,),
    )
    rows = cursor.fetchall()

    if len(rows) > 1:
        raise ValueError(
            f"'{DEMO_PROJECT_NAME}' 프로젝트가 여러 개 있습니다: "
            f"{[row[0] for row in rows]}"
        )

    if rows:
        project_id, read_only, owner_user_id = rows[0]

        if owner_user_id is not None:
            raise ValueError(
                f"'{DEMO_PROJECT_NAME}' 프로젝트가 사용자 소유 프로젝트입니다: "
                f"id={project_id}"
            )

        cursor.execute(
            """
            UPDATE projects
            SET mode = %s,
                rule_id = %s,
                provider = %s,
                upstream_url = %s,
                read_only = TRUE
            WHERE id = %s;
            """,
            (
                DEMO_PROJECT_MODE,
                DEMO_PROJECT_RULE_ID,
                DEMO_PROJECT_PROVIDER,
                DEMO_PROJECT_UPSTREAM_URL,
                project_id,
            ),
        )

        return project_id

    cursor.execute(
        """
        INSERT INTO projects (
            name,
            mode,
            rule_id,
            provider,
            upstream_url,
            owner_user_id,
            read_only
        )
        VALUES (%s, %s, %s, %s, %s, NULL, TRUE)
        RETURNING id;
        """,
        (
            DEMO_PROJECT_NAME,
            DEMO_PROJECT_MODE,
            DEMO_PROJECT_RULE_ID,
            DEMO_PROJECT_PROVIDER,
            DEMO_PROJECT_UPSTREAM_URL,
        ),
    )

    return cursor.fetchone()[0]


def load_demo_metadata():
    """공식 데모 집계/제외/계정 보정 파일을 session_id 기준으로 인덱싱한다."""
    required = (DEMO_AGGREGATE, DEMO_EXCLUSIONS, DEMO_CORRECTIONS)
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("데모 메타데이터 파일이 없습니다: " + ", ".join(missing))

    aggregate = load_json(DEMO_AGGREGATE)
    exclusions = load_json(DEMO_EXCLUSIONS)
    corrections = load_json(DEMO_CORRECTIONS)

    counted = {}
    for row in aggregate.get("session_rows") or []:
        session_id = row.get("session_id")
        if not session_id:
            raise ValueError("aggregate-main.json에 session_id 없는 행이 있습니다.")
        if session_id in counted:
            raise ValueError(f"aggregate-main.json에 session_id가 중복됩니다: {session_id}")
        counted[session_id] = row

    excluded = exclusions.get("sessions") or {}
    if not isinstance(excluded, dict):
        raise ValueError("exclusions.json의 sessions는 객체여야 합니다.")

    corrected_accounts = {}
    for row in corrections.get("sessions") or []:
        session_id = row.get("session_id")
        actual = row.get("actual")
        if not session_id or not actual:
            raise ValueError("account-corrections.json에 session_id/actual이 없는 행이 있습니다.")
        if session_id in corrected_accounts:
            raise ValueError(f"account-corrections.json에 session_id가 중복됩니다: {session_id}")
        corrected_accounts[session_id] = actual

    return {
        "counted": counted,
        "excluded": excluded,
        "corrected_accounts": corrected_accounts,
    }


def apply_demo_metadata(session, demo_summary, metadata):
    """service/load_demo.py와 같은 기준으로 데모 세션의 공식 상태를 붙인다."""
    session_id = session["id"]
    aggregate_row = metadata["counted"].get(session_id)
    exclusion = metadata["excluded"].get(session_id)

    if aggregate_row is not None:
        validity = "valid"
    elif exclusion is not None and exclusion.get("excluded"):
        validity = "excluded"
    else:
        validity = "not_counted"

    if aggregate_row is not None and exclusion is not None and exclusion.get("excluded"):
        raise ValueError(
            f"{session_id}: aggregate에 포함됐지만 exclusions에서도 제외 처리되어 있습니다."
        )

    batch = demo_summary.get("batch") or {}
    rerun_of = batch.get("rerun_of")
    if exclusion is not None and exclusion.get("rerun_of") != rerun_of:
        raise ValueError(
            f"{session_id}: batch.rerun_of와 exclusions.rerun_of가 다릅니다."
        )

    account_label = demo_summary.get("account_label")
    account_corrected = metadata["corrected_accounts"].get(session_id, account_label)

    session["validity"] = validity
    session["exclusion_code"] = (exclusion or {}).get("excluded")
    session["rerun_of"] = rerun_of
    session["replaced_by"] = (exclusion or {}).get("replaced_by")
    session["source"] = "demo-record"

    # 원래 라벨은 유지하고, 보정된 실제 라벨을 별도 값으로 보존한다.
    session["session_data"]["account_label"] = account_label
    session["session_data"]["account_corrected"] = account_corrected
    session["session_data"]["counted"] = aggregate_row is not None

    # 2-3에서 기존 service API 응답을 재구성할 수 있도록
    # aggregate의 구조화된 계산 결과만 보존한다. 에이전트 발언/reasoning 원문은 없다.
    if aggregate_row is not None:
        session["session_data"]["aggregate"] = aggregate_row

    return session


def _validate_demo_payload_contract(run_dir, scenario_info, session, judgement_rows):
    """Fail on malformed canonical demo data before any DB transaction starts."""
    if scenario_info.get("schema_version") != "scenario-v2":
        raise ValueError(
            f"{run_dir.name}: demo scenario는 scenario-v2여야 합니다."
        )
    if not scenario_info.get("scenario_hash"):
        raise ValueError(f"{run_dir.name}: scenario_hash가 없습니다.")
    if not session.get("id"):
        raise ValueError(f"{run_dir.name}: session id가 없습니다.")
    if session.get("source") != "demo-record":
        raise ValueError(f"{run_dir.name}: demo session source가 올바르지 않습니다.")
    if not session.get("started_at"):
        raise ValueError(f"{run_dir.name}: started_at이 없습니다.")

    seen = set()
    for row in judgement_rows:
        step = row.get("step_id")
        criteria = row.get("criteria") or {}
        rule_id = criteria.get("criteria_version")
        decision = criteria.get("decision")

        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError(
                f"{run_dir.name}: 유효하지 않은 judgement step_id={step!r}"
            )
        if not rule_id or not decision:
            raise ValueError(
                f"{run_dir.name} step {step}: judgement criteria 식별 정보가 없습니다."
            )

        identity = (step, rule_id)
        if identity in seen:
            raise ValueError(
                f"{run_dir.name}: judgement가 중복됩니다: step={step}, rule_id={rule_id}"
            )
        seen.add(identity)


def demo_session_payload(run_dir, metadata=None):
    """demo 폴더의 여러 파생 파일을 sessions/judgements 형태로 정리한다."""
    metadata = metadata or load_demo_metadata()
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

    replay_steps = (replay or {}).get("steps") or []

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
        # Git/Windows 체크아웃에서 LF -> CRLF만 바뀐 경우는 허용한다.
        # DB의 scenario_hash 자체는 요구사항대로 현재 scenario.yaml 원본 바이트 SHA-256을 유지한다.
        scenario_bytes = (run_dir / "scenario.yaml").read_bytes()
        lf_hash = hashlib.sha256(scenario_bytes.replace(b"\r\n", b"\n")).hexdigest()
        if manifest_hash != lf_hash:
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
        "git_dirty": code_meta.get("git_dirty"),
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
        "replay_steps": replay_steps,
        "role_labels": (replay or {}).get("role_labels") or {},
        "escalated_by": (replay or {}).get("escalated_by"),
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

    apply_demo_metadata(session, demo_summary, metadata)

    # The scenario file is a trusted specification and can legitimately contain
    # task/system text.  It must still never contain credentials.
    assert_no_secrets(
        scenario_info["config"],
        f"{run_dir.name}: scenario config",
    )

    # Everything below is operational/session data.  Scan the *complete values
    # that will actually be persisted*, not just replay_steps.
    assert_safe_storage_json(
        session["execution_config"],
        f"{run_dir.name}: execution_config",
    )
    assert_safe_storage_json(
        session["session_data"],
        f"{run_dir.name}: session_data",
    )

    judgement_rows = judgements.get("steps") or []
    _validate_demo_payload_contract(
        run_dir,
        scenario_info,
        session,
        judgement_rows,
    )

    for row in judgement_rows:
        result_data = {
            "collection": row.get("collection"),
            "progress": row.get("progress") or {},
            "criteria": row.get("criteria") or {},
        }
        assert_safe_storage_json(
            result_data,
            f"{run_dir.name}: judgement step {row.get('step_id')}",
        )

    return {
        "scenario": scenario_info,
        "session": session,
        "judgements": judgement_rows,
    }


def _assert_demo_session_identity(cursor, session_id, demo_project_id):
    """A session id may never move between sources or projects."""
    cursor.execute(
        """
        SELECT s.source, sc.project_id
        FROM sessions s
        JOIN scenarios sc ON sc.id = s.scenario_id
        WHERE s.id = %s;
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return

    source, project_id = row
    if source != "demo-record" or project_id != demo_project_id:
        raise ValueError(
            f"session_id={session_id!r}는 다른 source/project에서 이미 사용 중입니다."
        )


def upsert_demo_session(cursor, scenario_id, session):
    cursor.execute(
        """
        INSERT INTO sessions (
            id, scenario_id, status, termination_reason, phase, guardrail_mode,
            model, steps_reached, total_tokens, first_stop_step,
            started_at, ended_at, execution_config, session_data,
            validity, exclusion_code, rerun_of, replaced_by, source
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
            %s, %s, %s, %s, %s
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
            session_data = EXCLUDED.session_data,
            validity = EXCLUDED.validity,
            exclusion_code = EXCLUDED.exclusion_code,
            rerun_of = EXCLUDED.rerun_of,
            replaced_by = EXCLUDED.replaced_by,
            source = EXCLUDED.source
        WHERE sessions.source = EXCLUDED.source
        RETURNING id;
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
            session["validity"],
            session["exclusion_code"],
            session["rerun_of"],
            session["replaced_by"],
            session["source"],
        ),
    )

    if cursor.fetchone() is None:
        raise ValueError(
            f"session_id={session['id']!r}는 다른 source의 세션에서 이미 사용 중입니다."
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
        );
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


def _replace_demo_children(cursor, session_id, judgement_rows):
    """Make one demo session an exact mirror of the current canonical record."""
    # Canonical demo records do not contain original observations/LLM calls.
    # Delete accidental/stale rows instead of silently keeping data that the
    # source record no longer contains.
    cursor.execute("DELETE FROM llm_calls WHERE session_id = %s;", (session_id,))
    cursor.execute("DELETE FROM observations WHERE session_id = %s;", (session_id,))
    cursor.execute("DELETE FROM judgements WHERE session_id = %s;", (session_id,))

    for row in judgement_rows:
        upsert_demo_judgement(cursor, session_id, row)


def _write_demo_payload(cursor, project_id, payload):
    session_id = payload["session"]["id"]
    _assert_demo_session_identity(cursor, session_id, project_id)

    scenario_id = upsert_scenario(cursor, project_id, payload["scenario"])
    upsert_demo_session(cursor, scenario_id, payload["session"])
    _replace_demo_children(cursor, session_id, payload["judgements"])

    return session_id, len(payload["judgements"])


def _prepare_all_demo_payloads():
    """Parse and validate every file before opening a write transaction."""
    metadata = load_demo_metadata()
    payloads = []
    seen_session_ids = set()

    for folder in demo_folders():
        payload = demo_session_payload(folder, metadata=metadata)
        session_id = payload["session"]["id"]
        if session_id in seen_session_ids:
            raise ValueError(f"demo session_id가 중복됩니다: {session_id}")
        seen_session_ids.add(session_id)
        payloads.append(payload)

    return payloads


def _prune_stale_demo_rows(cursor, project_id, current_session_ids):
    """Remove only stale canonical demo rows from the read-only demo project."""
    cursor.execute(
        """
        SELECT s.id
        FROM sessions s
        JOIN scenarios sc ON sc.id = s.scenario_id
        WHERE sc.project_id = %s
          AND s.source = 'demo-record'
          AND NOT (s.id = ANY(%s));
        """,
        (project_id, list(current_session_ids)),
    )
    stale_ids = [row[0] for row in cursor.fetchall()]

    if stale_ids:
        cursor.execute("DELETE FROM llm_calls WHERE session_id = ANY(%s);", (stale_ids,))
        cursor.execute("DELETE FROM observations WHERE session_id = ANY(%s);", (stale_ids,))
        cursor.execute("DELETE FROM judgements WHERE session_id = ANY(%s);", (stale_ids,))
        cursor.execute("DELETE FROM sessions WHERE id = ANY(%s);", (stale_ids,))

    # Scenario versions in the demo project are derived data too.  Keep exactly
    # the versions still referenced by current demo sessions.
    cursor.execute(
        """
        DELETE FROM scenarios sc
        WHERE sc.project_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM sessions s WHERE s.scenario_id = sc.id
          );
        """,
        (project_id,),
    )

    return stale_ids


def _verify_demo_structure(cursor, project_id, expected_sessions, expected_judgements):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM sessions s
        JOIN scenarios sc ON sc.id = s.scenario_id
        WHERE sc.project_id = %s AND s.source = 'demo-record';
        """,
        (project_id,),
    )
    session_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM judgements j
        JOIN sessions s ON s.id = j.session_id
        JOIN scenarios sc ON sc.id = s.scenario_id
        WHERE sc.project_id = %s AND s.source = 'demo-record';
        """,
        (project_id,),
    )
    judgement_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM observations o
        JOIN sessions s ON s.id = o.session_id
        JOIN scenarios sc ON sc.id = s.scenario_id
        WHERE sc.project_id = %s AND s.source = 'demo-record';
        """,
        (project_id,),
    )
    observation_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM llm_calls l
        JOIN sessions s ON s.id = l.session_id
        JOIN scenarios sc ON sc.id = s.scenario_id
        WHERE sc.project_id = %s AND s.source = 'demo-record';
        """,
        (project_id,),
    )
    llm_call_count = cursor.fetchone()[0]

    if session_count != expected_sessions:
        raise RuntimeError(
            f"demo session sync 검증 실패: expected={expected_sessions}, actual={session_count}"
        )
    if judgement_count != expected_judgements:
        raise RuntimeError(
            f"demo judgement sync 검증 실패: expected={expected_judgements}, actual={judgement_count}"
        )
    if observation_count != 0 or llm_call_count != 0:
        raise RuntimeError(
            "canonical demo에는 observation/llm_call 원본이 없어야 합니다: "
            f"observations={observation_count}, llm_calls={llm_call_count}"
        )


def import_demo(run_value, metadata=None, project_id=None):
    """demo run 하나를 읽기 전용 데모 프로젝트에 정확히 동기화한다."""
    run_dir = resolve_run_dir(run_value, demo=True)
    payload = demo_session_payload(run_dir, metadata=metadata)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            demo_project_id = ensure_demo_project(cursor)
            if project_id is None:
                project_id = demo_project_id
            elif project_id != demo_project_id:
                raise ValueError(
                    "demo record는 읽기 전용 '데모' 프로젝트에만 저장할 수 있습니다."
                )

            return _write_demo_payload(cursor, project_id, payload)


def demo_folders():
    root = PROJECT_ROOT / "runs" / "demo"
    if not root.is_dir():
        raise FileNotFoundError(f"demo runs 폴더가 없습니다: {root}")
    return sorted(
        folder
        for folder in root.iterdir()
        if folder.is_dir() and (folder / "record/judgements.json").is_file()
    )


def import_all_demos():
    """현재 runs/demo 전체를 한 transaction으로 canonical DB에 동기화한다."""
    payloads = _prepare_all_demo_payloads()
    if not payloads:
        raise FileNotFoundError(
            "canonical demo record가 하나도 없어 DB 동기화를 중단합니다."
        )

    current_session_ids = {payload["session"]["id"] for payload in payloads}
    expected_judgements = sum(len(payload["judgements"]) for payload in payloads)

    results = []
    stale_ids = []

    # All file parsing/security validation happened above.  From here to the
    # end of the context manager, either the complete dataset commits or the
    # whole transaction rolls back.
    with get_connection() as conn:
        with conn.cursor() as cursor:
            project_id = ensure_demo_project(cursor)

            # Preflight every id before changing any row so a foreign-source
            # collision fails the whole import without partial writes.
            for payload in payloads:
                _assert_demo_session_identity(
                    cursor,
                    payload["session"]["id"],
                    project_id,
                )

            for payload in payloads:
                results.append(_write_demo_payload(cursor, project_id, payload))

            stale_ids = _prune_stale_demo_rows(
                cursor,
                project_id,
                current_session_ids,
            )
            _verify_demo_structure(
                cursor,
                project_id,
                expected_sessions=len(payloads),
                expected_judgements=expected_judgements,
            )

    # Print only after commit; otherwise a later rollback could leave a log
    # claiming rows were saved when they were not.
    for session_id, count in results:
        print(f"{session_id}: judgements {count}")

    print("demo 전체 PostgreSQL 동기화 성공")
    print("project_id:", project_id)
    print("sessions:", len(payloads))
    print("judgements:", expected_judgements)
    print("stale demo sessions removed:", len(stale_ids))

    return len(payloads), expected_judgements


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
    args = parser.parse_args()

    if args.all:
        import_all_demos()
        return

    session_id, count = import_demo(args.run)

    print("demo PostgreSQL 저장 성공")
    print("session_id:", session_id)
    print("judgements:", count)
    print("observations: 0 (demo record 원본 없음)")
    print("llm_calls: 0 (demo record 원본 없음)")


if __name__ == "__main__":
    main()
