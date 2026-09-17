"""Version dispatch; the original progress-v1 implementation remains frozen."""
from progress_signal_v1 import VERSION, normalized, comparable_tests
from progress_signal_v1 import calculate_progress as calculate_v1


def calculate_progress(history, current, *, version=VERSION):
    if version == "progress-v1":
        return calculate_v1(history, current)
    return {"version": version, "state": "unmeasured", "reason": "unsupported progress version"}
