"""deadlock-v0.3 (DM-10, DM-22): the deadlock-v0.2 streak rule over progress-v3 states.

deadlock-v0.2 stays frozen; this is its loop with every number read from the pinned parameters. The
parameters come from the proxy configuration (guardrail-deadlock-v0.3-kmu.yaml); no default lives here.
"""
import copy
import hashlib
import json

from explain_v1 import STOP_DECISIONS, VERSION as EXPLAIN_VERSION, explain, signals_from

VERSION = "deadlock-v0.3"
# Identifiers that define this version. Tunable numbers are only type- and range-checked.
FIXED = {"criteria_version": VERSION, "progress_version": "progress-v3", "explanation_version": EXPLAIN_VERSION,
         "comparison_scope": "same_agent_id",
         "consecutive_steps_unit": "global_step", "grace_steps_unit": "global_step",
         "missing_review_steps_unit": "global_step", "plateau_steps_unit": "global_step"}
MINIMUM = {"consecutive_steps": 1, "grace_steps": 0, "missing_review_steps": 1, "plateau_steps": 1,
           "handoff_record_threshold": 2}
T1_METRICS = ("status_advance", "adopted_items", "new_issue_ids")
KEYS = set(FIXED) | set(MINIMUM) | {"t3_global_revert", "t1_metrics"}


def validate_parameters(parameters):
    if not isinstance(parameters, dict):
        raise ValueError("deadlock-v0.3 requires criteria_parameters in the configuration")
    if set(parameters) != KEYS:
        raise ValueError("criteria_parameters keys must be exactly: " + ", ".join(sorted(KEYS)))
    for key, value in FIXED.items():
        if parameters[key] != value:
            raise ValueError(f"criteria_parameters.{key} must be {value}")
    for key, minimum in MINIMUM.items():
        if type(parameters[key]) is not int or parameters[key] < minimum:
            raise ValueError(f"criteria_parameters.{key} must be an integer >= {minimum}")
    if type(parameters["t3_global_revert"]) is not bool:
        raise ValueError("criteria_parameters.t3_global_revert must be true or false")
    metrics = parameters["t1_metrics"]
    if (not isinstance(metrics, list) or any(m not in T1_METRICS for m in metrics)
            or len(set(metrics)) != len(metrics)):
        raise ValueError("criteria_parameters.t1_metrics must be distinct names from " + ", ".join(T1_METRICS))


def pin_criteria(version=VERSION, parameters=None):
    if version != VERSION:
        raise ValueError("Unsupported criteria version")
    validate_parameters(parameters)
    parameters = copy.deepcopy(parameters)
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"criteria_version": version, "criteria_parameters": parameters, "criteria_sha256": digest}


def evaluate_criteria(observations, pin, role_labels=None):
    """role_labels (DM-26) changes only the explanation sentence, never the decision."""
    try:
        valid = pin_criteria(pin.get("criteria_version"), pin.get("criteria_parameters"))
    except (ValueError, TypeError):
        valid = None
    if valid is None or any(pin.get(key) != value for key, value in valid.items()):
        return {"criteria_version": pin.get("criteria_version"), "decision": "unmeasured",
                "reason": "criteria not pinned, unsupported or snapshot mismatch"}
    spec = valid["criteria_parameters"]
    streak = missing = 0
    declaration = None
    first_deadlock = first_termination = None
    decision, reason = "unmeasured", "no observations"
    states, streak_steps = [], []
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
        if (progress.get("version") != spec["progress_version"]
                or state not in ("progress", "oscillating", "stagnant", "unmeasured", "baseline")):
            state = "unmeasured"
        if state == "unmeasured" or disposition == "unknown":
            missing += 1
            streak = 0
            states, streak_steps = [], []
            decision, reason = "unmeasured", "observation or termination context missing"
            continue
        missing = 0
        if state not in ("stagnant", "oscillating") or (declaration is not None and step <= declaration):
            streak = 0
            states, streak_steps = [], []
            decision, reason = "continue", "progress, baseline or declaration step"
            continue
        streak += 1
        states.append(state)
        streak_steps.append(step)
        if declaration is not None and step - declaration <= spec["grace_steps"]:
            decision, reason = "continue", "post-declaration grace"
        elif streak >= spec["consecutive_steps"]:
            if declaration is None:
                decision, reason = "deadlock", "consecutive stagnant/oscillating steps without declaration"
                if first_deadlock is None:
                    first_deadlock = step
            else:
                decision, reason = "termination_failure", "post-declaration nonprogress beyond grace"
                if first_termination is None:
                    first_termination = step
        else:
            decision, reason = "continue", "insufficient consecutive evidence"
    result = {"criteria_version": VERSION, "criteria_sha256": valid["criteria_sha256"],
              "decision": decision, "reason": reason, "consecutive_steps": streak,
              "consecutive_states": states, "consecutive_step_ids": streak_steps, "unmeasured_steps": missing,
              "needs_observation_review": missing >= spec["missing_review_steps"],
              "first_deadlock_step": first_deadlock, "first_termination_failure_step": first_termination,
              "declared_step": declaration}
    if decision in STOP_DECISIONS:
        # DM-9: every STOP record carries its sentence and the values behind it. A failure here must not
        # turn the decision itself into unmeasured.
        try:
            result["explanation"] = explain(signals_from(observations, result, spec), role_labels)
        except Exception as error:
            result["explanation"] = {"explanation_version": spec["explanation_version"], "status": "failed",
                                     "reason": type(error).__name__}
    return result
