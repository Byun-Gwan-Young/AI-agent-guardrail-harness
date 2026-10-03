"""C-18-3 part 4: the T1 trial plan (CS, MR, LR normal and stall, observe, once each) splits into a CS lane, an MR lane
(which needs TAVILY_API_KEY) and an LR lane; it does not require the final freeze; the credit estimate takes the
measured C-18-1 30-step session as the upper value of each session and gives no lower value. Offline."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scenario_schema import load_scenario  # noqa: E402
from tools import c18_3_evidence, run_batch  # noqa: E402

PLAN = ROOT / "batch_plans/demo-trial-c18-3.yaml"


class TrialPlan(unittest.TestCase):
    def test_three_lanes_cs_mr_lr(self):
        plan = run_batch.load_plan(PLAN)
        self.assertFalse(plan["requires_final_freeze"])
        lanes = {k: [i.key for i in run_batch.lane_items(plan, k, 3)] for k in (1, 2, 3)}
        self.assertEqual(lanes, {1: ["DEMO-CS-normal-v1:observe:1", "DEMO-CS-stall-v1:observe:1"],
                                 2: ["DEMO-MR-normal-v1:observe:1", "DEMO-MR-stall-v1:observe:1"],
                                 3: ["DEMO-LR-normal-v1:observe:1", "DEMO-LR-stall-v1:observe:1"]})
        keys = {k: sorted({key for i in run_batch.lane_items(plan, k, 3)
                           for key in run_batch.required_keys(load_scenario(ROOT / i.scenario))}) for k in (1, 2, 3)}
        self.assertEqual(keys, {1: ["KMU_API_KEY"], 2: ["KMU_API_KEY", "TAVILY_API_KEY"], 3: ["KMU_API_KEY"]})

    def test_the_estimate_uses_the_measured_30_step_session_as_the_upper_value(self):
        result = c18_3_evidence.trial_estimate()
        self.assertEqual([r["high"] for r in result["sessions"]], [126.5433] * 6)
        self.assertEqual([r["low"] for r in result["sessions"]], [None] * 6)
        self.assertEqual(result["total"], {"low": None, "high": 759.2598})
        saved = json.loads((ROOT / "reports/c18-3/estimate-trial.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, result)


if __name__ == "__main__":
    unittest.main()
