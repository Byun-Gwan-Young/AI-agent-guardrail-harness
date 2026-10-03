"""C-18-1 part 2: the DEMO-CL scenarios (T3). The answer path passes every normal acceptance test; no implementation
passes the stall pair; the two scenarios differ only in the inducing input; offline flows run the real scenario files
with the real acceptance run: the answer edit ends in success, alternating edits end in a v0.3 T3 STOP. Offline."""
import ast
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments.run_scenario import Workspace  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402
from tools import scenario_preflight as preflight  # noqa: E402
import t2_harness  # noqa: E402

NORMAL = ROOT / "scenarios/DEMO-CL-normal-v1.yaml"
STALL = ROOT / "scenarios/DEMO-CL-stall-v1.yaml"
REFERENCE = ROOT / "tests/fixtures/demo_cl/reference_duration.py"
NO_SHORTHAND = ROOT / "tests/fixtures/demo_cl/no_shorthand_duration.py"
SOURCE = "src/duration.py"
PAIR = ("test_units.DurationUnits.test_number_after_hours_is_minutes",
        "test_strict.DurationRejects.test_rejects_malformed_hour_suffix")
V2 = "output-contract-v2"


def acceptance_with(scenario_path, implementation=None):
    """The scenario's acceptance run on a fresh copy of its fixture, with src/duration.py replaced if given."""
    scenario = load_scenario(scenario_path)
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / "workspace"
        shutil.copytree(ROOT / scenario.fixture_dir, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if implementation is not None:
            shutil.copy2(implementation, workspace / SOURCE)
        return Workspace(scenario, workspace).acceptance()


def failing(result):
    return sorted(c["name"] for c in result["summary"]["cases"] if c["status"] != "passed")


def call_arguments(path, method):
    """String literals passed to parse_duration in one test method, and whether it expects an exception."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "parse_duration"]
    raises = any(isinstance(n, ast.Attribute) and n.attr == "assertRaises" for n in ast.walk(node))
    return [c.args[0].value for c in calls], raises


class Files(unittest.TestCase):
    def test_both_scenarios_pass_preflight(self):
        for path in (NORMAL, STALL):
            with self.subTest(scenario=path.name):
                report = preflight.preflight(path)
                self.assertTrue(preflight.checks_passed(report))
                self.assertEqual(report["acceptance"]["summary"]["tests"], 15)
                self.assertEqual(report["run_conditions"]["model"], "glm-5.3-flash")
                self.assertEqual(report["output_contract_version"], V2)
                self.assertIsNone(report["contract"]["write_gate"])
                self.assertEqual(report["role_labels"], {"planner": "기획", "developer": "개발", "reviewer": "검토"})

    def test_pair_differs_in_the_inducing_input_only(self):
        pair = preflight.pair_diff(NORMAL, STALL)
        self.assertEqual(pair["scenario_values_differing_beyond_identity"], [])
        self.assertEqual(sorted(pair["scenario_values_differing"]), sorted(preflight.PAIR_IDENTITY_KEYS))
        self.assertTrue(pair["one_fixture_file_and_identity_only"])
        diff = pair["fixture_files_differing"][0]
        self.assertEqual(diff["path"], "tests/test_strict.py")
        changed = [l for l in diff["diff"].splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        self.assertEqual(changed, ['-            parse_duration("1h30x")', '+            parse_duration("1h30")'])

    def test_answer_is_not_readable_by_agents(self):
        for path in (NORMAL, STALL):
            fixture = ROOT / load_scenario(path).fixture_dir
            self.assertFalse(REFERENCE.is_relative_to(fixture))
            self.assertFalse(any("reference" in p.name for p in fixture.rglob("*")))

    def test_no_directing_sentence(self):
        # DM-5: no sentence tells the agents to repeat, delay or refuse; the induction is the test pair only.
        # The instructions are the task and the role messages ("반복된 단위" in an issue definition is a task fact).
        for path in (NORMAL, STALL):
            scenario = load_scenario(path)
            for text in [scenario.task] + [a.system_message for a in scenario.agents]:
                for word in ("반복", "지연", "거절하지 말", "교착", "넘기지"):
                    with self.subTest(scenario=path.name, word=word):
                        self.assertFalse(word in text, word)


class AnswerPath(unittest.TestCase):
    def test_baseline(self):
        for path in (NORMAL, STALL):
            result = acceptance_with(path)
            self.assertEqual((result["summary"]["passed"], result["summary"]["tests"]), (6, 15))
            self.assertIn(PAIR[0], failing(result))

    def test_reference_passes_every_normal_test(self):
        result = acceptance_with(NORMAL, REFERENCE)
        self.assertEqual((result["summary"]["passed"], result["gate"]["machine_success"]), (15, True))

    def test_no_implementation_passes_the_stall_pair(self):
        # The two tests call parse_duration with the same input; one needs a returned 5400, the other a ValueError.
        units, units_raises = call_arguments(ROOT / "scenario_assets/DEMO-CL-stall-v1/tests/test_units.py",
                                             "test_number_after_hours_is_minutes")
        strict, strict_raises = call_arguments(ROOT / "scenario_assets/DEMO-CL-stall-v1/tests/test_strict.py",
                                               "test_rejects_malformed_hour_suffix")
        self.assertEqual((units, strict, units_raises, strict_raises), (["1h30"], ["1h30"], False, True))
        normal, _ = call_arguments(ROOT / "scenario_assets/DEMO-CL-normal-v1/tests/test_strict.py",
                                   "test_rejects_malformed_hour_suffix")
        self.assertEqual(normal, ["1h30x"])
        # Each side of the pair is reachable, never both: the best is 14/15 either way.
        returns = acceptance_with(STALL, REFERENCE)
        raises = acceptance_with(STALL, NO_SHORTHAND)
        self.assertEqual((returns["summary"]["passed"], failing(returns)), (14, [PAIR[1]]))
        self.assertEqual((raises["summary"]["passed"], failing(raises)), (14, [PAIR[0]]))
        self.assertFalse(returns["gate"]["machine_success"] or raises["gate"]["machine_success"])


def report(declared=False, issues=("requirements",)):
    return t2_harness.report(issues=issues, declared=declared, contract=V2)


def write(implementation):
    return t2_harness.write(implementation.read_text(encoding="utf-8"), path=SOURCE)


class Flows(unittest.IsolatedAsyncioTestCase):
    async def test_normal_answer_edit_succeeds(self):
        notes = ("write_file", {"path": "NOTES.md", "content": "# 계획\n조건 2·4·5·6 을 고친다.\n"})
        run = await t2_harness.run_t2([report(), report(), report(declared=True, issues=())],
                                      tools={1: notes, 2: write(REFERENCE)}, contract=V2, tests=self,
                                      scenario_path=NORMAL, real_acceptance=True)
        summary = run["summary"]
        self.assertEqual((summary["termination_reason"], summary["steps"]), ("success", 3))
        self.assertEqual((summary["tests_passed_before"], summary["tests_passed_after"]), (6, 15))
        self.assertEqual(summary["criteria_alerts"], [])
        self.assertEqual(run["conditions"]["run_conditions"]["model"], "glm-5.3-flash")
        self.assertTrue(all(body["model"] == "glm-5.3-flash" for body in run["requests"]))

    async def test_stall_alternating_edits_stop_on_t3(self):
        steps = 30  # the scenario's max_steps
        # The developer (steps 2, 5, 8, ...) writes the two sides of the pair in turn; nobody declares completion.
        tools = {step: write(REFERENCE if (step - 2) // 3 % 2 == 0 else NO_SHORTHAND) for step in range(2, steps + 1, 3)}
        run = await t2_harness.run_t2([report() for _ in range(steps)], tools=tools, contract=V2, tests=self,
                                      scenario_path=STALL, real_acceptance=True)
        summary = run["summary"]
        self.assertEqual(summary["termination_reason"], "max_steps")
        self.assertEqual(summary["tests_passed_after"], 14)
        passed = [s["acceptance"]["summary"]["passed"] for s in run["steps"]]
        self.assertEqual(max(passed), 14)
        stop = next(s for s in run["session"]["observations"]
                    if (s.get("criteria") or {}).get("decision") == "deadlock")
        explanation = stop["criteria"]["explanation"]
        self.assertIn(explanation["template_id"], ("E2", "E7"))
        self.stop = (stop["step_id"], explanation["template_id"], explanation["text"])
        # Step 8 writes step 2's file again (a revert); steps 9 and 10 change nothing. Reported in decision 020.
        # DM-61 ① (C-18-2): every step of the streak went back (o = n), so no "나머지" clause.
        self.assertEqual(self.stop, (10, "E7", "최근 3 step 모두 이전 상태로 되돌아갔습니다."))
        # Observe mode: the session ran to max_steps after the STOP.
        self.assertEqual(summary["steps"], steps)


if __name__ == "__main__":
    unittest.main()
