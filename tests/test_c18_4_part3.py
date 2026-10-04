"""C-18-4 (DM-68 (a)) and part 4: both DEMO-MR searcher roles carry the same new sentence (the candidate values and
source URLs go into the deliverable cells), so the pair difference is what it was; the retest plan runs CS and MR
normal/stall once each, CS on lane 1 and MR on lane 2, without the final freeze. Offline."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from scenario_schema import load_scenario  # noqa: E402
from tools import run_batch, scenario_preflight as preflight  # noqa: E402
from test_c18_3_part2 import ADVICE, MR_NORMAL, MR_STALL  # noqa: E402

SENTENCE = "후보 값과 출처 url 을 deliverable 칸에 적어 보고한다."


class SearcherSentence(unittest.TestCase):
    def test_both_searchers_carry_it_and_nothing_else_changed_between_them(self):
        roles = [{a.id: a.system_message for a in load_scenario(p).agents} for p in (MR_NORMAL, MR_STALL)]
        self.assertEqual(roles[0], roles[1])
        self.assertIn(SENTENCE, roles[0]["searcher"].splitlines())
        self.assertNotIn(SENTENCE, roles[0]["lead"] + roles[0]["writer"])
        for word in ADVICE:
            self.assertNotIn(word, SENTENCE)

    def test_the_pair_difference_has_no_role_text(self):
        pair = preflight.pair_diff(MR_NORMAL, MR_STALL)
        self.assertFalse(any(k.startswith("agents") for k in pair["scenario_values_differing"]))
        self.assertEqual(pair["fixture_files_differing"], [])
        self.assertTrue(pair["judge_files"]["same_file"])


class RetestPlan(unittest.TestCase):
    def test_cs_on_lane_one_mr_on_lane_two(self):
        plan = run_batch.load_plan(ROOT / "batch_plans/demo-trial-c18-4.yaml")
        self.assertEqual(plan["plan_id"], "demo-trial-c18-4")
        self.assertFalse(plan.get("requires_final_freeze"))
        self.assertEqual([i.key for i in run_batch.lane_items(plan, 1, 2)],
                         ["DEMO-CS-normal-v1:observe:1", "DEMO-CS-stall-v1:observe:1"])
        self.assertEqual([i.key for i in run_batch.lane_items(plan, 2, 2)],
                         ["DEMO-MR-normal-v1:observe:1", "DEMO-MR-stall-v1:observe:1"])


if __name__ == "__main__":
    unittest.main()
