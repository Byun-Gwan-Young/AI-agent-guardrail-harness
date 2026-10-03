"""explain-v1 (DM-9): one Korean STOP-reason sentence built only from judgement signal values.

No LLM call and no model text (narrative, reasoning). A value that was not measured is written as UNMEASURED,
never guessed. Templates and their selection order are frozen with deadlock-v0.3 (criteria parameter
explanation_version, record docs/criteria/explain-v1.json). Design: docs/design/demo-block-and-explanation.md 2,
plus DM-27 (E1-T1 for a session without test observations), DM-26 (optional role display names) and DM-31
(E1 and E1-T1 name only the signals of the metrics the scenario selected). The session registration (DM-35) supplies
role and status display names, the E5 required count (DM-29) and the selected metrics; without it, IDs and
"(측정 안 됨)" remain. DM-36: a particle after a name slot is written in the template as "{slot:받침형/모음형}" and
attached to the name by the DM-31 final-consonant rule. DM-42: after a quoted status name a particle or '입니다' is
attached with no space, and a path slot reads "{path} 파일이". DM-43: E4 is chosen only when both role names and the
round-trip count are known; otherwise selection moves on to the next template. DM-49: a particle or '입니다' after a
number is attached too ("step 1의", "12/16입니다"); number units keep their space ("3 step", "5 번"), and a particle
that follows a final consonant is chosen by the number read aloud. DM-52 ⑥: a particle after the unit word "step" is
attached as well ("6 step은"), "step" counting as a word with a final consonant (스텝). DM-50: each template has required values (without
one, selection moves on to the next template) and auxiliary values (without one, its phrase is left out: the
REDUCED sentence). "(측정 안 됨)" is written only in the last fallback E1.
"""
VERSION = "explain-v1"
UNMEASURED = "(측정 안 됨)"
TEMPLATES = {
    # {signals} is the selected metrics' phrases joined with "·" plus the subject particle (DM-31).
    "E1": "최근 {n} step 동안 {roles} 모두 {signals:이/가} 없습니다. 통과 테스트 {pass}/{total}.",
    # DM-27: E1 for a session with no test observation (T1 dialogue task) reports the dialogue signals instead.
    "E1-T1": "최근 {n} step 동안 {roles} 모두 {signals:이/가} 없습니다. 처리 상태 '{status}'.",
    # DM-49: what follows a number is attached to it ("step 1의", "12/16입니다", "12/16에서", "step 4에").
    "E2": "{path} 파일이 step {k}의 내용으로 되돌아갔고, 통과 테스트는 {m} step 동안 {pass}/{total}입니다.",
    "E3": "step {a} 이후 {m} step 동안 파일이 {c} 번 바뀌었지만 통과 테스트는 {pass}/{total}에서 늘지 않았습니다.",
    # DM-36: the particles after the two role names follow the names ("환불 담당과 배송 담당이").
    # DM-42: what follows a quoted status name is attached to it ("'접수'에서", "'분류'입니다").
    "E4": "{role_a:과/와} {role_b:이/가} 문의를 서로 {h} 번 넘겼고 처리 상태는 '{status}'에서 바뀌지 않았습니다.",
    "E5": "최근 {n} step 동안 채택 항목이 {adopted}/{required}에서 늘지 않았고 처리 상태는 '{status}'입니다.",
    "E6": "step {d}에 완료가 선언됐지만 이후 {n} step 동안 진전이 없습니다. 통과 테스트 {pass}/{total}.",
    # DM-52 ⑥: a particle after the unit word "step" is attached too; "step" has a final consonant (스텝), so 은.
    "E7": "최근 {n} step 중 {o} step은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다.",
}
# E6 for a dialogue (T1) task: the second sentence reports the status instead of tests.
E6_DIALOGUE = "step {d}에 완료가 선언됐지만 이후 {n} step 동안 진전이 없습니다. 처리 상태는 '{status}'입니다."
# DM-50: a template is chosen only with all of its required values. Every other value of a template is auxiliary.
# E1 is the last fallback and has none: it alone writes "(측정 안 됨)".
FALLBACK = "E1"
REQUIRED_VALUES = {"E1": (), "E1-T1": ("n", "roles", "signals"), "E2": ("path", "k"), "E3": ("a", "m", "c"),
                   "E4": ("role_a", "role_b", "h"), "E5": ("n", "adopted", "required"), "E6": ("d", "n"),
                   "E7": ("n", "o")}
# DM-50: the sentence without the auxiliary phrase, used when any auxiliary value is missing (both E6 forms).
REDUCED = {
    "E1-T1": "최근 {n} step 동안 {roles} 모두 {signals:이/가} 없습니다.",
    "E2": "{path} 파일이 step {k}의 내용으로 되돌아갔습니다.",
    "E3": "step {a} 이후 {m} step 동안 파일이 {c} 번 바뀌었지만 통과 테스트는 늘지 않았습니다.",
    "E4": "{role_a:과/와} {role_b:이/가} 문의를 서로 {h} 번 넘겼습니다.",
    "E5": "최근 {n} step 동안 채택 항목이 {adopted}/{required}에서 늘지 않았습니다.",
    "E6": "step {d}에 완료가 선언됐지만 이후 {n} step 동안 진전이 없습니다.",
}
STOP_DECISIONS = ("deadlock", "termination_failure")
# DM-31, DM-36: particle pairs a template may attach to a slot, as "after a final consonant/otherwise".
PARTICLES = ("과/와", "이/가", "은/는", "을/를")
# DM-49: the last digit of a number, read aloud, decides the particle.
DIGITS = "0123456789"
DIGITS_WITH_FINAL_CONSONANT = "013678"
# DM-31: the signal each selected progress metric reports, in sentence order. An unselected metric is never named.
SIGNAL_PHRASES = (("artifact.files_changed", "산출물 변경"), ("artifact.test_pass_count", "테스트 증가"),
                  ("artifact.build_status", "빌드 상태 변화"), ("conversation.status_advance", "처리 상태 변화"),
                  ("conversation.adopted_items", "채택 항목"), ("conversation.new_issue_ids", "새 쟁점"),
                  ("conversation.open_issues_count", "새 쟁점"), ("conversation.proposal_value_delta", "제안 값 변화"),
                  ("conversation.new_info_ratio", "새 정보"))
# Records made before DM-31 carry no selection; they rebuild with the sentence they were made with.
UNRECORDED_SELECTION = {"E1": ["산출물 변경", "테스트 증가", "새 쟁점"], "E1-T1": ["처리 상태 변화", "채택 항목", "새 쟁점"]}
# demo-block-and-explanation.md 2-3 plus DM-27: the first template whose condition holds and, DM-50, whose required
# values are all there. Exactly one.
SELECTION_ORDER = (("E6", "termination_failure"), ("E2", "global_revert_in_streak"),
                   ("E3", "test_plateau_in_streak"), ("E4", "handoff_pair_and_count_at_or_above_threshold"),
                   ("E5", "adopted_items_selected"), ("E7", "oscillating_in_streak"),
                   ("E1-T1", "no_test_observation_in_session"), ("E1", "otherwise"))


def selected_metrics(source, metric):
    """The metrics a judgement uses: conversation names only for a conversation source, artifact names likewise."""
    return (["conversation." + m for m in metric.get("conversation", []) if source in ("conversation", "both")]
            + ["artifact." + m for m in metric.get("artifact", []) if source in ("artifact", "both")])


def registered_labels(registration):
    """(role labels, status labels) from a session registration, or (None, None) without one."""
    if not registration:
        return None, None
    statuses = (registration.get("status_values") or []) + (registration.get("terminal_statuses") or [])
    return registration.get("role_labels") or None, {s["id"]: s["label"] for s in statuses} or None


def signals_from(observations, criteria, parameters, registration=None):
    """Signal values behind one STOP record, read from progress-v3 records, the criteria result and the
    session registration only."""
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
    # The observation API keeps a registered session's observations on the registered selection.
    chosen = registration if registration else stop
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
        "selected_metrics": selected_metrics(chosen.get("progress_source"), chosen.get("progress_metric") or {}),
        # DM-29: the scenario's required item count, registered at session start; unmeasured without it.
        "adopted_required": (registration or {}).get("required_adopted_items"),
    }


def condition_holds(name, signals):
    handoff = signals.get("handoff") or {}
    return {
        "termination_failure": lambda: signals["decision"] == "termination_failure",
        "global_revert_in_streak": lambda: bool(signals.get("global_revert")),
        "test_plateau_in_streak": lambda: bool(signals.get("test_plateau_in_streak")),
        # DM-43: both role names and the count must be there; E4 never writes a role it does not know.
        "handoff_pair_and_count_at_or_above_threshold": lambda: (
            isinstance(handoff.get("roles"), list) and len(handoff["roles"]) == 2
            and all(r is not None for r in handoff["roles"])
            and handoff.get("count") is not None and handoff["count"] >= signals["handoff_threshold"]),
        "adopted_items_selected": lambda: bool(signals.get("adopted_metric_selected")),
        "oscillating_in_streak": lambda: "oscillating" in (signals.get("consecutive_states") or []),
        # False only when it was checked: records made before DM-27 have no such key and keep E1.
        "no_test_observation_in_session": lambda: signals.get("test_observed_in_session") is False,
        "otherwise": lambda: True,
    }[name]()


def choose(signals, role_labels=None, status_labels=None):
    """(template ID, its values, the earlier templates whose condition held but a required value was missing).

    DM-50: the first template in SELECTION_ORDER whose condition holds and whose required values are all there.
    A display name never makes a value missing, so the choice depends on the signal values only."""
    skipped = []
    for template_id, name in SELECTION_ORDER:
        if not condition_holds(name, signals):
            continue
        values = template_values(template_id, signals, role_labels, status_labels)
        missing = [k for k in REQUIRED_VALUES[template_id] if values[k] is None]
        if not missing:
            return template_id, values, skipped
        skipped.append({"template_id": template_id, "missing_required": missing})
    raise AssertionError("the fallback E1 has no condition and no required value")


def select(signals):
    return choose(signals)[0]


def checked_labels(labels):
    """DM-26, DM-35: an optional ID -> display name map (session registration). An ID without one stays as is."""
    if labels is None:
        return {}
    if not isinstance(labels, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                                           for k, v in labels.items()):
        raise ValueError("labels must map IDs to non-empty display names")
    return labels


def explain(signals, role_labels=None, status_labels=None):
    """Sentence plus the values that produced it.

    explain(record['signals'], record['role_labels'], record['status_labels']) rebuilds it.
    """
    template_id, values, skipped = choose(signals, role_labels, status_labels)
    # DM-50: a missing auxiliary value leaves its phrase out; only the fallback E1 writes "(측정 안 됨)".
    reduced = template_id != FALLBACK and any(values[k] is None for k in values
                                              if k not in REQUIRED_VALUES[template_id])
    if reduced:
        template = REDUCED[template_id]
    else:
        template = (E6_DIALOGUE if template_id == "E6" and signals.get("task_kind") == "dialogue"
                    else TEMPLATES[template_id])
    text = template.format_map({k: Slot(render(v)) for k, v in values.items()})
    return {"explanation_version": VERSION, "template_id": template_id, "text": text, "values": values,
            "missing_values": sorted(k for k, v in values.items() if v is None),
            "form": "fallback" if template_id == FALLBACK else "reduced" if reduced else "full",
            "skipped_templates": skipped,
            "signals": signals, "role_labels": role_labels, "status_labels": status_labels}


def template_values(template_id, signals, role_labels=None, status_labels=None):
    """The values a template writes, display names applied; None where a value was not measured."""
    labels, status_names = checked_labels(role_labels), checked_labels(status_labels)
    def role(value):
        return labels.get(value, value) if value is not None else None
    raw_status = signals.get("status")
    status = status_names.get(raw_status, raw_status) if raw_status is not None else None
    roles = list(dict.fromkeys(role(r) for r in signals.get("streak_roles") or [] if r is not None))
    handoff = signals.get("handoff") or {}
    pair = handoff.get("roles") or [None, None]
    revert = signals.get("global_revert") or {}
    states = signals.get("consecutive_states")
    tests = {"pass": signals.get("test_pass_count"), "total": signals.get("test_total_count")}
    absent = signal_phrases(signals.get("selected_metrics"), template_id)
    return {
        "E1": {"n": signals.get("consecutive_steps"), "roles": roles or None, "signals": absent, **tests},
        "E1-T1": {"n": signals.get("consecutive_steps"), "roles": roles or None, "signals": absent,
                  "status": status},
        "E2": {"path": ", ".join(revert["paths"]) if revert.get("paths") else None, "k": revert.get("revert_to_step"),
               "m": signals.get("steps_since_test_max"), **tests},
        "E3": {"a": signals.get("test_max_step"), "m": signals.get("steps_since_test_max"),
               "c": signals.get("file_state_changes_since_test_max"), **tests},
        "E4": {"role_a": role(pair[0]), "role_b": role(pair[1]), "h": handoff.get("count"), "status": status},
        "E5": {"n": signals.get("consecutive_steps"), "adopted": signals.get("adopted_count"),
               "required": signals.get("adopted_required"), "status": status},
        "E6": {"d": signals.get("declared_step"), "n": signals.get("consecutive_steps"),
               **({"status": status} if signals.get("task_kind") == "dialogue" else tests)},
        "E7": {"n": signals.get("consecutive_steps"),
               "o": states.count("oscillating") if isinstance(states, list) else None},
    }[template_id]


def signal_phrases(selected, template_id):
    if template_id not in UNRECORDED_SELECTION:
        return None
    if selected is None:
        return list(UNRECORDED_SELECTION[template_id])
    chosen = set(selected)
    phrases = list(dict.fromkeys(phrase for name, phrase in SIGNAL_PHRASES if name in chosen))
    return phrases or None


def has_final_consonant(text):
    """DM-31: the last character is a Hangul syllable with a final consonant. DM-49: a last digit is read aloud, and
    0, 1, 3, 6, 7, 8 (영 일 삼 육 칠 팔) end in one. Anything else (a role ID such as "refund") counts as none."""
    last = text[-1] if text else ""
    if last in DIGITS:
        return last in DIGITS_WITH_FINAL_CONSONANT
    return "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0


class Slot(str):
    """A rendered value. A template spec "{slot:과/와}" attaches the particle to it with no space (DM-31, DM-36);
    "(측정 안 됨)" takes none, as DM-31 wrote it."""

    def __format__(self, spec):
        if not spec:
            return str(self)
        if spec not in PARTICLES:
            raise ValueError("unknown particle pair: " + spec)
        if self == UNMEASURED:
            return str(self)
        after_final, otherwise = spec.split("/")
        return str(self) + (after_final if has_final_consonant(self) else otherwise)


def render(value):
    if value is None:
        return UNMEASURED
    if isinstance(value, list):
        return "·".join(str(v) for v in value) if value else UNMEASURED
    return str(value)
