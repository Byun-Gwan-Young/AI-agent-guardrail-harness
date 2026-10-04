"""C-19-1 part 1: tools/aggregate_demo.py over the committed trial records (demo-records-v1 + record/replay.json):
termination classes, "k of n", first STOP templates, detection delay only for artifact tasks (S-27, S-20), "if
stopped" savings, representatives by rule; sessions of another final freeze or condition group are excluded; block
runs are compared with the observe mean only (DM-23). Offline, no raw log."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import aggregate_demo  # noqa: E402

RUNS = ROOT / "runs/demo"
CL = ["DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a", "DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1"]
CT_STALL = "DEMO-CT-stall-v1-819eb0783b724840b9333f480a599666"
MR_NORMAL = "DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b"


def trials():
    return aggregate_demo.aggregate(["demo-trial-c18-2", "demo-trial-c18-3"], sessions=CL)


class Trials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = trials()
        cls.tables = {t["scenario_id"]: t for t in cls.result["scenarios"]}

    def test_sessions_and_classes(self):
        self.assertEqual((self.result["sessions"], self.result["excluded"]), (11, []))
        self.assertEqual(self.result["freeze_check"], "not applied (no --final-freeze-sha256: trial plans)")
        self.assertEqual(self.tables["DEMO-CT-stall-v1"]["stalled_k_of_n"], "1 / 1")
        self.assertEqual(self.tables["DEMO-LR-stall-v1"]["escalated_by"], {"writer": 1})
        self.assertEqual(self.tables["DEMO-MR-stall-v1"]["escalated_by"], {"searcher": 1})
        self.assertEqual(self.tables["DEMO-CS-stall-v1"]["classes"]["success"], 1)

    def test_first_stops_templates_and_detection_delay(self):
        cl, ct, mr = (self.tables[s] for s in ("DEMO-CL-stall-v1", "DEMO-CT-stall-v1", "DEMO-MR-normal-v1"))
        self.assertEqual((cl["first_stop_steps"], cl["first_stop_templates"]), ([15], {"E6": 1}))
        self.assertEqual((ct["first_stop_steps"], ct["first_stop_templates"]), ([9], {"E1": 1}))
        # CL: the last pass-count/workspace change is at step 8, so the stall starts at 9 and the STOP comes 6 later.
        self.assertEqual(cl["detection_delay"]["values"], [6])
        # CT: the late approval and edits (steps 27-29) end the stall; the STOP at 9 is an early STOP (S-20).
        self.assertEqual((ct["detection_delay"]["values"], ct["detection_delay"]["early_stops"],
                          ct["detection_delay"]["median_of_non_negative"]), ([-21], 1, None))
        self.assertTrue(mr["detection_delay"]["method"].startswith("not computed"))
        self.assertEqual(mr["false_positive_runs"], {"success_with_stop": 0, "escalated_with_stop": 0})

    def test_if_stopped_savings_and_headline(self):
        self.assertEqual(self.tables["DEMO-CT-stall-v1"]["if_stopped_token_ratio_mean"], 0.7755)
        self.assertEqual(self.tables["DEMO-CL-stall-v1"]["if_stopped_token_ratio_mean"], 0.5648)
        h = self.result["headline"]
        self.assertEqual((h["normal_runs_with_stop"], h["normal_false_positive_runs"], h["stall_runs_detected"]),
                         (1, 0, 2))
        self.assertEqual(h["scope"], aggregate_demo.SCOPE)

    def test_representatives_follow_the_rule(self):
        chosen = {r["scenario_id"]: r for r in self.result["representatives"]}
        self.assertEqual(chosen["DEMO-CT-stall-v1"]["session_id"], CT_STALL)
        self.assertIn("E1", chosen["DEMO-CT-stall-v1"]["reason"])
        self.assertNotIn("DEMO-MR-normal-v1", chosen)  # no successful run
        self.assertNotIn("DEMO-LR-stall-v1", chosen)  # escalated, no STOP
        self.assertEqual(set(chosen), {"DEMO-CL-normal-v1", "DEMO-CL-stall-v1", "DEMO-CS-normal-v1",
                                       "DEMO-CT-normal-v1", "DEMO-CT-stall-v1", "DEMO-LR-normal-v1"})

    def test_markdown_carries_the_scope(self):
        text = aggregate_demo.markdown(self.result)
        self.assertIn("데모 세션 기준", text)
        self.assertIn("| DEMO-CT-stall-v1 |", text)


class Synthetic(unittest.TestCase):
    """Copies of committed sessions with edited batch values, in a temporary runs root."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def copy(self, session, name, **batch):
        target = self.root / name
        shutil.copytree(RUNS / session, target)
        conditions = json.loads((target / "conditions.json").read_text(encoding="utf-8"))
        conditions["batch"] = {**(conditions.get("batch") or {}), "plan_id": "demo-main-v1", **batch}
        (target / "conditions.json").write_text(json.dumps(conditions), encoding="utf-8")
        return target

    def test_another_freeze_or_condition_group_is_excluded(self):
        for n in range(3):
            self.copy(CT_STALL, f"DEMO-CT-stall-v1-{n}", final_freeze_sha256="f" * 64, mode="observe", repeat=n + 1)
        odd = self.copy(CT_STALL, "DEMO-CT-stall-v1-9", final_freeze_sha256="e" * 64, mode="observe", repeat=4)
        other = self.copy(CT_STALL, "DEMO-CT-stall-v1-8", final_freeze_sha256="f" * 64, mode="observe", repeat=5)
        summary = json.loads((other / "record/demo-summary.json").read_text(encoding="utf-8"))
        summary["condition_group"] = "cg-other"
        (other / "record/demo-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        result = aggregate_demo.aggregate(["demo-main-v1"], freeze="f" * 64, runs_root=self.root)
        self.assertEqual(result["sessions"], 3)
        reasons = {r["session_id"]: r["excluded_because"] for r in result["excluded"]}
        self.assertEqual(set(reasons), {odd.name, other.name})
        self.assertIn("final freeze", reasons[odd.name][0])
        self.assertIn("condition group cg-other", reasons[other.name][0])
        self.assertEqual(result["scenarios"][0]["stalled_k_of_n"], "3 / 3")

    def test_block_runs_are_compared_with_the_observe_mean(self):
        for n in range(2):
            self.copy(CT_STALL, f"DEMO-CT-stall-v1-o{n}", mode="observe", repeat=n + 1)
        block = self.copy(CT_STALL, "DEMO-CT-stall-v1-b0", mode="block", repeat=1)
        for name, update in (("summary.json", {"termination_reason": "guardrail_stop", "steps": 10}),
                             ("record/demo-summary.json", {"tokens": {"prompt": 100000, "completion": 0},
                                                           "credits_estimated": {"value": 13.0},
                                                           "condition_group": "cg-block"})):
            data = json.loads((block / name).read_text(encoding="utf-8"))
            data.update(update)
            (block / name).write_text(json.dumps(data), encoding="utf-8")
        result = aggregate_demo.aggregate(["demo-main-v1"], runs_root=self.root)
        table = result["scenarios"][0]
        self.assertEqual(table["observe_runs"], 2)
        self.assertEqual(table["block"]["runs"], 1)
        self.assertEqual(table["block"]["token_saving_vs_observe"], round(1 - 100000 / 785742, 4))
        self.assertEqual(table["block"]["credit_saving_vs_observe"], round(1 - 13.0 / 132.59626, 4))
        self.assertEqual(table["block"]["classes"], {"guardrail_stop": 1})


if __name__ == "__main__":
    unittest.main()
