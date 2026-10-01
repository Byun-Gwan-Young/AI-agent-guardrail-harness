"""explain-v1 (DM-9): one Korean STOP-reason sentence built only from judgement signal values.

No LLM call and no model text (narrative, reasoning). A value that was not measured is written as UNMEASURED,
never guessed. Templates and their selection order are frozen with deadlock-v0.3 (criteria parameter
explanation_version). Design: docs/design/demo-block-and-explanation.md 2.
"""
VERSION = "explain-v1"
UNMEASURED = "(측정 안 됨)"
TEMPLATES = {
    "E1": "최근 {n} step 동안 {roles} 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 {pass}/{total}.",
    "E2": "{path} 가 step {k} 의 내용으로 되돌아갔고, 통과 테스트는 {m} step 동안 {pass}/{total} 입니다.",
    "E3": "step {a} 이후 {m} step 동안 파일이 {c} 번 바뀌었지만 통과 테스트는 {pass}/{total} 에서 늘지 않았습니다.",
    "E4": "{role_a} 과 {role_b} 가 문의를 서로 {h} 번 넘겼고 처리 상태는 '{status}' 에서 바뀌지 않았습니다.",
    "E5": "최근 {n} step 동안 채택 항목이 {adopted}/{required} 에서 늘지 않았고 처리 상태는 '{status}' 입니다.",
    "E6": "step {d} 에 완료가 선언됐지만 이후 {n} step 동안 진전이 없습니다. 통과 테스트 {pass}/{total}.",
    "E7": "최근 {n} step 중 {o} step 은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다.",
}
# E6 for a dialogue (T1) task: the second sentence reports the status instead of tests.
E6_DIALOGUE = "step {d} 에 완료가 선언됐지만 이후 {n} step 동안 진전이 없습니다. 처리 상태는 '{status}' 입니다."
STOP_DECISIONS = ("deadlock", "termination_failure")


def signals_from(observations, criteria, parameters):
    """Signal values behind one STOP record, read from progress-v3 records and the criteria result only."""
    by_step = {o["step_id"]: o for o in observations}
    stop = observations[-1]
    progress = stop.get("progress") or {}
    artifact = stop.get("artifact") or {}
    conversation = stop.get("conversation") or {}
    streak = [by_step[s] for s in criteria.get("consecutive_step_ids", []) if s in by_step]
    t3_streak = [(o["step_id"], (o.get("progress") or {}).get("t3") or {}) for o in streak]
    revert = next(({"step": s, "paths": t["changed_paths"], "revert_to_step": t["revert_to_step"]}
                   for s, t in reversed(t3_streak) if t.get("applied") == "global_revert"), None)
    t3 = progress.get("t3") or {}
    adopted = (progress.get("metrics") or {}).get("conversation.adopted_items") or {}
    statuses = [(o.get("conversation") or {}).get("status") for o in observations]
    return {
        "decision": criteria["decision"], "stop_step": stop["step_id"],
        "task_kind": "dialogue" if stop.get("progress_source") == "conversation" else "artifact",
        "consecutive_steps": criteria.get("consecutive_steps"),
        "consecutive_states": criteria.get("consecutive_states"),
        "streak_roles": [o.get("agent_id") for o in streak], "declared_step": criteria.get("declared_step"),
        "test_pass_count": artifact.get("test_pass_count"), "test_total_count": artifact.get("test_total_count"),
        "global_revert": revert,
        "test_plateau_in_streak": any(t.get("applied") == "test_plateau" for _, t in t3_streak),
        "test_max_step": t3.get("test_max_step"), "steps_since_test_max": t3.get("steps_since_test_max"),
        "file_state_changes_since_test_max": t3.get("file_state_changes_since_test_max"),
        "handoff": progress.get("handoff"), "handoff_threshold": parameters["handoff_record_threshold"],
        "status": next((s for s in reversed(statuses) if s is not None), None),
        "adopted_metric_selected": "adopted_items" in (stop.get("progress_metric") or {}).get("conversation", []),
        "adopted_count": (adopted.get("value") or {}).get("session_distinct"),
        # The scenario's required item count has no observation field yet (runner T1 unit, after C-17-1).
        "adopted_required": None,
    }


def select(signals):
    """demo-block-and-explanation.md 2-3. Exactly one template."""
    handoff = signals.get("handoff") or {}
    if signals["decision"] == "termination_failure":
        return "E6"
    if signals.get("global_revert"):
        return "E2"
    if signals.get("test_plateau_in_streak"):
        return "E3"
    if handoff.get("count") is not None and handoff["count"] >= signals["handoff_threshold"]:
        return "E4"
    if signals.get("adopted_metric_selected"):
        return "E5"
    if "oscillating" in (signals.get("consecutive_states") or []):
        return "E7"
    return "E1"


def explain(signals, role_labels=None):
    """Sentence plus the values that produced it; explain(record['signals'], record['role_labels']) rebuilds it."""
    template_id = select(signals)
    labels = role_labels or {}
    def role(value):
        return labels.get(value, value) if value is not None else None
    roles = list(dict.fromkeys(role(r) for r in signals.get("streak_roles") or [] if r is not None))
    handoff = signals.get("handoff") or {}
    pair = handoff.get("roles") or [None, None]
    revert = signals.get("global_revert") or {}
    states = signals.get("consecutive_states")
    tests = {"pass": signals.get("test_pass_count"), "total": signals.get("test_total_count")}
    values = {
        "E1": {"n": signals.get("consecutive_steps"), "roles": roles or None, **tests},
        "E2": {"path": ", ".join(revert["paths"]) if revert.get("paths") else None, "k": revert.get("revert_to_step"),
               "m": signals.get("steps_since_test_max"), **tests},
        "E3": {"a": signals.get("test_max_step"), "m": signals.get("steps_since_test_max"),
               "c": signals.get("file_state_changes_since_test_max"), **tests},
        "E4": {"role_a": role(pair[0]), "role_b": role(pair[1]), "h": handoff.get("count"),
               "status": signals.get("status")},
        "E5": {"n": signals.get("consecutive_steps"), "adopted": signals.get("adopted_count"),
               "required": signals.get("adopted_required"), "status": signals.get("status")},
        "E6": {"d": signals.get("declared_step"), "n": signals.get("consecutive_steps"),
               **({"status": signals.get("status")} if signals.get("task_kind") == "dialogue" else tests)},
        "E7": {"n": signals.get("consecutive_steps"),
               "o": states.count("oscillating") if isinstance(states, list) else None},
    }[template_id]
    template = E6_DIALOGUE if template_id == "E6" and signals.get("task_kind") == "dialogue" else TEMPLATES[template_id]
    text = template.format_map({k: render(v) for k, v in values.items()})
    return {"explanation_version": VERSION, "template_id": template_id, "text": text, "values": values,
            "missing_values": sorted(k for k, v in values.items() if v is None),
            "signals": signals, "role_labels": role_labels}


def render(value):
    if value is None:
        return UNMEASURED
    if isinstance(value, list):
        return "·".join(str(v) for v in value) if value else UNMEASURED
    return str(value)
