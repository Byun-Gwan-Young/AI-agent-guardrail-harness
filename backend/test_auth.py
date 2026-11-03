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
        self.state_patch = patch("backend.auth.service.fetch_account_state", return_value={
            "account_status": "active", "deletion_requested_at": None,
            "deletion_due_at": None, "can_restore": None})
        self.state = self.state_patch.start()
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
        self.state_patch.stop()
        self.allowed.stop()
        self.upsert.stop()
        self.audit.stop()
        with service._lock:
            service._sessions.clear()

    def post_new_identity(self, email):
        self.client.cookies.set("g_csrf_token", "csrf")
        with patch("backend.routers.auth.verify_google_token", return_value={
            "sub": "555", "name": "New", "email": email, "email_verified": True}):
            return self.client.post("/api/auth/google", data={"credential": "token", "g_csrf_token": "csrf"},
                                    follow_redirects=False)

    def test_check_sends_strangers_to_login_and_lets_members_in(self):
        # DM-110 : what Caddy forward_auth asks before every page.
        response = self.client.get("/api/auth/check", follow_redirects=False)
        self.assertEqual((response.status_code, response.headers["location"]), (303, "/login"))
        signed_in = self.post_new_identity("member@example.org")
        self.assertEqual((signed_in.status_code, signed_in.headers["location"]), (303, "/"))
        self.assertEqual(self.client.get("/api/auth/check", follow_redirects=False).status_code, 204)
        self.state.return_value = self.pending()
        self.assertEqual(self.client.get("/api/auth/check", follow_redirects=False).status_code, 303)

    def test_allow_list_is_the_default(self):
        self.allowed_mock.return_value = False
        self.assertEqual(self.post_new_identity("new@example.org").status_code, 403)
        self.upsert_mock.assert_not_called()
        self.assertIn("허용된 이메일만", self.client.get("/login").text)

    def test_open_signup_creates_the_account_without_the_allow_list(self):
        self.allowed_mock.return_value = False
        with patch.dict(os.environ, {"GUARDRAIL_OPEN_SIGNUP": "true"}):
            self.assertEqual(self.post_new_identity("new@example.org").status_code, 303)
            self.upsert_mock.assert_called_once_with("555", "new@example.org", "New")
            self.allowed_mock.assert_not_called()
            page = self.client.get("/login").text
        self.assertIn("처음 로그인하면 계정이 만들어집니다", page)
        self.assertNotIn("{{", page)

    def test_open_signup_still_needs_a_verified_email(self):
        with patch.dict(os.environ, {"GUARDRAIL_OPEN_SIGNUP": "true"}):
            self.client.cookies.set("g_csrf_token", "csrf")
            with patch("backend.routers.auth.verify_google_token", return_value={
                "sub": "556", "email": "x@example.org", "email_verified": False}):
                response = self.client.post("/api/auth/google", data={"credential": "t", "g_csrf_token": "csrf"},
                                            follow_redirects=False)
        self.assertEqual(response.status_code, 401)
        self.upsert_mock.assert_not_called()

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

    def pending(self, can_restore=True):
        from datetime import datetime, timezone
        return {"account_status": "pending_deletion", "can_restore": can_restore,
                "deletion_requested_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                "deletion_due_at": datetime(2026, 10, 31, tzinfo=timezone.utc)}

    def test_pending_login_is_restricted_and_dates_serialize(self):
        self.state.return_value = self.pending()
        self.assertEqual(self.post_identity().status_code, 303)
        user = self.client.get('/api/auth/me').json()
        self.assertEqual(user['session_scope'], 'recovery')
        self.assertEqual(user['account_status'], 'pending_deletion')
        self.assertIn('2026-10-31', user['deletion_due_at'])
        self.assertIn('복구', self.client.get('/login').text)

    def test_due_login_denied_without_cookie(self):
        self.state.return_value = self.pending(False)
        response = self.post_identity()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('set-cookie', response.headers)
        self.assertFalse(service._sessions)

    def test_recovery_page_keeps_google_reauthentication_visible(self):
        self.state.return_value = self.pending()
        self.post_identity()
        page = self.client.get('/login').text
        self.assertIn('<section style="display:block">', page.split('id="g_id_onload"')[0])

    def test_existing_sessions_downgrade_and_never_auto_upgrade(self):
        from backend.auth.dependencies import get_current_user
        from starlette.requests import Request
        from fastapi import HTTPException
        first = service.create_session({'id': 7, 'sub': '123'})
        second = service.create_session({'id': 7, 'sub': '123'})
        self.state.return_value = self.pending()
        request = Request({'type': 'http', 'headers': [
            (b'cookie', ('guardrail_session=' + first).encode())]})
        with self.assertRaises(HTTPException) as error:
            get_current_user(request)
        self.assertEqual(error.exception.status_code, 403)
        self.state.return_value = {'account_status': 'active', 'can_restore': None,
                                  'deletion_requested_at': None, 'deletion_due_at': None}
        self.assertEqual(service.get_user(second)['session_scope'], 'recovery')
        with self.assertRaises(HTTPException):
            get_current_user(request)

    def test_deleted_or_due_account_invalidates_all_sessions(self):
        for state in (None, self.pending(False)):
            first = service.create_session({'id': 7, 'sub': '123'})
            second = service.create_session({'id': 7, 'sub': '123'})
            self.state.return_value = state
            self.assertIsNone(service.get_user(first))
            self.assertIsNone(service.get_user(second))
            self.assertFalse(service._sessions)

    def test_status_db_failure_returns_503_on_me_and_page(self):
        from psycopg import OperationalError
        self.post_identity()
        self.state.side_effect = OperationalError('private data')
        for path in ('/api/auth/me', '/login'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private data', response.text)

    def post_identity(self, **overrides):
        info = {"sub": "123", "email": "a@example.com", "email_verified": True}
        info.update(overrides)
        self.client.cookies.set("g_csrf_token", "csrf")
        with patch("backend.routers.auth.verify_google_token", return_value=info):
            return self.client.post("/api/auth/google", data={
                "credential": "test", "g_csrf_token": "csrf",
            }, follow_redirects=False)

    def action(self, path, **overrides):
        payload = {"confirm": True, "csrf_token": self.client.get('/api/auth/me').json()['csrf_token']}
        payload.update(overrides)
        return self.client.post('/api/auth/' + path, json=payload)

    def test_withdraw_revokes_all_user_sessions_after_commit(self):
        self.post_identity()
        other_device = service.create_session({'id': 7, 'sub': '123'})
        different_user = service.create_session({'id': 8, 'sub': '456'})
        with patch('backend.auth.service.accounts.request_account_deletion', return_value=self.pending()) as withdraw:
            response = self.action('withdraw')
        self.assertEqual(response.status_code, 200)
        withdraw.assert_called_once_with(7)
        self.assertIn('Max-Age=0', response.headers['set-cookie'])
        self.assertIsNone(service.get_user(other_device))
        self.assertIsNotNone(service.get_user(different_user))
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_actions_reject_missing_confirmation_csrf_and_user_injection(self):
        self.post_identity()
        with patch('backend.auth.service.accounts.request_account_deletion') as withdraw:
            for overrides, status in (({'confirm': False}, 422), ({'confirm': 'true'}, 422),
                                      ({'csrf_token': 'wrong'}, 403), ({'user_id': 8}, 422)):
                self.assertEqual(self.action('withdraw', **overrides).status_code, status)
            withdraw.assert_not_called()

    def test_anonymous_actions_denied(self):
        for path in ('withdraw', 'restore'):
            response = self.client.post('/api/auth/' + path, json={'confirm': True, 'csrf_token': 'fake'})
            self.assertEqual(response.status_code, 401)

    def test_restore_requires_fresh_google_recovery_session(self):
        self.post_identity()
        self.state.return_value = self.pending()
        with patch('backend.auth.service.accounts.restore_account') as restore:
            self.assertEqual(self.action('restore').status_code, 403)
            restore.assert_not_called()
        self.post_identity()  # A new Google verification while pending.
        active = {'account_status': 'active', 'deletion_requested_at': None, 'deletion_due_at': None}
        with patch('backend.auth.service.accounts.restore_account', return_value=active) as restore:
            self.assertEqual(self.action('restore').status_code, 200)
            restore.assert_called_once_with(7)
        self.assertFalse(service._sessions)

    def test_restore_rejects_old_google_verification(self):
        self.state.return_value = self.pending()
        self.post_identity()
        with patch('backend.auth.service.time.time', return_value=service.time.time() + 601):
            with patch('backend.auth.service.accounts.restore_account') as restore:
                self.assertEqual(self.action('restore').status_code, 403)
                restore.assert_not_called()

    def test_account_write_failure_preserves_session(self):
        from psycopg import OperationalError
        self.post_identity()
        with patch('backend.auth.service.accounts.request_account_deletion', side_effect=OperationalError('secret')):
            response = self.action('withdraw')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)

    def test_restore_deadline_race_is_checked_again_by_storage(self):
        self.state.return_value = self.pending()
        self.post_identity()
        with patch('backend.auth.service.accounts.restore_account',
                   side_effect=RuntimeError('account deletion grace period has expired')):
            self.assertEqual(self.action('restore').status_code, 409)

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
