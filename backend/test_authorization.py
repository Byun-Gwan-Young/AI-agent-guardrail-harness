"""Reuse the SQLite API suite with authenticated owners; no external DB needed."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

from backend.auth.dependencies import get_current_user
from backend.auth.service import create_session
from backend.main import app

spec = importlib.util.spec_from_file_location(
    "session_api_fixture", Path(__file__).resolve().parent.parent / "tests/test_backend_sessions.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class AuthorizationTests(fixture.BackendTests):
    def setUp(self):
        super().setUp()
        self.db.executescript("""
            ALTER TABLE projects ADD COLUMN owner_user_id INTEGER;
            UPDATE projects SET owner_user_id = 7;
            INSERT INTO projects VALUES
              (3, 'Other owner', 'observe', 'deadlock-v0.3', '2026-10-12', 8),
              (4, 'Ownerless', 'observe', 'deadlock-v0.3', '2026-10-12', NULL);
            INSERT INTO scenarios VALUES (30, 3), (40, 4);
            INSERT INTO sessions (id, scenario_id, status)
              VALUES ('private', 30, 'ended'), ('ownerless', 40, 'ended');
            UPDATE sessions SET started_at = '2026-10-12T00:00:00+00:00'
              WHERE started_at IS NULL;
        """)
        app.dependency_overrides[get_current_user] = lambda: {"id": 7}

    def test_foreign_and_ownerless_projects_hidden(self):
        for project, session in ((3, 'private'), (4, 'ownerless'), (999, 'missing')):
            for suffix in ('', '/' + session):
                with self.subTest(project=project, suffix=suffix):
                    self.assertEqual(self.get(f'/api/projects/{project}/sessions{suffix}')[0], 404)

    def test_other_owner_can_access_own_project(self):
        import json
        app.dependency_overrides[get_current_user] = lambda: {"id": 8}
        status, body = self.get('/api/projects')
        self.assertEqual(status, 200)
        self.assertEqual([p['id'] for p in json.loads(body)], [3])
        self.assertEqual(self.get('/api/projects/3/sessions/private')[0], 200)
        self.assertEqual(self.get('/api/projects/1/sessions/saved-session')[0], 404)

    def test_anonymous_requests_rejected_before_db(self):
        app.dependency_overrides.clear()
        with patch('backend.db.get_connection') as connect:
            for path in ('/api/projects', '/api/projects/1/sessions',
                         '/api/projects/1/sessions/saved-session'):
                self.assertEqual(self.get(path)[0], 401)
            connect.assert_not_called()

    def test_real_cookie_dependency(self):
        from fastapi.testclient import TestClient
        app.dependency_overrides.clear()
        token = create_session({'id': 7, 'sub': 'google-user'})
        with TestClient(app) as client:
            client.cookies.set('guardrail_session', token)
            self.assertEqual(client.get('/api/projects').status_code, 200)
            client.cookies.set('guardrail_session', 'forged')
            self.assertEqual(client.get('/api/projects').status_code, 401)


if __name__ == '__main__':
    import unittest
    unittest.main()
