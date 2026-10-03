"""DEMO-CL stall check (C-18-1): the reference implementation without the "1h30" hour shorthand, so "1h30" raises
ValueError. With the reference implementation it covers both outcomes the stall pair asks of the input "1h30". Test
fixture only; self-contained so it can be copied to src/duration.py of a scratch workspace."""
import re

_FULL = re.compile(r"(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?")


def parse_duration(text):
    """Return the number of seconds in a duration such as "1h30m", "45s" or "90"."""
    if not isinstance(text, str):
        raise TypeError("duration must be a string")
    value = text.strip().lower()
    if re.fullmatch(r"[0-9]+", value):
        return int(value)
    match = _FULL.fullmatch(value)
    if not value or match is None or not any(match.groups()):
        raise ValueError("not a duration: " + repr(text))
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds
