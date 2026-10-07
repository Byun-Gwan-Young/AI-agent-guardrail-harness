"""C-19-6 : checks against the real PostgreSQL database (after `python -m service.load_demo load`).

Separate command, not part of tools/run_offline_tests.py (that runner discovers tests/ only and blocks sockets):

  GUARDRAIL_DB_URL=... venv/bin/python -B -m unittest service.test_live_db

Every test is skipped when GUARDRAIL_DB_URL is not set. Nothing is written: the API store opens read-only connections
and one test confirms a write is refused.
"""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service import load_demo, queries  # noqa: E402
from service.store import DB_NAME, DB_URL_ENV, database_name, postgres_store  # noqa: E402


@unittest.skipUnless(os.environ.get(DB_URL_ENV), f'{DB_URL_ENV} is not set')
class LiveDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = postgres_store()

    def test_database_name(self):
        self.assertEqual(database_name(self.store), DB_NAME)

    def test_loaded_rows_match_the_files(self):
        rows = load_demo.build_rows()
        for table in ('scenarios', 'sessions', 'steps', 'aggregates'):
            self.assertEqual(self.store.scalar(f'SELECT COUNT(*) FROM {table}'), len(rows[table]), table)
        stored = self.store.query('SELECT input_sha256, inputs FROM aggregates')[0]
        self.assertEqual(stored['inputs'], rows['aggregates'][0]['inputs'])

    def test_check_queries(self):
        aggregate = json.loads((ROOT / load_demo.AGGREGATE).read_text(encoding='utf-8'))
        result = queries.check(self.store, aggregate)
        self.assertEqual([c['check'] for c in result['comparisons'] if not c['same']], [])

    def test_api_store_is_read_only(self):
        with self.assertRaises(Exception):
            self.store.query("UPDATE scenarios SET title = title WHERE scenario_id = 'none' RETURNING scenario_id")

    def test_api_responses(self):
        from fastapi.testclient import TestClient
        from service.api import create_app
        client = TestClient(create_app(self.store))
        self.assertEqual(client.get('/api/sessions?validity=valid').json()['count'], 67)
        self.assertEqual([p['value'] for p in client.get('/api/summary').json()['presentation']][:4], [4, 2, 8, 60.8])


if __name__ == '__main__':
    unittest.main()
