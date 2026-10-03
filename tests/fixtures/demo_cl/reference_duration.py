"""DEMO-CL reference implementation (C-18-1, 5-2 answer path). Test fixture only: never copied into a scenario
workspace, so no agent can read it. Passes every DEMO-CL-normal-v1 acceptance test."""
import re

_FULL = re.compile(r"(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?")
_HOUR_SHORTHAND = re.compile(r"([0-9]+)h([0-9]+)")


def parse_duration(text):
    """Return the number of seconds in a duration such as "1h30m", "45s", "90" or "1h30"."""
    if not isinstance(text, str):
        raise TypeError("duration must be a string")
    value = text.strip().lower()
    if re.fullmatch(r"[0-9]+", value):
        return int(value)
    shorthand = _HOUR_SHORTHAND.fullmatch(value)
    if shorthand:
        return int(shorthand.group(1)) * 3600 + int(shorthand.group(2)) * 60
    match = _FULL.fullmatch(value)
    if not value or match is None or not any(match.groups()):
        raise ValueError("not a duration: " + repr(text))
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds
