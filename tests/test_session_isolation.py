import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from proxy import create_app


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = 0
        self.status = 200
        self.usage = {"total_tokens": 7, "prompt_tokens": 4, "completion_tokens": 3}

        def upstream(request):
            self.calls += 1
            return httpx.Response(self.status, json={
                "choices": [{"message": {"content": "ok"}}], "usage": self.usage,
            })

        async def no_sleep(seconds):
            pass

        self.transport = httpx.MockTransport(upstream)
        self.app = create_app(self.tmp.name, self.transport, no_sleep)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                        base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.tmp.cleanup()

    async def chat(self, key="run-a", body=None):
        return await self.client.post("/v1/chat/completions",
            headers={"X-Guardrail-Session": key} if key is not None else {},
            json=body if body is not None else {"messages": [{"role": "user", "content": "same task"}]})

    def read(self, key):
        return json.loads((Path(self.tmp.name) / f"{key}.json").read_text(encoding="utf-8"))

    async def test_two_runs_same_scenario_have_two_files_and_independent_turns(self):
        for key in ["run-a", "run-b"]:
            headers = {"X-Guardrail-Session": key}
            self.assertEqual((await self.client.post("/sessions", headers=headers)).status_code, 200)
            self.assertEqual((await self.chat(key)).status_code, 200)
            self.assertEqual((await self.chat(key)).status_code, 200)
            await self.client.post("/sessions/end", headers=headers)
            self.assertEqual([t["turn"] for t in self.read(key)["turns"]], [1, 2])
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 2)

    async def test_duplicate_start_and_closed_key_rejected_without_upstream_call(self):
        headers = {"X-Guardrail-Session": "run-a"}
        await self.chat()
        self.assertEqual((await self.client.post("/sessions", headers=headers)).status_code, 409)
        await self.client.post("/sessions/end", headers=headers)
        self.assertEqual((await self.chat()).status_code, 409)
        self.assertEqual(self.calls, 1)

    async def test_existing_file_preserved(self):
        path = Path(self.tmp.name) / "run-a.json"
        path.write_text("original", encoding="utf-8")
        self.assertEqual((await self.chat()).status_code, 409)
        self.assertEqual(path.read_text(encoding="utf-8"), "original")
        self.assertEqual(self.calls, 0)

    async def test_restart_recovers_active_and_preserves_turns(self):
        await self.chat()
        app = create_app(self.tmp.name, self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with self.assertLogs("session_store", level="WARNING"):
                r = await client.post("/v1/chat/completions", headers={"X-Guardrail-Session": "run-a"}, json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["turn"] for t in self.read("run-a")["turns"]], [1, 2])
        self.assertEqual(self.read("run-a")["status"], "active")

    async def test_create_failure_is_fail_open(self):
        with patch.object(self.app.state.store.repository, "create", side_effect=PermissionError("test")):
            with self.assertLogs("session_store", level="WARNING"):
                response = await self.chat()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.app.state.store.sessions["run-a"].turns), 1)

    async def test_ended_session_rejected_after_restart(self):
        await self.chat()
        await self.client.post("/sessions/end", headers={"X-Guardrail-Session": "run-a"})
        before = self.read("run-a")
        self.assertEqual(before["status"], "ended")
        app = create_app(self.tmp.name, self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for endpoint in ["/v1/chat/completions", "/sessions"]:
                r = await client.post(endpoint, headers={"X-Guardrail-Session": "run-a"}, json={})
                self.assertEqual(r.status_code, 409)
        self.assertEqual(self.read("run-a"), before)
        self.assertEqual(self.calls, 1)

    async def test_restart_can_end_active_session_without_chat(self):
        await self.chat()
        app = create_app(self.tmp.name, self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with self.assertLogs("session_store", level="WARNING"):
                r = await client.post("/sessions/end", headers={"X-Guardrail-Session": "run-a"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.read("run-a")["status"], "ended")

    async def test_explicit_start_rejects_active_file_after_restart(self):
        await self.chat()
        app = create_app(self.tmp.name, self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/sessions", headers={"X-Guardrail-Session": "run-a"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(self.read("run-a")["turns"]), 1)

    async def test_previous_closed_format_is_recovered(self):
        (Path(self.tmp.name) / "run-a.json").write_text(
            json.dumps({"session_id": "run-a", "closed": False, "turns": [{"turn": 1}]}),
            encoding="utf-8")
        with self.assertLogs("session_store", level="WARNING"):
            response = await self.chat()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.read("run-a")["status"], "active")
        self.assertEqual([t["turn"] for t in self.read("run-a")["turns"]], [1, 2])

    async def test_atomic_save_failure_preserves_previous_file_and_forwards(self):
        await self.chat()
        before = self.read("run-a")
        with patch("session_store.os.replace", side_effect=OSError("test")):
            with self.assertLogs("session_store", level="WARNING"):
                response = await self.chat()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.read("run-a"), before)
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])
        await self.chat()
        self.assertEqual([t["turn"] for t in self.read("run-a")["turns"]], [1, 2, 3])

    async def test_save_failure_is_fail_open(self):
        await self.chat()
        session = self.app.state.store.sessions["run-a"]
        with patch.object(self.app.state.store.repository, "save", side_effect=OSError("test")):
            with self.assertLogs("session_store", level="WARNING"):
                response = await self.chat()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "ok")
        self.assertEqual(len(session.turns), 2)

    async def test_http_errors_recorded_missing_usage_null_and_zero_preserved(self):
        for status in [400, 401, 429, 500, 503]:
            self.status, self.usage = status, None
            self.assertEqual((await self.chat()).status_code, status)
        self.status, self.usage = 200, {"total_tokens": 0}
        await self.chat()
        turns = self.read("run-a")["turns"]
        self.assertEqual([t["status_code"] for t in turns], [400, 401, 429, 500, 503, 200])
        self.assertTrue(all(t["tokens"] is None for t in turns[:-1]))
        self.assertEqual(turns[-1]["tokens"], 0)
        self.assertIsNone(turns[-1]["prompt_tokens"])

    async def test_hash_stable_and_header_takes_priority(self):
        r1, r2 = await self.chat(None), await self.chat(None)
        key = r1.headers["X-Guardrail-Session"]
        self.assertTrue(key.startswith("hash-"))
        self.assertEqual(r2.headers["X-Guardrail-Session"], key)
        self.assertEqual(len(self.read(key)["turns"]), 2)
        self.assertEqual((await self.chat()).headers["X-Guardrail-Session"], "run-a")

    async def test_connection_fallback_warns_and_is_stable(self):
        with self.assertLogs("proxy", level="WARNING"):
            a, b = await self.chat(None, {}), await self.chat(None, {})
        self.assertEqual(a.headers["X-Guardrail-Session"], b.headers["X-Guardrail-Session"])
        self.assertTrue(a.headers["X-Guardrail-Session"].startswith("connection-"))

    async def test_concurrent_turns_are_serialized(self):
        responses = await asyncio.gather(*(self.chat() for _ in range(5)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual([t["turn"] for t in self.read("run-a")["turns"]], list(range(1, 6)))

    async def test_unsafe_keys_rejected(self):
        for key in ["../escape", "CON", "a/b", "", "x" * 129]:
            self.assertEqual((await self.chat(key)).status_code, 400)
        self.assertEqual(self.calls, 0)


if __name__ == "__main__":
    unittest.main()
