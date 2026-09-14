import tempfile
import unittest

import httpx

from proxy import create_app


class HealthTest(unittest.IsolatedAsyncioTestCase):
    async def test_cached_health_counts_restarted_sessions_without_upstream_call(self):
        def forbidden(request):
            raise AssertionError("healthz must not call upstream")

        with tempfile.TemporaryDirectory() as directory:
            old = create_app(directory)
            old.state.store.start("active")
            old.state.store.end(old.state.store.start("ended"))
            app = create_app(directory, httpx.MockTransport(forbidden))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/healthz")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["status"], "ok")
                self.assertGreaterEqual(r.json()["uptime"], 0)
                self.assertEqual(r.json()["active_sessions"], 1)
                self.assertIsNone(r.json()["upstream_reachable"])
                self.assertIsNone(r.json()["policy_version"])
                app.state.upstream_health = {"reachable": False, "checked_at": "cached"}
                r = await c.get("/healthz")
                self.assertFalse(r.json()["upstream_reachable"])
                self.assertEqual(r.json()["upstream_checked_at"], "cached")
