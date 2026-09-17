"""Predeclared criteria over S3-A categories. No new numeric signal or intervention."""
import copy
import hashlib
import json

VERSION = "deadlock-v0.1"
SPEC = {"criteria_version": VERSION, "progress_version": "progress-v1", "epsilon": 0,
        "k": 1, "consecutive_steps": 3, "grace_steps": 2, "missing_review_steps": 3}


def pin_criteria(version=VERSION):
    if version != VERSION:
        raise ValueError("Unsupported criteria version")
    parameters = copy.deepcopy(SPEC)
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"criteria_version": version, "criteria_parameters": parameters, "criteria_sha256": digest}


def evaluate_criteria(observations, pin):
    valid = pin_criteria()
    if any(pin.get(key) != value for key, value in valid.items()):
        return {"criteria_version": pin.get("criteria_version"), "decision": "unmeasured",
                "reason": "criteria not pinned, unsupported or snapshot mismatch"}
    streak = missing = 0
    declaration = None
    first_deadlock = first_termination = None
    decision, reason = "unmeasured", "no observations"
    states = []
    for expected_step, observation in enumerate(observations, 1):
        step = observation["step_id"]
        if step != expected_step:
            return {"criteria_version": VERSION, "decision": "unmeasured", "reason": "nonconsecutive step IDs"}
        progress = observation.get("progress") or {}
        state = progress.get("state", "unmeasured")
        context = observation.get("termination_context") or {}
        disposition = context.get("declaration", "unknown")
        if disposition == "declared":
            declared = context.get("declared_step")
            if declaration is None:
                declaration = declared
                streak = 0
            elif declaration != declared:
                disposition = "unknown"
        elif disposition == "none" and declaration is not None:
            disposition = "unknown"
        if (progress.get("version") != SPEC["progress_version"]
                or state not in ("progress", "oscillating", "stagnant", "unmeasured", "baseline")):
            state = "unmeasured"
        if state == "unmeasured" or disposition == "unknown":
            missing += 1
            streak = 0
            states = []
            decision, reason = "unmeasured", "observation or termination context missing"
            continue
        missing = 0
        if state not in ("stagnant", "oscillating") or (declaration is not None and step <= declaration):
            streak = 0
            states = []
            decision, reason = "continue", "progress, baseline or declaration step"
            continue
        streak += 1
        states.append(state)
        if declaration is not None and step - declaration <= SPEC["grace_steps"]:
            decision, reason = "continue", "post-declaration grace"
        elif streak >= SPEC["consecutive_steps"]:
            if declaration is None:
                decision, reason = "deadlock", "three consecutive stagnant/oscillating steps without declaration"
                if first_deadlock is None:
                    first_deadlock = step
            else:
                decision, reason = "termination_failure", "post-declaration nonprogress beyond grace"
                if first_termination is None:
                    first_termination = step
        else:
            decision, reason = "continue", "insufficient consecutive evidence"
    return {"criteria_version": VERSION, "criteria_sha256": valid["criteria_sha256"],
            "decision": decision, "reason": reason, "consecutive_steps": streak,
            "consecutive_states": states, "unmeasured_steps": missing,
            "needs_observation_review": missing >= SPEC["missing_review_steps"],
            "first_deadlock_step": first_deadlock, "first_termination_failure_step": first_termination}
