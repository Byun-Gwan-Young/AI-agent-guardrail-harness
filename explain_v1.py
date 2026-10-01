"""explain-v1 (DM-9): one Korean STOP-reason sentence built only from judgement signal values.

No LLM call and no model text (narrative, reasoning). A value that was not measured is written as UNMEASURED,
never guessed. Templates and their selection order are frozen with deadlock-v0.3 (criteria parameter
explanation_version, record docs/criteria/explain-v1.json). Design: docs/design/demo-block-and-explanation.md 2,
plus DM-27 (E1-T1 for a session without test observations), DM-26 (optional role display names) and DM-31
(E1 and E1-T1 name only the signals of the metrics the scenario selected).
"""
VERSION = "explain-v1"
UNMEASURED = "(측정 안 됨)"
TEMPLATES = {
    # {signals} is the selected metrics' phrases joined with "·" plus the subject particle (DM-31).
    "E1": "최근 {n} step 동안 {roles} 모두 {signals} 없습니다. 통과 테스트 {pass}/{total}.",
    # DM-27: E1 for a session with no test observation (T1 dialogue task) reports the dialogue signals instead.
    "E1-T1": "최근 {n} step 동안 {roles} 모두 {signals} 없습니다. 처리 상태 '{status}'.",
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
# DM-31: the signal each selected progress metric reports, in sentence order. An unselected metric is never named.
SIGNAL_PHRASES = (("artifact.files_changed", "산출물 변경"), ("artifact.test_pass_count", "테스트 증가"),
                  ("artifact.build_status", "빌드 상태 변화"), ("conversation.status_advance", "처리 상태 변화"),
                  ("conversation.adopted_items", "채택 항목"), ("conversation.new_issue_ids", "새 쟁점"),
                  ("conversation.open_issues_count", "새 쟁점"), ("conversation.proposal_value_delta", "제안 값 변화"),
                  ("conversation.new_info_ratio", "새 정보"))
# Records made before DM-31 carry no selection; they rebuild with the sentence they were made with.
UNRECORDED_SELECTION = {"E1": ["산출물 변경", "테스트 증가", "새 쟁점"], "E1-T1": ["처리 상태 변화", "채택 항목", "새 쟁점"]}
# demo-block-and-explanation.md 2-3 plus DM-27: the first template whose condition holds. Exactly one.
SELECTION_ORDER = (("E6", "termination_failure"), ("E2", "global_revert_in_streak"),
                   ("E3", "test_plateau_in_streak"), ("E4", "handoff_at_or_above_threshold"),
                   ("E5", "adopted_items_selected"), ("E7", "oscillating_in_streak"),
                   ("E1-T1", "no_test_observation_in_session"), ("E1", "otherwise"))


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
    metric = stop.get("progress_metric") or {}
    source = stop.get("progress_source")
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
        "test_observed_in_session": any((o.get("artifact") or {}).get("test_pass_count") is not None
                                        for o in observations),
        # DM-31: the metrics the judgement used, so the sentence names only those.
        "selected_metrics": ["conversation." + m for m in metric.get("conversation", [])
                             if source in ("conversation", "both")]
                            + ["artifact." + m for m in metric.get("artifact", []) if source in ("artifact", "both")],
        # DM-29: the required item count and status display names come with the runner T1 unit.
        "adopted_required": None,
    }


def condition_holds(name, signals):
    handoff = signals.get("handoff") or {}
    return {
        "termination_failure": lambda: signals["decision"] == "termination_failure",
        "global_revert_in_streak": lambda: bool(signals.get("global_revert")),
        "test_plateau_in_streak": lambda: bool(signals.get("test_plateau_in_streak")),
        "handoff_at_or_above_threshold": lambda: (handoff.get("count") is not None
                                                  and handoff["count"] >= signals["handoff_threshold"]),
        "adopted_items_selected": lambda: bool(signals.get("adopted_metric_selected")),
        "oscillating_in_streak": lambda: "oscillating" in (signals.get("consecutive_states") or []),
        # False only when it was checked: records made before DM-27 have no such key and keep E1.
        "no_test_observation_in_session": lambda: signals.get("test_observed_in_session") is False,
        "otherwise": lambda: True,
    }[name]()


def select(signals):
    return next(template_id for template_id, name in SELECTION_ORDER if condition_holds(name, signals))


def checked_labels(role_labels):
    """DM-26: an optional role ID -> display name map (registered by the runner). A role without one keeps its ID."""
    if role_labels is None:
        return {}
    if not isinstance(role_labels, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                                                for k, v in role_labels.items()):
        raise ValueError("role_labels must map role IDs to non-empty display names")
    return role_labels


def explain(signals, role_labels=None):
    """Sentence plus the values that produced it; explain(record['signals'], record['role_labels']) rebuilds it."""
    template_id = select(signals)
    labels = checked_labels(role_labels)
    def role(value):
        return labels.get(value, value) if value is not None else None
    roles = list(dict.fromkeys(role(r) for r in signals.get("streak_roles") or [] if r is not None))
    handoff = signals.get("handoff") or {}
    pair = handoff.get("roles") or [None, None]
    revert = signals.get("global_revert") or {}
    states = signals.get("consecutive_states")
    tests = {"pass": signals.get("test_pass_count"), "total": signals.get("test_total_count")}
    absent = signal_phrases(signals.get("selected_metrics"), template_id)
    values = {
        "E1": {"n": signals.get("consecutive_steps"), "roles": roles or None, "signals": absent, **tests},
        "E1-T1": {"n": signals.get("consecutive_steps"), "roles": roles or None, "signals": absent,
                  "status": signals.get("status")},
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
    text = template.format_map({k: render_subject(v) if k == "signals" else render(v) for k, v in values.items()})
    return {"explanation_version": VERSION, "template_id": template_id, "text": text, "values": values,
            "missing_values": sorted(k for k, v in values.items() if v is None),
            "signals": signals, "role_labels": role_labels}


def signal_phrases(selected, template_id):
    if template_id not in UNRECORDED_SELECTION:
        return None
    if selected is None:
        return list(UNRECORDED_SELECTION[template_id])
    chosen = set(selected)
    phrases = list(dict.fromkeys(phrase for name, phrase in SIGNAL_PHRASES if name in chosen))
    return phrases or None


def render_subject(phrases):
    """Joined phrases with the Korean subject particle of the last syllable (이 after a final consonant, else 가)."""
    if not phrases:
        return UNMEASURED
    text = "·".join(phrases)
    last = text[-1]
    final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return text + ("이" if final else "가")


def render(value):
    if value is None:
        return UNMEASURED
    if isinstance(value, list):
        return "·".join(str(v) for v in value) if value else UNMEASURED
    return str(value)
