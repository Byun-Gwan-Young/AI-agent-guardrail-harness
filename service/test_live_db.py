"""Read-only integration checks for the unified PostgreSQL database.

Run separately when GUARDRAIL_DB_URL is set::

    python -X utf8 -m unittest service.test_live_db -v

No test writes to PostgreSQL.  The service Store opens every connection read-only.
"""

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service import load_demo, queries  # noqa: E402
from service.store import DB_URL_ENV, database_name, postgres_store  # noqa: E402


@unittest.skipUnless(os.environ.get(DB_URL_ENV), f'{DB_URL_ENV} is not set')
class UnifiedLiveDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = postgres_store()

    def test_database_is_reachable_and_unified(self):
        self.assertTrue(database_name(self.store))
        self.assertTrue(queries._unified_schema(self.store))

    def test_demo_session_ids_match_committed_records(self):
        expected = {row['session_id'] for row in load_demo.build_rows()['sessions']}
        actual = {row['id'] for row in self.store.query(
            "SELECT id FROM sessions WHERE source = 'demo-record' ORDER BY id"
        )}
        self.assertEqual(actual, expected)

    def test_unified_check_queries(self):
        aggregate = load_demo.load_json(ROOT / load_demo.AGGREGATE)
        result = queries.check(self.store, aggregate)
        self.assertTrue(result['ok'])
        self.assertEqual([c['check'] for c in result['comparisons'] if not c['same']], [])
        self.assertEqual(result['sessions_by_validity'], {'excluded': 30, 'not_counted': 18, 'valid': 67})

    def test_api_store_is_read_only(self):
        with self.assertRaises(Exception):
            self.store.query("UPDATE projects SET name = name WHERE id = -1 RETURNING id")

    def test_api_responses(self):
        from fastapi.testclient import TestClient
        from service.api import create_app
        client = TestClient(create_app(self.store))
        self.assertEqual(client.get('/api/sessions?validity=valid').json()['count'], 67)
        self.assertEqual([p['value'] for p in client.get('/api/summary').json()['presentation']][:4], [4, 2, 8, 60.8])
        self.assertEqual(client.get('/api/scenarios').status_code, 200)


if __name__ == '__main__':
    unittest.main()
