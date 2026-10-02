"""C-17-5 part 3: integration flows of scenario-v2 artifact tasks, offline (fake upstream, in-memory proxy).

Approval normal (spec, approval, edit, all tests, success), approval stall under observe (refused writes, unchanged
files, a v0.3 STOP, the run goes on, no runner error) and under block (403, guardrail_stop), and the T3 shapes on a
CL-like task without a gate: a revert is not progress, and without a new best pass count for more than K = 6 steps
the STOP is E2 ("… 파일이 …") or E3. Fixed order planner (1, 4, ...), developer (2, 5, ...), reviewer (3, 6, ...).
The DM-37 equivalence and the scenario-v1 bytes are tests/test_artifact_v2.py and tests/test_dialogue_flows.py.
Demo scenarios themselves are C-18.
"""
from pathlib import Path
import unittest

from t2_harness import BLOCK_CONFIG, GATE, OBSERVE_CONFIG, SOURCE, V2, report, run_t2, source, write

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = (ROOT / "scenario_assets/A-1/src/task_query.py").read_text(encoding="utf-8")
STALL_E1 = "최근 3 step 동안 기획·개발·리뷰 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 7/16."


def decisions(run):
    return [o["criteria"]["decision"] for o in run["session"]["observations"]]


def first_stop(run):
    return next(o for o in run["session"]["observations"] if o["criteria"]["decision"] == "deadlock")


class ApprovalFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_spec_approval_edit_tests_success(self):
        reports = [report(), report(), report(approved=True), report(), report(),
                   report(approved=True, declared=True, issues=())]
        tools = {1: write("# spec\n", "SPEC.md"), 5: write(source(16))}
        run = await run_t2(reports, tools=tools, gate=GATE, max_steps=8, tests=self)
        summary = run["summary"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["steps"]), (0, "success", 6))
        self.assertEqual((summary["tests_passed_before"], summary["tests_passed_after"]), (7, 16))
        self.assertEqual((summary["approval"]["approved_step"], summary["approval"]["refused_writes"]), (3, 0))
        self.assertEqual(summary["criteria_alerts"], [])
        self.assertNotIn("deadlock", decisions(run))

    async def stall(self, config):
        # The reviewer never approves; the developer writes every turn and is refused every time.
        tools = {s: write(source(16)) for s in (2, 5, 8, 11)}
        return await run_t2([report(approved=False) for _ in range(12)], tools=tools, gate=GATE, max_steps=12,
                            config=config, tests=self)

    async def test_stall_under_observe_records_the_stop_and_keeps_running(self):
        run = await self.stall(OBSERVE_CONFIG)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["steps"], summary["error"]),
                         (0, "max_steps", 12, None))
        self.assertEqual(decisions(run).index("deadlock"), 5)
        stop = first_stop(run)["criteria"]["explanation"]
        self.assertEqual((stop["template_id"], stop["text"]), ("E1", STALL_E1))
        # Every write refused, no file changed, no strict failure, never a runner error.
        self.assertEqual(summary["approval"]["refused_writes_by_step"], {"2": 1, "5": 1, "8": 1, "11": 1})
        self.assertIsNone(summary["approval"]["approved_step"])
        self.assertEqual((run["out"] / "workspace" / SOURCE).read_text(encoding="utf-8"), ORIGINAL)
        self.assertEqual({s["consecutive_strict_failures"] for s in steps}, {0})
        self.assertEqual([s["failure_reasons"] for s in steps if s["step_status"] == "failed"],
                         [["write_refused_before_approval"]] * 4)
        self.assertEqual(summary["tests_passed_after"], 7)

    async def test_stall_under_block_ends_with_guardrail_stop(self):
        run = await self.stall(BLOCK_CONFIG)
        summary = run["summary"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["steps"]), (0, "guardrail_stop", 7))
        block = summary["guardrail_stop"]
        self.assertEqual((block["stop_step"], block["blocked_step"], block["template_id"], block["message"]),
                         (6, 7, "E1", STALL_E1))
        self.assertEqual(block["message"], first_stop(run)["criteria"]["explanation"]["text"])
        self.assertEqual(run["steps"][-1]["step_status"], "blocked")
        self.assertEqual(summary["approval"]["refused_writes"], 2)
        self.assertEqual(run["session"]["meta"]["guardrail_block"]["refused_requests"], 1)


class T3FlowTests(unittest.IsolatedAsyncioTestCase):
    """A CL-like task (output-contract-v2, no gate): the developer edits, the pass count never sets a new best."""

    async def run_edits(self, tools, steps):
        return await run_t2([report(contract=V2) for _ in range(steps)], tools=tools, contract=V2, max_steps=steps,
                            tests=self)

    async def test_a_revert_after_k_steps_stops_with_e2(self):
        # Best 9 at step 2; new contents at 5 and 8; at 11 the developer restores the original file, a state the
        # session saw at step 1 (the developer never did): a global revert, not progress, past K = 6.
        tools = {2: write(source(9)), 5: write(source(8)), 8: write(source(8) + "# b\n"), 11: write(ORIGINAL)}
        run = await self.run_edits(tools, 13)
        observations = run["session"]["observations"]
        t3 = observations[10]["progress"]["t3"]
        self.assertEqual((observations[10]["progress"]["state"], t3["applied"], t3["revert_to_step"]),
                         ("oscillating", "global_revert", 1))
        self.assertEqual(decisions(run).index("deadlock"), 10)
        stop = observations[10]["criteria"]["explanation"]
        self.assertEqual((stop["template_id"], stop["text"]),
                         ("E2", "src/task_query.py 파일이 step 1의 내용으로 되돌아갔고, 통과 테스트는 9 step 동안 7/16입니다."))
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")

    async def test_a_role_returning_to_its_own_earlier_file_is_not_progress(self):
        tools = {2: write(source(9)), 5: write(source(8)), 8: write(source(9)), 11: write(source(8))}
        run = await self.run_edits(tools, 12)
        states = [o["progress"]["state"] for o in run["session"]["observations"]]
        self.assertEqual(states[7:], ["oscillating"] * 5)
        stop = first_stop(run)
        self.assertEqual((stop["step_id"], stop["criteria"]["explanation"]["template_id"]), (10, "E7"))

    async def test_edits_without_a_new_best_for_more_than_k_steps_stop_with_e3(self):
        tools = {2: write(source(9)), **{s: write(source(8) + f"# edit {s}\n") for s in (5, 8, 11)}}
        run = await self.run_edits(tools, 11)
        observations = run["session"]["observations"]
        # Within K the file changes still count; past it they do not.
        self.assertEqual([o["progress"]["state"] for o in observations[4:8]], ["progress"] * 4)
        self.assertEqual([o["progress"]["t3"]["applied"] for o in observations[8:]], ["test_plateau"] * 3)
        stop = first_stop(run)
        self.assertEqual((stop["step_id"], stop["criteria"]["explanation"]["text"]),
                         (11, "step 2 이후 9 step 동안 파일이 3 번 바뀌었지만 통과 테스트는 8/16에서 늘지 않았습니다."))


if __name__ == "__main__":
    unittest.main()
