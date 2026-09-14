import json
import tempfile
import unittest
from pathlib import Path

import httpx
import yaml

from proxy import create_app


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_tool_request_and_error_body_preserved(self):
        client = self.make_client()
        self.statuses = [400]
        self.response = {'error': {'code':'tool_use_failed','failed_generation':'{"name":"print_tree"}'}}
        tools = [{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]
        await self.chat(client, tools=tools, tool_choice='auto')
        turn = self.read()['turns'][0]
        self.assertEqual(turn['request_body']['tools'], tools)
        self.assertEqual(turn['upstream_request_body']['tool_choice'], 'auto')
        self.assertEqual(turn['response_body'], self.response)
        self.assertNotIn('authorization', turn['request_body'])

    async def test_seed_audit_success_does_not_claim_applied(self):
        client = self.make_client()
        await self.chat(client)
        audit = self.read()['turns'][0]['seed_audit']
        self.assertEqual(self.sent[0]['seed'], 42)
        self.assertEqual(audit['forwarded_seed'], 42)
        self.assertTrue(audit['forwarded'])
        self.assertTrue(audit['request_succeeded'])
        self.assertIsNone(audit['model_applied_seed'])
        self.assertEqual(self.read()['meta']['seed_status'], 'unverified')

    async def test_seed_audit_stripped_and_error(self):
        client = self.make_client({'models': {'fake-model': {'seed_supported': False}}})
        self.statuses = [400]
        await self.chat(client)
        audit = self.read()['turns'][0]['seed_audit']
        self.assertNotIn('seed', self.sent[0])
        self.assertFalse(audit['forwarded'])
        self.assertFalse(audit['request_succeeded'])
        self.assertEqual(audit['response_status'], 400)

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 100.0
        self.sent, self.waits = [], []
        self.statuses = [200]
        self.response = {"choices": [{"message": {"content": "answer"}}],
                         "usage": {"total_tokens": 3}}
        self.network_error = False
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()
        self.tmp.cleanup()

    def make_client(self, config=None):
        path = self.root / "guardrail.yaml"
        path.write_text(yaml.safe_dump(config or {}), encoding="utf-8")

        def upstream(request):
            self.sent.append(json.loads(request.content))
            self.now += .01
            if self.network_error:
                raise httpx.ConnectError("offline", request=request)
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(status, json=self.response)

        async def sleep(delay):
            self.waits.append(delay)
            self.now += delay + .001  # Scheduling overhead is measured, not assumed.

        app = create_app(self.root / "logs", httpx.MockTransport(upstream), sleep,
                         config_path=path, clock=lambda: self.now,
                         jitter=lambda lower, upper: (lower + upper) / 2)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.clients.append(client)
        return client

    async def chat(self, client, **overrides):
        body = {"model": "fake-model", "temperature": 0.2, "seed": 42,
                "max_tokens": 80, "messages": [{"role": "user", "content": "task"}]}
        body.update(overrides)
        return await client.post("/v1/chat/completions", json=body, headers={
            "X-Guardrail-Session": "run-a", "X-Guardrail-Scenario": "scenario-1",
            "X-Guardrail-Run-Index": "2", "X-Guardrail-Framework-Version": "test-framework/1",
        })

    def read(self):
        return json.loads((self.root / "logs" / "run-a.json").read_text(encoding="utf-8"))

    async def test_meta_conditions_end_and_restart_are_preserved(self):
        config = {"models": {"fake-model": {"seed_supported": True}}}
        client = self.make_client(config)
        await self.chat(client)
        meta = self.read()["meta"]
        self.assertEqual({k: meta[k] for k in ["model", "temperature", "seed", "max_tokens",
                         "scenario_id", "run_index", "framework_version"]}, {
            "model": "fake-model", "temperature": .2, "seed": 42, "max_tokens": 80,
            "scenario_id": "scenario-1", "run_index": 2, "framework_version": "test-framework/1"})
        self.assertIsNotNone(meta["started_at"])
        self.assertIsNone(meta["ended_at"])
        self.assertIsNone(meta["termination_reason"])
        restarted = self.make_client(config)
        with self.assertLogs("session_store", level="WARNING"):
            await self.chat(restarted)
        self.assertEqual(self.read()["meta"]["started_at"], meta["started_at"])
        await restarted.post("/sessions/end", headers={"X-Guardrail-Session": "run-a"},
                             json={"termination_reason": "max_messages"})
        ended = self.read()["meta"]
        self.assertEqual(ended["termination_reason"], "max_messages")
        self.assertIsNotNone(ended["ended_at"])
        await restarted.post("/sessions/end", headers={"X-Guardrail-Session": "run-a"})
        self.assertEqual(self.read()["meta"], ended)

    async def test_unsupported_seed_is_null_labelled_and_not_forwarded(self):
        client = self.make_client({"models": {"fake-model": {"seed_supported": False}}})
        await self.chat(client)
        meta = self.read()["meta"]
        self.assertIsNone(meta["seed"])
        self.assertEqual(meta["seed_status"], "unsupported")
        self.assertIn("미지원", meta["seed_note"])
        self.assertEqual(meta["requested_seed"], 42)
        self.assertNotIn("seed", self.sent[0])

    async def test_unknown_seed_does_not_claim_support(self):
        await self.chat(self.make_client())
        meta = self.read()["meta"]
        self.assertIsNone(meta["seed"])
        self.assertEqual(meta["seed_status"], "unverified")
        self.assertEqual(meta["requested_seed"], 42)

    async def test_backoff_success_stops_and_timing_excludes_wait(self):
        self.statuses = [429, 429, 200]
        response = await self.chat(self.make_client())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.waits, [.75, 1.5])
        turn = self.read()["turns"][0]
        self.assertEqual(turn["retry_count"], 2)
        self.assertAlmostEqual(turn["upstream_ms"], 30)
        self.assertAlmostEqual(turn["retry_wait_ms"], 2252)
        self.assertAlmostEqual(turn["total_ms"] - turn["retry_wait_ms"], 30)
        self.assertNotIn("elapsed", turn)

    async def test_exhausted_429_has_six_jittered_retries_no_final_sleep(self):
        self.statuses = [429]
        response = await self.chat(self.make_client())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(self.sent), 7)
        self.assertEqual(self.waits, [.75, 1.5, 3, 6, 12, 24])
        for n, delay in enumerate(self.waits):
            self.assertGreaterEqual(delay, 2 ** n / 2)
            self.assertLessEqual(delay, 2 ** n)
        self.assertEqual(len(self.read()["turns"]), 1)
        self.assertIsNone(self.read()["turns"][0]["tool_calls"])

    async def test_default_full_text_and_configured_truncation_only_affects_log(self):
        text = "가나다" * 400
        self.response["choices"][0]["message"]["content"] = text
        client = self.make_client()
        await self.chat(client, messages=[{"role": "user", "content": text}])
        self.assertEqual(self.read()["turns"][0]["in"], text)
        self.assertEqual(self.read()["turns"][0]["out"], text)
        client = self.make_client({"log": {"truncate": 10}})
        with self.assertLogs("session_store", level="WARNING"):
            response = await self.chat(client, messages=[{"role": "user", "content": text}])
        self.assertEqual(self.read()["turns"][1]["out"], text[:10])
        self.assertEqual(self.sent[-1]["messages"][0]["content"], text)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], text)

    async def test_tool_calls_count_all_choices_and_distinguish_zero_unknown(self):
        client = self.make_client()
        await self.chat(client)
        self.response["choices"] = [
            {"message": {"content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]}},
            {"message": {"content": None, "tool_calls": [{"id": "c"}]}},
        ]
        await self.chat(client)
        self.statuses = [500]
        await self.chat(client)
        self.assertEqual([t["tool_calls"] for t in self.read()["turns"]], [0, 3, None])

    async def test_cached_reachability_updates_on_http_and_network_failure(self):
        client = self.make_client()
        self.statuses = [503]
        await self.chat(client)
        cached = (await client.get("/healthz")).json()
        self.assertTrue(cached["upstream_reachable"])
        self.assertIsNotNone(cached["upstream_checked_at"])
        self.network_error = True
        self.assertEqual((await self.chat(client)).status_code, 502)
        self.assertFalse((await client.get("/healthz")).json()["upstream_reachable"])
        self.assertEqual(len(self.sent), 2)

    async def test_parameter_changes_are_flagged_and_recorded_per_turn(self):
        client = self.make_client()
        await self.chat(client)
        await self.chat(client, temperature=.7)
        record = self.read()
        self.assertTrue(record["meta"]["conditions_mixed"])
        self.assertEqual(record["meta"]["temperature"], .2)
        self.assertEqual(record["turns"][1]["request_params"]["temperature"], .7)
