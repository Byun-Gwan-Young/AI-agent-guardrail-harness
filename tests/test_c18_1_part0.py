"""C-18-1 part 0 (DM-58 ③ ④): gateway prices with the glm cached-input price, the runner's /credits/ readings around a
scenario-v2 session (credits_measured) and the manifest's estimated and measured credits side by side. Offline."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tools import gateway_prices  # noqa: E402
from experiments import gateway_usage  # noqa: E402
from tools import analyze_session, c18_1_evidence, probe_gateway  # noqa: E402
import t1_harness  # noqa: E402
import t2_harness  # noqa: E402

DEMO = {"model": None, "reasoning_effort": None, "reasoning_effort_evidence": None,
        "run_conditions": "demo-conditions.yaml"}


def turn(prompt, completion, cached=0, reasoning=0, tokens=True):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion,
             "prompt_tokens_details": {"cached_tokens": cached},
             "completion_tokens_details": {"reasoning_tokens": reasoning}}
    return {"tokens": prompt + completion if tokens else None, "prompt_tokens": prompt, "completion_tokens": completion,
            "response_body": {"usage": usage}}


def reading(used, at, field="monthly_allocated.used"):
    return {"read_at": at, "http_status": 200, "used": used, "field": field}


class Prices(unittest.TestCase):
    def test_probe_evidence_matches_the_table(self):
        evidence = c18_1_evidence.prices()
        self.assertEqual(evidence["glm_cached_rate_per_million"], 30.0)
        self.assertTrue(evidence["glm_no_cache_check"]["prices_reproduce_credits"])
        self.assertTrue(all(v if isinstance(v, bool) else all(v.values())
                            for v in evidence["table_matches"].values()))

    def test_glm_estimate_reproduces_the_cached_probe_request(self):
        # gateway-probe-44ec8e43… second request: 1,094 prompt (1,088 cached), 610 completion, 0.33854 credits.
        result = gateway_prices.estimate("glm-5.3-flash", [turn(1094, 610, cached=1088, reasoning=410)])
        self.assertEqual((result["status"], result["value"]), ("computed", 0.33854))
        self.assertEqual(result["tokens"]["cached_prompt"], 1088)
        self.assertEqual(result["cached_price"], "known")

    def test_unknown_cached_price_is_charged_at_the_input_price(self):
        result = gateway_prices.estimate("qwen3.8-flash", [turn(1000, 100, cached=800)])
        self.assertEqual(result["value"], round((1000 * 150 + 100 * 470) / 1e6, 5))
        self.assertTrue(result["cached_price"].startswith("unknown"))

    def test_missing_price_and_missing_usage(self):
        self.assertEqual(gateway_prices.estimate("other-model", [turn(1, 1)])["status"], "unmeasured")
        partial = gateway_prices.estimate("glm-5.3-flash", [turn(1000, 10), turn(5, 5, tokens=False)])
        self.assertEqual((partial["status"], partial["tokens"]["usage_missing_turns"]), ("incomplete", 1))
        self.assertEqual(partial["value"], round((1000 * 150 + 10 * 500) / 1e6, 5))

    def test_gpt_oss_manifest_credits_unchanged(self):
        counts = {"known_prompt": 1000, "known_completion": 100, "total_status": "measured"}
        self.assertEqual(analyze_session.session_credits(gateway_prices.GPT_OSS, counts, [turn(1000, 100)]),
                         analyze_session.session_credits(gateway_prices.GPT_OSS, counts))


class Readings(unittest.TestCase):
    def test_fields_are_the_probe_fields(self):
        self.assertEqual(gateway_usage.CREDIT_USED_FIELDS, probe_gateway.CREDIT_USED_FIELDS)
        self.assertEqual(gateway_usage.CREDITS_PATH, probe_gateway.CREDITS_PATH)

    def test_record(self):
        measured = gateway_usage.record(reading(10.5, "a"), reading(12.75, "b"))
        self.assertEqual((measured["status"], measured["value"], measured["field"]),
                         ("measured", 2.25, "monthly_allocated.used"))
        self.assertTrue(measured["exact_only_if_alone"])
        self.assertEqual(gateway_usage.record(None, None)["status"], "unmeasured")
        self.assertEqual(gateway_usage.record(reading(1, "a"), {"read_at": "b", "error": "ConnectTimeout"})["status"],
                         "unmeasured")
        mixed = gateway_usage.record(reading(1, "a"), reading(2, "b", "total.used"))
        self.assertIn("different fields", mixed["reason"])

    def test_reading_never_raises_and_sends_the_key_only_in_the_header(self):
        seen = []

        def answer(request):
            seen.append(request)
            return httpx.Response(200, json={"monthly_allocated": {"used": 7.5}})
        real = httpx.AsyncClient

        class Client(real):
            def __init__(self, *a, **kw):
                super().__init__(*a, transport=httpx.MockTransport(answer), **kw)
        upstream = {"base_url": "https://gateway.example/v1/gateway"}
        with mock.patch("httpx.AsyncClient", Client):
            result = asyncio.run(gateway_usage.reading(upstream, "secret-value"))
        self.assertEqual((result["used"], result["field"]), (7.5, "monthly_allocated.used"))
        self.assertEqual(str(seen[0].url), "https://gateway.example/v1/gateway/credits/")
        self.assertEqual(seen[0].headers["authorization"], "Bearer secret-value")
        self.assertNotIn("secret-value", json.dumps(result))

        def broken(request):
            raise httpx.ConnectError("down")

        class Down(real):
            def __init__(self, *a, **kw):
                super().__init__(*a, transport=httpx.MockTransport(broken), **kw)
        with mock.patch("httpx.AsyncClient", Down):
            self.assertEqual(asyncio.run(gateway_usage.reading(upstream, "k"))["error"], "ConnectError")
        self.assertIn("no upstream", asyncio.run(gateway_usage.reading(None, "k"))["error"])


def artifact_reports():
    return [t2_harness.report(contract="output-contract-v2"),
            t2_harness.report(contract="output-contract-v2"),
            t2_harness.report(declared=True, contract="output-contract-v2")]


class RunnerRecords(unittest.IsolatedAsyncioTestCase):
    async def run_artifact(self, readings):
        calls = []

        async def fake(upstream, key):
            calls.append((upstream.get("base_url"), key))
            return readings.pop(0)
        with mock.patch.object(gateway_usage, "reading", fake):
            run = await t2_harness.run_t2(artifact_reports(), tools={2: t2_harness.write(t2_harness.source(16))},
                                          contract="output-contract-v2", max_steps=3, tests=self,
                                          scenario_changes=DEMO)
        return run, calls

    async def test_artifact_run_records_two_readings(self):
        run, calls = await self.run_artifact([reading(100.0, "t0"), reading(100.42, "t1")])
        self.assertEqual(run["summary"]["termination_reason"], "success")
        usage = run["summary"]["gateway_usage"]
        self.assertEqual((usage["status"], usage["value"]), ("measured", 0.42))
        self.assertEqual([c[1] for c in calls], ["fake", "fake"])
        self.assertEqual(calls[0][0], run["conditions"]["upstream"]["base_url"])
        # The readings are not model requests: the fake upstream saw only chat requests.
        self.assertTrue(all("messages" in body for body in run["requests"]))
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            manifest = analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])
        self.assertNotIn("credits", manifest)
        self.assertEqual(manifest["credits_measured"]["value"], 0.42)
        estimated = manifest["credits_estimated"]
        self.assertEqual((estimated["status"], estimated["model"]), ("computed", "glm-5.3-flash"))
        self.assertEqual(estimated["value"], gateway_prices.estimate("glm-5.3-flash", run["session"]["turns"])["value"])

    async def test_failed_reading_does_not_stop_the_session(self):
        run, _ = await self.run_artifact([{"read_at": "t0", "error": "ConnectError"},
                                          {"read_at": "t1", "error": "ConnectError"}])
        self.assertEqual(run["summary"]["termination_reason"], "success")
        self.assertEqual(run["summary"]["gateway_usage"]["status"], "unmeasured")

    async def test_unpatched_reading_stays_offline_and_unmeasured(self):
        # In the harness the reading reaches the in-memory proxy, which has no /credits/ route (no network, 404).
        run = await t2_harness.run_t2(artifact_reports(), tools={2: t2_harness.write(t2_harness.source(16))},
                                      contract="output-contract-v2", max_steps=3, tests=self, scenario_changes=DEMO)
        usage = run["summary"]["gateway_usage"]
        self.assertEqual((usage["status"], usage["before"]["http_status"]), ("unmeasured", 404))
        self.assertEqual(run["summary"]["termination_reason"], "success")

    async def test_dialogue_run_records_two_readings(self):
        readings = [reading(5.0, "t0"), reading(5.5, "t1")]

        async def fake(upstream, key):
            return readings.pop(0)
        report = {"narrative": "n", "status": "received", "handoff_to": "refund", "adopted_items": [],
                  "deliverable": None, "open_issue_ids": [], "unlisted_issues": [], "info_items": None,
                  "completion_declared": False}
        with mock.patch.object(gateway_usage, "reading", fake):
            run = await t1_harness.run_t1([report], max_steps=1, tests=self)
        self.assertEqual(run["summary"]["gateway_usage"]["value"], 0.5)

    def test_scenario_v1_runs_read_no_credits(self):
        source = (ROOT / "experiments/run_scenario.py").read_text(encoding="utf-8")
        self.assertIn("            if artifact_v2:\n                upstream_meta = meta.get('upstream')", source)


class KeycheckCommitted(unittest.TestCase):
    def test_c17_7_keycheck_is_tracked_and_clean(self):
        path = "reports/c17-7/evidence-keycheck.json"
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=ROOT, capture_output=True)
        self.assertEqual(tracked.returncode, 0)
        scan = json.loads((ROOT / path).read_text(encoding="utf-8"))["probe_9d2b2053_secret_scan"]
        # The PM ran it with the key in the environment: the key value itself was searched for (D-11).
        self.assertEqual((scan["clean"], scan["hits"], scan["environment_variables_checked"]),
                         (True, {}, {"KMU_API_KEY": "set"}))


if __name__ == "__main__":
    unittest.main()
