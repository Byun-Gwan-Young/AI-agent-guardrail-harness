"""Duration text parser."""
import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_PART = re.compile(r"(\d+)([hms])")


def parse_duration(text):
    """Return the number of seconds in a duration such as "1h30m" or "45s"."""
    if text.isdigit():
        return int(text)
    total = 0
    for number, unit in _PART.findall(text):
        total += int(number) * _UNITS[unit]
    return total
