"""C-17-6 part 2: web_search (Tavily) and academic_search (arXiv) with every response stored as received (DM-13,
DM-21), settings from the scenario, fact-sentence errors without retry, and replay from the stored responses only."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse

from pydantic import ValidationError
import yaml

from experiments import dialogue_tools, search_tools
from experiments.tool_results import ToolFactError
from scenario_schema import ScenarioV2
from search_fixtures import (ACADEMIC, ARXIV_200, ARXIV_400, KEY, LR, MR, TAVILY_200, TAVILY_432, WEB, FakeClock,
                             FakeTransport, NoNetwork)
from t1_harness import FIXTURE, FIXTURES


def judge_module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), FIXTURES / "scenario_judges" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.judge


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clock = FakeClock()

    def session(self, *responses, settings=None, environ=None):
        self.transport = FakeTransport(*responses)
        self.search = search_tools.SearchSession(
            settings or {"web_search": WEB, "academic_search": ACADEMIC}, self.dir,
            environ={"TAVILY_API_KEY": KEY} if environ is None else environ, transport=self.transport,
            clock=self.clock.clock, sleep=self.clock.sleep, now=lambda: "2026-10-02T00:00:00+00:00")
        self.dispatch = dialogue_tools.ToolDispatch(dialogue_tools.IMPLEMENTATIONS, FIXTURES, {"search": self.search})
        self.dispatch.step_id, self.dispatch.agent_id = 2, "searcher"
        return dict(zip(("web_search", "academic_search"), self.dispatch.tools(["web_search", "academic_search"])))

    def records(self):
        path = self.dir / search_tools.RECORDS_FILE
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TavilyTests(Case):
    def test_request_storage_results_and_model_text(self):
        tools = self.session((200, TAVILY_200))
        text = tools["web_search"]("AI coding assistant pricing")
        call = self.transport.calls[0]
        self.assertEqual((call["method"], call["url"], call["timeout"]), ("POST", search_tools.TAVILY_ENDPOINT, 20.0))
        self.assertEqual(json.loads(call["body"]), {"query": "AI coding assistant pricing", "search_depth": "basic",
                                                    "topic": "general", "max_results": 3, "include_answer": False,
                                                    "include_raw_content": False, "include_images": False})
        self.assertEqual(call["headers"]["Authorization"], "Bearer " + KEY)
        [record] = self.records()
        # Stored exactly as received, under its sha256; the request record has no key.
        stored = self.dir / record["response"]["path"]
        self.assertEqual((stored.read_bytes(), record["response"]["sha256"], record["response"]["redacted"]),
                         (TAVILY_200, search_tools.sha256(TAVILY_200), False))
        self.assertEqual(record["request"]["body"], json.loads(call["body"]))
        self.assertNotIn("Authorization", record["request"]["headers"])
        self.assertNotIn(KEY, json.dumps(record))
        self.assertEqual(record["results"][0], {"rank": 1, "title": "Tool A pricing (synthetic fixture)",
                                                "url": "https://example.com/tool-a/pricing",
                                                "excerpt": "Synthetic excerpt for offline tests. Tool A lists an "
                                                           "individual plan and a team plan."})
        # The model text is the normalized results; the record keeps it with its truncation result.
        shown = json.loads(text)
        self.assertEqual((shown["result_count"], shown["results_left_out"], shown["excerpts_cut_to_chars"]), (3, 0, None))
        self.assertEqual(shown["results"][1], {"title": "Tool B plans (synthetic fixture)",
                                               "url": "https://example.org/tool-b/plans",
                                               "excerpt": "Synthetic excerpt for offline tests. Tool B has a free "
                                                          "tier and a paid tier."})
        self.assertEqual((record["model_text"], record["outcome"], record["truncation"]["truncated"]), (text, "ok", False))
        self.assertEqual((record["settings"], record["dispatch_seq"], record["step_id"], record["agent_id"]),
                         (WEB, 1, 2, "searcher"))
        # The tool call record refers to it by seq and hash and carries the results for the judge.
        self.assertEqual(self.dispatch.records[0]["search"], {
            "record_seq": 1, "provider": "tavily", "outcome": "ok", "response_sha256": record["response"]["sha256"],
            "results": record["results"], "results_sent": 3, "total_results": None})
        self.assertEqual(self.dispatch.records[0]["result"], text)

    def test_a_key_echoed_by_the_provider_is_replaced_and_never_written(self):
        echoed = TAVILY_200.replace(b"AI coding assistant pricing", KEY.encode())
        tools = self.session((200, echoed), (401, b'{"detail": {"error": "bad key ' + KEY.encode() + b'"}}'))
        tools["web_search"]("q")
        with self.assertRaises(ToolFactError) as raised:
            tools["web_search"]("q")
        first, second = self.records()
        self.assertEqual((first["response"]["redacted"], first["response"]["received_sha256"]),
                         (True, search_tools.sha256(echoed)))
        self.assertNotIn(KEY, str(raised.exception))
        self.assertIn(search_tools.REDACTED, second["error"]["message"])
        for path in self.dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY.encode(), path.read_bytes(), path)


class ArxivTests(Case):
    def test_request_and_results(self):
        tools = self.session((200, ARXIV_200))
        text = tools["academic_search"]('all:"multi-agent" AND all:failure')
        url = self.transport.calls[0]["url"]
        self.assertTrue(url.startswith(search_tools.ARXIV_ENDPOINT + "?"))
        self.assertEqual(dict(urllib.parse.parse_qsl(url.split("?", 1)[1])),
                         {"search_query": 'all:"multi-agent" AND all:failure', "start": "0", "max_results": "3",
                          "sortBy": "relevance", "sortOrder": "descending"})
        self.assertNotIn("Authorization", self.transport.calls[0]["headers"])
        [record] = self.records()
        self.assertEqual([(r["id"], r["year"]) for r in record["results"]],
                         [("2601.00001v1", 2026), ("2602.00002v2", 2026), ("cs/0101001v3", 2001)])
        self.assertEqual(record["results"][0]["title"], "Synthetic Paper One: Failure Modes of Multi-Agent Systems")
        self.assertEqual(record["results"][0]["authors"], ["Test Author A", "Test Author B"])
        self.assertEqual(record["results"][0]["excerpt"], "Synthetic abstract for offline tests only. It has line "
                                                          "breaks and extra spaces that the tool collapses.")
        self.assertEqual(record["total_results"], 1234)
        self.assertEqual(json.loads(text)["total_results"], 1234)
        self.assertEqual((self.dir / record["response"]["path"]).read_bytes(), ARXIV_200)
        self.assertTrue(record["response"]["path"].endswith(".xml"))

    def test_the_request_interval(self):
        tools = self.session((200, ARXIV_200), (200, ARXIV_200), (200, TAVILY_200), (200, ARXIV_200))
        tools["academic_search"]("a")
        self.clock.now += 1.0
        tools["academic_search"]("b")
        tools["web_search"]("c")
        self.clock.now += 5.0
        tools["academic_search"]("d")
        # One arXiv request every 3 s from the end of the previous one; Tavily is not delayed.
        self.assertEqual(self.clock.slept, [2.0])
        self.assertEqual([r["waited_seconds"] for r in self.records()], [0.0, 2.0, 0.0, 0.0])


class LimitAndFailureTests(Case):
    def test_per_session_call_limit(self):
        tools = self.session((200, TAVILY_200), (200, TAVILY_200), settings={"web_search": {**WEB, "max_calls_per_session": 2}})
        tools["web_search"]("a")
        tools["web_search"]("b")
        with self.assertRaises(ToolFactError) as raised:
            tools["web_search"]("c")
        self.assertEqual(str(raised.exception),
                         "web_search was not run: the limit of 2 web_search calls for this session is reached.")
        self.assertEqual(len(self.transport.calls), 2)
        self.assertEqual([r["outcome"] for r in self.records()], ["ok", "ok", "limit_reached"])
        self.assertEqual(self.search.summary()["requests_sent"], {"web_search": 2})

    def test_failures_are_fact_errors_with_error_records_and_no_retry(self):
        cases = [
            ("web_search", TimeoutError("timed out"), "timeout",
             "web_search failed: no response from Tavily (timed out). No results."),
            ("web_search", urllib.error.URLError(TimeoutError("connect")), "timeout",
             "web_search failed: no response from Tavily (timed out). No results."),
            ("web_search", urllib.error.URLError("name resolution"), "network_error",
             "web_search failed: no response from Tavily (network error). No results."),
            ("web_search", (432, TAVILY_432), "http_error",
             "web_search failed: HTTP 432 from Tavily. This request exceeds your plan's set usage limit. "
             "(synthetic fixture) No results."),
            ("academic_search", (400, ARXIV_400), "http_error",
             "academic_search failed: HTTP 400 from arXiv. incorrect id format for 1234.12345 No results."),
            ("web_search", (200, b"<html>not json</html>"), "parse_error",
             "web_search failed: the Tavily response could not be read. No results."),
            ("academic_search", (200, ARXIV_400), "provider_error",
             "academic_search failed: arXiv returned an error: incorrect id format for 1234.12345 No results."),
        ]
        for tool, response, outcome, message in cases:
            with self.subTest(outcome=outcome, tool=tool):
                self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
                tools = self.session(response)
                with self.assertRaises(ToolFactError) as raised:
                    tools[tool]("q")
                self.assertEqual(str(raised.exception), message)
                self.assertEqual(len(self.transport.calls), 1)
                [record] = self.records()
                self.assertEqual((record["outcome"], record["model_text"], record["results"]), (outcome, message, None))
                stored = outcome in ("parse_error", "provider_error")
                # A failed request keeps an error record instead of a response; a 200 that cannot be read is stored.
                self.assertEqual(record["response"] is not None, stored)
                self.assertIsNotNone(record["error"])
                self.assertEqual(self.dispatch.records[0]["search"]["outcome"], outcome)
                self.assertTrue(self.dispatch.records[0]["is_error"])

    def test_invalid_query_and_missing_key_send_nothing(self):
        tools = self.session(environ={})
        for query, message in (("  ", "web_search needs query as a non-empty string."),
                               ("q", "web_search was not run: the search key is not configured.")):
            with self.assertRaises(ToolFactError) as raised:
                tools["web_search"](query)
            self.assertEqual(str(raised.exception), message)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual([r["outcome"] for r in self.records()], ["invalid_arguments", "missing_key"])


class TruncationTests(unittest.TestCase):
    normalized = search_tools.normalize("arxiv", ARXIV_200)

    def test_excerpts_are_cut_uniformly_to_fit(self):
        full, _ = search_tools.fit("arxiv", self.normalized, 100000)
        limit = len(full) - 40
        text, info = search_tools.fit("arxiv", self.normalized, limit)
        shown = json.loads(text)
        self.assertLessEqual(len(text), limit)
        self.assertEqual((info["truncated"], info["results_sent"], info["sent_chars"], info["full_chars"]),
                         (True, 3, len(text), len(full)))
        cap = info["excerpts_cut_to_chars"]
        self.assertEqual(shown["excerpts_cut_to_chars"], cap)
        for item, result in zip(shown["results"], self.normalized["results"]):
            expected = result["excerpt"] if len(result["excerpt"]) <= cap else result["excerpt"][:cap] + "…"
            self.assertEqual(item["excerpt"], expected)
        # The largest cut that fits: one more character does not.
        self.assertGreater(len(search_tools.render("arxiv", self.normalized, self.normalized["results"], cap + 1, 0)),
                           limit)

    def test_results_are_left_out_when_empty_excerpts_do_not_fit(self):
        text, info = search_tools.fit("arxiv", self.normalized, 200)
        shown = json.loads(text)
        self.assertLessEqual(len(text), 200)
        self.assertEqual((info["results_sent"], shown["results_left_out"], shown["excerpts_cut_to_chars"]),
                         (len(shown["results"]), 3 - len(shown["results"]), 0))
        self.assertLess(info["results_sent"], 3)

    def test_deterministic(self):
        self.assertEqual(search_tools.fit("arxiv", self.normalized, 500), search_tools.fit("arxiv", self.normalized, 500))


class ReplayTests(Case):
    def run_calls(self):
        tools = self.session((200, TAVILY_200), (200, ARXIV_200), (432, TAVILY_432))
        tools["web_search"]("a")
        tools["academic_search"]("b")
        with self.assertRaises(ToolFactError):
            tools["web_search"]("c")
        (self.dir / "tool-dispatch.json").write_text(json.dumps(self.dispatch.records, ensure_ascii=False),
                                                     encoding="utf-8")

    def test_replay_rebuilds_the_tool_records_from_stored_responses_only(self):
        self.run_calls()
        no_network = NoNetwork()
        original = search_tools.TRANSPORT
        search_tools.TRANSPORT = no_network
        try:
            records = search_tools.load_records(self.dir)
            replayed = search_tools.replay_tool_records(self.dir)
        finally:
            search_tools.TRANSPORT = original
        self.assertEqual(no_network.calls, [])
        self.assertEqual([r["outcome"] for r in records], ["ok", "ok", "http_error"])
        self.assertEqual(replayed, json.loads(json.dumps(self.dispatch.records)))
        # The judge gives the same answer on the live and the replayed tool records.
        mr = judge_module("TEST-MR-v2")
        report = {"status": "resolved", "deliverable": {"sources": ["https://example.org/tool-b/plans"]}}
        live = mr(copy.deepcopy(report), tool_records=copy.deepcopy(self.dispatch.records), inputs_dir=FIXTURES)
        self.assertEqual(live, {"machine_success": True, "result": "resolved", "missing": []})
        self.assertEqual(mr(copy.deepcopy(report), tool_records=replayed, inputs_dir=FIXTURES), live)
        unseen = {"status": "resolved", "deliverable": {"sources": ["https://example.com/elsewhere"]}}
        self.assertEqual(mr(unseen, tool_records=replayed, inputs_dir=FIXTURES)["missing"],
                         ["source_not_in_search_results:https://example.com/elsewhere"])
        lr = judge_module("TEST-LR-v2")
        papers = {"status": "resolved", "deliverable": {"sources": ["2601.00001v1", "cs/0101001v3"]}}
        self.assertEqual(lr(papers, tool_records=replayed, inputs_dir=FIXTURES)["result"], "resolved")

    def test_a_changed_stored_response_or_record_is_refused(self):
        self.run_calls()
        first = self.records()[0]
        stored = self.dir / first["response"]["path"]
        good = stored.read_bytes()
        stored.write_bytes(good.replace(b"Tool A", b"Tool Z"))
        with self.assertRaisesRegex(search_tools.ReplayMismatch, "stored response hash"):
            search_tools.load_records(self.dir)
        stored.write_bytes(good)
        lines = (self.dir / search_tools.RECORDS_FILE).read_text(encoding="utf-8").splitlines()
        changed = json.loads(lines[0])
        changed["results"][0]["url"] = "https://example.com/invented"
        (self.dir / search_tools.RECORDS_FILE).write_text("\n".join([json.dumps(changed)] + lines[1:]) + "\n",
                                                          encoding="utf-8")
        with self.assertRaisesRegex(search_tools.ReplayMismatch, "results differ"):
            search_tools.load_records(self.dir)


class SettingsSchemaTests(unittest.TestCase):
    def data(self, changes):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data.update(copy.deepcopy(changes))
        return data

    def test_research_shapes_validate(self):
        for changes in (MR, LR):
            scenario = ScenarioV2.model_validate(self.data(changes))
            tool = scenario.agents[1].tools[0]
            self.assertEqual(scenario.tool_settings.model_dump(exclude_none=True), {tool: changes["tool_settings"][tool]})

    def test_settings_go_with_the_tools(self):
        cases = {
            "used without settings": {**MR, "tool_settings": None},
            "settings without the tool": {"tool_settings": {"web_search": WEB}},
            "other tool's settings": {**MR, "tool_settings": {"web_search": WEB, "academic_search": ACADEMIC}},
            "arXiv faster than 3 s": {**LR, "tool_settings": {"academic_search": {**ACADEMIC, "min_interval_seconds": 1}}},
            "Tavily over 20 results": {**MR, "tool_settings": {"web_search": {**WEB, "max_results": 21}}},
            "missing setting": {**MR, "tool_settings": {"web_search": {k: v for k, v in WEB.items() if k != "topic"}}},
            "unknown setting": {**MR, "tool_settings": {"web_search": {**WEB, "include_answer": True}}},
        }
        for name, changes in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError):
                ScenarioV2.model_validate(self.data(changes))

    def test_the_tool_interface_has_no_result_count_argument(self):
        dispatch = dialogue_tools.ToolDispatch({}, FIXTURES)
        web, academic = dispatch.tools(["web_search", "academic_search"])
        import inspect
        self.assertEqual((list(inspect.signature(web).parameters), list(inspect.signature(academic).parameters)),
                         (["query"], ["query"]))


if __name__ == "__main__":
    unittest.main()
