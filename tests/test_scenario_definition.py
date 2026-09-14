import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from artifact_hook import capture_artifact
from progress_signal import calculate_progress
from scenario_checks import check_acceptance
from scenario_schema import Scenario, load_scenario, token_estimate
from suite_identity import compute_test_suite_id


ROOT = Path(__file__).resolve().parent
if ROOT.name == "tests":
    ROOT = ROOT.parent
SCENARIO_PATH = ROOT / "scenarios" / "A-1-ambiguous-task-query.yaml"


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO_PATH)
        self.fixture = ROOT / self.scenario.fixture_dir
        self.suite = self.scenario.success_criteria.test_suite

    def identity(self, workspace):
        return compute_test_suite_id(workspace, self.suite.test_roots, self.suite.contract_files, self.suite.command)

    def run_acceptance(self, workspace, report):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(workspace / "acceptance_runner.py"), "--report-dir", str(report)],
                                capture_output=True, text=True, env=env, timeout=30)
        return result.returncode, json.loads((report / "summary.json").read_text(encoding="utf-8"))

    def test_a1_schema_has_both_sources_unknown_outcome_and_no_claimed_seed(self):
        self.assertEqual(self.scenario.progress_source, "both")
        self.assertEqual(self.scenario.expected_outcome, "unknown")
        self.assertIsNone(self.scenario.seed)
        self.assertEqual(self.identity(self.fixture), self.suite.test_suite_id)

    def test_rejects_unsupported_seed_claim_or_missing_acceptance_suite(self):
        data = self.scenario.model_dump()
        data["seed"] = 42
        with self.assertRaises(ValidationError):
            Scenario.model_validate(data)
        data = self.scenario.model_dump()
        data["success_criteria"]["test_suite"] = None
        with self.assertRaises(ValidationError):
            Scenario.model_validate(data)

    def test_starter_really_has_partial_test_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            code, summary = self.run_acceptance(self.fixture, Path(temp))
            self.assertEqual(code, 1)
            self.assertGreater(summary["passed"], 0)
            self.assertGreater(summary["failed"], 0)
            self.assertEqual(summary["errors"], 0)
            self.assertEqual(summary["tests"], self.suite.expected_test_count)
            self.assertFalse(check_acceptance(self.scenario, self.fixture, summary)["machine_success"])

    def test_source_changes_preserve_suite_but_test_edit_breaks_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "candidate"
            shutil.copytree(self.fixture, workspace, ignore=shutil.ignore_patterns("__pycache__"))
            before_id = self.identity(workspace)
            module = workspace / "src" / "task_query.py"
            module.write_text(module.read_text(encoding="utf-8") + "\n# implementation edit\n", encoding="utf-8")
            self.assertEqual(self.identity(workspace), before_id)
            _, summary = self.run_acceptance(workspace, workspace / "check-results")
            a = capture_artifact(workspace, ["src/task_query.py"], junit_path="check-results/junit.xml",
                                 test_suite_id=before_id)
            test = workspace / "tests" / "test_task_query.py"
            test.write_text(test.read_text(encoding="utf-8") + "\n# test edit\n", encoding="utf-8")
            after_id = self.identity(workspace)
            self.assertNotEqual(after_id, before_id)
            _, after_summary = self.run_acceptance(workspace, workspace / "check-results-after")
            self.assertEqual(summary["passed"], after_summary["passed"])
            b = capture_artifact(workspace, ["src/task_query.py"], junit_path="check-results-after/junit.xml",
                                 test_suite_id=after_id)
            old = {"step_id": 1, "progress_source": "artifact",
                   "progress_metric": {"artifact": ["test_pass_count"]}, "artifact": a}
            current = {**old, "step_id": 2, "artifact": b}
            result = calculate_progress([old], current)
            self.assertEqual(result["state"], "unmeasured")
            self.assertEqual(check_acceptance(self.scenario, workspace, summary)["reason"], "test_suite_changed")

    def test_adding_test_file_changes_suite_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "candidate"
            shutil.copytree(self.fixture, workspace, ignore=shutil.ignore_patterns("__pycache__"))
            (workspace / "tests" / "extra.txt").write_text("new test data", encoding="utf-8")
            self.assertNotEqual(self.identity(workspace), self.suite.test_suite_id)

    def test_token_estimate_is_explicit_assumption_not_a_total_hard_cap(self):
        estimate = token_estimate(self.scenario)
        self.assertTrue(estimate["assumed"])
        self.assertIsNone(estimate["total_token_hard_cap"])
        self.assertEqual(estimate["completion_caps_at_expected_calls"][0],
                         self.scenario.max_tokens * self.scenario.token_estimate.expected_llm_calls_min)
