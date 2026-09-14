import json
import tempfile
import unittest
from pathlib import Path

import httpx

from deadlock_policy import VERSION, pin_criteria
from proxy import create_app
from test_progress_signal import snapshot


class CriteriaIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_pinned_persisted_and_recovered(self):
        with tempfile.TemporaryDirectory() as root:
            def upstream(request):
                return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
            app = create_app(root, httpx.MockTransport(upstream))
            headers = {"X-Guardrail-Session": "a"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for step in range(1, 5):
                    await client.post("/v1/chat/completions", json={"messages": []}, headers=headers)
                    body = snapshot(step)
                    body["termination_context"] = {"declaration": "none", "source_kind": "scenario_rule",
                                                   "evidence": "test scenario not completed"}
                    response = await client.post("/sessions/observations", json=body, headers=headers)
                self.assertEqual(response.json()["observation"]["criteria"]["decision"], "deadlock")
            record = json.loads((Path(root) / "a.json").read_text(encoding="utf-8"))
            self.assertEqual(record["meta"]["criteria_version"], VERSION)
            self.assertEqual(record["meta"]["criteria_sha256"], pin_criteria()["criteria_sha256"])
            new = create_app(root)
            with self.assertLogs("session_store", level="WARNING"):
                recovered = new.state.store.get("a")
            self.assertEqual(recovered.meta, record["meta"])
            self.assertEqual(recovered.observations[-1]["criteria"]["first_deadlock_step"], 4)

    async def test_old_session_not_silently_assigned_new_criteria(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.json").write_text(json.dumps({"session_id": "a", "status": "active", "turns": []}), encoding="utf-8")
            app = create_app(root)
            with self.assertLogs("session_store", level="WARNING"):
                session = app.state.store.get("a")
            self.assertIsNone(session.meta.get("criteria_version"))
