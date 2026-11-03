"""Exercise the ASGI app and repository SQL without an external database."""

import asyncio
import json
import sqlite3
import unittest
from unittest.mock import patch

from psycopg import OperationalError

from backend.auth.dependencies import get_current_user
from backend.main import app


# Routes now require login (18aaee9); tests act as the owner of projects 1 and 2.
TEST_USER = {"id": 1, "account_status": "active", "session_scope": "full", "csrf_token": "test-csrf"}


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, parameters=()):
        self.cursor.execute(sql.replace("%s", "?"), parameters)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return Cursor(self.connection)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


async def request(path):
    messages = []
    path, _, query = path.partition("?")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app({
        "type": "http", "asgi": {"version": "3.0"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": query.encode(),
        "root_path": "", "headers": [],
        "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8030),
    }, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, body


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY, name TEXT, mode TEXT,
                rule_id TEXT, created_at TEXT, owner_user_id INTEGER
            );
            INSERT INTO projects VALUES (1, 'Demo', 'observe', 'deadlock-v0.3', '2026-10-12T00:00:00+00:00', 1);
            INSERT INTO projects VALUES (2, 'Empty', 'observe', 'deadlock-v0.3', '2026-10-12T00:00:00+00:00', 1);
            CREATE TABLE scenarios (id INTEGER PRIMARY KEY, project_id INTEGER);
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, scenario_id INTEGER, status TEXT,
                termination_reason TEXT, phase TEXT, guardrail_mode TEXT,
                model TEXT, steps_reached INTEGER, total_tokens INTEGER,
                first_stop_step INTEGER, started_at TEXT, ended_at TEXT
            );
            INSERT INTO scenarios VALUES (10, 1);
            INSERT INTO sessions VALUES (
                'saved-session', 10, 'ended', 'success', 'main', 'observe',
                'demo-model', 5, 1200, NULL, '2026-10-12T00:00:00+00:00', NULL
            );
        """)

        self.connection_patch = patch(
            "backend.db.get_connection", side_effect=lambda: Connection(self.db)
        )
        self.connection_patch.start()
        app.dependency_overrides[get_current_user] = lambda: dict(TEST_USER)

    def tearDown(self):
        self.connection_patch.stop()
        app.dependency_overrides.clear()
        self.db.close()

    def get(self, path):
        return asyncio.run(request(path))

    def test_login_required(self):
        app.dependency_overrides.clear()
        for path in ('/api/projects', '/api/projects/1/sessions', '/api/projects/1/sessions/saved-session'):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 401)

    def test_docs_and_openapi(self):
        status, body = self.get("/docs")
        self.assertEqual(status, 200)
        self.assertIn(b"swagger-ui", body)
        status, body = self.get("/openapi.json")
        self.assertEqual(status, 200)
        self.assertIn("/api/projects/{project_id}/sessions/{session_id}", json.loads(body)["paths"])

    def test_health(self):
        status, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["database"], "ok")

    def test_session_detail(self):
        status, body = self.get("/api/projects/1/sessions/saved-session")
        self.assertEqual(status, 200)
        session = json.loads(body)
        self.assertEqual(session["total_tokens"], 1200)
        self.assertEqual(session["scenario_id"], 10)
        self.assertIsNone(session["first_stop_step"])
        self.assertIsNone(session["ended_at"])

    def test_missing_session(self):
        self.assertEqual(self.get("/api/projects/1/sessions/missing")[0], 404)

    def test_project_list(self):
        status, body = self.get("/api/projects")
        self.assertEqual(status, 200)
        self.assertEqual([p["id"] for p in json.loads(body)], [1, 2])

    def test_session_pagination_and_project_scope(self):
        self.db.executescript("""
            INSERT INTO scenarios VALUES (20, 2);
            INSERT INTO sessions (id, scenario_id, status, started_at)
            VALUES ('new-session', 10, 'ended', '2026-10-13T00:00:00+00:00');
            INSERT INTO sessions (id, scenario_id, status, started_at)
            VALUES ('other-project-session', 20, 'ended', '2026-10-14T00:00:00+00:00');
        """)
        for offset, expected in ((0, ['new-session']), (1, ['saved-session']), (2, [])):
            with self.subTest(offset=offset):
                status, body = self.get(f"/api/projects/1/sessions?limit=1&offset={offset}")
                self.assertEqual(status, 200)
                page = json.loads(body)
                self.assertEqual(page["total"], 2)
                self.assertEqual(page["limit"], 1)
                self.assertEqual(page["offset"], offset)
                self.assertEqual([s["id"] for s in page["items"]], expected)

    def test_empty_and_missing_project_lists(self):
        status, body = self.get("/api/projects/2/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"items": [], "total": 0, "limit": 20, "offset": 0})
        self.assertEqual(self.get("/api/projects/999/sessions")[0], 404)

    def test_invalid_pagination(self):
        for query in ('limit=0', 'limit=201', 'offset=-1', 'limit=abc', 'offset=9223372036854775808'):
            with self.subTest(query=query):
                self.assertEqual(self.get('/api/projects/1/sessions?' + query)[0], 422)
        self.assertEqual(self.get('/api/projects/0/sessions')[0], 422)

    def test_invalid_input_does_not_connect(self):
        paths = (
            '/api/projects/0/sessions',
            '/api/projects/1/sessions?offset=9223372036854775808',
            '/api/projects/1/sessions?limit=0',
            '/api/projects/0/sessions/saved-session',
            '/api/projects/invalid/sessions/saved-session',
            '/api/projects/1/sessions/' + 'x' * 201,
        )
        with patch('backend.db.get_connection', side_effect=OperationalError('offline')) as connect:
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(self.get(path)[0], 422)
            connect.assert_not_called()

    def test_valid_session_requests_with_database_offline(self):
        with patch('backend.db.get_connection', side_effect=OperationalError('offline')):
            for path in ('/api/projects/1/sessions', '/api/projects/1/sessions/saved-session'):
                with self.subTest(path=path):
                    status, body = self.get(path)
                    self.assertEqual(status, 503)
                    self.assertEqual(json.loads(body), {'detail': 'Database unavailable'})

    def test_other_project(self):
        self.assertEqual(self.get("/api/projects/2/sessions/saved-session")[0], 404)

    def test_invalid_project(self):
        for project in ("0", "-1", "invalid"):
            with self.subTest(project=project):
                self.assertEqual(self.get(f"/api/projects/{project}/sessions/saved-session")[0], 422)

    def test_unavailable_database(self):
        app.dependency_overrides.clear()
        for error in (OperationalError("private connection details"), RuntimeError("missing configuration")):
            with self.subTest(error=type(error).__name__):
                with patch("backend.db.get_connection", side_effect=error):
                    status, body = self.get("/healthz")
                self.assertEqual(status, 503)
                self.assertEqual(json.loads(body), {"detail": "Database unavailable"})


if __name__ == "__main__":
    unittest.main()
