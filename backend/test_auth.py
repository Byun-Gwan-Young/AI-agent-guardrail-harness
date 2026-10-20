import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import service
from backend.routers.auth import router


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "test.apps.googleusercontent.com",
            "AUTH_COOKIE_SECURE": "false",
        })
        self.env.start()
        self.allowed = patch("backend.auth.service.accounts.is_email_allowed", return_value=True)
        self.upsert = patch("backend.auth.service.accounts.upsert_user_from_google", side_effect=
                            lambda sub, email, name: {"id": 7, "google_sub": sub,
                                                      "email": email, "name": name})
        self.audit = patch("backend.auth.service.accounts.record_auth_event")
        self.allowed_mock = self.allowed.start()
        self.upsert_mock = self.upsert.start()
        self.audit_mock = self.audit.start()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.allowed.stop()
        self.upsert.stop()
        self.audit.stop()
        with service._lock:
            service._sessions.clear()

    def test_login_logout_and_escape(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.client.cookies.set("g_csrf_token", "csrf")
        with patch("backend.routers.auth.verify_google_token", return_value={
            "sub": "123", "name": "<script>alert(1)</script>", "email": "a@example.com",
            "email_verified": True,
        }):
            response = self.client.post("/api/auth/google", data={
                "credential": "test", "g_csrf_token": "csrf",
            }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/auth/me").json()["sub"], "123")
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], 7)
        self.upsert_mock.assert_called_once_with("123", "a@example.com", "<script>alert(1)</script>")
        page = self.client.get("/login").text
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("{{", page)
        self.assertEqual(self.client.post("/api/auth/logout", data={
            "csrf_token": "wrong",
        }).status_code, 403)
        token = self.client.cookies.get("guardrail_session")
        self.client.post("/api/auth/logout", data={"csrf_token": token})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_csrf_rejected_before_verification(self):
        with patch("backend.routers.auth.verify_google_token") as verify:
            response = self.client.post("/api/auth/google", data={
                "credential": "test", "g_csrf_token": "wrong",
            })
        self.assertEqual(response.status_code, 400)
        verify.assert_not_called()

    def test_invalid_token(self):
        self.client.cookies.set("g_csrf_token", "csrf")
        with patch("backend.routers.auth.verify_google_token", side_effect=ValueError):
            response = self.client.post("/api/auth/google", data={
                "credential": "bad", "g_csrf_token": "csrf",
            })
        self.assertEqual(response.status_code, 401)

    def test_expired_session(self):
        token = service.create_session({"sub": "123"})
        with patch("backend.auth.service.time.time", return_value=10**12):
            self.assertIsNone(service.get_user(token))

    def post_identity(self, **overrides):
        info = {"sub": "123", "email": "a@example.com", "email_verified": True}
        info.update(overrides)
        self.client.cookies.set("g_csrf_token", "csrf")
        with patch("backend.routers.auth.verify_google_token", return_value=info):
            return self.client.post("/api/auth/google", data={
                "credential": "test", "g_csrf_token": "csrf",
            }, follow_redirects=False)

    def test_disallowed_email_never_creates_user_or_session(self):
        self.allowed_mock.return_value = False
        response = self.post_identity()
        self.assertEqual(response.status_code, 403)
        self.upsert_mock.assert_not_called()
        self.audit_mock.assert_called_once()
        self.assertFalse(service._sessions)
        self.assertNotIn("set-cookie", response.headers)

    def test_unverified_email_rejected_before_db(self):
        self.assertEqual(self.post_identity(email_verified=False).status_code, 401)
        self.allowed_mock.assert_not_called()
        self.upsert_mock.assert_not_called()

    def test_db_failure_does_not_issue_session_or_expose_details(self):
        from psycopg import OperationalError
        for target in (self.allowed_mock, self.upsert_mock):
            with self.subTest(target=target):
                target.side_effect = OperationalError("private connection details")
                response = self.post_identity()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private", response.text)
                self.assertFalse(service._sessions)
                target.side_effect = None


if __name__ == "__main__":
    unittest.main()
