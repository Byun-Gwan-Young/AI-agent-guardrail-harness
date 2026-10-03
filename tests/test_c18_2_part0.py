"""C-18-2 part 0: the C-18-1 trial follow-up. demo-conditions.yaml with reasoning effort high and its trial evidence
(DM-60), the E7 sentence when every step went back (DM-61 ①, refrozen), the summary tool's tool names and the
condition group's empty fields split by kind, and the closed-list value an artifact run now records. Offline."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import criteria_freeze  # noqa: E402
from experiment_config import load_run_conditions  # noqa: E402
from experiments import gateway_usage, run_scenario  # noqa: E402
from explain_v1 import E7_ALL, TEMPLATES, explain  # noqa: E402
from tools import c18_2_evidence, summarize_demo_session  # noqa: E402
import t2_harness  # noqa: E402
import test_c17_6_part0 as c176  # noqa: E402
import test_c18_1_part2 as cl  # noqa: E402

EVIDENCE = "reports/c18-1/trial-summary.json"


class DemoConditionsHigh(unittest.TestCase):
    def test_high_with_the_trial_sessions_as_evidence(self):
        conditions = load_run_conditions("demo-conditions.yaml")
        self.assertEqual((conditions["model"], conditions["reasoning_effort"], conditions["reasoning_effort_evidence"]),
                         ("glm-5.3-flash", "high", EVIDENCE))
        text = (ROOT / "demo-conditions.yaml").read_text(encoding="utf-8")
        self.assertNotIn("medium 은 데모 조건에서만", text)
        for session, tokens in (("d5460d69", "9,800"), ("f08705fe", "25,527"), ("c3a4c019", "")):
            self.assertIn(session, text)
            self.assertIn(tokens, text)

    def test_the_evidence_file_holds_the_reasoning_tokens(self):
        record = json.loads((ROOT / EVIDENCE).read_text(encoding="utf-8"))["reasoning_effort_evidence"]
        by_session = {e["session_id"][:26]: (e["requested"], e["reasoning_tokens"]) for e in record["sessions"]}
        self.assertEqual(by_session, {"DEMO-CL-normal-v1-c3a4c019": ("medium", 0),
                                      "DEMO-CL-normal-v1-d5460d69": ("high", 9800),
                                      "DEMO-CL-stall-v1-f08705feb": ("high", 25527)})
        self.assertEqual([s[:26] for s in record["medium_rejected"]], ["DEMO-CL-normal-v1-c3a4c019"])
        self.assertEqual(len(record["high_sessions_with_reasoning_tokens"]), 2)

    def test_the_step_4_errors_were_planner_writes_outside_its_paths(self):
        failures = json.loads((ROOT / EVIDENCE).read_text(encoding="utf-8"))["failed_tool_results"]
        rows = [r for rows in failures.values() for r in rows]
        self.assertEqual(len(rows), 4)
        self.assertEqual({(r["step_id"], r["role"], r["path"], r["outside_writable_paths"], r["error_summary"])
                          for r in rows},
                         {(4, "planner", "src/duration.py", True, "Role is not authorized to edit this file")})


class E7AllReverted(unittest.TestCase):
    def test_every_step_went_back(self):
        result = explain(c176.signals(consecutive_states=["oscillating"] * 3, test_plateau_in_streak=False))
        self.assertEqual((result["template_id"], result["text"], result["form"]),
                         ("E7", "최근 3 step 모두 이전 상태로 되돌아갔습니다.", "full"))
        self.assertEqual(result["values"], {"n": 3, "o": 3})

    def test_some_steps_went_back(self):
        result = explain(c176.signals(consecutive_states=["oscillating", "stagnant", "oscillating"],
                                      test_plateau_in_streak=False))
        self.assertEqual(result["text"], "최근 3 step 중 2 step은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다.")

    def test_the_rebuild_from_the_record_gives_the_same_sentence(self):
        result = explain(c176.signals(consecutive_states=["oscillating"] * 3, test_plateau_in_streak=False))
        self.assertEqual(explain(result["signals"], result["role_labels"], result["status_labels"])["text"],
                         result["text"])

    def test_the_variant_is_frozen(self):
        record = criteria_freeze.explanation_record()
        self.assertEqual(record["variants"]["E7"], {"all_reverted": E7_ALL})
        self.assertEqual(TEMPLATES["E7"], "최근 {n} step 중 {o} step은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다.")
        frozen = json.loads((ROOT / criteria_freeze.EXPLANATION_RECORD).read_text(encoding="utf-8"))
        self.assertEqual(frozen["variants"]["E7"], {"all_reverted": E7_ALL})
        self.assertEqual(frozen["templates_sha256"], record["templates_sha256"])
        snapshot = json.loads((ROOT / "docs/criteria/deadlock-v0.3.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["implementation_sha256"], criteria_freeze.implementation_sha256())


class MissingFieldClasses(unittest.TestCase):
    MISSING = ["closed_list_check", "dialogue_flow", "recent_messages_rule", "requested_seed",
               "search_settings_sha256"]

    def test_an_artifact_run_before_c18_2(self):
        conditions = {"task_kind": "artifact", "requested_seed": None, "tools": {"planner": [], "developer": []}}
        self.assertEqual(summarize_demo_session.missing_field_classes(self.MISSING, conditions),
                         {"not_applicable": ["dialogue_flow", "recent_messages_rule", "search_settings_sha256"],
                          "recorded_null": ["requested_seed"], "missing": ["closed_list_check"]})

    def test_a_dialogue_run_with_search(self):
        conditions = {"task_kind": "dialogue", "tools": {"searcher": ["web_search"]}}
        self.assertEqual(summarize_demo_session.missing_field_classes(["search_settings_sha256", "dialogue_flow"],
                                                                      conditions),
                         {"not_applicable": [], "recorded_null": [],
                          "missing": ["search_settings_sha256", "dialogue_flow"]})


class ArtifactRunSummary(unittest.IsolatedAsyncioTestCase):
    async def test_closed_list_value_and_tool_names(self):
        readings = [{"read_at": "a", "http_status": 200, "used": 1.0, "field": "monthly_allocated.used"},
                    {"read_at": "b", "http_status": 200, "used": 1.5, "field": "monthly_allocated.used"}]

        async def fake(upstream, key):
            return readings.pop(0)
        # Step 1 (planner) writes the source file it may not write: a refused tool result, as in the trial step 4.
        outside = ("write_file", {"path": "src/duration.py", "content": "x\n"})
        with mock.patch.object(gateway_usage, "reading", fake):
            run = await t2_harness.run_t2([cl.report(), cl.report(), cl.report(declared=True, issues=())],
                                          tools={1: outside, 2: cl.write(cl.REFERENCE)}, contract=cl.V2, tests=self,
                                          scenario_path=cl.NORMAL, real_acceptance=True)
        self.assertEqual(run["conditions"]["closed_list_check"], run_scenario.ARTIFACT_CLOSED_LIST_CHECK)
        result = summarize_demo_session.summarize(run["out"])
        self.assertEqual(result["tool_results"]["error_results_by_tool"], {"write_file": 1})
        self.assertEqual(result["tool_results"]["error_results_by_summary"],
                         {"Role is not authorized to edit this file": 1})
        self.assertEqual(result["condition_group_missing_by_class"],
                         {"not_applicable": ["dialogue_flow", "recent_messages_rule", "search_settings_sha256"],
                          "recorded_null": ["requested_seed"], "missing": []})
        self.assertEqual(c18_2_evidence.failed_tool_results(run["out"])[0]["outside_writable_paths"], True)


if __name__ == "__main__":
    unittest.main()
