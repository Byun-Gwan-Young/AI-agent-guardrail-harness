"""Proxy upstream read limit (C-18-7 part 0-1, DM-79). Offline only: in-memory proxy, a fake upstream that keeps the
read limit the way a network transport does. A generation is "simulated seconds" long; the fake waits one thousandth
of it, so 130 s takes 0.13 s."""
from pathlib import Path
import tempfile
import unittest

import httpx

import proxy
from pinned_configs import demo_model
from proxy import create_app

ROOT = Path(__file__).resolve().parents[1]
OBSERVE_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu.yaml"
DEMO_MODEL = demo_model()
HEADERS = {"X-Guardrail-Session": "slow", "X-Guardrail-Phase": "demo"}
SCALE = 0.001


class SlowUpstream(httpx.AsyncBaseTransport):
    """Answers after `seconds` of simulated generation, or raises ReadTimeout when that is past the request's read
    limit (httpcore applies request.extensions["timeout"] the same way; nothing is sent before the reply)."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.timeouts = []

    async def handle_async_request(self, request):
        import asyncio
        limit = request.extensions["timeout"]
        self.timeouts.append(limit)
        if limit["read"] is not None and self.seconds > limit["read"]:
            await asyncio.sleep(limit["read"] * SCALE)
            raise httpx.ReadTimeout("simulated read timeout", request=request)
        await asyncio.sleep(self.seconds * SCALE)
        return httpx.Response(200, json={"choices": [{"message": {"content": "late but whole"}}],
                                         "usage": {"prompt_tokens": 4, "completion_tokens": 5200,
                                                   "total_tokens": 5204}})


class ProxyReadLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())

    async def ask(self, seconds):
        upstream = SlowUpstream(seconds)
        app = create_app(Path(self.directory) / "logs", upstream, config_path=OBSERVE_CONFIG)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(client.aclose)
        response = await client.post("/v1/chat/completions", json={"messages": [{"content": "go"}], "model": DEMO_MODEL},
                                     headers=HEADERS)
        log = (await client.get("/log", headers=HEADERS)).json()
        return response, log["turns"][-1], upstream

    def test_limit_is_read_600_and_connect_120(self):
        self.assertEqual(proxy.UPSTREAM_TIMEOUT.as_dict(), {"connect": 120, "read": 600, "write": 120, "pool": 120})

    async def test_a_130_second_generation_is_forwarded_whole(self):
        # Under the earlier limit (120 s for every phase) this reply became the proxy's 502 (DM-79).
        response, turn, upstream = await self.ask(130)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "late but whole")
        self.assertEqual((turn["status_code"], turn["completion_tokens"]), (200, 5200))
        self.assertEqual(upstream.timeouts, [{"connect": 120, "read": 600, "write": 120, "pool": 120}])

    async def test_past_600_seconds_is_still_the_proxys_502(self):
        response, turn, _ = await self.ask(610)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"error": "Upstream connection failed"})
        self.assertEqual((turn["status_code"], turn["response_body"]), (502, {}))

    async def test_the_earlier_limit_would_have_cut_130_seconds(self):
        # The fake honours the limit it is given: with the old value the same reply is cut, so the test above passes
        # because of the new limit and not because the fake ignores limits.
        original = proxy.UPSTREAM_TIMEOUT
        proxy.UPSTREAM_TIMEOUT = httpx.Timeout(120)
        try:
            response, _, _ = await self.ask(130)
        finally:
            proxy.UPSTREAM_TIMEOUT = original
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
