"""C-17-6 part 1: the local CS tools lookup_order and read_policy (read-only, inside inputs_dir, decision 018)."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from experiments import cs_tools, dialogue_tools
from experiments.tool_results import ToolFactError
from t1_harness import FIXTURES, report, run_t1

INPUTS = FIXTURES / "scenario_assets/TEST-T1-v2"
FIXED = {"turn_order": "fixed"}


def sha256(path):
    return cs_tools.sha256(Path(path).read_bytes())


def dispatch(inputs=INPUTS):
    d = dialogue_tools.ToolDispatch(dialogue_tools.IMPLEMENTATIONS, inputs)
    d.step_id, d.agent_id = 2, "refund"
    return d, dict(zip(("lookup_order", "read_policy"), d.tools(["lookup_order", "read_policy"])))


class LookupOrderTests(unittest.TestCase):
    def test_returns_the_one_record_and_records_the_source(self):
        d, tools = dispatch()
        text = tools["lookup_order"]("A-100")
        orders = json.loads((INPUTS / "orders.json").read_text(encoding="utf-8"))["orders"]
        self.assertEqual(json.loads(text), orders[0])
        self.assertEqual(d.records[0]["source"], {"file": "orders.json", "sha256": sha256(INPUTS / "orders.json")})
        self.assertEqual((d.records[0]["is_error"], d.records[0]["result"]), (False, text))

    def test_an_unknown_id_is_a_fact_error(self):
        d, tools = dispatch()
        for order_id, message in (("Z-9", 'No order with order_id "Z-9" in the order data.'),
                                  ("a-100", 'No order with order_id "a-100" in the order data.'),
                                  ("", "lookup_order needs order_id as a non-empty string.")):
            with self.subTest(order_id=order_id), self.assertRaises(ToolFactError) as raised:
                tools["lookup_order"](order_id)
            self.assertEqual(str(raised.exception), message)
        self.assertTrue(all(r["is_error"] and r["result"] is None for r in d.records))
        self.assertEqual(d.records[0]["error"], 'ToolFactError: No order with order_id "Z-9" in the order data.')
        self.assertEqual(d.records[0]["source"]["file"], "orders.json")

    def test_read_only(self):
        before = {p: p.read_bytes() for p in INPUTS.rglob("*") if p.is_file()}
        _, tools = dispatch()
        tools["lookup_order"]("A-101")
        tools["read_policy"]("refund")
        self.assertEqual({p: p.read_bytes() for p in INPUTS.rglob("*") if p.is_file()}, before)


class ReadPolicyTests(unittest.TestCase):
    def test_reads_a_document_by_name(self):
        expected = (INPUTS / "policies/refund.md").read_text(encoding="utf-8")
        for name in ("refund", "refund.md", "policies/refund.md"):
            d, tools = dispatch()
            with self.subTest(name=name):
                self.assertEqual(tools["read_policy"](name), expected)
                self.assertEqual(d.records[0]["source"], {"file": "policies/refund.md",
                                                          "sha256": sha256(INPUTS / "policies/refund.md")})

    def test_paths_and_unknown_names_are_refused_with_the_document_names(self):
        refused = ("../../scenario_judges/TEST-T1-v2.py", "/etc/passwd", "policies/../orders.json", "..",
                   "orders.json", "policies/refund", "Refund", "returns", "policies/sub/refund.md", "")
        for name in refused:
            d, tools = dispatch()
            with self.subTest(name=name), self.assertRaises(ToolFactError) as raised:
                tools["read_policy"](name)
            self.assertEqual(str(raised.exception), "No policy document named " + json.dumps(name) + ". read_policy "
                             "reads only the policy documents of the task: handling_codes, refund, shipping.")
            self.assertTrue(d.records[0]["is_error"])

    def test_a_link_out_of_inputs_dir_is_not_a_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs, outside = Path(tmp) / "inputs", Path(tmp) / "secret.md"
            shutil.copytree(INPUTS, inputs)
            outside.write_text("OUTSIDE", encoding="utf-8")
            os.symlink(outside, inputs / "policies/leak.md")
            self.assertNotIn("leak", cs_tools.policy_documents(inputs))
            _, tools = dispatch(inputs)
            with self.assertRaises(ToolFactError) as raised:
                tools["read_policy"]("leak")
            self.assertNotIn("OUTSIDE", str(raised.exception))
            self.assertEqual(cs_tools.input_problems("read_policy", inputs),
                             ["policies/leak.md is not a policy document (name or location)"])


class InputFormatTests(unittest.TestCase):
    """The formats C-18 follows; the pre-run check (part 3) reports these problems."""

    def check(self, tool, files):
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in files.items():
                (Path(tmp) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / name).write_text(content, encoding="utf-8")
            return cs_tools.input_problems(tool, tmp)

    def test_fixture_inputs_are_fine(self):
        self.assertEqual((cs_tools.input_problems("lookup_order", INPUTS),
                          cs_tools.input_problems("read_policy", INPUTS)), ([], []))

    def test_order_data_problems(self):
        cases = {"missing": ({}, ["orders.json not found"]),
                 "not json": ({"orders.json": "{"}, ["orders.json is not UTF-8 JSON: JSONDecodeError"]),
                 "a list": ({"orders.json": "[]"}, ['orders.json must be an object with the one key "orders" holding a list']),
                 "extra key": ({"orders.json": '{"orders": [], "x": 1}'},
                               ['orders.json must be an object with the one key "orders" holding a list']),
                 "no id": ({"orders.json": '{"orders": [{"id": "A"}]}'},
                           ["orders.json: every order is an object with a non-empty string order_id"]),
                 "number id": ({"orders.json": '{"orders": [{"order_id": 7}]}'},
                               ["orders.json: every order is an object with a non-empty string order_id"]),
                 "duplicate": ({"orders.json": '{"orders": [{"order_id": "A"}, {"order_id": "A"}]}'},
                               ["orders.json: order_id values must be unique"])}
        for name, (files, problems) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.check("lookup_order", files), problems)

    def test_policy_problems(self):
        self.assertEqual(self.check("read_policy", {}), ["policies/ not found"])
        self.assertEqual(self.check("read_policy", {"policies/notes.txt": "x"}), ["policies/ has no policy document"])
        self.assertEqual(self.check("read_policy", {"policies/Refund.md": "x", "policies/ok.md": "y"}),
                         ["policies/Refund.md is not a policy document (name or location)"])
        self.assertEqual(cs_tools.input_problems("read_policy", "/nonexistent-inputs"), ["inputs_dir not found"])


class RunnerPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_fact_error_reaches_the_model_as_an_error_result(self):
        tools = {1: ("lookup_order", {"order_id": "Z-9"}), 2: ("read_policy", {"name": "refund"})}
        run = await run_t1([report("triage"), report("triage")], tools=tools, scenario_changes=FIXED, max_steps=2,
                           implementations=dict(dialogue_tools.IMPLEMENTATIONS), tests=self)
        steps, records = run["steps"], run["dispatch"]
        self.assertEqual([(r["tool"], r["is_error"], r["source"]["file"]) for r in records],
                         [("lookup_order", True, "orders.json"), ("read_policy", False, "policies/refund.md")])
        # G0-6: a tool error fails the step without stopping the run.
        self.assertEqual((steps[0]["step_status"], steps[0]["failure_reasons"]), ("failed", ["tool_execution_error"]))
        self.assertEqual(steps[0]["tool_executions"][0]["error_summary"],
                         'No order with order_id "Z-9" in the order data.')
        self.assertEqual(steps[1]["step_status"], "completed")
        tool_messages = [m for body in run["requests"] for m in body["messages"] if m.get("role") == "tool"]
        self.assertEqual(tool_messages[0]["content"], 'No order with order_id "Z-9" in the order data.')
        self.assertEqual(tool_messages[-1]["content"], (INPUTS / "policies/refund.md").read_text(encoding="utf-8"))
        implementations = run["conditions"]["tool_implementations"]
        self.assertEqual((implementations["lookup_order"], implementations["read_policy"]),
                         ("experiments.cs_tools.lookup_order", "experiments.cs_tools.read_policy"))


if __name__ == "__main__":
    unittest.main()
