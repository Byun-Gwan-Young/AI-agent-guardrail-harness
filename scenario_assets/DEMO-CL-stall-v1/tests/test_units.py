import unittest

from duration import parse_duration


class DurationUnits(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration("1h30m"), 5400)

    def test_minutes_and_seconds(self):
        self.assertEqual(parse_duration("2m5s"), 125)

    def test_seconds_unit(self):
        self.assertEqual(parse_duration("45s"), 45)

    def test_bare_number_is_seconds(self):
        self.assertEqual(parse_duration("90"), 90)

    def test_number_after_hours_is_minutes(self):
        self.assertEqual(parse_duration("1h30"), 5400)

    def test_uppercase_unit(self):
        self.assertEqual(parse_duration("1H"), 3600)

    def test_surrounding_spaces(self):
        self.assertEqual(parse_duration(" 3m "), 180)

    def test_zero(self):
        self.assertEqual(parse_duration("0s"), 0)
