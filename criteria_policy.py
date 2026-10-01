"""Criteria dispatch including deadlock-v0.3.

deadlock_policy.py (v0.1/v0.2 dispatch) is P0-2 protected and stays byte-identical, so the configurable
deadlock-v0.3 is routed here first and every other version falls through to it unchanged.
"""
from deadlock_policy import VERSION
from deadlock_policy import pin_criteria as pin_legacy, evaluate_criteria as evaluate_legacy
from deadlock_policy import progress_version_for as legacy_progress_version_for
from deadlock_policy_v03 import VERSION as V03
from deadlock_policy_v03 import pin_criteria as pin_v03, evaluate_criteria as evaluate_v03


def pin_criteria(version=VERSION, parameters=None):
    # Only deadlock-v0.3 reads its parameters from the configuration; earlier versions fix them in code.
    if version == V03:
        return pin_v03(version, parameters)
    if parameters is not None:
        raise ValueError("criteria_parameters are configurable only for " + V03)
    return pin_legacy(version)


def progress_version_for(pin):
    if pin.get("criteria_version") != V03:
        return legacy_progress_version_for(pin)
    try:
        expected = pin_v03(V03, pin.get("criteria_parameters"))
    except ValueError:
        return None
    if any(pin.get(k) != v for k, v in expected.items()):
        return None
    return expected["criteria_parameters"]["progress_version"]


def evaluate_criteria(observations, pin, registration=None):
    # The session registration (DM-35) only exists for deadlock-v0.3 sessions; earlier versions never see it.
    if pin.get("criteria_version") == V03:
        return evaluate_v03(observations, pin, registration)
    return evaluate_legacy(observations, pin)
