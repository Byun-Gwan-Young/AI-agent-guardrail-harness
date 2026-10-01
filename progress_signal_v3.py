"""progress-v3 (deadlock-v0.3, DM-10/DM-22): progress-v2 movement plus T1 dialogue and T3 artifact signals.

progress-v1/v2 stay frozen and are only called from here. Every parameter (K, H, the T1 metric names and the
T3 global-revert switch) comes from the pinned criteria parameters (guardrail-deadlock-v0.3-kmu.yaml).
Design: docs/design/demo-deadlock-v0.3.md.
"""
import copy
import hashlib
import json

from progress_signal import histories_by_agent
from progress_signal_v1 import calculate_progress as calculate_v1

VERSION = "progress-v3"
# T1 metric -> conversation field (demo-deadlock-v0.3.md 2-1, demo-runner-extension.md 4).
T1_FIELDS = {"status_advance": "status", "adopted_items": "adopted_items", "new_issue_ids": "open_issue_ids"}
RECURRENT = ("oscillation", "reopen", "revert")


def calculate_progress(history, current, parameters):
    agent_id = current.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return {"version": VERSION, "state": "unmeasured", "reason": "agent_id missing",
                "comparison_step_id": None, "history_step_ids": []}
    selected = histories_by_agent(history).get(agent_id, [])
    names = current["progress_metric"]["conversation"]
    t1 = [m for m in names if m in parameters["t1_metrics"]]
    if any(m not in T1_FIELDS for m in t1):
        return {"version": VERSION, "state": "unmeasured", "reason": "unsupported T1 metric",
                "comparison_step_id": None, "history_step_ids": []}
    result = {"version": VERSION, "comparison_step_id": selected[-1]["step_id"] if selected else None,
              "history_step_ids": [o["step_id"] for o in selected]}
    if selected and (selected[-1]["progress_source"] != current["progress_source"]
                     or selected[-1]["progress_metric"] != current["progress_metric"]):
        # Checked here because the T1 names are hidden from progress-v1 below.
        return {**result, "state": "unmeasured", "reason": "metric selection changed", "metrics": {}, "events": [],
                "flags": {"oscillation": [], "reopen": [], "revert": [], "test_plateau": False},
                "coverage_complete": False}
    base = calculate_v1([legacy_view(o, t1) for o in selected], legacy_view(current, t1))
    result = {**base, **result}
    metrics, events, flags = dict(base["metrics"]), list(base["events"]), copy.deepcopy(base["flags"])
    if current["progress_source"] in ("conversation", "both"):
        for name in t1:
            metric, found = dialogue_metric(name, history, current)
            metrics["conversation." + name] = metric
            for item, kind in found:
                events.append({"metric": "conversation." + name, "item": item, "kind": kind})
                if kind in flags:
                    flags[kind].append(item)
    missing = [name for name, metric in metrics.items() if metric["status"] == "unmeasured"]
    conv = current.get("conversation") or {}
    if not selected:
        # Same as progress-v2: a role's first observation is its baseline.
        moved = base["state"] == "baseline" or any(conv.get(T1_FIELDS[m]) is not None for m in t1)
        state = "baseline" if moved else "unmeasured"
    elif events:
        all_recurrent = all(e["kind"] in RECURRENT for e in events)
        state = ("unmeasured" if missing else "oscillating") if all_recurrent else "progress"
    else:
        state = "unmeasured" if missing else "stagnant"
    t3 = artifact_signal(history, current, parameters)
    if t3 is not None:
        kinds = {e["metric"] for e in events if e["kind"] not in RECURRENT}
        t3["only_file_change_progress"] = state == "progress" and kinds == {"artifact.files_changed"}
        if t3["only_file_change_progress"]:
            if parameters["t3_global_revert"] and t3["global_revert"]:
                t3["applied"], state = "global_revert", "unmeasured" if missing else "oscillating"
            elif t3["test_plateau"]:
                t3["applied"], state = "test_plateau", "unmeasured" if missing else "stagnant"
    return {**result, "state": state, "metrics": metrics, "events": events, "flags": flags,
            "coverage_complete": not missing,
            "conversation_moved": any(e["metric"].startswith("conversation.") for e in events),
            "artifact_moved": any(e["metric"].startswith("artifact.") for e in events),
            "t3": t3, "handoff": handoff_exchange(history, current, parameters["handoff_record_threshold"])}


def legacy_view(observation, t1):
    """The observation as progress-v1 reads it: T1 metric names hidden, everything else untouched."""
    metric = observation["progress_metric"]
    view = {**metric, "conversation": [m for m in metric["conversation"] if m not in t1]}
    return {**observation, "progress_metric": view}


def dialogue_metric(name, history, current):
    """T1 signals compare with the whole session (all roles), unlike the per-role progress-v2 metrics."""
    conv = current.get("conversation") or {}
    kind = conv.get("source_kind")
    earlier = [h.get("conversation") or {} for h in history]
    earlier = [c for c in earlier if c.get("source_kind") == kind]
    now = conv.get(T1_FIELDS[name])
    if name == "status_advance":
        order = conv.get("status_values")
        if not (isinstance(order, list) and order and all(isinstance(s, str) for s in order)
                and len(set(order)) == len(order)):
            return unmeasured("status_values missing or invalid"), []
        if now not in order:
            # Includes the terminal status (e.g. escalated), which is outside the ordered list.
            return unmeasured("status missing or outside status_values"), []
        before = [c["status"] for c in earlier if c.get("status_values") == order and c.get("status") in order]
        if not before:
            return unmeasured("no earlier status in the session"), []
        index, best, previous = order.index(now), max(order.index(s) for s in before), order.index(before[-1])
        value = {"status": now, "index": index, "session_max_index": best, "previous_status": before[-1]}
        if index > best:
            return measured(value), [(now, "new")]
        if index < previous:
            return measured(value), [(now, "oscillation")]
        return measured(value), []
    if now is None or not isinstance(now, list) or any(not isinstance(v, str) for v in now):
        return unmeasured("observation missing or invalid"), []
    before = [c[T1_FIELDS[name]] for c in earlier if isinstance(c.get(T1_FIELDS[name]), list)]
    if not before:
        return unmeasured("no earlier value in the session"), []
    seen = set().union(*map(set, before))
    novel = sorted(set(now) - seen)
    # Closing, reopening or reordering earlier IDs is not movement here (DM-22).
    value = {"first_seen": novel, "session_distinct": len(seen | set(now)), "current_count": len(set(now))}
    return measured(value), [(item, "new") for item in novel]


def measured(value):
    return {"value": value, "status": "measured"}


def unmeasured(reason):
    return {"value": None, "status": "unmeasured", "reason": reason}


def combined_state(observation, scope):
    artifact = observation.get("artifact") or {}
    if artifact.get("file_hashes") is None or artifact.get("files_scope_id") != scope:
        return None
    encoded = json.dumps(artifact["file_hashes"], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def artifact_signal(history, current, parameters):
    """T3 values: global revert (a) and pass-count plateau (b). Applied by the caller only to file-only progress."""
    if current["progress_source"] not in ("artifact", "both") or "files_changed" not in current["progress_metric"]["artifact"]:
        return None
    artifact = current.get("artifact") or {}
    scope = artifact.get("files_scope_id")
    sequence = history + [current]
    states = [combined_state(o, scope) for o in sequence]
    now = states[-1]
    previous = states[-2] if history else None
    first_seen = {}
    for observation, state in zip(history, states):
        if state is not None:
            first_seen.setdefault(state, observation["step_id"])
    changed = []
    if now is not None and previous is not None:
        before = (history[-1].get("artifact") or {})["file_hashes"]
        changed = [p for p in sorted(set(artifact["file_hashes"]) | set(before))
                   if artifact["file_hashes"].get(p) != before.get(p)]
    revert = now is not None and previous is not None and now != previous and now in first_seen
    best = best_step = None
    if artifact.get("test_pass_count") is not None:
        for observation in sequence:
            other = observation.get("artifact") or {}
            if (other.get("test_pass_count") is not None and other.get("test_suite_id") == artifact.get("test_suite_id")
                    and other.get("test_total_count") == artifact.get("test_total_count")
                    and (best is None or other["test_pass_count"] > best)):
                best, best_step = other["test_pass_count"], observation["step_id"]
    since = current["step_id"] - best_step if best_step is not None else None
    changes = unknown = None
    if best_step is not None:
        changes = unknown = 0
        for index, observation in enumerate(sequence[1:], 1):
            if observation["step_id"] <= best_step:
                continue
            if states[index] is None or states[index - 1] is None:
                unknown += 1
            elif states[index] != states[index - 1]:
                changes += 1
    return {"global_state_sha256": now, "previous_global_step": history[-1]["step_id"] if history else None,
            "changed_paths": changed, "global_revert": revert, "revert_to_step": first_seen.get(now) if revert else None,
            "test_pass_count": artifact.get("test_pass_count"), "test_total_count": artifact.get("test_total_count"),
            "test_max": best, "test_max_step": best_step, "steps_since_test_max": since,
            "plateau_steps": parameters["plateau_steps"],
            "test_plateau": None if since is None else since > parameters["plateau_steps"],
            "file_state_changes_since_test_max": changes, "file_state_unknown_steps_since_test_max": unknown,
            "only_file_change_progress": False, "applied": None}


def handoff_exchange(history, current, threshold):
    """Recorded only (DM-22): consecutive passes between the same two roles, A->B->A->B = 3."""
    if "handoff_to" not in (current.get("conversation") or {}):
        return None
    passes = []
    for observation in reversed(history + [current]):
        giver, receiver = observation.get("agent_id"), (observation.get("conversation") or {}).get("handoff_to")
        if not (isinstance(giver, str) and isinstance(receiver, str) and receiver and giver != receiver):
            break
        if passes and (receiver, giver) != passes[-1][1:]:
            break
        passes.append((observation["step_id"], giver, receiver))
    if not passes:
        return {"roles": None, "count": 0, "first_step": None, "threshold": threshold, "at_or_above_threshold": False}
    first = passes[-1]
    return {"roles": [first[1], first[2]], "count": len(passes), "first_step": first[0],
            "threshold": threshold, "at_or_above_threshold": len(passes) >= threshold}
