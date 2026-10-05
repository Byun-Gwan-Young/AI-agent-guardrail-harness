"""C-18-3 part 3: the final freeze (tools/final_freeze.py, DM-33). What the record covers, create and check on a copy of
the files in a scratch Git repository (refused over uncommitted files or an existing record; every kind of later change
named), and the batch runner: the main plan runs only while the check passes and hands the record hash to each session
(conditions.json batch, manifest run.batch); trial plans run as before. Offline (local git only)."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import criteria_freeze  # noqa: E402
from experiments import run_scenario  # noqa: E402
from tools import analyze_session, final_freeze, run_batch  # noqa: E402
import test_c18_2_part2 as batch_tests  # noqa: E402

SCENARIOS = ["DEMO-CL-normal-v1", "DEMO-CL-stall-v1", "DEMO-CS-normal-v1", "DEMO-CS-stall-v1", "DEMO-CT-N-v1",
             "DEMO-CT-normal-v1", "DEMO-CT-stall-v1", "DEMO-LR-normal-v1", "DEMO-LR-stall-v1", "DEMO-MR-normal-v1",
             "DEMO-MR-stall-v1"]
FAKE_FREEZE = "f" * 64


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout


def scratch_copy(directory):
    """The covered files (and what reading them needs) in a scratch Git repository, committed."""
    root = Path(directory)
    paths, _ = final_freeze.covered_paths(ROOT)
    for relative in paths:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, root / relative)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "copy")
    return root


class Coverage(unittest.TestCase):
    def test_the_record_covers_the_eleven_scenarios_and_what_they_read(self):
        values = final_freeze.content()
        self.assertEqual(values["scenario_ids"], SCENARIOS)
        files = set(values["files"])
        for name in (*criteria_freeze.V03_IMPLEMENTATION, *final_freeze.FROZEN_RECORDS, *final_freeze.PROXY_CONFIGS,
                     "demo-conditions.yaml", "batch_plans/demo-main-v1.yaml", "json_subset.py"):
            self.assertIn(name, files)
        for scenario in SCENARIOS:
            self.assertIn(f"scenarios/{scenario}.yaml", files)
        for name in ("scenario_judges/DEMO-CS-v1.py", "scenario_judges/DEMO-MR-v1.py",
                     "scenario_judges/DEMO-LR-normal-v1.py", "scenario_judges/DEMO-LR-stall-v1.py",
                     "scenario_assets/DEMO-CS-stall-v1/policies/refund.md", "scenario_assets/DEMO-MR-v1/README.md",
                     "scenario_assets/DEMO-CL-stall-v1/tests/test_strict.py", "scenario_assets/A-1/SPEC.md"):
            self.assertIn(name, files)
        self.assertFalse(any("__pycache__" in f or f.endswith(".pyc") for f in files))
        self.assertEqual(len(files), 62)  # 61 (C-18-3) + json_subset.py (C-18-6, DM-73 ②)
        self.assertEqual(values["criteria_freeze"], criteria_freeze.freeze("deadlock-v0.3"))
        self.assertEqual({v["guardrail_mode"] for v in values["proxy_criteria"].values()}, {None, "block"})

    def test_the_content_hash_is_stable(self):
        self.assertEqual(final_freeze.content()["sha256"], final_freeze.content()["sha256"])

    def test_this_checkout_matches_its_final_freeze_record(self):
        # Made once in C-18-6 (DM-33, DM-73 ⑤); a later change to a covered file fails here before the main run does.
        result = final_freeze.check()
        self.assertEqual((result["ok"], result["differences"]), (True, []))
        record = json.loads((ROOT / final_freeze.RECORD).read_text(encoding="utf-8"))
        self.assertEqual((len(record["files"]), len(record["scenario_ids"])), (62, 11))


class CreateAndCheck(unittest.TestCase):
    def setUp(self):
        self.root = scratch_copy(self.enterContext(tempfile.TemporaryDirectory()))

    def test_create_then_check_passes_and_a_second_create_is_refused(self):
        made = final_freeze.create(self.root)
        self.assertEqual((made["scenarios"], made["git_commit"]), (11, git(self.root, "rev-parse", "HEAD").strip()))
        record = json.loads((self.root / final_freeze.RECORD).read_text(encoding="utf-8"))
        self.assertEqual(record["sha256"], final_freeze.content(self.root)["sha256"])
        result = final_freeze.check(self.root)
        self.assertEqual((result["ok"], result["differences"], result["sha256"]), (True, [], record["sha256"]))
        self.assertEqual(result["record_file_sha256"], final_freeze.sha256_file(self.root / final_freeze.RECORD))
        with self.assertRaisesRegex(ValueError, "made once"):
            final_freeze.create(self.root)

    def test_create_is_refused_over_uncommitted_files(self):
        policy = self.root / "scenario_assets/DEMO-CS-stall-v1/policies/refund.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "- 추가 문장.\n", encoding="utf-8")
        (self.root / "scenario_assets/DEMO-MR-v1/notes.md").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "commit these files") as raised:
            final_freeze.create(self.root)
        self.assertIn("scenario_assets/DEMO-CS-stall-v1/policies/refund.md", str(raised.exception))
        self.assertIn("scenario_assets/DEMO-MR-v1/notes.md", str(raised.exception))
        self.assertFalse((self.root / final_freeze.RECORD).exists())

    def test_check_names_every_change(self):
        final_freeze.create(self.root)
        judge = self.root / "scenario_judges/DEMO-MR-v1.py"
        judge.write_text(judge.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        (self.root / "scenario_assets/DEMO-LR-v1/extra.md").write_text("x", encoding="utf-8")
        conditions = self.root / "demo-conditions.yaml"
        conditions.write_text(conditions.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        explain = self.root / "explain_v1.py"
        explain.write_text(explain.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        result = final_freeze.check(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["differences"], ["demo-conditions.yaml: changed", "explain_v1.py: changed",
                                                 "scenario_assets/DEMO-LR-v1/extra.md: not in the record",
                                                 "scenario_judges/DEMO-MR-v1.py: changed",
                                                 "criteria_freeze: changed"])

    def test_a_missing_file_is_named(self):
        final_freeze.create(self.root)
        (self.root / "scenario_assets/DEMO-CS-normal-v1/policies/shipping.md").unlink()
        result = final_freeze.check(self.root)
        self.assertEqual(result["differences"],
                         ["scenario_assets/DEMO-CS-normal-v1/policies/shipping.md: no longer read by the plan or missing"])


class BatchRunner(batch_tests.Base):
    def plan(self, items, plan_id="test-plan", requires=None):
        data = {"plan_version": run_batch.PLAN_VERSION, "plan_id": plan_id, "items": items}
        if requires is not None:
            data["requires_final_freeze"] = requires
        path = self.directory / (plan_id + ".yaml")
        path.write_text(json.dumps(data), encoding="utf-8")
        return run_batch.load_plan(path)

    def test_the_main_plan_requires_the_final_freeze_and_trial_plans_do_not(self):
        self.assertTrue(run_batch.load_plan(ROOT / "batch_plans/demo-main-v1.yaml")["requires_final_freeze"])
        self.assertFalse(run_batch.load_plan(ROOT / "batch_plans/demo-trial-c18-2.yaml")["requires_final_freeze"])
        with self.assertRaisesRegex(ValueError, "requires_final_freeze"):
            self.plan(batch_tests.CT_ITEMS, requires="yes")

    def test_without_a_passing_check_no_session_starts(self):
        plan = self.plan(batch_tests.CT_ITEMS, requires=True)
        failing = lambda: {"ok": False, "record_file_sha256": None, "differences": ["no final freeze record (x)"]}
        result, runner, _ = self.lane(plan, [], freeze_check=failing)
        self.assertEqual(runner.commands, [])
        self.assertEqual(result["stopped"], "final freeze check failed: no final freeze record (x)")

    def test_a_change_during_the_lane_stops_before_the_next_session(self):
        plan = self.plan(batch_tests.CT_ITEMS, requires=True)
        answers = [{"ok": True, "record_file_sha256": FAKE_FREEZE, "differences": []}] * 3 + \
                  [{"ok": False, "record_file_sha256": FAKE_FREEZE, "differences": ["demo-conditions.yaml: changed"]}]
        result, runner, _ = self.lane(plan, ["success", "success"], freeze_check=lambda: answers.pop(0))
        self.assertEqual(len(runner.commands), 2)
        self.assertTrue(result["stopped"].endswith("final freeze check failed: demo-conditions.yaml: changed"))
        batch = json.loads(runner.commands[0][runner.commands[0].index("--batch-item") + 1])
        self.assertEqual(batch["final_freeze_sha256"], FAKE_FREEZE)
        lines = [json.loads(l) for l in (self.records / "test-plan" / "lane-1-of-1.jsonl").read_text().splitlines()]
        self.assertEqual([l.get("final_freeze_sha256") for l in lines if l["event"] in ("lane_started", "session")],
                         [FAKE_FREEZE] * 3)

    def test_a_trial_plan_never_calls_the_check(self):
        plan = self.plan(batch_tests.CT_ITEMS[:1])

        def never():
            raise AssertionError("trial plans run as before")
        result, runner, _ = self.lane(plan, ["success", "success"], freeze_check=never)
        self.assertIsNone(result["stopped"])
        batch = json.loads(runner.commands[0][runner.commands[0].index("--batch-item") + 1])
        self.assertNotIn("final_freeze_sha256", batch)
        self.assertEqual(set(batch), set(run_scenario.BATCH_ITEM_KEYS))


class RunnerBatchItem(unittest.TestCase):
    def args(self, batch):
        return type("A", (), {"account_label": None, "batch_item": json.dumps(batch), "run_index": 1})()

    def test_the_freeze_hash_is_optional_and_checked(self):
        batch = {k: None for k in run_scenario.BATCH_ITEM_KEYS} | {"mode": "observe", "repeat": 1}
        self.assertEqual(run_scenario.run_labels(self.args(batch), True)["batch"], batch)
        with_freeze = {**batch, "final_freeze_sha256": FAKE_FREEZE}
        self.assertEqual(run_scenario.run_labels(self.args(with_freeze), True)["batch"], with_freeze)
        for bad in ({**batch, "final_freeze_sha256": "abc"}, {**batch, "final_freeze_sha256": None},
                    {**batch, "other": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                run_scenario.run_labels(self.args(bad), True)


class EndToEnd(batch_tests.EndToEnd):
    """The real runner and proxies: the record hash reaches conditions.json and the manifest (run.batch)."""

    def test_a_lane_end_to_end(self):
        path = self.directory / "main-like.yaml"
        path.write_text(json.dumps({"plan_version": run_batch.PLAN_VERSION, "plan_id": "main-like",
                                    "requires_final_freeze": True, "items": [batch_tests.CT_ITEMS[2]]}),
                        encoding="utf-8")
        plan = run_batch.load_plan(path)
        passing = lambda: {"ok": True, "record_file_sha256": FAKE_FREEZE, "differences": []}
        with mock.patch.dict("os.environ", batch_tests.KEYS):
            result = run_batch.run_lane(plan, 1, 1, runner=self.in_process, get=self.views, runs_root=self.runs,
                                        records_root=self.records, environ=batch_tests.KEYS, out=lambda s: None,
                                        freeze_check=passing)
        self.assertIsNone(result["stopped"])
        [ran] = result["ran"]
        self.assertEqual(ran["termination_reason"], "guardrail_stop")
        conditions = json.loads((self.runs / ran["session_id"] / "conditions.json").read_text("utf-8"))
        self.assertEqual(conditions["batch"]["final_freeze_sha256"], FAKE_FREEZE)
        with mock.patch.object(analyze_session, "ROOT", self.directory):
            manifest = analyze_session.manifest(analyze_session.analyse(ran["session_id"]), "measure", [])
        self.assertEqual(manifest["run"]["batch"]["final_freeze_sha256"], FAKE_FREEZE)


if __name__ == "__main__":
    unittest.main()
