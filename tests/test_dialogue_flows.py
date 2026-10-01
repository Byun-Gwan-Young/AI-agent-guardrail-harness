"""C-17-4 part 3: integration flows on the synthetic TEST-T1-v2 fixture, offline (fake upstream, in-memory proxy).

Normal flow, stall under observe (E1-T1 with registered Korean names, run continues) and under block (403,
guardrail_stop, sentence in the error body), escalated ending, mixed vocabulary violations and shape errors, the
CS router (tests/test_dialogue_router.py), and the scenario-v1 path compared byte for byte with the capture made
before C-17-4 (tests/fixtures/c17-4-v1-requests.json). Demo scenarios themselves are C-18.
"""
import json
from pathlib import Path
import unittest

from t1_harness import BLOCK_CONFIG, DELIVERABLE, report, run_t1
import v1_request_capture

ROOT = Path(__file__).resolve().parents[1]
# Fixed order with two T1 metrics: E1-T1 names only these (DM-31), and E5 (adopted items) is not selected.
STALL = {"turn_order": "fixed", "progress_metric": {"conversation": ["status_advance", "new_issue_ids"], "artifact": []},
         "required_adopted_items": None}


def conversations(run):
    return [o["conversation"] for o in run["session"]["observations"]]


class NormalFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_advances_to_the_last_status_judge_passes_no_stop(self):
        reports = [report("triage", handoff="refund", adopted=["ticket"]),
                   report("assigned", handoff="intake", adopted=["ticket", "owner"]),
                   report("resolved", adopted=["ticket", "owner", "code"], deliverable=DELIVERABLE, declared=True,
                          issues=())]
        run = await run_t1(reports, tools={1: ("lookup_order", {"order_id": "A-100"})}, tests=self)
        summary = run["summary"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["steps"]), (0, "success", 3))
        self.assertEqual(summary["completion_gate"], {"machine_success": True, "result": "resolved", "missing": []})
        self.assertEqual(summary["criteria_alerts"], [])
        self.assertEqual([o["criteria"]["decision"] for o in run["session"]["observations"]], ["continue"] * 3)
        self.assertEqual([c["status"] for c in conversations(run)], ["triage", "assigned", "resolved"])
        self.assertEqual(run["session"]["meta"]["termination_reason"], "success")


class StallTests(unittest.IsolatedAsyncioTestCase):
    async def test_observe_records_the_stop_and_keeps_running(self):
        run = await run_t1([report("received") for _ in range(8)], scenario_changes=STALL, tests=self)
        summary, observations = run["summary"], run["session"]["observations"]
        self.assertEqual((summary["termination_reason"], summary["steps"], run["code"]), ("max_steps", 8, 0))
        decisions = [o["criteria"]["decision"] for o in observations]
        self.assertEqual(decisions.index("deadlock"), 5)
        stop = observations[5]["criteria"]["explanation"]
        # DM-26, DM-31, DM-35: registered Korean role and status names, only the selected signals.
        self.assertEqual((stop["template_id"], stop["text"]),
                         ("E1-T1", "최근 3 step 동안 접수·환불 담당·배송 담당 모두 처리 상태 변화·새 쟁점이 없습니다. "
                                   "처리 상태 '접수'."))
        self.assertEqual(len(summary["criteria_alerts"]), decisions.count("deadlock"))
        self.assertNotIn("guardrail_block", run["session"]["meta"])

    async def test_adopted_items_selected_gives_e5_with_the_registered_count(self):
        run = await run_t1([report("triage", adopted=["ticket"]) for _ in range(6)],
                           scenario_changes={"turn_order": "fixed"}, max_steps=6, tests=self)
        stop = run["session"]["observations"][5]["criteria"]["explanation"]
        self.assertEqual((stop["template_id"], stop["text"]),
                         ("E5", "최근 3 step 동안 채택 항목이 1/3 에서 늘지 않았고 처리 상태는 '분류' 입니다."))

    async def test_block_refuses_the_next_request_and_ends_with_guardrail_stop(self):
        run = await run_t1([report("received") for _ in range(8)], config=BLOCK_CONFIG, scenario_changes=STALL,
                           tests=self)
        summary, steps, session = run["summary"], run["steps"], run["session"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["error"]), (0, "guardrail_stop", None))
        self.assertEqual((summary["guardrail_stop"]["stop_step"], summary["guardrail_stop"]["blocked_step"]), (6, 7))
        text = session["observations"][5]["criteria"]["explanation"]["text"]
        self.assertEqual(summary["guardrail_stop"]["message"], text)
        self.assertIn("접수·환불 담당·배송 담당", text)
        self.assertEqual(session["turns"][-1]["response_body"]["error"]["message"], text)
        self.assertEqual(session["turns"][-1]["status_code"], 403)
        self.assertEqual([s["step_status"] for s in steps], ["completed"] * 6 + ["blocked"])
        self.assertEqual((len(session["observations"]), session["meta"]["guardrail_block"]["refused_requests"]), (6, 1))
        self.assertEqual(run["conditions"]["guardrail_mode"], "block")
        self.assertEqual(summary["total_tokens"], sum(t["tokens"] for t in session["turns"]))


class EscalationTests(unittest.IsolatedAsyncioTestCase):
    async def test_escalated_status_ends_the_run(self):
        reports = [report("triage", handoff="refund"), report("escalated", narrative="정책이 서로 떠넘깁니다")]
        run = await run_t1(reports, tests=self)
        summary = run["summary"]
        self.assertEqual((summary["termination_reason"], summary["terminal_status"], summary["steps"], run["code"]),
                         ("escalated", "escalated", 2, 0))
        self.assertEqual(summary["completion_gate"]["result"], "escalated")
        last = run["session"]["observations"][-1]
        self.assertEqual(last["conversation"]["status"], "escalated")
        # A terminal status is outside the order: unmeasured for status_advance, never a STOP (DM-18).
        self.assertEqual(last["progress"]["metrics"]["conversation.status_advance"]["status"], "unmeasured")
        self.assertEqual(summary["criteria_alerts"], [])
        self.assertEqual(run["session"]["meta"]["termination_reason"], "escalated")

    async def test_another_terminal_status_ends_under_its_own_reason(self):
        changes = {"terminal_statuses": [{"id": "escalated", "label": "에스컬레이션"},
                                         {"id": "withdrawn", "label": "철회"}]}
        run = await run_t1([report("withdrawn")], scenario_changes=changes, tests=self)
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["terminal_status"]),
                         ("terminal_status", "withdrawn"))


class VocabularyTests(unittest.IsolatedAsyncioTestCase):
    async def test_violations_are_counted_not_observed_and_kept_out_of_the_strict_stop(self):
        reports = [report("triage"), report("closed"), report("triage", handoff="nobody"), report("closed"),
                   "not json", report("assigned"), "not json", "not json"]
        run = await run_t1(reports, scenario_changes={"turn_order": "fixed"}, tests=self)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual([s["vocabulary_violation"] for s in steps],
                         [None, "status_not_allowed", "handoff_to_not_allowed", "status_not_allowed", None, None, None,
                          None])
        self.assertEqual([s["consecutive_strict_failures"] for s in steps], [0, 0, 0, 0, 1, 0, 1, 2])
        self.assertEqual([s["consecutive_vocabulary_violations"] for s in steps], [0, 1, 2, 3, 0, 0, 0, 0])
        self.assertEqual((summary["vocabulary_violations_total"], summary["vocabulary_violation_steps"]), (3, [2, 3, 4]))
        # Three violations in a row do not stop the run; two shape errors in a row do.
        self.assertEqual((summary["termination_reason"], summary["error"]),
                         ("strict_output_failures", "two_consecutive_strict_failed_steps"))
        self.assertEqual([s["step_status"] for s in steps],
                         ["completed", "failed", "failed", "failed", "failed", "completed", "failed", "failed"])
        # The violating values never reach the observation: no status, no handoff_to, the step unmeasured.
        observed = conversations(run)
        for index in (1, 2, 3, 4, 6, 7):
            self.assertNotIn("status", observed[index])
            self.assertNotIn("handoff_to", observed[index])
            self.assertEqual(run["session"]["observations"][index]["progress"]["state"], "unmeasured")
        self.assertEqual(observed[5]["status"], "assigned")
        self.assertEqual(steps[1]["collection"]["final_output_reason"],
                         "final output contract violation: status_not_allowed")


class ScenarioV1PathTests(unittest.IsolatedAsyncioTestCase):
    async def test_a1_v4_requests_are_byte_identical_to_the_pre_c17_4_capture(self):
        expected = json.loads((ROOT / "tests/fixtures/c17-4-v1-requests.json").read_text(encoding="utf-8"))
        now = v1_request_capture.record(await v1_request_capture.capture())
        canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(canonical(now["first_request_messages"]), canonical(expected["first_request_messages"]))
        self.assertEqual(now["first_request_messages_sha256"], expected["first_request_messages_sha256"])
        self.assertEqual(now["request_body_sha256"], expected["request_body_sha256"])
        self.assertEqual((now["termination_reason"], now["request_count"]), ("max_steps", 12))


if __name__ == "__main__":
    unittest.main()
