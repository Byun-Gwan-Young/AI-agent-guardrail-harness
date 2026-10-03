import unittest

from duration import parse_duration


class DurationRejects(unittest.TestCase):
    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_duration("")

    def test_rejects_unit_without_number(self):
        with self.assertRaises(ValueError):
            parse_duration("h")

    def test_rejects_malformed_hour_suffix(self):
        with self.assertRaises(ValueError):
            parse_duration("1h30")

    def test_rejects_units_out_of_order(self):
        with self.assertRaises(ValueError):
            parse_duration("30m1h")

    def test_rejects_repeated_unit(self):
        with self.assertRaises(ValueError):
            parse_duration("1m1m")

    def test_rejects_sign(self):
        with self.assertRaises(ValueError):
            parse_duration("-5s")

    def test_rejects_non_string(self):
        with self.assertRaises(TypeError):
            parse_duration(90)
