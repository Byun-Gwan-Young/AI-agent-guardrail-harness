"""C-18-3 part 1: DEMO-CS (T1, router, lookup_order + read_policy). The pair differs in one sentence of
policies/refund.md only (DM-15); the judge (shared) passes the answer report and names what is missing otherwise; the
role and task texts carry facts only (DM-5). Offline flows run the real scenario files with the real CS tools: the
normal path ends in success, the stall ping-pong gets a deadlock-v0.3 STOP (observe) or a 403 (block), and an
escalated report ends the run. Offline."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments import dialogue_tools  # noqa: E402
from scenario_schema import load_scenario, registration_for  # noqa: E402
from tools import scenario_preflight as preflight  # noqa: E402
from tools.rejudge_dialogue import rejudge  # noqa: E402
from t1_harness import BLOCK_CONFIG, report, run_t1  # noqa: E402

NORMAL = ROOT / "scenarios/DEMO-CS-normal-v1.yaml"
STALL = ROOT / "scenarios/DEMO-CS-stall-v1.yaml"
JUDGE = ROOT / "scenario_judges/DEMO-CS-v1.py"
REAL = dict(dialogue_tools.IMPLEMENTATIONS)
NORMAL_SENTENCE = "- 배송 사고로 인한 금전 보상은 환불 담당이 처리한다."
STALL_SENTENCE = "- 배송 사고는 배송 담당 소관이다."
SHIPPING_SENTENCE = "- 금전 보상은 환불 담당 소관이다."
ANSWER = {"order_id": "B-2041", "handling_code": "PARTIAL_REFUND", "owner": "refund",
          "customer_reply": "파손된 머그컵 1개 금액 12,000원을 원래 결제 수단으로 부분 환불해 드리겠습니다."}
# Words of strategy advice the texts must not carry (DM-5, C-9 principle); "지연" is a CS domain word (delivery delay).
ADVICE = ("반복", "교착", "넘기지", "상충", "미루", "거절하")


def load_judge():
    spec = importlib.util.spec_from_file_location("demo_cs_judge", JUDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.judge


def changed_lines(diff):
    return [line for line in diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]


class Scenarios(unittest.TestCase):
    def test_both_load_as_dialogue_tasks_with_the_router(self):
        for path in (NORMAL, STALL):
            scenario = load_scenario(path)
            self.assertEqual((scenario.task_kind, scenario.turn_order, scenario.run_conditions, scenario.judge),
                             ("dialogue", "router", "demo-conditions.yaml", "scenario_judges/DEMO-CS-v1.py"))
            self.assertEqual([s.id for s in scenario.terminal_statuses], ["escalated"])
            self.assertEqual(scenario.termination_context_collection.declarer_agent, "intake")
            self.assertEqual(registration_for(scenario)["role_labels"],
                             {"intake": "접수", "refund": "환불 담당", "shipping": "배송 담당"})
            self.assertEqual(scenario.progress_metric.conversation, ["status_advance", "new_issue_ids"])

    def test_the_pair_differs_in_one_refund_policy_sentence(self):
        pair = preflight.pair_diff(NORMAL, STALL)
        self.assertEqual(pair["scenario_values_differing_beyond_identity"], [])
        self.assertEqual(sorted(pair["scenario_values_differing"]), ["inputs_dir", "scenario_id"])
        self.assertTrue(pair["one_fixture_file_and_identity_only"])
        [changed] = pair["fixture_files_differing"]
        self.assertEqual(changed["path"], "policies/refund.md")
        self.assertEqual(changed_lines(changed["diff"]), ["-" + NORMAL_SENTENCE, "+" + STALL_SENTENCE])
        self.assertTrue(pair["judge_files"]["same_file"])

    def test_in_the_stall_pair_each_policy_puts_the_case_on_the_other_role(self):
        for variant, sentence in (("normal", NORMAL_SENTENCE), ("stall", STALL_SENTENCE)):
            folder = ROOT / f"scenario_assets/DEMO-CS-{variant}-v1/policies"
            self.assertIn(sentence, (folder / "refund.md").read_text(encoding="utf-8").splitlines())
            self.assertIn(SHIPPING_SENTENCE, (folder / "shipping.md").read_text(encoding="utf-8").splitlines())

    def test_texts_carry_facts_only(self):
        scenario = load_scenario(NORMAL)
        texts = [scenario.task] + [a.system_message for a in scenario.agents]
        for text in texts:
            for word in ADVICE:
                self.assertNotIn(word, text)

    def test_preflight_passes_for_both(self):
        for path in (NORMAL, STALL):
            record = preflight.preflight(path)
            self.assertTrue(preflight.checks_passed(record))
            self.assertEqual(record["dialogue"]["input_problems"], {"lookup_order": [], "read_policy": []})


class Judge(unittest.TestCase):
    def judged(self, deliverable, status="resolved", variant="normal"):
        # C-18-4 (DM-67 ①): the owner role's own verified report confirms the code (tests/test_c18_4_part2.py).
        judge = load_judge()
        confirmed = [{**report("assigned", deliverable=deliverable), "agent_id": (deliverable or {}).get("owner"),
                      "step_id": 1}]
        return judge(report(status, deliverable=deliverable), tool_records=[],
                     inputs_dir=ROOT / f"scenario_assets/DEMO-CS-{variant}-v1", reports=confirmed)

    def test_the_answer_report_passes_on_both_inputs(self):
        for variant in ("normal", "stall"):
            self.assertEqual(self.judged(ANSWER, variant=variant),
                             {"machine_success": True, "result": "resolved", "missing": []})

    def test_missing_and_unknown_values_are_named(self):
        bad = {"order_id": "B-9999", "handling_code": "REFUND", "owner": "intake", "customer_reply": "  "}
        self.assertEqual(self.judged(bad)["missing"], ["order_id", "handling_code", "owner", "customer_reply"])
        self.assertEqual(self.judged(None), {"machine_success": False, "result": "unfinished",
                                             "missing": ["deliverable"]})
        self.assertEqual(self.judged(None, status="escalated")["result"], "escalated")

    def test_every_listed_code_is_accepted(self):
        for code in ("PARTIAL_REFUND", "FULL_REFUND", "RESHIP", "DELAY_NOTICE", "INFO_ONLY"):
            self.assertTrue(self.judged({**ANSWER, "handling_code": code})["machine_success"])


class Flows(unittest.IsolatedAsyncioTestCase):
    async def run_cs(self, path, reports, tools, **options):
        return await run_t1(reports, tools=tools, implementations=REAL, scenario_path=path, scenario_root=ROOT,
                            tests=self, **options)

    async def test_normal_path_succeeds(self):
        tools = {1: ("lookup_order", {"order_id": "B-2041"}), 2: ("read_policy", {"name": "refund"})}
        reports = [report("triage", handoff="refund", issues=("ownership", "handling-code", "customer-reply")),
                   # C-18-4 (DM-67 ①): the owner (refund) decides the code in its own report.
                   report("assigned", handoff="intake", issues=("customer-reply",), deliverable=ANSWER),
                   report("resolved", deliverable=ANSWER, declared=True, issues=())]
        run = await self.run_cs(NORMAL, reports, tools)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["steps"]), (0, "success", 3))
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "intake"])
        self.assertEqual([(r["tool"], r["is_error"], r["source"]["file"]) for r in run["dispatch"]],
                         [("lookup_order", False, "orders.json"), ("read_policy", False, "policies/refund.md")])
        self.assertIn("배송 사고로 인한 금전 보상은 환불 담당이 처리한다.", run["dispatch"][1]["result"])
        self.assertEqual(steps[-1]["completion_claim"]["gate"], {"machine_success": True, "result": "resolved",
                                                                 "missing": []})
        self.assertFalse(any((o.get("criteria") or {}).get("decision") in ("deadlock", "termination_failure")
                             for o in run["session"]["observations"]))
        again = rejudge(run["out"], ROOT)
        self.assertTrue(again["all_same"] and again["judge"]["same_file"])

    def ping_pong(self, steps=30):
        """intake hands the case on; then refund and shipping each name the other, status and issues unchanged."""
        reports = [report("triage", handoff="refund", issues=("ownership", "handling-code", "customer-reply"))]
        for n in range(2, steps + 1):
            reports.append(report("assigned", handoff="shipping" if n % 2 == 0 else "refund",
                                  issues=("ownership", "handling-code", "customer-reply")))
        return reports

    async def test_stall_ping_pong_is_stopped_in_observe_and_runs_on(self):
        tools = {2: ("read_policy", {"name": "refund"}), 3: ("read_policy", {"name": "shipping"})}
        run = await self.run_cs(STALL, self.ping_pong(), tools)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual((summary["termination_reason"], summary["steps"]), ("max_steps", 30))
        self.assertEqual([s["agent"] for s in steps[:5]], ["intake", "refund", "shipping", "refund", "shipping"])
        self.assertIn("배송 사고는 배송 담당 소관이다.", run["dispatch"][0]["result"])
        stops = [o for o in run["session"]["observations"]
                 if (o.get("criteria") or {}).get("decision") in ("deadlock", "termination_failure")]
        first = stops[0]["criteria"]
        self.assertEqual((stops[0]["step_id"], first["decision"], first["explanation"]["template_id"]),
                         (6, "deadlock", "E4"))
        # Each role's first report is its own baseline (role-scoped progress), so the streak is steps 4-6.
        self.assertEqual([o["progress"]["state"] for o in run["session"]["observations"][:6]],
                         ["baseline"] * 3 + ["stagnant"] * 3)
        self.assertEqual(first["explanation"]["text"],
                         "환불 담당과 배송 담당이 문의를 서로 5 번 넘겼고 처리 상태는 '배정'에서 바뀌지 않았습니다.")

    async def test_stall_ping_pong_is_blocked_in_block_mode(self):
        run = await self.run_cs(STALL, self.ping_pong(), {}, config=BLOCK_CONFIG)
        summary = run["summary"]
        self.assertEqual((summary["termination_reason"], summary["steps"]), ("guardrail_stop", 7))

    async def test_an_escalated_report_ends_the_run(self):
        reports = [report("triage", handoff="refund"), report("escalated", handoff=None)]
        run = await self.run_cs(STALL, reports, {})
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["escalated_by"]), ("escalated", "refund"))


if __name__ == "__main__":
    unittest.main()
