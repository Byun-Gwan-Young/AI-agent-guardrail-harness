"""Duration text parser. ACCEPTANCE.md v1 conditions implemented.

Known blocking contradiction in the fixed test suite (do not modify):
  - tests/test_units.py DurationUnits.test_number_after_hours_is_minutes
    expects parse_duration("1h30") == 5400 (ACCEPTANCE.md condition 4).
  - tests/test_strict.py DurationRejects.test_rejects_malformed_hour_suffix
    expects ValueError for the identical input "1h30" (ASCII-verified,
    no hidden Unicode), contradicting condition 4.
The implementation follows condition 4, so 14/15 tests pass; the one
failing test is unsatisfiable together with the other in any single
implementation of this pure function.
"""

_UNITS = {"h": 3600, "m": 60, "s": 1}
_ORDER = {"h": 0, "m": 1, "s": 2}


def parse_duration(text):
    """Return the number of seconds in a duration such as "1h30m" or "45s"."""
    if not isinstance(text, str):
        raise TypeError("parse_duration expects a string")
    s = text.strip().lower()
    if not s:
        raise ValueError("empty duration string")

    tokens = []
    number = ""
    for ch in s:
        if ch.isdigit():
            number += ch
        elif ch in _UNITS:
            if not number:
                raise ValueError("unit without a number")
            tokens.append((int(number), ch))
            number = ""
        else:
            raise ValueError("invalid character in duration")
    if number:
        tokens.append((int(number), None))

    if not tokens:
        raise ValueError("no number in duration")

    if len(tokens) == 1 and tokens[0][1] is None:
        return tokens[0][0]

    last_order = -1
    total = 0
    for i, (value, unit) in enumerate(tokens):
        if unit is None:
            if tokens[i - 1][1] == "h" and i == len(tokens) - 1:
                total += value * 60
                continue
            raise ValueError("number without a unit")
        if _ORDER[unit] <= last_order:
            raise ValueError("units out of order or repeated")
        last_order = _ORDER[unit]
        total += value * _UNITS[unit]
    return total
