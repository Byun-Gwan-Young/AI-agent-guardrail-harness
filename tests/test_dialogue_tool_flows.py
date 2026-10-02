"""C-17-6 part 3: the pre-run tool check, the PM search check tool (offline) and integration flows with the real tools
(CS: router + lookup_order + read_policy; MR: fake Tavily; LR: fake arXiv). Success is judged on the stored tool
records, replay recomputes it without searching, and no key string is left in the session folder."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments import dialogue_tools, search_tools
from t1_harness import DELIVERABLE, FIXTURES, report, run_t1
from tools import analyze_session, probe_search
from tools.rejudge_dialogue import rejudge
from search_fixtures import (ARXIV_200, KEY, LR, MR, TAVILY_200, FakeClock, FakeTransport, NoNetwork)

REAL = dict(dialogue_tools.IMPLEMENTATIONS)


def files_with(folder, needle):
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*") if p.is_file()
                  and needle.encode() in p.read_bytes())


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    async def refused(self, pattern, environ=None, **options):
        with mock.patch.dict(os.environ, environ or {}), self.assertRaisesRegex(ValueError, pattern) as raised:
            if "TAVILY_API_KEY" not in (environ or {}):
                os.environ.pop("TAVILY_API_KEY", None)
            await run_t1([], implementations=REAL, tests=self, **options)
        return str(raised.exception)

    async def test_a_missing_key_stops_before_any_call(self):
        transport = FakeTransport()
        with mock.patch.object(search_tools, "TRANSPORT", transport):
            message = await self.refused("Key environment variable not set: TAVILY_API_KEY", scenario_changes=MR)
        self.assertEqual(transport.calls, [])
        self.assertTrue(message.startswith("Pre-run check failed: "))

    async def test_missing_inputs_and_tools_are_all_named(self):
        # The harness resolves inputs_dir against tests/fixtures; an empty inputs folder is made there for the test.
        with tempfile.TemporaryDirectory(dir=FIXTURES / "scenario_assets") as tmp:
            (Path(tmp) / "policies").mkdir()
            relative = Path(tmp).relative_to(FIXTURES).as_posix()
            with self.assertRaises(ValueError) as raised:
                await run_t1([], implementations={"lookup_order": REAL["lookup_order"]}, tests=self,
                             scenario_changes={"turn_order": "fixed", "inputs_dir": relative})
        self.assertEqual(str(raised.exception),
                         "Pre-run check failed: Tools without an implementation: read_policy; "
                         "lookup_order input: orders.json not found; read_policy input: policies/ has no policy document")
        with self.assertRaises(ValueError) as raised:
            await run_t1([], implementations=REAL, tests=self,
                         scenario_changes={"turn_order": "fixed", "inputs_dir": "scenario_assets/NOT-THERE"})
        self.assertEqual(str(raised.exception), "Pre-run check failed: inputs_dir not found: scenario_assets/NOT-THERE")

    async def test_a_run_folder_is_not_made_when_refused(self):
        # The session ID (and with it the run folder) is made only after the check; reaching it fails the test.
        with mock.patch.dict(os.environ), \
                mock.patch("experiments.dialogue_runner.uuid.uuid4", side_effect=AssertionError("run folder made")):
            os.environ.pop("TAVILY_API_KEY", None)
            with self.assertRaisesRegex(ValueError, "^Pre-run check failed: Key environment variable not set"):
                await run_t1([], implementations=REAL, scenario_changes=MR, tests=self)

    async def test_the_check_is_recorded(self):
        reports = [report("triage"), report("triage"), report("triage")]
        with mock.patch.object(search_tools, "TRANSPORT", FakeTransport()), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": KEY}):
            run = await run_t1(reports, implementations=REAL, scenario_changes=MR, max_steps=3, tests=self)
        self.assertEqual(run["conditions"]["tool_preflight"],
                         {"check": "dialogue-tool-preflight-v1", "tools_implemented": ["web_search"],
                          "keys": {"TAVILY_API_KEY": "present"}, "inputs_dir": "scenario_assets/TEST-T1-v2",
                          "input_problems": {}})
        self.assertEqual(files_with(run["root"], KEY), [])


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_cs_router_with_order_lookup_and_policy(self):
        tools = {1: ("lookup_order", {"order_id": "A-100"}), 2: ("read_policy", {"name": "refund.md"})}
        reports = [report("triage", handoff="refund", adopted=["ticket"]),
                   report("assigned", handoff="intake", adopted=["ticket", "owner"]),
                   report("resolved", adopted=["ticket", "owner", "code"], deliverable=DELIVERABLE, declared=True,
                          issues=())]
        run = await run_t1(reports, tools=tools, implementations=REAL, max_steps=4, tests=self)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual((run["code"], summary["termination_reason"]), (0, "success"))
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "intake"])
        self.assertEqual([(r["tool"], r["is_error"], r["source"]["file"]) for r in run["dispatch"]],
                         [("lookup_order", False, "orders.json"), ("read_policy", False, "policies/refund.md")])
        # The judge read the stored call records: the deliverable's order was looked up.
        self.assertEqual(steps[-1]["completion_claim"]["gate"], {"machine_success": True, "result": "resolved",
                                                                 "missing": []})
        again = rejudge(run["out"], FIXTURES)
        self.assertTrue(again["all_same"] and again["judge"]["same_file"])
        self.assertEqual(again["search_calls"], 0)

    async def test_cs_success_needs_the_order_in_the_tool_records(self):
        tools = {1: ("lookup_order", {"order_id": "Z-9"})}
        reports = [report("triage", handoff="refund"), report("assigned", handoff="intake"),
                   report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=tools, implementations=REAL, max_steps=3, tests=self)
        claim = run["steps"][-1]["completion_claim"]
        self.assertEqual((claim["accepted"], claim["gate"]["missing"]), (False, ["order_id_not_looked_up"]))
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")

    async def mr(self, sources, *responses, max_steps=3):
        transport = FakeTransport(*(responses or [(200, TAVILY_200)]))
        reports = [report("triage", adopted=["a"]), report("assigned", adopted=["a", "b"]),
                   report("resolved", adopted=["a", "b", "c"], deliverable={"sources": sources}, declared=True,
                          issues=())]
        with mock.patch.object(search_tools, "TRANSPORT", transport), mock.patch.dict(os.environ, {"TAVILY_API_KEY": KEY}):
            run = await run_t1(reports, tools={2: ("web_search", {"query": "AI coding assistant pricing"})},
                               implementations=REAL, scenario_changes=MR, max_steps=max_steps, tests=self)
        return run, transport

    async def test_mr_success_from_stored_search_results_and_replay_without_search(self):
        run, transport = await self.mr(["https://example.org/tool-b/plans", "https://example.com/tool-a/pricing"])
        summary, out = run["summary"], run["out"]
        self.assertEqual((run["code"], summary["termination_reason"]), (0, "success"))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(summary["search"]["requests_sent"], {"web_search": 1})
        [call] = run["dispatch"]
        record = json.loads((out / search_tools.RECORDS_FILE).read_text(encoding="utf-8"))
        self.assertEqual((call["search"]["record_seq"], call["search"]["response_sha256"]),
                         (record["seq"], search_tools.sha256(TAVILY_200)))
        self.assertEqual((out / record["response"]["path"]).read_bytes(), TAVILY_200)
        self.assertEqual(call["result"], record["model_text"])
        # Replay: judge recomputation from the stored responses only.
        no_network = NoNetwork()
        with mock.patch.object(search_tools, "TRANSPORT", no_network):
            again = rejudge(out, FIXTURES)
        self.assertEqual(no_network.calls, [])
        self.assertTrue(again["all_same"])
        self.assertEqual((again["search_calls"], again["stored_responses_checked"], again["searched_again"]),
                         (1, 1, False))
        self.assertEqual(again["steps"][-1]["recomputed_claim_gate"]["result"], "resolved")
        # No key string anywhere in the session folder, the proxy log or the conditions.
        self.assertEqual(files_with(run["root"], KEY), [])
        self.assertEqual(run["conditions"]["search"]["web_search"]["key_env"], "TAVILY_API_KEY")

    async def test_mr_a_source_not_in_the_results_is_not_success(self):
        run, _ = await self.mr(["https://example.com/elsewhere"])
        claim = run["steps"][-1]["completion_claim"]
        self.assertEqual((claim["accepted"], claim["gate"]["missing"]),
                         (False, ["source_not_in_search_results:https://example.com/elsewhere"]))
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")
        self.assertTrue(rejudge(run["out"], FIXTURES)["all_same"])

    async def test_mr_a_failed_search_is_an_error_result_and_the_run_goes_on(self):
        run, transport = await self.mr(["https://example.org/tool-b/plans"], TimeoutError("timed out"))
        self.assertEqual(len(transport.calls), 1)
        step = run["steps"][1]
        self.assertEqual((step["step_status"], step["failure_reasons"]), ("failed", ["tool_execution_error"]))
        self.assertEqual(step["tool_executions"][0]["error_summary"],
                         "web_search failed: no response from Tavily (timed out). No results.")
        self.assertEqual(run["summary"]["search"]["outcomes"], {"timeout": 1})
        self.assertEqual(run["steps"][-1]["completion_claim"]["gate"]["missing"],
                         ["source_not_in_search_results:https://example.org/tool-b/plans"])
        self.assertTrue(rejudge(run["out"], FIXTURES)["all_same"])

    async def test_lr_two_searches_keep_the_interval_and_the_manifest_records_them(self):
        clock = FakeClock()
        transport = FakeTransport((200, ARXIV_200), (200, ARXIV_200))
        reports = [report("triage", adopted=["a"]), report("assigned", adopted=["a", "b"]),
                   report("assigned", adopted=["a", "b"]), report("assigned", adopted=["a", "b"]),
                   report("assigned", adopted=["a", "b"]),
                   report("resolved", adopted=["a", "b", "c"], declared=True, issues=(),
                          deliverable={"sources": ["2601.00001v1", "cs/0101001v3"]})]
        tools = {2: ("academic_search", {"query": 'all:"multi-agent"'}), 5: ("academic_search", {"query": "ti:failure"})}
        with mock.patch.object(search_tools, "TRANSPORT", transport), \
                mock.patch.object(search_tools, "CLOCK", clock.clock), mock.patch.object(search_tools, "SLEEP", clock.sleep):
            run = await run_t1(reports, tools=tools, implementations=REAL, scenario_changes=LR, max_steps=6, tests=self)
        self.assertEqual((run["code"], run["summary"]["termination_reason"]), (0, "success"))
        self.assertEqual(len(transport.calls), 2)
        # Both calls in one process: the second waited for the 3 s interval (the fake clock does not move otherwise).
        self.assertEqual(clock.slept, [3.0])
        self.assertEqual(run["summary"]["search"]["responses_stored"], 1)
        again = rejudge(run["out"], FIXTURES)
        self.assertTrue(again["all_same"])
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            manifest = analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])
            scan = analyze_session.analyse(run["session_id"])["secret_scan"]
        self.assertEqual(manifest["manifest_version"], "session-manifest-v0.6")
        self.assertEqual(manifest["task"]["tool_settings"], {"academic_search": LR["tool_settings"]["academic_search"]})
        self.assertEqual(manifest["task"]["search"]["academic_search"]["provider"], "arxiv")
        self.assertEqual(manifest["search"]["requests_sent"], {"academic_search": 2})
        self.assertEqual(manifest["task"]["tool_preflight"]["keys"], {})
        # D-11 for a run with search tools: the Tavily pattern is part of the scan.
        self.assertIn("tavily_key", scan["patterns"])
        self.assertTrue(scan["clean"])


class ProbeTests(unittest.TestCase):
    def run_probe(self, *responses, environ=None):
        transport = FakeTransport(*responses)
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = probe_search.main(["--output-root", str(tmp)], transport=transport,
                                     environ={"TAVILY_API_KEY": KEY} if environ is None else environ)
        folders = list(tmp.iterdir())
        result = json.loads((folders[0] / "result.json").read_text(encoding="utf-8")) if folders else None
        return code, result, transport, folders[0] if folders else None, stderr.getvalue()

    def test_fixture_shaped_responses_pass_and_are_stored(self):
        code, result, transport, folder, _ = self.run_probe((200, TAVILY_200), (200, ARXIV_200))
        self.assertEqual((code, result["all_ok"], result["llm_calls"], result["requests_sent"]), (0, True, 0, 2))
        self.assertEqual([c["method"] for c in transport.calls], ["POST", "GET"])
        self.assertEqual((folder / "tavily-response.json").read_bytes(), TAVILY_200)
        self.assertEqual((folder / "arxiv-response.xml").read_bytes(), ARXIV_200)
        for name in ("tavily", "arxiv"):
            shape = result["providers"][name]["shape"]
            self.assertEqual((shape["same_shape"], shape["missing_in_response"], shape["type_differences"]),
                             (True, [], {}))
        self.assertEqual(result["providers"]["arxiv"]["normalized"]["results"], 3)
        self.assertEqual((result["secret_scan"]["clean"], files_with(folder, KEY)), (True, []))
        self.assertNotIn("Authorization", json.dumps(result["providers"]["tavily"]["request"]["headers"]))

    def test_a_changed_shape_is_reported(self):
        changed = json.loads(TAVILY_200)
        for item in changed["results"]:
            item.pop("content")
            item["score"] = "high"
        changed["usage"] = {"credits": 1}
        code, result, _, _, _ = self.run_probe((200, json.dumps(changed).encode()), (200, ARXIV_200))
        shape = result["providers"]["tavily"]["shape"]
        self.assertEqual(code, 1)
        self.assertEqual((shape["same_shape"], shape["tool_fields_present"]), (False, False))
        self.assertEqual(shape["missing_in_response"], ["results[].content"])
        self.assertEqual(shape["extra_in_response"], ["usage", "usage.credits"])
        self.assertEqual(shape["type_differences"], {"results[].score": {"fixture": ["number"], "response": ["string"]}})

    def test_optional_arxiv_elements_absent_is_not_a_change(self):
        lean = ARXIV_200
        for element in (b"arxiv:comment", b"arxiv:doi", b"arxiv:journal_ref", b"arxiv:affiliation"):
            start = lean.index(b"<" + element)
            lean = lean[:start] + lean[lean.index(b"</" + element + b">", start) + len(element) + 3:]
        code, result, _, _, _ = self.run_probe((200, TAVILY_200), (200, lean))
        shape = result["providers"]["arxiv"]["shape"]
        self.assertEqual((code, shape["same_shape"], len(shape["optional_absent"])), (0, True, 4))

    def test_without_the_key_nothing_is_sent(self):
        code, result, transport, folder, stderr = self.run_probe(environ={})
        self.assertEqual((code, result, folder, transport.calls), (2, None, None, []))
        self.assertEqual(stderr.strip(), "TAVILY_API_KEY is not set; nothing was sent.")

    def test_a_network_error_and_an_echoed_key(self):
        echoed = TAVILY_200.replace(b"AI coding assistant pricing", KEY.encode())
        code, result, _, folder, _ = self.run_probe((200, echoed), OSError("unreachable " + KEY))
        self.assertEqual(code, 1)
        self.assertEqual(result["providers"]["arxiv"]["outcome"], "no_response")
        self.assertTrue(result["providers"]["tavily"]["response"]["redacted"])
        self.assertEqual(files_with(folder, KEY), [])


if __name__ == "__main__":
    unittest.main()
