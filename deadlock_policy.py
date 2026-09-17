"""Version dispatch over pinned criteria; preserve legacy calculations unchanged."""
from deadlock_policy_v01 import VERSION, SPEC
from deadlock_policy_v01 import pin_criteria as pin_v01, evaluate_criteria as evaluate_v01


def pin_criteria(version=VERSION):
    return pin_v01(version)


def progress_version_for(pin):
    try:
        expected = pin_criteria(pin.get("criteria_version"))
    except ValueError:
        return None
    if any(pin.get(k) != v for k, v in expected.items()):
        return None
    return expected["criteria_parameters"]["progress_version"]


def evaluate_criteria(observations, pin):
    return evaluate_v01(observations, pin)
