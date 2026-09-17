"""Version dispatch; the original progress-v1 implementation remains frozen."""
from progress_signal_v1 import VERSION, normalized, comparable_tests
from progress_signal_v1 import calculate_progress as calculate_v1


def calculate_progress(history, current, *, version=VERSION):
    if version == "progress-v1":
        return calculate_v1(history, current)
    if version == "progress-v2":
        agent_id = current.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            return {"version": version, "state": "unmeasured", "reason": "agent_id missing",
                    "comparison_step_id": None, "history_step_ids": []}
        # References to the persisted global sequence; include missing observations.
        # This derived index is rebuilt after restart, never persisted separately.
        by_agent = histories_by_agent(history)
        selected = by_agent.get(agent_id, [])
        result = calculate_v1(selected, current)
        return {**result, "version": version,
                "comparison_step_id": selected[-1]["step_id"] if selected else None,
                "history_step_ids": [o["step_id"] for o in selected]}
    return {"version": version, "state": "unmeasured", "reason": "unsupported progress version"}


def histories_by_agent(history):
    by_agent = {}
    for observation in history:
        agent_id = observation.get("agent_id")
        if isinstance(agent_id, str) and agent_id:
            by_agent.setdefault(agent_id, []).append(observation)
    return by_agent
