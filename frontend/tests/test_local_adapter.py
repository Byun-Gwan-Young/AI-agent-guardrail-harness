"""Local composition checks without DB credentials, Google calls or an event loop."""
import runpy
import unittest
from pathlib import Path
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]

class LocalAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = runpy.run_path(str(ROOT / 'frontend/dev_server.py'), run_name='adapter_test')

    def gate(self, user):
        fn = self.scope['gate_query_api']
        original = fn.__globals__['optional_account']
        fn.__globals__['optional_account'] = lambda request: user
        request = Request({'type': 'http', 'path': '/api/summary', 'headers': [], 'scheme': 'http'})
        try:
            coroutine = fn(request, None)
            try:
                coroutine.send(None)
            except StopIteration as result:
                return result.value
            self.fail('Unauthenticated gate attempted downstream IO')
        finally:
            fn.__globals__['optional_account'] = original

    def test_anonymous_query_is_rejected_before_database_access(self):
        self.assertEqual(self.gate(None).status_code, 401)

    def test_recovery_account_cannot_read_shared_query_api(self):
        self.assertEqual(self.gate({'account_status': 'pending_deletion', 'session_scope': 'recovery'}).status_code, 403)

    def test_original_auth_query_and_live_routes_are_registered(self):
        paths = self.scope['app'].openapi()['paths']
        for path in ('/api/auth/google', '/api/projects', '/api/summary', '/api/sessions/{session_id}/steps', '/api/live/sessions'):
            self.assertIn(path, paths)

    def test_reference_preserves_all_curated_sessions(self):
        data = self.scope['reference']()
        self.assertEqual(len(data['sessions']), 67)
        self.assertEqual(data['headline']['observe_sessions'], 54)

if __name__ == '__main__':
    unittest.main()
