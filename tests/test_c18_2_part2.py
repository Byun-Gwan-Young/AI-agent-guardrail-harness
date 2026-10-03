"""C-18-2 part 2: the batch runner (tools/run_batch.py, DM-63). Plan files, lane split with the LR lane rule (DM-52 ④),
resume without running an item twice, the stop after two runner_errors in a row, the stop on a proxy whose mode,
criteria freeze or pinned model does not match, missing keys, reruns, the progress view, the runner's account label
and batch item (manifest v0.7), the proxy's GET /conditions, and one lane run end to end through the real runner and
proxies with a fake upstream. Offline."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import criteria_freeze  # noqa: E402
from experiment_config import load_run_conditions  # noqa: E402
from experiments import run_scenario  # noqa: E402
from tools import analyze_session, run_batch  # noqa: E402
import t2_harness  # noqa: E402
import test_c18_2_part1 as ct  # noqa: E402

MAIN = ROOT / "batch_plans/demo-main-v1.yaml"
TRIAL = ROOT / "batch_plans/demo-trial-c18-2.yaml"
KEYS = {"KMU_API_KEY": "kmu-fake-value"}


def proxy_view(mode="observe", **changes):
    """What a correctly started demo proxy answers on GET /conditions."""
    conditions = load_run_conditions("demo-conditions.yaml")
    view = {"criteria_version": "deadlock-v0.3", "criteria_sha256": "x",
            "criteria_freeze_sha256": criteria_freeze.freeze("deadlock-v0.3")["sha256"], "guardrail_mode": mode,
            "pinned_model": {"name": conditions["model"], "source": "run_conditions",
                             "run_conditions": "demo-conditions.yaml", "run_conditions_sha256": conditions["sha256"]},
            "config_file": "guardrail-deadlock-v0.3-kmu.yaml", "upstream_host": "h"}
    return {**view, **changes}


def get_for(views=None):
    views = views or {}
    return lambda url: views.get(url) or proxy_view("block" if url.endswith(":8001") else "observe")


class FakeRunner:
    """Stands in for one run_scenario process: writes the session folder a real run leaves (conditions.json with the
    batch item, summary.json) and returns (exit code, session ID). endings: termination reasons in call order."""

    def __init__(self, runs_root, endings):
        self.runs_root, self.endings, self.commands = Path(runs_root), list(endings), []

    def __call__(self, command, log):
        self.commands.append(command)
        batch = json.loads(command[command.index("--batch-item") + 1])
        ending = self.endings.pop(0)
        session_id = batch["item"].split(":")[0] + "-" + uuid.uuid4().hex
        folder = self.runs_root / session_id
        folder.mkdir(parents=True)
        label = command[command.index("--account-label") + 1] if "--account-label" in command else None
        (folder / "conditions.json").write_text(json.dumps({"batch": batch, "account_label": label}), encoding="utf-8")
        if ending is not None:  # None: the process died before writing its summary
            (folder / "summary.json").write_text(json.dumps({"termination_reason": ending}), encoding="utf-8")
        log.write("session_id: " + session_id + "\n")
        return (1 if ending in (None, "runner_error") else 0), session_id


def fake_summary(folder):
    return {"session_id": Path(folder).name, "termination_reason": "x", "steps": 1, "tests_passed": None,
            "first_stop": None, "credits_measured": {"value": 1.0}, "credits_estimated": {"value": 1.0},
            "condition_group": "cg-x", "model": "glm-5.3-flash", "account_label": None,
            "key_scan": {"clean": True, "key_values_checked": ["KMU_API_KEY"]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs = self.directory / "runs" / "demo"
        self.records = self.directory / "runs" / "demo-batches"
        self.runs.mkdir(parents=True)

    def lane(self, plan, endings, lane=1, lanes=1, **options):
        runner = options.pop("runner", None) or FakeRunner(self.runs, endings)
        lines = []
        result = run_batch.run_lane(plan, lane, lanes, runner=runner, get=options.pop("get", get_for()),
                                    summarize=fake_summary, runs_root=self.runs, records_root=self.records,
                                    environ=options.pop("environ", KEYS), out=lines.append, **options)
        return result, runner, lines

    def plan(self, items, plan_id="test-plan"):
        path = self.directory / (plan_id + ".yaml")
        path.write_text(json.dumps({"plan_version": run_batch.PLAN_VERSION, "plan_id": plan_id, "items": items}),
                        encoding="utf-8")
        return run_batch.load_plan(path)


CT_ITEMS = [{"scenario": "scenarios/DEMO-CT-normal-v1.yaml", "mode": "observe", "repeats": [1, 2]},
            {"scenario": "scenarios/DEMO-CT-stall-v1.yaml", "mode": "observe", "repeats": [1]},
            {"scenario": "scenarios/DEMO-CT-stall-v1.yaml", "mode": "block", "repeats": [1]}]


class Plans(Base):
    def test_main_and_trial_plans(self):
        main, trial = run_batch.load_plan(MAIN), run_batch.load_plan(TRIAL)
        modes = lambda plan: [sum(i.mode == m for i in plan["items"]) for m in run_batch.MODES]
        self.assertEqual((len(main["items"]), modes(main)), (70, [55, 15]))
        observed = {i.scenario_id for i in main["items"] if i.mode == "observe"}
        blocked = {i.scenario_id for i in main["items"] if i.mode == "block"}
        self.assertEqual(len(observed), 11)
        self.assertEqual(blocked, {"DEMO-CL-stall-v1", "DEMO-CT-stall-v1", "DEMO-CS-stall-v1", "DEMO-MR-stall-v1",
                                   "DEMO-LR-stall-v1"})
        self.assertEqual(Counter_of(main, "observe"), {s: 5 for s in observed})
        self.assertEqual(Counter_of(main, "block"), {s: 3 for s in blocked})
        self.assertEqual({i.scenario_id for i in main["items"] if i.one_at_a_time}, {"DEMO-LR-normal-v1",
                                                                                   "DEMO-LR-stall-v1"})
        self.assertEqual([i.key for i in trial["items"]], ["DEMO-CT-normal-v1:observe:1", "DEMO-CT-stall-v1:observe:1",
                                                           "DEMO-CT-N-v1:observe:1"])

    def test_bad_plans_are_refused(self):
        good = {"scenario": "scenarios/DEMO-CT-N-v1.yaml", "mode": "observe", "repeats": [1]}
        cases = {"mode": [{**good, "mode": "warn"}], "repeat zero": [{**good, "repeats": [0]}],
                 "repeat twice": [{**good, "repeats": [1, 1]}], "item twice": [good, good],
                 "path": [{**good, "scenario": "../x.yaml"}], "outside scenarios": [{**good, "scenario": "x/a.yaml"}],
                 "extra key": [{**good, "model": "m"}], "empty": []}
        for name, items in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.plan(items, plan_id="bad")


def Counter_of(plan, mode):
    counts = {}
    for i in plan["items"]:
        if i.mode == mode:
            counts[i.scenario_id] = counts.get(i.scenario_id, 0) + 1
    return counts


class Lanes(Base):
    def test_lr_lane_holds_lr_only(self):
        main = run_batch.load_plan(MAIN)
        for lanes in (2, 4, 5):
            with self.subTest(lanes=lanes):
                split = [run_batch.lane_items(main, k, lanes) for k in range(1, lanes + 1)]
                self.assertTrue(split[-1] and all(i.one_at_a_time for i in split[-1]))
                self.assertFalse(any(i.one_at_a_time for lane in split[:-1] for i in lane))
                keys = [i.key for lane in split for i in lane]
                self.assertEqual(sorted(keys), sorted(i.key for i in main["items"]))
        self.assertEqual([len(run_batch.lane_items(main, k, 4)) for k in range(1, 5)], [19, 19, 19, 13])

    def test_one_lane_runs_everything_and_lane_numbers_are_checked(self):
        main = run_batch.load_plan(MAIN)
        self.assertEqual(run_batch.lane_items(main, 1, 1), main["items"])
        for lane, lanes in ((0, 3), (4, 3)):
            with self.assertRaises(ValueError):
                run_batch.lane_items(main, lane, lanes)

    def test_without_lr_items_every_lane_is_general(self):
        trial = run_batch.load_plan(TRIAL)
        self.assertEqual([[i.key for i in run_batch.lane_items(trial, k, 3)] for k in (1, 2, 3)],
                         [["DEMO-CT-normal-v1:observe:1"], ["DEMO-CT-stall-v1:observe:1"], ["DEMO-CT-N-v1:observe:1"]])

    def test_one_at_a_time_must_match_the_search_tool(self):
        plan = self.plan([{**CT_ITEMS[0], "one_at_a_time": True}])
        result, runner, _ = self.lane(plan, [])
        self.assertIn("one_at_a_time must be set exactly", result["stopped"])
        self.assertEqual(runner.commands, [])


class Resume(Base):
    def test_done_items_are_not_run_again(self):
        plan = self.plan(CT_ITEMS)
        first, runner, _ = self.lane(plan, ["success", "max_steps", "max_steps", "guardrail_stop"])
        self.assertIsNone(first["stopped"])
        self.assertEqual(len(runner.commands), 4)
        again, runner2, lines = self.lane(plan, [])
        self.assertEqual((again["ran"], len(again["skipped"])), ([], 4))
        self.assertEqual(runner2.commands, [])
        # Another lane count does not run them again either: done comes from the session folders.
        other, runner3, _ = self.lane(plan, [], lane=2, lanes=3)
        self.assertEqual(runner3.commands, [])

    def test_stopped_lane_resumes_where_it_stopped(self):
        plan = self.plan(CT_ITEMS)
        get = get_for({"http://127.0.0.1:8001": proxy_view("observe")})  # the block proxy is not up yet
        first, runner, _ = self.lane(plan, ["success", "success", "max_steps"], get=get)
        self.assertIn("proxy mode observe, plan item block", first["stopped"])
        self.assertEqual(len(runner.commands), 3)
        second, runner2, _ = self.lane(plan, ["guardrail_stop"])
        self.assertEqual([r["item"] for r in second["ran"]], ["DEMO-CT-stall-v1:block:1"])

    def test_failed_items_wait_for_rerun_failed(self):
        plan = self.plan(CT_ITEMS[:1])
        self.lane(plan, ["runner_error", None])  # an error, then a process that died before its summary
        status = run_batch.status(plan, 1, self.runs)["lanes"][1]
        self.assertEqual((status["failed_items"], status["interrupted_items"]),
                         (["DEMO-CT-normal-v1:observe:1"], ["DEMO-CT-normal-v1:observe:2"]))
        again, runner, _ = self.lane(plan, [])
        self.assertEqual((runner.commands, [s["state"] for s in again["skipped"]]), ([], ["failed", "interrupted"]))
        rerun, runner, _ = self.lane(plan, ["success", "success"], rerun_failed=True)
        batches = [json.loads(c[c.index("--batch-item") + 1]) for c in runner.commands]
        self.assertTrue(all(b["rerun_of"] for b in batches))
        self.assertEqual(run_batch.status(plan, 1, self.runs)["total"]["done"], 2)


class Stops(Base):
    def test_two_runner_errors_in_a_row_stop_the_lane(self):
        plan = self.plan(CT_ITEMS)
        result, runner, _ = self.lane(plan, ["runner_error", "runner_error", "success", "success"])
        self.assertIn("2 runner_error in a row", result["stopped"])
        self.assertEqual(len(runner.commands), 2)

    def test_a_success_between_errors_resets_the_count(self):
        plan = self.plan(CT_ITEMS)
        result, runner, _ = self.lane(plan, ["runner_error", "success", "runner_error", "success"])
        self.assertIsNone(result["stopped"])
        self.assertEqual(len(runner.commands), 4)

    def test_proxy_mismatches_stop_before_the_session(self):
        conditions = load_run_conditions("demo-conditions.yaml")
        wrong = {"mode": proxy_view("block"), "criteria": proxy_view(criteria_version="deadlock-v0.2"),
                 "freeze": proxy_view(criteria_freeze_sha256="0" * 64),
                 "model": proxy_view(pinned_model={"name": "qwen3.8-flash",
                                                   "run_conditions_sha256": conditions["sha256"]}),
                 "conditions file": proxy_view(pinned_model={"name": conditions["model"],
                                                             "run_conditions_sha256": "0" * 64})}
        expected = {"mode": "proxy mode block", "criteria": "proxy criteria deadlock-v0.2", "freeze": "freeze differs",
                    "model": "proxy model qwen3.8-flash", "conditions file": "changed since the proxy started"}
        plan = self.plan(CT_ITEMS[:1])
        for name, view in wrong.items():
            with self.subTest(case=name):
                result, runner, _ = self.lane(plan, [], get=get_for({"http://127.0.0.1:8000": view}))
                self.assertIn(expected[name], result["stopped"])
                self.assertEqual(runner.commands, [])

    def test_unreachable_proxy_stops(self):
        def down(url):
            raise httpx.ConnectError("refused")
        result, runner, _ = self.lane(self.plan(CT_ITEMS[:1]), [], get=down)
        self.assertIn("cannot read http://127.0.0.1:8000/conditions: ConnectError", result["stopped"])

    def test_missing_key_stops_and_names_only_the_variable(self):
        result, runner, lines = self.lane(self.plan(CT_ITEMS[:1]), [], environ={})
        self.assertEqual(result["stopped"], "not set in this window: KMU_API_KEY")
        self.assertEqual(runner.commands, [])

    def test_a_key_in_the_session_folder_stops(self):
        def leaked(folder):
            return {**fake_summary(folder), "key_scan": {"clean": False, "key_values_checked": ["KMU_API_KEY"]}}
        runner = FakeRunner(self.runs, ["success", "success"])
        result = run_batch.run_lane(self.plan(CT_ITEMS[:1]), 1, 1, runner=runner, get=get_for(), summarize=leaked,
                                    runs_root=self.runs, records_root=self.records, environ=KEYS, out=lambda s: None)
        self.assertIn("the key scan found a key", result["stopped"])
        self.assertEqual(len(runner.commands), 1)


class Commands(Base):
    def test_command_names_the_contract_proxy_and_batch_item(self):
        plan = self.plan(CT_ITEMS)
        result, runner, _ = self.lane(plan, ["success"] * 4, account_label="A")
        first = runner.commands[0]
        self.assertEqual(first[1:3], ["experiments/run_scenario.py", "scenarios/DEMO-CT-normal-v1.yaml"])
        options = dict(zip(first[3::2], first[4::2]))
        self.assertEqual((options["--output-contract"], options["--proxy-url"], options["--run-index"],
                          options["--api-key-env"], options["--account-label"], options["--phase"]),
                         ("output-contract-v3", "http://127.0.0.1:8000", "1", "KMU_API_KEY", "A", "demo"))
        block = dict(zip(runner.commands[3][3::2], runner.commands[3][4::2]))
        self.assertEqual(block["--proxy-url"], "http://127.0.0.1:8001")
        self.assertNotIn("kmu-fake-value", json.dumps(runner.commands))
        record = (self.records / "test-plan" / "lane-1-of-1.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("kmu-fake-value", record)
        events = [json.loads(l)["event"] for l in record.splitlines()]
        self.assertEqual(events, ["lane_started"] + ["session"] * 4 + ["lane_finished"])

    def test_ct_n_runs_with_contract_v2(self):
        plan = self.plan([{"scenario": "scenarios/DEMO-CT-N-v1.yaml", "mode": "observe", "repeats": [3]}])
        _, runner, _ = self.lane(plan, ["success"])
        options = dict(zip(runner.commands[0][3::2], runner.commands[0][4::2]))
        self.assertEqual((options["--output-contract"], options["--run-index"]), ("output-contract-v2", "3"))


class RunnerLabels(unittest.TestCase):
    def args(self, **values):
        return type("A", (), {"account_label": None, "batch_item": None, "run_index": 1, **values})()

    def test_labels_are_checked_and_only_for_demo_runs(self):
        batch = {k: None for k in run_scenario.BATCH_ITEM_KEYS} | {"mode": "observe", "repeat": 1}
        self.assertEqual(run_scenario.run_labels(self.args(account_label="A-1", batch_item=json.dumps(batch)), True),
                         {"account_label": "A-1", "batch": batch})
        self.assertEqual(run_scenario.run_labels(self.args(), True), {"account_label": None, "batch": None})
        self.assertIsNone(run_scenario.run_labels(self.args(), False))
        bad = [(self.args(account_label="A"), False), (self.args(account_label="a b"), True),
               (self.args(account_label="x" * 33), True), (self.args(batch_item="[1]"), True),
               (self.args(batch_item=json.dumps({**batch, "repeat": 2})), True),
               (self.args(batch_item=json.dumps({**batch, "mode": "warn"})), True),
               (self.args(batch_item=json.dumps({"plan_id": "p"})), True)]
        for args, demo in bad:
            with self.subTest(args=vars(args)), self.assertRaises(ValueError):
                run_scenario.run_labels(args, demo)


class ProxyConditions(unittest.TestCase):
    def test_get_conditions_reports_the_pin_without_calling_upstream(self):
        from proxy import create_app

        def no_upstream(request):
            raise AssertionError("GET /conditions must not call the upstream")
        for name, mode in (("guardrail-deadlock-v0.3-kmu.yaml", "observe"),
                           ("guardrail-deadlock-v0.3-kmu-block.yaml", "block")):
            with tempfile.TemporaryDirectory() as directory, self.subTest(config=name):
                app = create_app(Path(directory) / "logs" / "demo", transport=httpx.MockTransport(no_upstream),
                                 config_path=ROOT / name)
                view = TestClient(app).get("/conditions").json()
                expected = proxy_view(mode)
                self.assertEqual({k: view[k] for k in ("criteria_version", "criteria_freeze_sha256", "guardrail_mode",
                                                       "pinned_model", "config_file")},
                                 {**{k: expected[k] for k in ("criteria_version", "criteria_freeze_sha256",
                                                              "guardrail_mode", "pinned_model")}, "config_file": name})
                self.assertNotIn("kmu", json.dumps(view).lower().replace("kmu.yaml", "").replace("kmu-block", ""))


class EndToEnd(Base):
    """One lane through the real runner and the real observe and block proxies; only the upstream is fake."""

    SCRIPTS = {"DEMO-CT-normal-v1": ([ct.report(), ct.report(), ct.report(approved=True), ct.report(), ct.report(),
                                      ct.report(declared=True, issues=(), approved=True)],
                                     {2: ct.write(ct.REFERENCE), 5: ct.write(ct.REFERENCE)}),
               "DEMO-CT-stall-v1": ([ct.report(approved=False) for _ in range(30)],
                                    {s: ct.write(ct.REFERENCE) for s in range(2, 31, 3)})}
    CONFIGS = {"http://127.0.0.1:8000": ROOT / "guardrail-deadlock-v0.3-kmu.yaml",
               "http://127.0.0.1:8001": ROOT / "guardrail-deadlock-v0.3-kmu-block.yaml"}

    def in_process(self, command, log):
        """run_scenario.main() in this process for one command, through the proxy its --proxy-url names."""
        from proxy import create_app
        options = dict(zip(command[3::2], command[4::2]))
        scenario_id = Path(command[2]).stem
        reports, tools = self.SCRIPTS[scenario_id]
        upstream = t2_harness.Upstream(reports, tools)
        app = create_app(self.directory / "logs" / "demo", transport=httpx.MockTransport(upstream),
                         config_path=self.CONFIGS[options["--proxy-url"]])
        real_client = httpx.AsyncClient

        class OfflineClient(real_client):
            def __init__(self, *a, **kw):
                kw.setdefault("transport", httpx.ASGITransport(app=app))
                super().__init__(*a, **kw)
        clean = {"git_commit": "0" * 40, "git_dirty": False, "git_state_status": "measured", "git_state_reason": None}
        out = io.StringIO()
        with mock.patch.object(run_scenario, "DEMO_OUTPUT_ROOT", self.runs), \
                mock.patch.object(run_scenario, "git_state", return_value=clean), \
                mock.patch("httpx.AsyncClient", OfflineClient), mock.patch.dict("os.environ", KEYS), \
                mock.patch.object(sys, "argv", ["run_scenario.py"] + command[2:]), contextlib.redirect_stdout(out):
            code = run_scenario.main()
        log.write(out.getvalue())
        session_id = next(l.split()[1] for l in out.getvalue().splitlines() if l.startswith("session_id:"))
        return code, session_id

    def views(self, url):
        from proxy import create_app
        app = create_app(self.directory / "logs" / "demo", transport=httpx.MockTransport(lambda r: None),
                         config_path=self.CONFIGS[url])
        return TestClient(app).get("/conditions").json()

    def test_a_lane_end_to_end(self):
        plan = self.plan([CT_ITEMS[0] | {"repeats": [1]}, CT_ITEMS[2]], plan_id="e2e")
        lines = []
        with mock.patch.dict("os.environ", KEYS):
            result = run_batch.run_lane(plan, 1, 1, account_label="B", runner=self.in_process, get=self.views,
                                        runs_root=self.runs, records_root=self.records, environ=KEYS,
                                        out=lines.append)
        self.assertIsNone(result["stopped"], lines)
        self.assertEqual([(r["item"], r["termination_reason"]) for r in result["ran"]],
                         [("DEMO-CT-normal-v1:observe:1", "success"), ("DEMO-CT-stall-v1:block:1", "guardrail_stop")])
        summaries = [r["summary"] for r in result["ran"]]
        self.assertEqual([(s["steps"], s["first_stop_step"], s["account_label"], s["key_scan_clean"])
                          for s in summaries], [(6, None, "B", True), (7, 6, "B", True)])
        self.assertEqual(summaries[0]["key_values_checked"], ["KMU_API_KEY"])
        conditions = json.loads((self.runs / result["ran"][1]["session_id"] / "conditions.json").read_text("utf-8"))
        self.assertEqual((conditions["account_label"], conditions["batch"]["item"], conditions["batch"]["lane"],
                          conditions["batch"]["plan_sha256"]), ("B", "DEMO-CT-stall-v1:block:1", 1,
                                                                plan["plan_sha256"]))
        # Manifest v0.7: v0.6 plus the account label and the batch item.
        with mock.patch.object(analyze_session, "ROOT", self.directory):
            session_id = result["ran"][0]["session_id"]
            manifest = analyze_session.manifest(analyze_session.analyse(session_id), "measure", [])
        self.assertEqual(manifest["manifest_version"], "session-manifest-v0.7")
        self.assertEqual((manifest["run"]["account_label"], manifest["run"]["batch"]["item"]),
                         ("B", "DEMO-CT-normal-v1:observe:1"))
        # Status after the lane: both done; a second start runs nothing.
        status = run_batch.status(plan, 1, self.runs)
        self.assertEqual((status["total"]["done"], status["lanes"][1]["endings"]),
                         (2, {"success": 1, "guardrail_stop": 1}))
        again = run_batch.run_lane(plan, 1, 1, runner=self.in_process, get=self.views, runs_root=self.runs,
                                   records_root=self.records, environ=KEYS, out=lambda s: None)
        self.assertEqual((again["ran"], len(again["skipped"])), ([], 2))


if __name__ == "__main__":
    unittest.main()
