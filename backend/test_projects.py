import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import OperationalError

from backend.auth import service
from backend.routers.projects import router


class ProjectCreationTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(service._sessions.clear)
        self.state_patch = patch('backend.auth.service.fetch_account_state', return_value={
            'account_status': 'active', 'can_restore': None,
            'deletion_requested_at': None, 'deletion_due_at': None})
        self.state = self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        token = service.create_session({'id': 7, 'sub': 'google-user'})
        self.client.cookies.set('guardrail_session', token)
        self.csrf = service.get_user(token)['csrf_token']
        storage_patch = patch('backend.routers.projects.accounts.create_project', return_value={
            'id': 42, 'name': 'My project', 'mode': 'observe', 'rule_id': 'deadlock-v0.3',
            'created_at': '2026-11-03T00:00:00Z', 'owner_user_id': 7,
            'upstream_url': 'https://internal.example', 'provider': 'groq', 'read_only': False})
        self.create = storage_patch.start()
        self.addCleanup(storage_patch.stop)

    def post(self, **fields):
        return self.client.post('/api/projects', json={
            'name': 'My project', 'csrf_token': self.csrf, **fields})

    def test_created_as_authenticated_owner_with_default_mode(self):
        response = self.post(name='  My project  ')
        self.assertEqual(response.status_code, 201)
        self.create.assert_called_once_with(7, 'My project', 'observe')
        self.assertEqual(response.json()['id'], 42)
        self.assertNotIn('upstream_url', response.json())
        self.assertNotIn('csrf_token', response.json())

    def test_explicit_block_mode(self):
        self.assertEqual(self.post(mode='block').status_code, 201)
        self.create.assert_called_once_with(7, 'My project', 'block')

    def test_invalid_fields_and_owner_injection(self):
        for fields in ({'name': '   '}, {'name': 'x' * 101}, {'name': 12},
                       {'mode': 'warn'}, {'owner_user_id': 8}, {'rule_id': 'other'},
                       {'upstream_url': 'http://localhost'}, {'provider': 'custom'},
                       {'read_only': True}):
            with self.subTest(fields=fields):
                self.assertEqual(self.post(**fields).status_code, 422)
        self.create.assert_not_called()

    def test_csrf_rejected_before_write(self):
        self.assertEqual(self.post(csrf_token='wrong').status_code, 403)
        self.assertEqual(self.client.post('/api/projects', json={'name': 'test'}).status_code, 422)
        self.create.assert_not_called()

    def test_anonymous_rejected(self):
        self.client.cookies.clear()
        self.assertEqual(self.post().status_code, 401)
        self.create.assert_not_called()

    def test_secret_like_project_name_rejected(self):
        self.assertEqual(self.post(name='gsk_' + 'A' * 30).status_code, 422)
        self.create.assert_not_called()

    def test_recovery_session_rejected(self):
        self.state.return_value = {'account_status': 'pending_deletion', 'can_restore': True,
                                   'deletion_requested_at': None, 'deletion_due_at': None}
        self.assertEqual(self.post().status_code, 403)
        self.create.assert_not_called()

    def test_storage_rechecks_withdrawal_and_deleted_user(self):
        for error, status in ((RuntimeError('account is pending deletion'), 403),
                              (LookupError('user not found'), 401)):
            self.create.side_effect = error
            self.assertEqual(self.post().status_code, status)

    def test_storage_errors_do_not_leak_configuration(self):
        for error, status in ((RuntimeError('private config'), 503),
                              (OperationalError('private password'), 503),
                              (ValueError('private provider config'), 503)):
            self.create.side_effect = error
            response = self.post()
            self.assertEqual(response.status_code, status)
            self.assertNotIn('private', response.text)
