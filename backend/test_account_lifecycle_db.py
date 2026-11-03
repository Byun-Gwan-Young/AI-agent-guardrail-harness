"""Opt-in PostgreSQL tests in an isolated schema, entirely rolled back.

RUN_ACCOUNT_DB_TESTS=1 python -m unittest backend.test_account_lifecycle_db
Requires CREATE SCHEMA permission on the configured development database.
"""
import os
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql
from storage import accounts
from storage.db import get_connection


@unittest.skipUnless(os.getenv('RUN_ACCOUNT_DB_TESTS') == '1', 'opt-in PostgreSQL tests')
class LifecycleDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.conn.execute("SET LOCAL lock_timeout = '5s'")
        name = 'account_test_' + uuid4().hex
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        self.conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(name)))
        schema = Path(__file__).resolve().parent.parent / 'storage/schema.sql'
        self.conn.execute(schema.read_text(encoding='utf-8'), prepare=False)

        @contextmanager
        def nested_connection():
            with self.conn.transaction():
                yield self.conn

        self.patch = patch('storage.accounts.get_connection', nested_connection)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        state_patch = patch('backend.repositories.accounts.get_connection', nested_connection)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.user = self.conn.execute("INSERT INTO users(google_sub,email) VALUES ('one','one@example.invalid') RETURNING id").fetchone()[0]
        self.other = self.conn.execute("INSERT INTO users(google_sub,email) VALUES ('two','two@example.invalid') RETURNING id").fetchone()[0]
        self.project = self.conn.execute("""INSERT INTO projects(name,rule_id,upstream_url,owner_user_id)
            VALUES ('test','rule','https://example.invalid',%s) RETURNING id""", (self.user,)).fetchone()[0]

    def test_withdraw_retry_restore_and_keys(self):
        key = accounts.issue_api_key(self.project, self.user, 'test')
        before = accounts.verify_api_key(key[0])
        self.assertIsNotNone(before)
        first = accounts.request_account_deletion(self.user)
        self.assertEqual(first['account_status'], 'pending_deletion')
        self.assertEqual((first['deletion_due_at']-first['deletion_requested_at']).days, 30)
        again = accounts.request_account_deletion(self.user)
        self.assertEqual(first['deletion_due_at'], again['deletion_due_at'])
        self.assertTrue(again['already_pending'])
        self.assertIsNone(accounts.verify_api_key(key[0]))
        with self.assertRaises(RuntimeError):
            accounts.issue_api_key(self.project, self.user, 'blocked')
        self.assertEqual(accounts.restore_account(self.user)['account_status'], 'active')
        self.assertIsNone(accounts.verify_api_key(key[0]))
        self.assertEqual(self.conn.execute('SELECT account_status FROM users WHERE id=%s', (self.other,)).fetchone()[0], 'active')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM auth_events WHERE kind='account_deletion_requested'").fetchone()[0], 1)

    def test_restore_at_deadline_rejected(self):
        accounts.request_account_deletion(self.user)
        self.conn.execute("""UPDATE users SET deletion_requested_at=CURRENT_TIMESTAMP-INTERVAL '30 days',
            deletion_due_at=CURRENT_TIMESTAMP WHERE id=%s""", (self.user,))
        with self.assertRaisesRegex(RuntimeError, 'expired'):
            accounts.restore_account(self.user)

    def test_final_purge_preserves_other_users_and_demo(self):
        accounts.allow_email('one@example.invalid')
        accounts.issue_api_key(self.project, self.user, 'purge-test')
        demo = self.conn.execute("""INSERT INTO projects(name,rule_id,upstream_url,read_only)
            VALUES ('demo','rule','https://example.invalid',true) RETURNING id""").fetchone()[0]
        for project_id, session_id in ((self.project, 'owned-run'), (demo, 'demo-run')):
            scenario = self.conn.execute("""INSERT INTO scenarios
                (project_id,scenario_key,scenario_hash,schema_version,name,config)
                VALUES (%s,'test','hash','v2','test','{}') RETURNING id""", (project_id,)).fetchone()[0]
            self.conn.execute("INSERT INTO sessions(id,scenario_id,status,source) VALUES (%s,%s,'ended','live')", (session_id, scenario))
            self.conn.execute("INSERT INTO observations(session_id,step,observation_data) VALUES (%s,1,'{}')", (session_id,))
            self.conn.execute("INSERT INTO judgements(session_id,step,decision,rule_id,result_data) VALUES (%s,1,'CONTINUE','rule','{}')", (session_id,))
            self.conn.execute("INSERT INTO llm_calls(session_id,call_index) VALUES (%s,1)", (session_id,))
        accounts.request_account_deletion(self.user)
        with self.assertRaisesRegex(RuntimeError, 'not expired'):
            accounts.purge_account(self.user)
        self.conn.execute("""UPDATE users SET deletion_requested_at=CURRENT_TIMESTAMP-INTERVAL '30 days',
            deletion_due_at=CURRENT_TIMESTAMP WHERE id=%s""", (self.user,))
        preview = accounts.preview_account_purge(self.user)
        self.assertTrue(preview['deletion_due'])
        self.assertEqual(preview['counts']['projects'], 1)
        result = accounts.purge_due_accounts()
        self.assertEqual(result['purged_count'], 1)
        self.assertEqual(result['failed_count'], 0)
        self.assertIsNone(self.conn.execute('SELECT id FROM users WHERE id=%s', (self.user,)).fetchone())
        self.assertFalse(accounts.is_email_allowed('one@example.invalid'))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM auth_events WHERE user_id=%s', (self.user,)).fetchone()[0], 0)
        self.assertIsNotNone(self.conn.execute('SELECT id FROM users WHERE id=%s', (self.other,)).fetchone())
        self.assertIsNotNone(self.conn.execute('SELECT id FROM projects WHERE id=%s', (demo,)).fetchone())
        self.assertIsNone(self.conn.execute("SELECT id FROM sessions WHERE id='owned-run'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT id FROM sessions WHERE id='demo-run'").fetchone())
        for table in ('observations', 'judgements', 'llm_calls'):
            self.assertEqual(self.conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE session_id='owned-run'").format(sql.Identifier(table))).fetchone()[0], 0)
            self.assertEqual(self.conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE session_id='demo-run'").format(sql.Identifier(table))).fetchone()[0], 1)

    def test_first_google_login_registers_only_once(self):
        from backend.auth.service import login_with_google, _sessions
        self.addCleanup(_sessions.clear)
        accounts.allow_email('new@example.invalid')
        identity = {'sub': 'new-google-sub', 'email': 'new@example.invalid', 'email_verified': True}
        login_with_google(identity)
        login_with_google(identity)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM users WHERE google_sub='new-google-sub'").fetchone()[0], 1)

    def test_project_creation_http_ownership_defaults_and_audit_rollback(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.auth.dependencies import get_current_user
        from backend.routers.projects import router
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: {'id': self.user, 'csrf_token': 'test-csrf'}
        with patch.dict(os.environ, {'GUARDRAIL_DEFAULT_PROVIDER': 'groq'}), TestClient(app) as client:
            response = client.post('/api/projects', json={'name': '  New project  ', 'csrf_token': 'test-csrf'})
            self.assertEqual(response.status_code, 201)
            project_id = response.json()['id']
            row = self.conn.execute('SELECT name,owner_user_id,mode,rule_id,read_only,provider FROM projects WHERE id=%s', (project_id,)).fetchone()
            self.assertEqual(row, ('New project', self.user, 'observe', accounts.DEFAULT_RULE_ID, False, 'groq'))
            self.assertEqual(self.conn.execute("SELECT count(*) FROM auth_events WHERE kind='project_created' AND user_id=%s", (self.user,)).fetchone()[0], 1)
            with patch('storage.accounts._record_auth_event_cursor', side_effect=RuntimeError('audit failure')):
                response = client.post('/api/projects', json={'name': 'Rolled back', 'csrf_token': 'test-csrf'})
                self.assertEqual(response.status_code, 503)
            self.assertEqual(self.conn.execute("SELECT count(*) FROM projects WHERE name='Rolled back'").fetchone()[0], 0)
            accounts.request_account_deletion(self.user)
            # Override deliberately supplies stale full authentication; SQL guard must reject it.
            response = client.post('/api/projects', json={'name': 'After withdrawal', 'csrf_token': 'test-csrf'})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.conn.execute("SELECT count(*) FROM projects WHERE name='After withdrawal'").fetchone()[0], 0)

    def test_audit_failure_rolls_back_status_and_key_revocation(self):
        key = accounts.issue_api_key(self.project, self.user, 'test')
        with patch('storage.accounts._record_auth_event_cursor', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                accounts.request_account_deletion(self.user)
        self.assertEqual(self.conn.execute('SELECT account_status FROM users WHERE id=%s', (self.user,)).fetchone()[0], 'active')
        self.assertIsNotNone(accounts.verify_api_key(key[0]))

    def test_http_login_withdraw_reauthenticate_restore(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.routers.auth import router
        from backend.auth import service
        self.addCleanup(service._sessions.clear)
        accounts.allow_email('one@example.invalid')
        app = FastAPI()
        app.include_router(router)
        identity = {'sub': 'one', 'email': 'one@example.invalid', 'email_verified': True}
        with patch.dict(os.environ, {'AUTH_COOKIE_SECURE': 'false'}), patch(
            'backend.routers.auth.verify_google_token', return_value=identity
        ), TestClient(app) as client:
            def login():
                client.cookies.set('g_csrf_token', 'test-csrf')
                response = client.post('/api/auth/google', data={
                    'credential': 'test-credential', 'g_csrf_token': 'test-csrf'
                }, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                return client.get('/api/auth/me').json()

            user = login()
            self.assertEqual(user['session_scope'], 'full')
            result = client.post('/api/auth/withdraw', json={
                'confirm': True, 'csrf_token': user['csrf_token']})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(client.get('/api/auth/me').status_code, 401)
            user = login()
            self.assertEqual(user['session_scope'], 'recovery')
            result = client.post('/api/auth/restore', json={
                'confirm': True, 'csrf_token': user['csrf_token']})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(client.get('/api/auth/me').status_code, 401)
            self.assertEqual(login()['session_scope'], 'full')
