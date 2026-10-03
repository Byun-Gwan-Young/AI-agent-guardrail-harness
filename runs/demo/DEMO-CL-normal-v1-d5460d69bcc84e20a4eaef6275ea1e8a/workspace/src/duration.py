"""Duration text parser."""
import re

_PLAIN = re.compile(r"(\d+)")
_HOUR_TRAILING = re.compile(r"(\d+)h(\d+)?")
_UNITS = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


def parse_duration(text):
    if not isinstance(text, str):
        raise TypeError("duration text must be a string")
    s = text.strip().lower()
    if not s:
        raise ValueError("empty duration")
    if "h" in s:
        m = _HOUR_TRAILING.fullmatch(s)
        if m is not None:
            hours = int(m.group(1))
            minutes = int(m.group(2)) if m.group(2) is not None else 0
            return hours * 3600 + minutes * 60
    m = _PLAIN.fullmatch(s)
    if m is not None:
        return int(m.group(1))
    m = _UNITS.fullmatch(s)
    if m is not None and any(g is not None for g in m.groups()):
        return (int(m.group(1)) if m.group(1) else 0) * 3600 + (
            int(m.group(2)) if m.group(2) else 0) * 60 + (
            int(m.group(3)) if m.group(3) else 0)
    raise ValueError("invalid duration: %r" % (text,))
