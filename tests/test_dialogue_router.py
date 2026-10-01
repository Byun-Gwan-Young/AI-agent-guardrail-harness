"""C-17-4 part 2: the CS router turn order (DM-19), offline.

The next role is the verified final report's handoff_to; with no report, a null, the same role or a value outside
the roles, the fixed order. No model call of its own, no model reasoning. The decision and its basis are in each
step record; handoff round trips are recorded by progress-v3 only and never change the judgement (DM-22).
"""
import unittest

from criteria_policy import evaluate_criteria
from experiments.dialogue_runner import next_turn
from progress_signal_v3 import calculate_progress as calculate_v3
from scenario_schema import load_scenario
from t1_harness import DELIVERABLE, FIXTURE, report, run_t1

LOOKUP = {1: ("lookup_order", {"order_id": "A-100"})}


def without_handoff(observation):
    keep = {k: observation[k] for k in ("agent_id", "step_id", "llm_turns", "progress_source", "progress_metric",
                                        "artifact", "termination_context", "collection", "issue_report")}
    conversation = {k: v for k, v in observation["conversation"].items() if k != "handoff_to"}
    return {**keep, "conversation": conversation, "extracted_conversation": None}


class RouterRuleTests(unittest.TestCase):
    def test_router_rules(self):
        router = load_scenario(FIXTURE)  # turn_order: router; roles intake, refund, shipping
        cases = [(0, report(handoff="shipping"), None, 2, "handoff_to", None),
                 (1, report(handoff="intake"), None, 0, "handoff_to", None),
                 (1, report(handoff=None), None, 2, "fixed_order_fallback", "no_handoff"),
                 (1, report(handoff="refund"), None, 2, "fixed_order_fallback", "self_handoff"),
                 (2, report(handoff="nobody"), None, 0, "fixed_order_fallback", "handoff_to_not_allowed"),
                 (2, None, "handoff_to_not_allowed", 0, "fixed_order_fallback", "handoff_to_not_allowed"),
                 (2, None, "strict_schema_mismatch", 0, "fixed_order_fallback", "strict_schema_mismatch"),
                 (0, None, None, 1, "fixed_order_fallback", "no_verified_final_report")]
        for current, value, failure, index, rule, reason in cases:
            with self.subTest(current=current, value=value, failure=failure):
                chosen, route = next_turn(router, current, value, failure)
                self.assertEqual((chosen, route["rule"], route["fallback_reason"]), (index, rule, reason))
                self.assertEqual(route["next_agent"], ["intake", "refund", "shipping"][index])
                self.assertEqual(route["basis"], "verified_final_report" if value is not None else None)


class RouterRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_handoff_chooses_the_next_role(self):
        reports = [report("triage", handoff="refund", adopted=["ticket"]),
                   report("assigned", handoff="intake", adopted=["ticket", "owner"]),
                   report("resolved", adopted=["ticket", "owner", "code"], deliverable=DELIVERABLE, declared=True,
                          issues=())]
        run = await run_t1(reports, tools=LOOKUP, tests=self)
        steps = run["steps"]
        self.assertEqual((run["summary"]["termination_reason"], run["conditions"]["turn_order"]), ("success", "router"))
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "intake"])
        self.assertEqual([(s["route"]["rule"], s["route"]["next_agent"], s["route"]["handoff_to"]) for s in steps],
                         [("handoff_to", "refund", "refund"), ("handoff_to", "intake", "intake"),
                          ("fixed_order_fallback", "refund", None)])
        self.assertTrue(all(s["route"]["basis"] == "verified_final_report" for s in steps))

    async def test_round_trips_are_recorded_and_do_not_change_the_judgement(self):
        handoffs = ["refund", "shipping", "refund", "shipping", "refund", "shipping"]
        run = await run_t1([report("triage", handoff=h) for h in handoffs], max_steps=6, tests=self)
        self.assertEqual([s["agent"] for s in run["steps"]],
                         ["intake", "refund", "shipping", "refund", "shipping", "refund"])
        observations = run["session"]["observations"]
        # Consecutive passes between the same two roles: intake->refund is a different pair from refund<->shipping.
        self.assertEqual([(o["progress"]["handoff"] or {}).get("count") for o in observations], [1, 1, 2, 3, 4, 5])
        stop = observations[5]["criteria"]
        self.assertEqual((stop["decision"], stop["explanation"]["template_id"]), ("deadlock", "E4"))
        self.assertEqual(stop["explanation"]["text"],
                         "환불 담당과 배송 담당이 문의를 서로 5 번 넘겼고 처리 상태는 '분류'에서 바뀌지 않았습니다.")
        # The same observations without handoff_to are judged the same; only the sentence changes (DM-22).
        meta = run["session"]["meta"]
        history = []
        for observation in observations:
            raw = without_handoff(observation)
            record = {**raw, "progress": calculate_v3(history, raw, meta["criteria_parameters"], meta["registration"])}
            history.append({**record, "criteria": evaluate_criteria(history + [record], meta, meta["registration"])})
        self.assertEqual([(h["progress"]["state"], h["criteria"]["decision"]) for h in history],
                         [(o["progress"]["state"], o["criteria"]["decision"]) for o in observations])
        self.assertEqual(history[5]["criteria"]["explanation"]["template_id"], "E5")
        # The router never calls a model of its own, and a step keeps the per-step call limit.
        self.assertEqual(len(run["requests"]), sum(s["llm_calls"] for s in run["steps"]))
        self.assertTrue(all(s["llm_calls"] <= 3 for s in run["steps"]))

    async def test_unusable_handoffs_fall_back_to_the_fixed_order(self):
        reports = [report("triage", handoff="nobody"), report("triage", handoff="refund"), report("triage")]
        run = await run_t1(reports, max_steps=3, tests=self)
        steps = run["steps"]
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "shipping"])
        # Outside the roles: a vocabulary violation, nothing observed, the fixed order next.
        self.assertEqual((steps[0]["vocabulary_violation"], steps[0]["route"]["fallback_reason"],
                          steps[0]["route"]["basis"]), ("handoff_to_not_allowed", "handoff_to_not_allowed", None))
        # The same role: the report is valid; the turn ignores it and, since DM-44 (C-17-5), it is a vocabulary
        # violation whose value is left out of the observation (tests/test_c17_5_part0.py).
        self.assertEqual((steps[1]["step_status"], steps[1]["route"]["fallback_reason"], steps[1]["vocabulary_violation"]),
                         ("completed", "self_handoff", "handoff_to_self"))
        self.assertNotIn("handoff_to", run["session"]["observations"][1]["conversation"])
        self.assertEqual(run["session"]["observations"][1]["conversation"]["status"], "triage")
        self.assertEqual(run["summary"]["route_fallbacks"],
                         [{"step_id": 1, "reason": "handoff_to_not_allowed"}, {"step_id": 2, "reason": "self_handoff"},
                          {"step_id": 3, "reason": "no_handoff"}])

    async def test_a_verified_report_of_a_failed_step_still_routes(self):
        # An unknown tool call fails the step, but its final report is verified (G0-13) and its handoff_to is used.
        run = await run_t1([report("triage", handoff="shipping"), report("triage")], max_steps=2,
                           tools={1: ("print_tree", {})}, tests=self)
        first = run["steps"][0]
        self.assertEqual((first["step_status"], first["failure_reasons"], first["shared_narrative_source"]),
                         ("failed", ["unknown_tool", "tool_execution_error"], "verified_final_report"))
        self.assertEqual((first["route"]["rule"], run["steps"][1]["agent"]), ("handoff_to", "shipping"))
        self.assertEqual(run["session"]["observations"][0]["conversation"]["handoff_to"], "shipping")


if __name__ == "__main__":
    unittest.main()
