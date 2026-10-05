"""C-18-5 part 2 (DM-72 (나)): the DEMO-MR deliverable is a partial report. Each cell of both MR files may be null
(the subset's one nullable form, the same {"anyOf": [<schema>, {"type": "null"}]} output-contract-v3 sends for the whole
deliverable), the row and cell structure stays, and the judge still needs every cell with a value and a shown source.
A searcher's partial table passes the contract and reaches the writer's request through t1-handoff-v1. Offline."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import json_subset  # noqa: E402
from experiments.dialogue_contract import for_dialogue_scenario  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402
from tools import scenario_preflight as preflight  # noqa: E402
from t1_harness import report  # noqa: E402
import test_c18_3_part2 as part2  # noqa: E402  (module import: its Flows class is not collected here again)
from test_c18_3_part2 import (ADOPTED_MR, MR_NORMAL, MR_STALL, PRODUCTS, TAVILY, URLS, load_judge,  # noqa: E402
                              search_call, table)

CELL = {"type": "object", "additionalProperties": False, "required": ["value"],
        "properties": {"value": {"type": "string"}}}
NULLABLE = {"anyOf": [CELL, {"type": "null"}]}


def row_schema(cell):
    return {"type": "object", "additionalProperties": False, "required": ["rows"], "properties": {"rows": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["c"],
                                   "properties": {"c": cell}}}}}


def partial():
    """What a searcher found so far: cursor pricing only, every other cell null."""
    rows = [{"product": p, "pricing": None, "features": None} for p in PRODUCTS]
    rows[1]["pricing"] = {"value": "Pro 월 20달러", "source_url": URLS["cursor"]}
    return {"rows": rows}


class Subset(unittest.TestCase):
    def test_a_property_may_be_nullable_in_the_one_form(self):
        json_subset.check_schema(row_schema(NULLABLE))
        self.assertEqual(json_subset.errors({"rows": [{"c": None}, {"c": {"value": "x"}}]}, row_schema(NULLABLE)), [])
        self.assertEqual(json_subset.errors({"rows": [{"c": {"value": 1}}]}, row_schema(NULLABLE)),
                         ["deliverable.rows[0].c.value: expected string"])
        self.assertEqual(json_subset.errors({"rows": [{"c": None}]}, row_schema(CELL)),
                         ["deliverable.rows[0].c: expected object"])

    def test_no_other_anyof(self):
        bad = [{"anyOf": [{"type": "null"}, CELL]}, {"anyOf": [CELL]}, {"anyOf": [CELL, {"type": "null"}], "title": "x"},
               {"anyOf": [NULLABLE, {"type": "null"}]}, {"anyOf": [{"type": "date"}, {"type": "null"}]}]
        for cell in bad:
            with self.assertRaises(ValueError, msg=json.dumps(cell)):
                json_subset.check_schema(row_schema(cell))
        with self.assertRaises(ValueError):  # not on the root: output-contract-v3 already makes the deliverable nullable
            json_subset.check_schema(NULLABLE)
        items = row_schema(CELL)
        items["properties"]["rows"]["items"] = {"anyOf": [items["properties"]["rows"]["items"], {"type": "null"}]}
        with self.assertRaises(ValueError):  # not on array items
            json_subset.check_schema(items)


class MrSchema(unittest.TestCase):
    def cells(self, path):
        return load_scenario(path).deliverable_schema["properties"]["rows"]["items"]["properties"]

    def test_every_cell_of_both_files_is_nullable_with_the_same_inner_cell(self):
        normal, stall = self.cells(MR_NORMAL), self.cells(MR_STALL)
        self.assertEqual(normal["product"], stall["product"])
        self.assertNotIn("anyOf", normal["product"])
        for cells in (normal, stall):
            for name, cell in cells.items():
                if name != "product":
                    self.assertIsNotNone(json_subset.nullable_inner(cell), name)
        for name in ("pricing", "features"):
            self.assertEqual(normal[name], stall[name])
        self.assertEqual(json_subset.nullable_inner(stall["market_share"])["required"], ["value", "source_urls"])

    def test_the_contract_takes_a_partial_table_and_sends_the_null_form(self):
        contract = for_dialogue_scenario(load_scenario(MR_NORMAL))
        sent = contract.schema()["properties"]["deliverable"]["anyOf"][0]
        self.assertEqual(sent["properties"]["rows"]["items"]["properties"]["pricing"]["anyOf"][1], {"type": "null"})
        parsed = contract.parse(json.dumps(report("researching", adopted=[], deliverable=partial()),
                                           ensure_ascii=False))
        self.assertEqual(parsed["deliverable"], partial())

    def test_the_pair_difference_is_still_the_inducing_device_only(self):
        pair = preflight.pair_diff(MR_NORMAL, MR_STALL)
        cut = sorted({p[:p.find("market_share") + len("market_share")] if "market_share" in p else p
                      for p in pair["scenario_values_differing_beyond_identity"]})
        self.assertEqual(cut, ["allowed_issues", "deliverable_schema.properties.rows.items.properties.market_share",
                               "deliverable_schema.properties.rows.items.required", "initial_issue_ids",
                               "required_adopted_items", "task"])
        self.assertEqual(pair["fixture_files_differing"], [])
        self.assertTrue(pair["judge_files"]["same_file"])


class Judge(unittest.TestCase):
    judge = staticmethod(load_judge("DEMO-MR-v1"))

    def judged(self, deliverable):
        shown = [search_call("web_search", [{"url": u} for u in URLS.values()])]
        return self.judge(report("completed", deliverable=deliverable), tool_records=shown, inputs_dir=None)

    def test_a_null_cell_is_missing_at_completion(self):
        self.assertEqual(self.judged(partial())["missing"],
                         [f"{p}:{c}:value" for p in PRODUCTS for c in ("pricing", "features")
                          if (p, c) != ("cursor", "pricing")])
        self.assertTrue(self.judged(table())["machine_success"])


class PartialFlow(part2.Flows):
    async def test_the_searchers_partial_table_reaches_the_writer_and_the_run_succeeds(self):
        reports = [report("scoping", adopted=[], issues=("pricing", "features", "acceptance-review")),
                   report("researching", adopted=[], deliverable=partial(),
                          issues=("pricing", "features", "acceptance-review")),
                   report("completed", adopted=ADOPTED_MR, deliverable=table(), declared=True, issues=())]
        run, _ = await self.run_search(MR_NORMAL, reports, {2: ("web_search", {"query": "cursor pricing"})},
                                       (200, TAVILY))
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 3))
        self.assertEqual(run["steps"][1]["step_status"], "completed")
        writer = [r for r in run["requests"] if "채택된 값과 출처로 최종 비교표" in json.dumps(r, ensure_ascii=False)]
        self.assertTrue(writer)
        sent = json.dumps(writer[0]["messages"], ensure_ascii=False)
        self.assertIn("Pro 월 20달러", sent)
        self.assertIn(URLS["cursor"], sent)

    # The inherited flows of test_c18_3_part2 run there; only the partial flow runs here.
    test_mr_normal_path_succeeds_from_the_stored_results = None
    test_mr_stall_table_without_two_sources_is_refused_and_stopped = None
    test_lr_normal_path_succeeds_with_versioned_and_bare_ids = None
    test_lr_stall_selection_without_the_benchmark_is_refused_and_stopped = None


class RetestPlan(unittest.TestCase):
    def test_mr_normal_and_stall_once_on_one_lane_without_the_final_freeze(self):
        from tools import c18_5_estimate, run_batch
        plan = run_batch.load_plan(ROOT / "batch_plans/demo-trial-c18-5.yaml")
        self.assertEqual(plan["plan_id"], "demo-trial-c18-5")
        self.assertFalse(plan.get("requires_final_freeze"))
        self.assertEqual([i.key for i in run_batch.lane_items(plan, 1, 1)],
                         ["DEMO-MR-normal-v1:observe:1", "DEMO-MR-stall-v1:observe:1"])
        estimate = c18_5_estimate.estimate()
        self.assertEqual([r["c18_4_retest"]["scenario_id"] for r in estimate["sessions"]],
                         ["DEMO-MR-normal-v1", "DEMO-MR-stall-v1"])
        self.assertEqual(estimate["upper_reference"]["termination_reason"], "max_steps")


if __name__ == "__main__":
    unittest.main()
