"""C-17-5 part 2: the CT approval rule (DM-16) enforced by the runner on scenario-v2 artifact tasks.

Fixed order planner (1, 4, 7), developer (2, 5, 8), reviewer (3, 6, 9). Before the reviewer's verified spec_approved:
true, the developer's writes are not executed and return a fact-only error result; afterwards they run. The rule is
told to every role in one fact sentence, the same for any scenario with the same gate.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest
from unittest import mock

import yaml
from pydantic import ValidationError

from experiments.approval_gate import NOTICE, REFUSAL, REFUSED
from scenario_schema import ScenarioV2
from t2_harness import FIXTURE, GATE, SOURCE, V2, V3, report, run_t2, source, write
from tools import analyze_session

SPEC = "SPEC.md"
REFUSAL_TEXT = REFUSAL.format(spec_path=SPEC, set_by="reviewer")


def gated(data=None, **gate):
    data = data or yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    return {**data, "output_contract": V3, "write_gate": {**GATE, **gate}}


def executions(run, step):
    return run["steps"][step - 1]["tool_executions"]


class SchemaTests(unittest.TestCase):
    def test_off_by_default_and_valid_gate(self):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        self.assertIsNone(ScenarioV2.model_validate(data).write_gate)
        self.assertEqual(ScenarioV2.model_validate(gated(data)).write_gate.model_dump(), GATE)

    def test_gate_rules(self):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        cases = {"contract v2": {**gated(data), "output_contract": V2},
                 "unknown role": gated(data, role="tester"), "unknown approver": gated(data, set_by="boss"),
                 "self approval": gated(data, set_by="developer"), "role without write tool": gated(data, role="reviewer",
                                                                                                    set_by="planner"),
                 "spec not monitored": gated(data, spec_path="NOTES.md"), "absolute spec": gated(data, spec_path="/SPEC.md"),
                 "other requirement": gated(data, requires="approved")}
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError):
                ScenarioV2.model_validate(value)
        dialogue = yaml.safe_load((Path(__file__).parent / "fixtures/scenario-v2-dialogue.yaml").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValidationError, "write_gate belongs to artifact tasks"):
            ScenarioV2.model_validate({**dialogue, "write_gate": GATE})


class NoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_role_gets_the_same_single_fact_sentence(self):
        run = await run_t2([report()] * 3, gate=GATE, max_steps=3, tests=self)
        notice = NOTICE.format(role="developer", set_by="reviewer", spec_path=SPEC)
        systems = {r["messages"][0]["content"] for r in run["requests"] if "response_format" not in r}
        self.assertEqual(len(systems), 3)
        self.assertTrue(all(s.count(notice) == 1 for s in systems))
        recorded = run["conditions"]["write_gate"]
        self.assertEqual((recorded["notice"], recorded["notice_sha256"], recorded["rule_version"]),
                         (notice, hashlib.sha256(notice.encode()).hexdigest(), "write-gate-v1"))
        # One sentence of facts: no instruction to repeat, wait or refuse (DM-5).
        self.assertEqual(len(re.findall(r"[.!?] ", notice.strip() + " ")), 1)
        self.assertIsNone(re.search(r"(?i)\b(do not|don't|should|must|wait|retry|repeat|refuse|try)\b", notice + REFUSAL))
        # The contract's fact about spec_approved names the approver and the file.
        self.assertIn("Only the spec_approved of role reviewer is read: true from that role approves SPEC.md",
                      next(iter(systems)))

    async def test_same_sentence_whatever_else_differs_and_none_without_a_gate(self):
        changed = await run_t2([report()], gate=GATE, max_steps=1, tests=self,
                               scenario_changes={"task": "다른 과제 문장 (교착판 가정)."})
        first = await run_t2([report()], gate=GATE, max_steps=1, tests=self)
        self.assertEqual(changed["conditions"]["write_gate"], first["conditions"]["write_gate"])
        plain = await run_t2([report()], max_steps=1, tests=self)
        self.assertIsNone(plain["conditions"]["write_gate"])
        self.assertNotIn("Approval rule", plain["requests"][0]["messages"][0]["content"])
        self.assertIsNone(plain["summary"]["approval"])


class EnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_refused_before_approval_executed_after(self):
        reports = [report(), report(), report(approved=True), report(), report()]
        tools = {1: write("# spec v1\n", SPEC), 2: write(source(9)), 5: write(source(12))}
        run = await run_t2(reports, tools=tools, gate=GATE, max_steps=5, tests=self)
        # The planner is not gated: SPEC.md is written at step 1.
        self.assertEqual([(e["tool"], e["is_error"]) for e in executions(run, 1)], [("write_file", False)])
        refused = executions(run, 2)[0]
        self.assertEqual((refused["is_error"], refused["error_summary"], refused["approval_refused"]),
                         (True, REFUSAL_TEXT, True))
        step2 = run["steps"][1]
        self.assertEqual((step2["step_status"], step2["failure_reasons"], step2["consecutive_strict_failures"]),
                         ("failed", [REFUSED], 0))
        self.assertEqual(step2["approval"], {"reported_spec_approved": None, "counted": False, "approved": False,
                                             "approved_step": None, "refused_writes": 1})
        self.assertEqual(run["steps"][2]["approval"]["approved_step"], 3)
        # After approval the same call runs and the file changes.
        self.assertEqual(executions(run, 5)[0]["is_error"], False)
        self.assertEqual((run["out"] / "workspace" / SOURCE).read_text(encoding="utf-8"), source(12))
        self.assertEqual([o["artifact"]["test_pass_count"] for o in run["session"]["observations"]], [7, 7, 7, 7, 12])
        spec_hash = hashlib.sha256((run["out"] / "workspace" / SPEC).read_bytes()).hexdigest()
        self.assertEqual(run["summary"]["approval"], {"approved_step": 3, "spec_path": SPEC,
                                                      "spec_sha256_at_approval": spec_hash, "refused_writes": 1,
                                                      "refused_writes_by_step": {"2": 1}})
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["error"]), ("max_steps", None))

    async def test_only_the_approver_counts_and_approval_is_kept(self):
        reports = [report(approved=True), report(approved=True), report(approved=False), report(), report(approved=False),
                   report(approved=True), report(), report()]
        tools = {2: write(source(8)), 5: ("replace_in_file", {"path": SOURCE, "old": "a", "new": "b"}),
                 8: write(source(10))}
        run = await run_t2(reports, tools=tools, gate=GATE, max_steps=8, tests=self)
        approvals = [s["approval"] for s in run["steps"]]
        # Planner (1) and developer (2) report true: not counted. Reviewer false (3), then true (6): approved at 6.
        self.assertEqual([(a["counted"], a["approved_step"]) for a in approvals],
                         [(False, None), (False, None), (True, None), (False, None), (False, None), (True, 6),
                          (False, 6), (False, 6)])
        self.assertEqual([e["error_summary"] for e in executions(run, 5)], [REFUSAL_TEXT])  # replace_in_file too
        self.assertEqual(executions(run, 8)[0]["is_error"], False)
        self.assertEqual(run["summary"]["approval"]["refused_writes_by_step"], {"2": 1, "5": 1})

    async def test_approval_is_not_withdrawn(self):
        reports = [report(), report(), report(approved=True), report(), report(), report(approved=False), report(),
                   report()]
        run = await run_t2(reports, tools={8: write(source(11))}, gate=GATE, max_steps=8, tests=self)
        self.assertEqual(run["steps"][5]["approval"]["approved"], True)
        self.assertEqual(executions(run, 8)[0]["is_error"], False)

    async def test_the_refusal_reaches_the_final_report_request_as_a_fact(self):
        # S-31: is_error stays in the v10 final-report request.
        run = await run_t2([report(), report()], tools={2: write(source(9))}, gate=GATE, max_steps=2, tests=self)
        final = [r for r in run["requests"] if "response_format" in r][1]
        records = json.loads(final["messages"][1]["content"])["observed_records"]
        results = [item for r in records if r.get("type") == "FunctionExecutionResultMessage" for item in r["content"]]
        self.assertEqual(results, [{"name": "write_file", "content": REFUSAL_TEXT, "is_error": True}])

    async def test_other_tool_errors_keep_their_own_reason(self):
        # An unauthorized path after approval is a plain tool error (G0-6), not a refusal.
        reports = [report(), report(), report(approved=True), report(), report()]
        run = await run_t2(reports, tools={5: write("x", "tests/test_task_query.py")}, gate=GATE, max_steps=5, tests=self)
        error = executions(run, 5)[0]
        self.assertEqual((error["is_error"], "approval_refused" in error), (True, False))
        self.assertEqual(run["steps"][4]["failure_reasons"], ["tool_execution_error"])

    async def test_manifest_records_the_approval(self):
        reports = [report(), report(), report(approved=True)]
        run = await run_t2(reports, tools={2: write(source(9))}, gate=GATE, max_steps=3, tests=self)
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            manifest = analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])
        approval = manifest["approval"]
        self.assertEqual((approval["approved_step"], approval["refused_writes"], approval["gate"]), (3, 1, GATE))
        self.assertEqual(approval["notice_sha256"], run["conditions"]["write_gate"]["notice_sha256"])
        self.assertEqual(manifest["task"]["output_contract_version"], V3)


if __name__ == "__main__":
    unittest.main()
