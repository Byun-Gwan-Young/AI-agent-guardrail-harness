"""C-18-4 part 2 (DM-67 ①): in DEMO-CS the owner role decides the handling code. Both versions get the same fact
sentence in policies/handling_codes.md and the same judge rule: the final report's owner must have confirmed the same
handling_code in its own verified report. The pair still differs in one policies/refund.md line (DM-15). The runner
hands the session's verified reports to a judge that names a reports parameter and calls the others as before;
tools/rejudge_dialogue.py does the same from steps.json. Success is still the intake's own claim (DM-45). Offline."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments.dialogue_runner import judge_call  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402
from tools import scenario_preflight as preflight  # noqa: E402
from tools.rejudge_dialogue import rejudge  # noqa: E402
from t1_harness import report  # noqa: E402
from test_c18_3_part1 import ADVICE, ANSWER, NORMAL, NORMAL_SENTENCE, REAL, STALL, STALL_SENTENCE, changed_lines  # noqa: E402

JUDGE = ROOT / "scenario_judges/DEMO-CS-v1.py"
OWNER_RULE = ("처리 코드는 그 문의의 담당이 정한다. 접수 담당은 담당을 정하면 그 담당에게 넘기고, "
              "담당이 정한 처리 코드로 고객 답변을 확정한다.")


def cs_judge():
    spec = importlib.util.spec_from_file_location("demo_cs_judge_c18_4", JUDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.judge


def verified(agent, step, deliverable=None, status="assigned"):
    return {**report(status, deliverable=deliverable), "agent_id": agent, "step_id": step}


class Policy(unittest.TestCase):
    def test_both_versions_carry_the_same_owner_rule_sentence(self):
        texts = [(ROOT / f"scenario_assets/DEMO-CS-{v}-v1/policies/handling_codes.md").read_text(encoding="utf-8")
                 for v in ("normal", "stall")]
        self.assertEqual(texts[0], texts[1])
        self.assertIn(OWNER_RULE, texts[0].splitlines())
        for word in ADVICE:
            self.assertNotIn(word, OWNER_RULE)

    def test_the_pair_still_differs_in_one_refund_line(self):
        pair = preflight.pair_diff(NORMAL, STALL)
        self.assertEqual(sorted(pair["scenario_values_differing"]), ["inputs_dir", "scenario_id"])
        [changed] = pair["fixture_files_differing"]
        self.assertEqual((changed["path"], changed_lines(changed["diff"])),
                         ("policies/refund.md", ["-" + NORMAL_SENTENCE, "+" + STALL_SENTENCE]))
        self.assertTrue(pair["one_fixture_file_and_identity_only"] and pair["judge_files"]["same_file"])


class OwnerConfirmation(unittest.TestCase):
    judge = staticmethod(cs_judge())

    def judged(self, reports, deliverable=ANSWER, variant="normal"):
        return self.judge(report("resolved", deliverable=deliverable, declared=True), tool_records=[],
                          inputs_dir=ROOT / f"scenario_assets/DEMO-CS-{variant}-v1", reports=reports)

    def test_the_intake_alone_is_refused(self):
        for reports in ([], [verified("intake", 1, ANSWER, "resolved")], None):
            self.assertEqual(self.judged(reports), {"machine_success": False, "result": "unfinished",
                                                    "missing": ["owner_confirmation"]})

    def test_the_owners_own_report_with_the_same_code_passes(self):
        for variant in ("normal", "stall"):
            self.assertTrue(self.judged([verified("intake", 1), verified("refund", 2, ANSWER)], variant=variant)
                            ["machine_success"])
        shipping = {**ANSWER, "handling_code": "RESHIP", "owner": "shipping"}
        self.assertTrue(self.judged([verified("shipping", 3, shipping)], shipping)["machine_success"])

    def test_another_role_or_another_code_does_not_confirm(self):
        self.assertEqual(self.judged([verified("shipping", 2, ANSWER)])["missing"], ["owner_confirmation"])
        other = {**ANSWER, "handling_code": "FULL_REFUND"}
        self.assertEqual(self.judged([verified("refund", 2, other)])["missing"], ["owner_confirmation"])
        self.assertEqual(self.judged([verified("refund", 2, None)])["missing"], ["owner_confirmation"])

    def test_an_invalid_owner_or_code_is_named_without_the_confirmation(self):
        self.assertEqual(self.judged([], {**ANSWER, "owner": "intake"})["missing"], ["owner"])
        self.assertEqual(self.judged([], {**ANSWER, "handling_code": "REFUND"})["missing"], ["handling_code"])


class JudgeCall(unittest.TestCase):
    def test_reports_reach_only_a_judge_that_names_them(self):
        seen = {}

        def with_reports(report, *, tool_records, inputs_dir, reports=()):
            seen["reports"] = reports
            reports[0]["agent_id"] = "changed"
            return {"machine_success": False, "result": "unfinished", "missing": ["x"]}

        def without_reports(report, *, tool_records, inputs_dir):
            seen["called"] = True
            return {"machine_success": False, "result": "unfinished", "missing": ["x"]}
        history = [verified("refund", 2, ANSWER)]
        judge_call(with_reports, {}, tool_records=[], inputs_dir=None, reports=history)
        self.assertEqual(history[0]["agent_id"], "refund")  # a deep copy; the run's history is not changed
        self.assertEqual(seen["reports"][0]["step_id"], 2)
        judge_call(without_reports, {}, tool_records=[], inputs_dir=None, reports=history)
        self.assertTrue(seen["called"])

    def test_the_other_t1_judges_keep_their_interface(self):
        import inspect
        for name in ("DEMO-MR-v1", "DEMO-LR-normal-v1", "DEMO-LR-stall-v1"):
            spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scenario_judges" / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertNotIn("reports", inspect.signature(module.judge).parameters, name)
        self.assertEqual({load_scenario(p).judge for p in (NORMAL, STALL)}, {"scenario_judges/DEMO-CS-v1.py"})


class Flows(unittest.IsolatedAsyncioTestCase):
    async def run_cs(self, path, reports, tools):
        from t1_harness import run_t1
        return await run_t1(reports, tools=tools, implementations=REAL, scenario_path=path, scenario_root=ROOT,
                            tests=self)

    async def test_normal_intake_refund_intake_succeeds(self):
        tools = {1: ("read_policy", {"name": "handling_codes"}), 2: ("read_policy", {"name": "refund"})}
        reports = [report("triage", handoff="refund", issues=("ownership", "handling-code", "customer-reply")),
                   report("assigned", handoff="intake", issues=("customer-reply",), deliverable=ANSWER),
                   report("resolved", deliverable=ANSWER, declared=True, issues=())]
        run = await self.run_cs(NORMAL, reports, tools)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["steps"]), (0, "success", 3))
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "intake"])
        self.assertIn(OWNER_RULE, run["dispatch"][0]["result"])
        self.assertTrue(steps[-1]["completion_claim"]["accepted"])
        again = rejudge(run["out"], ROOT)
        self.assertTrue(again["all_same"] and again["judge"]["same_file"])

    async def test_the_intake_confirming_alone_is_refused_and_the_run_goes_on(self):
        reports = [report("resolved", deliverable=ANSWER, declared=True, issues=())]
        reports += [report("triage", handoff="refund", issues=("ownership",))] * 2
        run = await self.run_cs(NORMAL, reports + [report("triage", issues=("ownership",))] * 27, {})
        summary, steps = run["summary"], run["steps"]
        self.assertEqual(steps[0]["completion_claim"]["gate"]["missing"], ["owner_confirmation"])
        self.assertFalse(steps[0]["completion_claim"]["accepted"])
        self.assertNotEqual(summary["termination_reason"], "success")
        self.assertEqual(summary["completion_claims"][0]["reasons"], ["judge_unfinished"])
        again = rejudge(run["out"], ROOT)
        self.assertTrue(again["all_same"])

    async def test_stall_ping_pong_still_gets_e4(self):
        reports = [report("triage", handoff="refund", issues=("ownership", "handling-code", "customer-reply"))]
        reports += [report("assigned", handoff="shipping" if n % 2 == 0 else "refund",
                           issues=("ownership", "handling-code", "customer-reply")) for n in range(2, 31)]
        run = await self.run_cs(STALL, reports, {})
        first = next(o["criteria"] for o in run["session"]["observations"]
                     if (o.get("criteria") or {}).get("decision") == "deadlock")
        self.assertEqual(first["explanation"]["template_id"], "E4")


if __name__ == "__main__":
    unittest.main()
