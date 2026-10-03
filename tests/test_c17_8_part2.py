"""C-17-8 part 2: the demo model replaced in one place (DM-57) and the closed lists sent in the strict schema by default
(DM-55). demo-conditions.yaml sets the demo model and reasoning effort; demo scenarios name it with run_conditions and
the demo proxies are pinned to its model. The C-17 fixtures keep their own model (C-17-4 baseline, DM-37 copy)."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pydantic import ValidationError
import yaml

from experiment_config import RUN_CONDITIONS_VERSION, load_config, load_run_conditions, pinned_model
from experiments import dialogue_runner
from scenario_schema import ScenarioV2, load_scenario, resolve_run_conditions
from t1_harness import DELIVERABLE, FIXTURE, report, run_t1
import t2_harness
from tools import analyze_session
import v1_request_capture as capture

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo-conditions.yaml"
V03_CONFIGS = ("guardrail-deadlock-v0.3-kmu.yaml", "guardrail-deadlock-v0.3-kmu-block.yaml")
# DM-60 (C-18-2): reasoning effort high, backed by the C-18-1 trial sessions' reasoning tokens.
EVIDENCE = "reports/c18-1/trial-summary.json"
# A demo scenario: no model or reasoning effort of its own (DM-57).
RUN_CONDITIONS = {"model": None, "reasoning_effort": None, "reasoning_effort_evidence": None,
                  "run_conditions": "demo-conditions.yaml"}
FIXED = {"turn_order": "fixed"}
LOOKUP = {1: ("lookup_order", {"order_id": "A-100"})}


class DemoConditionsFileTests(unittest.TestCase):
    def test_the_one_place(self):
        conditions = load_run_conditions("demo-conditions.yaml")
        self.assertEqual((conditions["conditions_version"], conditions["model"], conditions["reasoning_effort"],
                          conditions["reasoning_effort_evidence"]),
                         (RUN_CONDITIONS_VERSION, "glm-5.3-flash", "high", EVIDENCE))
        self.assertEqual(len(conditions["sha256"]), 64)

    def test_both_demo_proxies_take_their_pin_from_it(self):
        conditions = load_run_conditions("demo-conditions.yaml")
        for name in V03_CONFIGS:
            with self.subTest(config=name):
                self.assertEqual(pinned_model(load_config(ROOT / name)),
                                 {"name": conditions["model"], "source": "run_conditions",
                                  "run_conditions": "demo-conditions.yaml", "run_conditions_sha256": conditions["sha256"]})

    def test_no_model_id_in_code(self):
        # The demo model appears in the run-conditions file only (and in records); no module or config names it.
        paths = (list(ROOT.glob("*.py")) + list((ROOT / "experiments").glob("*.py")) + list(ROOT.glob("guardrail*.yaml")))
        for path in paths:
            with self.subTest(path=path.name):
                self.assertNotIn("glm-5.3-flash", path.read_text(encoding="utf-8"))

    def test_the_file_is_checked(self):
        data = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
        bad = {"missing": {k: v for k, v in data.items() if k != "reasoning_effort"},
               "extra": {**data, "temperature": 0.0}, "version": {**data, "conditions_version": "x"},
               "effort": {**data, "reasoning_effort": "max"}, "model": {**data, "model": " glm"},
               "evidence": {**data, "reasoning_effort_evidence": 3}}
        with tempfile.TemporaryDirectory() as directory:
            for name, value in bad.items():
                (Path(directory) / "c.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")
                with self.subTest(case=name), self.assertRaises(ValueError):
                    load_run_conditions("c.yaml", Path(directory))
        for path in ("/abs.yaml", "../x.yaml", "a\\b.yaml"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                load_run_conditions(path)
        with self.assertRaisesRegex(ValueError, "not both"):
            pinned_model({"pinned_model": "m", "run_conditions": "demo-conditions.yaml"})


class ScenarioRunConditionsTests(unittest.TestCase):
    def data(self, **changes):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        return data

    def test_model_or_run_conditions(self):
        scenario = ScenarioV2.model_validate(self.data(**RUN_CONDITIONS))
        self.assertEqual((scenario.model, scenario.reasoning_effort, scenario.run_conditions),
                         (None, None, "demo-conditions.yaml"))
        cases = {"both": self.data(run_conditions="demo-conditions.yaml"),
                 "neither": self.data(model=None),
                 "effort with run_conditions": self.data(**{**RUN_CONDITIONS, "reasoning_effort": "high"}),
                 "path outside": self.data(**{**RUN_CONDITIONS, "run_conditions": "../demo-conditions.yaml"})}
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError):
                ScenarioV2.model_validate(data)

    def test_resolution_fills_the_file_values_and_leaves_other_scenarios_alone(self):
        scenario = ScenarioV2.model_validate(self.data(**RUN_CONDITIONS))
        resolved, record = resolve_run_conditions(scenario, ROOT)
        self.assertEqual((resolved.model, resolved.reasoning_effort, resolved.reasoning_effort_evidence),
                         ("glm-5.3-flash", "high", EVIDENCE))
        self.assertEqual(record, load_run_conditions("demo-conditions.yaml"))
        for path in (FIXTURE, capture.A1V4, capture.A1V4_V2):
            original = load_scenario(path)
            self.assertEqual(resolve_run_conditions(original, ROOT), (original, None))


class DemoRunTests(unittest.IsolatedAsyncioTestCase):
    """A demo scenario through the real demo proxy configuration (no test copy): one model, one reasoning effort."""

    async def test_dialogue_run_sends_the_demo_model_and_effort_with_the_enums(self):
        reports = [report("triage"), report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes={**FIXED, **RUN_CONDITIONS}, max_steps=2,
                           tests=self)
        requests = run["requests"]
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")
        self.assertEqual({(r["model"], r["reasoning_effort"]) for r in requests}, {("glm-5.3-flash", "high")})
        finals = [r for r in requests if "response_format" in r]
        self.assertTrue(finals and all('"enum"' in json.dumps(r["response_format"]) for r in finals))
        conditions = run["conditions"]
        self.assertEqual(conditions["run_conditions"], load_run_conditions("demo-conditions.yaml"))
        self.assertEqual((conditions["model"]["source"], conditions["model"]["name"],
                          conditions["model"]["scenario_model"]), ("scenario", "glm-5.3-flash", "glm-5.3-flash"))
        self.assertEqual(conditions["reasoning_effort"]["requested"], "high")
        self.assertEqual((conditions["reasoning_effort"]["applied"], conditions["reasoning_effort"]["evidence"]),
                         ("probe_indicated", EVIDENCE))
        self.assertEqual(conditions["proxy_pinned_model"]["source"], "run_conditions")
        self.assertEqual((conditions["closed_list_check"]["mode"], conditions["closed_list_check"]["basis"]),
                         ("provider_strict", dialogue_runner.CLOSED_LIST_DEFAULT_BASIS))
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            manifest = analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])
        fields = manifest["condition"]["group"]["fields"]
        self.assertEqual((fields["model"], fields["reasoning_effort"]["requested"], fields["closed_list_check"]),
                         ("glm-5.3-flash", "high", "provider_strict"))

    async def test_artifact_run_takes_the_same_conditions(self):
        run = await t2_harness.run_t2([t2_harness.report(contract=t2_harness.V2)], contract=t2_harness.V2, max_steps=1,
                                      scenario_changes=RUN_CONDITIONS, tests=self)
        self.assertEqual({(r["model"], r["reasoning_effort"]) for r in run["requests"]},
                         {("glm-5.3-flash", "high")})
        self.assertEqual(run["conditions"]["run_conditions"]["model"], "glm-5.3-flash")

    async def test_another_run_model_is_refused_by_the_demo_proxy_before_any_call(self):
        # The harness would re-pin a test copy to a stated run model; here the real demo configuration is used.
        with mock.patch("pinned_configs.for_model", lambda config, model: config):
            run = await run_t1([report("triage")], scenario_changes={**FIXED, **RUN_CONDITIONS}, max_steps=1,
                               tests=self, model="qwen3.8-flash")
        self.assertEqual((run["summary"]["termination_reason"], run["requests"]), ("runner_error", []))
        self.assertIn("pinned to glm-5.3-flash", run["summary"]["error"])


class ProbeDryRunTests(unittest.TestCase):
    """C-18 probes of a demo scenario use the demo model and effort, as its runs do (tools/probe_gateway.py)."""

    def test_a_dry_run_of_a_demo_scenario(self):
        from tools import probe_gateway
        with tempfile.TemporaryDirectory() as directory:
            data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
            for key, value in RUN_CONDITIONS.items():
                data.pop(key, None) if value is None else data.__setitem__(key, value)
            path = Path(directory) / "scenario.yaml"
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
                folder, result = probe_gateway.probe(path, ROOT / V03_CONFIGS[0],
                                                     [probe_gateway.V3_STRICT_NO_ENUMS], Path(directory) / "out",
                                                     "developer", None)
            body = json.loads((folder / (probe_gateway.V3_STRICT_NO_ENUMS + ".request.json")).read_text(encoding="utf-8"))
        self.assertEqual((result["model"], body["model"], body["reasoning_effort"], result["dry_run"]),
                         ("glm-5.3-flash", "glm-5.3-flash", "high", True))


class ProbeEvidenceTests(unittest.TestCase):
    """DM-57 values read again from the committed probe files (tools/c17_8_evidence.py)."""

    def test_the_probes_say_what_dm57_says(self):
        from tools import c17_8_evidence
        evidence = c17_8_evidence.model_evidence()
        self.assertTrue(evidence["checks"]["all_same_as_dm57"])
        self.assertEqual(evidence["checks"]["tool_calls_per_response"]["probe"],
                         {"glm-5.3-flash": 3, "qwen3.8-flash": 4, "gpt-5.4-nano": 3})
        self.assertEqual(evidence["checks"]["second_strict_request_cached_tokens"]["probe"]["glm-5.3-flash"], 1088)


if __name__ == "__main__":
    unittest.main()
