"""C-18-1 part 1: scenario_preflight for deadlock-v0.3 and scenario-v2. scenario-v1 / v0.2 records stay byte-equal to
the saved ones; a v2 record pins the criteria with the demo proxy configuration, checks the run-conditions file, the
contract / write_gate combination and (dialogue) the tools; --pair lists a normal/stall pair's differences. Offline."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import scenario_preflight as preflight  # noqa: E402

ARTIFACT = ROOT / "tests/fixtures/scenario-v2-artifact.yaml"
DIALOGUE = ROOT / "tests/fixtures/scenario-v2-dialogue.yaml"
DEMO = {"model": None, "reasoning_effort": None, "reasoning_effort_evidence": None,
        "run_conditions": "demo-conditions.yaml"}
# The saved records whose scenario files have not changed since (scenario_sha256 equal to the file now).
SAVED_V1 = {"scenarios/A-1-v2-ambiguous-task-query.yaml": "reports/p0-4/A-1-v2-preflight.json",
            "scenarios/A-1-v3-ambiguous-task-query.yaml": "reports/a-1-v3/preflight-kmu.json",
            "scenarios/A-1-v4-ambiguous-task-query.yaml": "reports/a-1-v4/preflight.json"}


def scenario_copy(directory, source=ARTIFACT, name="s.yaml", **changes):
    """A changed copy inside the repository tree (the record names paths relative to it)."""
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = Path(directory) / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def demo_copy(directory, name="s.yaml", **changes):
    data = {**DEMO, **changes}
    return scenario_copy(directory, name=name, **{k: v for k, v in data.items() if v is not None},
                         **{k: None for k, v in data.items() if v is None})


class ScenarioV1Unchanged(unittest.TestCase):
    def test_records_equal_the_saved_ones(self):
        for scenario, saved in SAVED_V1.items():
            with self.subTest(scenario=scenario):
                self.assertEqual(preflight.preflight(ROOT / scenario),
                                 json.loads((ROOT / saved).read_text(encoding="utf-8")))

    def test_v1_command_output_and_code_unchanged(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(out), \
                mock.patch.object(sys, "argv", ["preflight", str(ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml"),
                                                "--output", str(Path(directory) / "r.json")]):
            code = preflight.main()
        shown = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(list(shown)[-1], "acceptance")
        self.assertNotIn("cases", shown["acceptance"])
        self.assertNotIn("criteria", shown)


class ScenarioV2Artifact(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(dir=ROOT / "tests")
        self.addCleanup(shutil.rmtree, self.directory)

    def test_demo_record(self):
        report = preflight.preflight(demo_copy(self.directory))
        criteria, conditions = report["criteria"], report["run_conditions"]
        self.assertEqual((report["criteria_version"], report["progress_version"]), ("deadlock-v0.3", "progress-v3"))
        self.assertEqual((criteria["parameters"]["plateau_steps"], criteria["parameters"]["handoff_record_threshold"]),
                         (6, 4))
        self.assertTrue(criteria["frozen_criteria_sha256_matches"] and criteria["frozen_implementation_matches"]
                        and criteria["frozen_templates_match"])
        self.assertTrue(conditions["points_to_demo_conditions"] and conditions["proxy_pins_the_same_model"])
        self.assertEqual(report["contract"]["combination"], "v2 without write_gate (CL, CT-N)")
        self.assertEqual(report["role_labels"], {"planner": "기획", "developer": "개발", "reviewer": "리뷰"})
        self.assertTrue(report["fixture_suite_id_matches"] and report["fixture_unchanged"])
        self.assertEqual(report["acceptance"]["summary"]["tests"], 16)
        self.assertTrue(preflight.checks_passed(report))

    def test_failed_checks(self):
        own_model = preflight.preflight(ARTIFACT)
        self.assertFalse(own_model["run_conditions"]["points_to_demo_conditions"])
        self.assertFalse(preflight.checks_passed(own_model))
        v3_alone = preflight.preflight(demo_copy(self.directory, output_contract="output-contract-v3"))
        self.assertEqual((v3_alone["contract"]["combination"], v3_alone["contract"]["combination_ok"]),
                         ("v3 without write_gate", False))
        gate = {"role": "developer", "requires": "spec_approved", "set_by": "reviewer", "spec_path": "SPEC.md"}
        ct = preflight.preflight(demo_copy(self.directory, output_contract="output-contract-v3", write_gate=gate))
        self.assertEqual((ct["contract"]["combination"], ct["contract"]["write_gate"]), ("v3 with write_gate (CT)", gate))
        self.assertTrue(preflight.checks_passed(ct))

    def test_frozen_record_is_compared(self):
        changed = yaml.safe_load((ROOT / preflight.DEMO_CONFIG).read_text(encoding="utf-8"))
        changed["criteria_parameters"]["plateau_steps"] = 9
        config = Path(self.directory) / "c.yaml"
        config.write_text(yaml.safe_dump(changed, allow_unicode=True), encoding="utf-8")
        report = preflight.preflight(demo_copy(self.directory), config)
        self.assertFalse(report["criteria"]["frozen_criteria_sha256_matches"])
        self.assertFalse(preflight.checks_passed(report))
        with self.assertRaisesRegex(ValueError, "runs deadlock-v0.2"):
            preflight.preflight(demo_copy(self.directory), ROOT / "guardrail-deadlock-v0.2.yaml")

    def test_pair_lists_every_difference(self):
        a = demo_copy(self.directory, "a.yaml")
        b = demo_copy(self.directory, "b.yaml", scenario_id="TEST-T2-other")
        same_fixture = preflight.pair_diff(a, b)
        self.assertEqual(same_fixture["scenario_values_differing"], {"scenario_id": ["TEST-T2-v2", "TEST-T2-other"]})
        self.assertEqual((same_fixture["fixture_files_differing"], same_fixture["one_fixture_file_and_identity_only"]),
                         ([], False))
        c = demo_copy(self.directory, "c.yaml", title="다른 제목")
        self.assertEqual(preflight.pair_diff(a, c)["scenario_values_differing_beyond_identity"], ["title"])
        # Two fixture folders that differ in one file: listed with its unified diff.
        fixtures = Path(self.directory) / "fx"
        for name in ("one", "two"):
            shutil.copytree(ROOT / "scenario_assets/A-1", fixtures / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        spec = fixtures / "two" / "SPEC.md"
        spec.write_text(spec.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
        relative = lambda name: (fixtures / name).relative_to(ROOT).as_posix()
        one = demo_copy(self.directory, "one.yaml", fixture_dir=relative("one"))
        two = demo_copy(self.directory, "two.yaml", fixture_dir=relative("two"))
        pair = preflight.pair_diff(one, two)
        self.assertEqual([(f["path"], f["status"]) for f in pair["fixture_files_differing"]], [("SPEC.md", "different")])
        self.assertIn("+x", pair["fixture_files_differing"][0]["diff"])
        self.assertTrue(pair["one_fixture_file_and_identity_only"])


class ScenarioV2Dialogue(unittest.TestCase):
    def test_dialogue_record_without_environment(self):
        directory = tempfile.mkdtemp(dir=ROOT / "tests")
        self.addCleanup(shutil.rmtree, directory)
        path = scenario_copy(directory, DIALOGUE, **DEMO)
        with mock.patch.dict("os.environ", {}, clear=True):
            report = preflight.preflight(path)
        dialogue = report["dialogue"]
        self.assertEqual(report["contract"]["output_contract"], "output-contract-v3")
        self.assertEqual(dialogue["tools_used"], ["lookup_order", "read_policy"])
        self.assertEqual(dialogue["tools_without_implementation"], [])
        self.assertNotIn("acceptance", report)
        # The fixture's inputs and judge live under tests/fixtures, not the repository root: reported, not hidden.
        self.assertFalse(dialogue["inputs_dir_exists"] or dialogue["judge_exists"])
        self.assertFalse(preflight.checks_passed(report))
        self.assertNotIn("present", json.dumps(dialogue))


if __name__ == "__main__":
    unittest.main()
