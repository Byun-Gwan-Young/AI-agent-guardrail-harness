import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from artifact_hook import submit_observation
from proxy import create_app
from test_progress_signal import snapshot


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clients = []
        self.calls = 0

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()
        self.tmp.cleanup()

    def client(self, judgement_clock_ns=None):
        def response(request):
            self.calls += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "timeout: 500 ms"}}]})
        options = {} if judgement_clock_ns is None else {'judgement_clock_ns': judgement_clock_ns}
        app = create_app(self.tmp.name, httpx.MockTransport(response), **options)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.clients.append(client)
        return app, client

    async def turn(self, client):
        return await client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "task"}]},
                                 headers={"X-Guardrail-Session": "a"})

    async def test_hook_submit_persistence_restart_and_recurrence(self):
        app, client = self.client()
        for n, value in [(1, 500), (2, 800)]:
            response = await self.turn(client)
            self.assertEqual(response.headers["X-Guardrail-Turn"], str(n))
            result = await submit_observation(client, "a", snapshot(n, proposal=value))
            self.assertTrue(result["persisted"])
        app2, client2 = self.client()
        with self.assertLogs("session_store", level="WARNING"):
            await self.turn(client2)
        result = await submit_observation(client2, "a", snapshot(3))
        self.assertEqual(result["observation"]["progress"]["state"], "oscillating")
        record = json.loads((Path(self.tmp.name) / "a.json").read_text(encoding="utf-8"))
        self.assertEqual(len(record["observations"]), 3)
        self.assertEqual(record["turns"][0]["conversation_extracted"]["source_kind"], "extracted")

    async def test_same_payload_idempotent_different_payload_conflicts(self):
        app, client = self.client()
        await self.turn(client)
        first = await submit_observation(client, "a", snapshot(1))
        second = await submit_observation(client, "a", snapshot(1))
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["observation"], second["observation"])
        changed = await client.post("/sessions/observations", json=snapshot(1, proposal=800),
                                    headers={"X-Guardrail-Session": "a"})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(len(app.state.store.sessions["a"].observations), 1)
        self.assertEqual(self.calls, 1)

    async def test_reject_unknown_turn_out_of_order_and_invalid_schema(self):
        app, client = self.client()
        await self.turn(client)
        for payload, status in [(snapshot(2), 409), ({**snapshot(1), "llm_turns": [99]}, 409),
                                ({**snapshot(1), "progress": {"state": "progress"}}, 422)]:
            response = await client.post("/sessions/observations", json=payload,
                                         headers={"X-Guardrail-Session": "a"})
            self.assertEqual(response.status_code, status)

    async def test_observation_save_failure_reports_unpersisted_and_retry_flushes(self):
        app, client = self.client()
        await self.turn(client)
        with patch.object(app.state.store.repository, "save", side_effect=OSError("test")):
            with self.assertLogs("session_store", level="WARNING"):
                result = await submit_observation(client, "a", snapshot(1))
        self.assertFalse(result["persisted"])
        result = await submit_observation(client, "a", snapshot(1))
        self.assertTrue(result["persisted"])
        self.assertTrue(result["duplicate"])

    async def test_extractor_failure_does_not_block_response(self):
        app, client = self.client()
        with patch("proxy.extract_conversation", side_effect=RuntimeError("test")):
            with self.assertLogs("proxy", level="WARNING"):
                response = await self.turn(client)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(app.state.store.sessions["a"].turns[0]["conversation_extracted"])

    async def test_paired_comparison_recorded_without_affecting_verdict(self):
        app, client = self.client()
        await self.turn(client)
        payload = snapshot(1)
        payload["extracted_conversation"] = {"source_kind": "extracted", "proposal_values": {"timeout_ms": 999}}
        result = await submit_observation(client, "a", payload)
        self.assertFalse(result["observation"]["extraction_comparison"]["proposal_values"]["match"])
        self.assertEqual(result["observation"]["conversation"]["proposal_values"]["timeout_ms"], 500)

    async def test_judgement_uses_process_monotonic_nanoseconds_only(self):
        ticks = iter((1000, 1450))
        app, client = self.client(lambda: next(ticks))
        await self.turn(client)
        result = await submit_observation(client, "a", snapshot(1))
        self.assertEqual(result["observation"]["judgement_ns"], 450)
        stored = json.loads((Path(self.tmp.name) / "a.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["observations"][0]["judgement_ns"], 450)
