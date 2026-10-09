"""Regression test for PostgreSQL TIMESTAMPTZ API normalization."""

from datetime import datetime, timedelta, timezone
import unittest

from service.store import Store


class StoreTimezoneContractTests(unittest.TestCase):
    def test_timestamptz_is_normalized_to_utc_iso_string(self):
        store = Store(lambda: None, "postgres")
        value = datetime(
            2026, 10, 6, 12, 53, 5, 648849,
            tzinfo=timezone(timedelta(hours=9)),
        )
        self.assertEqual(
            store.from_db("started_at", value),
            "2026-10-06T03:53:05.648849+00:00",
        )

    def test_naive_datetime_keeps_existing_iso_behavior(self):
        store = Store(lambda: None, "postgres")
        value = datetime(2026, 10, 6, 3, 53, 5, 648849)
        self.assertEqual(
            store.from_db("started_at", value),
            "2026-10-06T03:53:05.648849",
        )


if __name__ == "__main__":
    unittest.main()
