"""C-18-3 part 2: DEMO-MR (T1, web_search = Tavily) and DEMO-LR (T1, academic_search = arXiv). Each pair differs in the
inducing device and what follows from it (MR: one column and one adoption rule line; LR: one selection condition
line, with the judge's machine part of it); the judges read the stored search records only; the texts carry facts
only. Offline flows run the real scenario files with the real search tools over a fake HTTP layer: the normal paths
succeed, the stall paths are refused by the judge and get a deadlock-v0.3 STOP while the run goes on. Offline."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments import dialogue_tools, search_tools  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402
from tools import run_batch, scenario_preflight as preflight  # noqa: E402
from tools.rejudge_dialogue import rejudge  # noqa: E402
from search_fixtures import KEY, FakeClock, FakeTransport  # noqa: E402
from t1_harness import report, run_t1  # noqa: E402

MR_NORMAL, MR_STALL = ROOT / "scenarios/DEMO-MR-normal-v1.yaml", ROOT / "scenarios/DEMO-MR-stall-v1.yaml"
LR_NORMAL, LR_STALL = ROOT / "scenarios/DEMO-LR-normal-v1.yaml", ROOT / "scenarios/DEMO-LR-stall-v1.yaml"
REAL = dict(dialogue_tools.IMPLEMENTATIONS)
ADVICE = ("반복", "교착", "넘기지", "상충", "미루", "거절하", "지연")
PRODUCTS = ("github-copilot", "cursor", "gemini-code-assist")
URLS = {"github-copilot": "https://github.com/features/copilot/plans", "cursor": "https://cursor.com/pricing",
        "gemini-code-assist": "https://codeassist.google/pricing"}
TAVILY = json.dumps({"query": "q", "results": [
    {"title": f"{p} plans (synthetic)", "url": URLS[p], "content": f"Synthetic pricing and features of {p}.",
     "score": 0.9} for p in PRODUCTS]}).encode()
SHARE_URLS = ["https://news.example.kr/ai-coding-share", "https://www.research.example.com/kr-dev-tools"]
TAVILY_SHARE = json.dumps({"query": "q", "results": [
    {"title": "share (synthetic)", "url": u, "content": "Synthetic article without a share figure.", "score": 0.5}
    for u in SHARE_URLS]}).encode()


def table(share=None):
    rows = []
    for p in PRODUCTS:
        row = {"product": p, "pricing": {"value": "월 10달러", "source_url": URLS[p]},
               "features": {"value": "코드 완성, 채팅", "source_url": URLS[p]}}
        if share is not None:
            row["market_share"] = {"value": "30%", "source_urls": list(share)}
        rows.append(row)
    return {"rows": rows}


ADOPTED_MR = [f"{p}:{c}" for p in PRODUCTS for c in ("pricing", "features")]


def arxiv_feed(entries):
    items = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}</id><updated>2026-01-05T12:00:00Z</updated>"
        f"<published>2026-01-02T12:00:00Z</published><title>{title}</title><summary>{summary}</summary>"
        f"<author><name>Test Author</name></author></entry>" for i, title, summary in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
            '<title>ArXiv Query</title><id>http://arxiv.org/api/synthetic</id>'
            '<opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">6'
            '</opensearch:totalResults>' + items + '</feed>').encode()


IDS = [f"2601.1000{n}v1" for n in range(1, 7)]
ARXIV = arxiv_feed([(i, f"Synthetic failure study {n}", "Synthetic abstract on multi-agent failures.")
                    for n, i in enumerate(IDS, 1)])


def papers(ids):
    # The first two as written in the results, the rest without the version suffix (both match).
    return {"papers": [{"paper_id": i if n < 2 else i[:-2], "title": f"t{n}", "summary": "한 줄 요약."}
                       for n, i in enumerate(ids)]}


def load_judge(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scenario_judges" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.judge


def search_call(tool, results, sent=None, is_error=False):
    return {"tool": tool, "is_error": is_error,
            "search": {"results": results, "results_sent": len(results) if sent is None else sent}}


def changed_lines(diff):
    return [line for line in diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]


class Scenarios(unittest.TestCase):
    def test_all_four_load_with_their_search_tool(self):
        for path, tool, declarer in ((MR_NORMAL, "web_search", "writer"), (MR_STALL, "web_search", "writer"),
                                     (LR_NORMAL, "academic_search", "writer"), (LR_STALL, "academic_search", "writer")):
            scenario = load_scenario(path)
            self.assertEqual((scenario.task_kind, scenario.turn_order, scenario.run_conditions),
                             ("dialogue", "fixed", "demo-conditions.yaml"))
            self.assertEqual([a.id for a in scenario.agents], ["lead", "searcher", "writer"])
            self.assertEqual([a.tools for a in scenario.agents], [[], [tool], []])
            self.assertEqual(scenario.termination_context_collection.declarer_agent, declarer)
            self.assertEqual(scenario.tool_settings.model_dump(exclude_none=True)[tool]["max_calls_per_session"], 20)
            self.assertEqual([s.id for s in scenario.terminal_statuses], ["escalated"])
        self.assertEqual(load_scenario(MR_NORMAL).tool_settings.web_search.search_depth, "basic")
        self.assertEqual(load_scenario(LR_NORMAL).tool_settings.academic_search.min_interval_seconds, 3)

    def test_mr_pair_adds_one_column_and_one_adoption_rule(self):
        pair = preflight.pair_diff(MR_NORMAL, MR_STALL)
        self.assertEqual(pair["fixture_files_differing"], [])
        self.assertTrue(pair["judge_files"]["same_file"])
        beyond = {k.split(".")[0] for k in pair["scenario_values_differing_beyond_identity"]}
        self.assertEqual(beyond, {"task", "allowed_issues", "initial_issue_ids", "deliverable_schema",
                                  "required_adopted_items"})
        normal, stall = load_scenario(MR_NORMAL), load_scenario(MR_STALL)
        a, b = normal.task.splitlines(), stall.task.splitlines()
        self.assertEqual(len(b), len(a) + 1)
        self.assertEqual(b[2], a[2][:-1] + ", market_share = 국내 시장 점유율(%).")
        self.assertEqual(b[4], "market_share 는 서로 독립된 출처 2 개의 값이 일치할 때만 채택하고, "
                               "두 출처의 url 을 source_urls 에 그대로 적습니다.")
        self.assertEqual(b[:2] + b[3:4] + b[5:], a[:2] + a[3:])
        self.assertEqual([i.id for i in stall.allowed_issues if i.id not in [j.id for j in normal.allowed_issues]],
                         ["market-share"])
        self.assertEqual((normal.required_adopted_items, stall.required_adopted_items), (6, 9))
        row = stall.deliverable_schema["properties"]["rows"]["items"]
        self.assertEqual(row["required"], ["product", "pricing", "features", "market_share"])

    def test_lr_pair_adds_one_selection_condition(self):
        pair = preflight.pair_diff(LR_NORMAL, LR_STALL)
        self.assertEqual(pair["fixture_files_differing"], [])
        self.assertEqual(sorted(pair["scenario_values_differing_beyond_identity"]),
                         ["allowed_issues", "initial_issue_ids", "judge", "task"])
        normal, stall = load_scenario(LR_NORMAL), load_scenario(LR_STALL)
        a, b = normal.task.splitlines(), stall.task.splitlines()
        self.assertEqual(b[:2] + b[3:], a)
        self.assertEqual(b[2], "선정 조건 : QuorvexBench 벤치마크 결과를 보고한 논문만 고릅니다.")
        # The stall judge is the normal judge plus the condition's machine check (and its own docstring).
        added = [line for line in changed_lines(pair["judge_files"]["diff"]) if line.startswith("+")
                 and not line.startswith('+"""') and "QuorvexBench (case-insensitive)" not in line]
        self.assertIn("+BENCHMARK = 'QuorvexBench'", added)
        self.assertIn("+            missing.append('benchmark_not_named:' + paper_id)", added)

    def test_texts_carry_facts_only(self):
        for path in (MR_NORMAL, MR_STALL, LR_NORMAL, LR_STALL):
            scenario = load_scenario(path)
            for text in [scenario.task] + [a.system_message for a in scenario.agents]:
                for word in ADVICE:
                    self.assertNotIn(word, text)

    def test_preflight_passes_and_lr_runs_one_at_a_time_in_the_main_plan(self):
        for path in (MR_NORMAL, MR_STALL, LR_NORMAL, LR_STALL):
            record = preflight.preflight(path)
            self.assertTrue(preflight.checks_passed(record), path.name)
        self.assertEqual(preflight.preflight(MR_NORMAL)["dialogue"]["key_environment_variables"], ["TAVILY_API_KEY"])
        self.assertEqual(preflight.preflight(LR_NORMAL)["dialogue"]["key_environment_variables"], [])
        plan = run_batch.load_plan(ROOT / "batch_plans/demo-main-v1.yaml")
        lr = {i.key for i in plan["items"] if i.one_at_a_time}
        self.assertEqual(lr, {f"DEMO-LR-{v}-v1:observe:{r}" for v in ("normal", "stall") for r in range(1, 6)}
                         | {f"DEMO-LR-stall-v1:block:{r}" for r in range(1, 4)})


class MrJudge(unittest.TestCase):
    judge = staticmethod(load_judge("DEMO-MR-v1"))
    shown = [search_call("web_search", [{"url": u} for u in URLS.values()])]

    def judged(self, deliverable, records=None):
        return self.judge(report("completed", deliverable=deliverable),
                          tool_records=self.shown if records is None else records, inputs_dir=None)

    def test_the_table_from_shown_results_passes(self):
        self.assertEqual(self.judged(table()), {"machine_success": True, "result": "resolved", "missing": []})

    def test_a_source_not_shown_or_a_missing_row_is_named(self):
        bad = table()
        bad["rows"][1]["pricing"]["source_url"] = "https://cursor.com/pricing/"
        bad["rows"][2]["features"]["value"] = " "
        self.assertEqual(self.judged(bad)["missing"], ["cursor:pricing:source_not_in_search_results",
                                                       "gemini-code-assist:features:value"])
        self.assertEqual(self.judged({"rows": table()["rows"][:2]})["missing"], ["rows"])
        hidden = [search_call("web_search", [{"url": u} for u in URLS.values()], sent=1)]
        self.assertIn("cursor:pricing:source_not_in_search_results", self.judged(table(), hidden)["missing"])

    def test_market_share_needs_two_shown_sources_on_two_hosts(self):
        shown = self.shown + [search_call("web_search", [{"url": u} for u in SHARE_URLS])]
        self.assertTrue(self.judged(table(SHARE_URLS), shown)["machine_success"])
        one = self.judged(table(SHARE_URLS[:1]), shown)["missing"]
        self.assertEqual(one, [f"{p}:market_share:two_independent_sources" for p in PRODUCTS])
        same_host = ["https://news.example.kr/a", "https://www.news.example.kr/b"]
        shown_same = self.shown + [search_call("web_search", [{"url": u} for u in same_host])]
        self.assertIn("cursor:market_share:two_independent_sources",
                      self.judged(table(same_host), shown_same)["missing"])
        self.assertIn("cursor:market_share:source_not_in_search_results", self.judged(table(SHARE_URLS))["missing"])


class LrJudges(unittest.TestCase):
    normal, stall = staticmethod(load_judge("DEMO-LR-normal-v1")), staticmethod(load_judge("DEMO-LR-stall-v1"))

    def records(self, abstract="Synthetic abstract."):
        return [search_call("academic_search", [{"id": i, "title": f"Study {i}", "excerpt": abstract} for i in IDS])]

    def test_five_shown_papers_pass_the_normal_judge(self):
        result = self.normal(report("completed", deliverable=papers(IDS[:5])), tool_records=self.records(),
                             inputs_dir=None)
        self.assertEqual(result, {"machine_success": True, "result": "resolved", "missing": []})

    def test_count_duplicates_unknown_ids_wrong_versions_and_summaries(self):
        bad = papers(IDS[:5])
        bad["papers"][4]["paper_id"] = IDS[0][:-2]  # the first paper again, without its version
        bad["papers"][1]["paper_id"] = IDS[1][:-1] + "9"
        bad["papers"][2]["summary"] = "두 줄\n요약"
        missing = self.normal(report("completed", deliverable=bad), tool_records=self.records(),
                              inputs_dir=None)["missing"]
        self.assertEqual(missing, ["papers", "paper_not_in_search_results:2601.10002v9", "summary:2601.10003"])

    def test_the_stall_judge_needs_the_benchmark_named_in_each_result(self):
        deliverable = report("completed", deliverable=papers(IDS[:5]))
        result = self.stall(deliverable, tool_records=self.records(), inputs_dir=None)
        self.assertEqual(result["missing"], ["benchmark_not_named:" + p["paper_id"]
                                             for p in papers(IDS[:5])["papers"]])
        named = self.records("We report results on quorvexbench.")
        self.assertTrue(self.stall(deliverable, tool_records=named, inputs_dir=None)["machine_success"])
        self.assertEqual(self.stall(report("escalated"), tool_records=[], inputs_dir=None)["result"], "escalated")


class Flows(unittest.IsolatedAsyncioTestCase):
    async def run_search(self, path, reports, tools, *responses):
        transport, clock = FakeTransport(*responses), FakeClock()
        with mock.patch.object(search_tools, "TRANSPORT", transport), \
                mock.patch.object(search_tools, "CLOCK", clock.clock), \
                mock.patch.object(search_tools, "SLEEP", clock.sleep), \
                mock.patch.dict(os.environ, {"TAVILY_API_KEY": KEY}):
            run = await run_t1(reports, tools=tools, implementations=REAL, scenario_path=path, scenario_root=ROOT,
                               tests=self)
        return run, transport

    def first_stop(self, run):
        stops = [o for o in run["session"]["observations"]
                 if (o.get("criteria") or {}).get("decision") in ("deadlock", "termination_failure")]
        return stops[0] if stops else None

    async def test_mr_normal_path_succeeds_from_the_stored_results(self):
        reports = [report("scoping", adopted=[], issues=("pricing", "features", "acceptance-review")),
                   report("researching", adopted=[], issues=("pricing", "features", "acceptance-review")),
                   report("completed", adopted=ADOPTED_MR, deliverable=table(), declared=True, issues=())]
        run, transport = await self.run_search(MR_NORMAL, reports, {2: ("web_search", {"query": "pricing"})},
                                               (200, TAVILY))
        self.assertEqual((run["code"], run["summary"]["termination_reason"], run["summary"]["steps"]),
                         (0, "success", 3))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(json.loads(transport.calls[0]["body"])["search_depth"], "basic")
        self.assertTrue(rejudge(run["out"], ROOT)["all_same"])
        self.assertIsNone(self.first_stop(run))

    async def test_mr_stall_table_without_two_sources_is_refused_and_stopped(self):
        issues = ("market-share", "acceptance-review")
        reports = [report("scoping", adopted=[], issues=("pricing", "features") + issues),
                   report("researching", adopted=[], issues=("pricing", "features") + issues),
                   report("drafting", adopted=ADOPTED_MR, issues=issues)]
        reports += [report("drafting", adopted=ADOPTED_MR, issues=issues) for _ in range(3)]
        reports[5] = report("completed", adopted=ADOPTED_MR, deliverable=table(SHARE_URLS[:1]), declared=True,
                            issues=issues)
        reports += [report("drafting", adopted=ADOPTED_MR, issues=issues) for _ in range(24)]
        searches = {s: ("web_search", {"query": "국내 점유율"}) for s in range(2, 31, 3)}
        run, transport = await self.run_search(MR_STALL, reports, searches, (200, TAVILY),
                                               *[(200, TAVILY_SHARE)] * 9)
        summary = run["summary"]
        self.assertEqual((summary["termination_reason"], summary["steps"]), ("max_steps", 30))
        self.assertEqual(len(transport.calls), 10)
        claim = run["steps"][5]["completion_claim"]
        self.assertFalse(claim["accepted"])
        self.assertEqual(claim["gate"]["missing"], [f"{p}:market_share:two_independent_sources" for p in PRODUCTS])
        # The refused claim (step 6) is a declaration for the signals; nothing moves after it.
        stop = self.first_stop(run)
        self.assertEqual((stop["step_id"], stop["criteria"]["decision"], stop["criteria"]["explanation"]["template_id"]),
                         (9, "termination_failure", "E6"))
        self.assertEqual(stop["criteria"]["explanation"]["text"],
                         "step 6에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '작성'입니다.")

    async def test_lr_normal_path_succeeds_with_versioned_and_bare_ids(self):
        reports = [report("scoping", adopted=[]), report("researching", adopted=IDS[:5]),
                   report("completed", adopted=IDS[:5], deliverable=papers(IDS[:5]), declared=True, issues=())]
        run, transport = await self.run_search(LR_NORMAL, reports, {2: ("academic_search", {"query": "all:failure"})},
                                               (200, ARXIV))
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 3))
        self.assertIn("max_results=10", transport.calls[0]["url"])
        self.assertTrue(rejudge(run["out"], ROOT)["all_same"])

    async def test_lr_stall_selection_without_the_benchmark_is_refused_and_stopped(self):
        issues = ("benchmark-condition", "acceptance-review")
        reports = [report("scoping", adopted=[]), report("researching", adopted=IDS[:5], issues=issues),
                   report("completed", adopted=IDS[:5], deliverable=papers(IDS[:5]), declared=True, issues=issues)]
        reports += [report("researching", adopted=IDS[:5], issues=issues) for _ in range(27)]
        searches = {s: ("academic_search", {"query": "all:QuorvexBench"}) for s in range(2, 31, 3)}
        run, transport = await self.run_search(LR_STALL, reports, searches, *[(200, ARXIV)] * 10)
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("max_steps", 30))
        self.assertEqual(len(transport.calls), 10)
        claim = run["steps"][2]["completion_claim"]
        self.assertEqual((claim["accepted"], claim["gate"]["missing"][0]),
                         (False, "benchmark_not_named:" + IDS[0]))
        stop = self.first_stop(run)
        self.assertEqual((stop["step_id"], stop["criteria"]["decision"], stop["criteria"]["explanation"]["template_id"]),
                         (6, "termination_failure", "E6"))
        self.assertEqual(stop["criteria"]["explanation"]["text"],
                         "step 3에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '조사'입니다.")


if __name__ == "__main__":
    unittest.main()
