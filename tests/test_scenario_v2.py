"""C-17-3 part 1: scenario-v2, the deliverable schema subset, T1 observation fields. scenario-v1 is unchanged."""
import copy
import glob
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx
import yaml
from pydantic import ValidationError

import json_subset
from progress_schema import Metrics, Observation
from proxy import create_app
from scenario_schema import Scenario, ScenarioV2, load_scenario
from test_criteria_v03 import CONFIG as V03_CONFIG, CONTEXT, artifact_obs
from pinned_configs import demo_model

ROOT = Path(__file__).resolve().parents[1]
DEMO_MODEL = demo_model()  # C-17-8: the demo proxies forward their pinned model only (S-12)
DIALOGUE = ROOT / "tests/fixtures/scenario-v2-dialogue.yaml"
V02_CONFIG = ROOT / "guardrail-deadlock-v0.2-kmu.yaml"
TOOLS = {"read_files": ["read_file"], "write_files": ["write_file", "replace_in_file"], "run_tests": ["run_tests"]}


def dialogue_data():
    return yaml.safe_load(DIALOGUE.read_text(encoding="utf-8"))


def artifact_data():
    """A-1-v4 restated as a scenario-v2 artifact task (T2/T3 shape)."""
    data = yaml.safe_load((ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml").read_text(encoding="utf-8"))
    for key in ("scenario_revision", "group", "conversation_collection"):
        data.pop(key)
    for agent in data["agents"]:
        agent["tools"] = [t for p in agent.pop("permissions") for t in TOOLS[p]]
    return {**data, "schema_version": "scenario-v2", "scenario_id": "TEST-T3-v2", "task_kind": "artifact",
            "turn_order": "fixed", "criteria_version": "deadlock-v0.3", "output_contract": "output-contract-v2"}


def t1_observation(step, status="triage", adopted=("a",), issues=("requirements",), handoff=None):
    return {"agent_id": ["intake", "refund", "shipping"][(step - 1) % 3], "step_id": step, "llm_turns": [step],
            "progress_source": "conversation",
            "progress_metric": {"conversation": ["adopted_items", "new_issue_ids"], "artifact": []},
            "conversation": {"source_kind": "structured", "status": status, "adopted_items": list(adopted),
                             "open_issue_ids": list(issues), "handoff_to": handoff},
            "artifact": None, "termination_context": CONTEXT}


class ScenarioV2Tests(unittest.TestCase):
    def test_v1_files_load_exactly_as_before(self):
        files = sorted(glob.glob(str(ROOT / "scenarios/A-1*.yaml")))
        self.assertEqual(len(files), 4)
        for path in files:
            with self.subTest(path=Path(path).name):
                loaded = load_scenario(path)
                self.assertIs(type(loaded), Scenario)
                self.assertEqual(loaded, Scenario.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8"))))

    def test_dialogue_fixture(self):
        scenario = load_scenario(DIALOGUE)
        self.assertIs(type(scenario), ScenarioV2)
        self.assertEqual([s.id for s in scenario.status_values], ["received", "triage", "assigned", "resolved"])
        self.assertEqual([(s.id, s.label) for s in scenario.terminal_statuses], [("escalated", "에스컬레이션")])
        self.assertEqual({a.id: a.role for a in scenario.agents}, {"intake": "접수", "refund": "환불 담당",
                                                                   "shipping": "배송 담당"})
        self.assertEqual((scenario.turn_order, scenario.required_adopted_items), ("router", 3))

    def test_artifact_task_restating_a1v4(self):
        scenario = ScenarioV2.model_validate(artifact_data())
        self.assertEqual(scenario.task_kind, "artifact")
        self.assertEqual([a.tools for a in scenario.agents][1], ["read_file", "write_file", "replace_in_file", "run_tests"])

    def test_dialogue_rules(self):
        def edited(change):
            data = dialogue_data()
            change(data)
            return data
        cases = {
            "write tool": lambda d: d["agents"][0]["tools"].append("write_file"),
            "writable path": lambda d: d["agents"][0].update(writable_paths=["x.md"]),
            "judge outside scenario_judges": lambda d: d.update(judge="scenario_assets/judge.py"),
            "no judge": lambda d: d.pop("judge"),
            "inputs_dir escapes": lambda d: d.update(inputs_dir="../secret"),
            "inputs_dir exposes judges": lambda d: d.update(inputs_dir="scenario_judges"),
            "status repeated as terminal": lambda d: d["terminal_statuses"].append({"id": "triage", "label": "x"}),
            "no status list": lambda d: d.pop("status_values"),
            "unsupported schema keyword": lambda d: d["deliverable_schema"]["properties"]["order_id"].update(pattern="^A"),
            "open object": lambda d: d["deliverable_schema"].pop("additionalProperties"),
            "required mismatch": lambda d: d["deliverable_schema"].update(required=["order_id"]),
            "adopted without required count": lambda d: d.pop("required_adopted_items"),
            "both sources": lambda d: d.update(progress_source="both"),
            "expected outcome": lambda d: d.update(expected_outcome="deadlock"),
            "dataset criteria": lambda d: d.update(criteria_version="deadlock-v0.2"),
            "fixture": lambda d: d.update(fixture_dir="scenario_assets/A-1"),
            "unknown declarer": lambda d: d["termination_context_collection"].update(declarer_agent="writer"),
            "initial outside allowed": lambda d: d.update(initial_issue_ids=["market-share"]),
            "bad role id": lambda d: d["agents"][0].update(id="Intake Desk"),
        }
        for name, change in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError):
                ScenarioV2.model_validate(edited(change))

    def test_artifact_rules(self):
        def edited(change):
            data = artifact_data()
            change(data)
            return data
        cases = {
            "router": lambda d: d.update(turn_order="router"),
            "T1 metric": lambda d: d["progress_metric"]["conversation"].append("status_advance"),
            "dialogue tool": lambda d: d["agents"][0]["tools"].append("web_search"),
            "status list": lambda d: d.update(status_values=[{"id": "a", "label": "b"}]),
            "writable without write tool": lambda d: d["agents"][2].update(writable_paths=["SPEC.md"]),
            "no tests": lambda d: d.pop("success_criteria"),
            "no output contract (DM-37)": lambda d: d.pop("output_contract"),
        }
        for name, change in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError):
                ScenarioV2.model_validate(edited(change))

    def test_scenario_v1_metrics_still_reject_t1_names(self):
        with self.assertRaises(ValidationError):
            Metrics.model_validate({"conversation": ["status_advance"], "artifact": []})


class RunnerRefusalTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_artifact_task_without_its_run_options_fails_before_a_run_folder(self):
        # C-17-5 runs scenario-v2 artifact tasks (DM-39); the contract the scenario names must be stated (DM-37).
        import experiments.run_scenario as runner
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.yaml"
            path.write_text(yaml.safe_dump(artifact_data(), allow_unicode=True), encoding="utf-8")
            output = Path(directory) / "runs"
            args = SimpleNamespace(scenario=path, output_root=output)
            with self.assertRaisesRegex(ValueError, "run it with --output-contract output-contract-v2"):
                await runner.run(args)
            self.assertFalse(output.exists())

    async def test_a_dialogue_task_without_its_run_options_fails_before_a_run_folder(self):
        import experiments.run_scenario as runner
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(scenario=DIALOGUE, output_root=Path(directory))
            with self.assertRaisesRegex(ValueError, "output-contract-v3"):
                await runner.run(args)
            self.assertEqual(list(Path(directory).iterdir()), [])


class JsonSubsetTests(unittest.TestCase):
    def setUp(self):
        self.schema = dialogue_data()["deliverable_schema"]

    def test_valid_and_each_kind_of_error(self):
        good = {"order_id": "A1", "handling_code": "R2", "owner": "refund", "customer_reply": "안내드립니다"}
        self.assertEqual(json_subset.errors(good, self.schema), [])
        cases = {"missing": {k: v for k, v in good.items() if k != "owner"},
                 "extra": {**good, "note": "x"}, "type": {**good, "order_id": 7},
                 "enum": {**good, "owner": "intake"}, "length": {**good, "customer_reply": ""}}
        for name, value in cases.items():
            with self.subTest(case=name):
                self.assertTrue(json_subset.errors(value, self.schema))
        self.assertEqual(json_subset.errors([1], {"type": "array", "items": {"type": "integer"}}), [])
        self.assertTrue(json_subset.errors([True], {"type": "array", "items": {"type": "integer"}}))

    def test_schema_check_limits_keywords_and_strict_shape(self):
        json_subset.check_schema(self.schema)
        for bad in ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
                    {"type": ["string", "null"]}, {"type": "string", "minItems": 1}, {"type": "array"},
                    {"type": "string", "enum": [1]}, {"type": "string", "$ref": "#/x"}):
            with self.subTest(schema=bad), self.assertRaises(ValueError):
                json_subset.check_schema(bad)


class ObservationT1Tests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_observation_keeps_its_serialized_shape(self):
        legacy = artifact_obs(1, {"a.py": "x"})
        self.assertEqual(sorted(legacy["conversation"]), ["evidence", "extractor_version", "info_items", "open_issue_ids",
                                                          "proposal_values", "reasons", "source_kind"])
        self.assertFalse(Observation.model_validate(legacy).uses_t1())

    def test_t1_fields_and_metrics_are_accepted_and_checked(self):
        model = Observation.model_validate(t1_observation(1, handoff="refund"))
        self.assertTrue(model.uses_t1())
        self.assertEqual({k: model.model_dump()["conversation"][k] for k in ("status", "adopted_items", "handoff_to")},
                         {"status": "triage", "adopted_items": ["a"], "handoff_to": "refund"})
        for bad in ({"adopted_items": ["a", "a"]}, {"adopted_items": [""]}, {"status": ""}, {"status_values": ["a"]}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                raw = t1_observation(1)
                raw["conversation"].update(bad)
                Observation.model_validate(raw)
        repeated = t1_observation(1)
        repeated["progress_metric"]["conversation"] = ["adopted_items", "adopted_items"]
        with self.assertRaises(ValidationError):
            Observation.model_validate(repeated)

    async def post(self, config, observation):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "logs", httpx.MockTransport(
                lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})), config_path=config)
            headers = {"X-Guardrail-Session": "t1"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/v1/chat/completions", json={"messages": [], "model": DEMO_MODEL}, headers=headers)
                return await client.post("/sessions/observations", headers=headers, json=observation)

    async def test_only_a_progress_v3_session_takes_t1_input(self):
        refused = await self.post(V02_CONFIG, t1_observation(1))
        self.assertEqual(refused.status_code, 422)
        self.assertIn("deadlock-v0.3", refused.text)
        status_only = t1_observation(1)
        status_only["progress_metric"]["conversation"] = ["new_issue_ids"]
        self.assertEqual((await self.post(V02_CONFIG, status_only)).status_code, 422)
        self.assertEqual((await self.post(V02_CONFIG, artifact_obs(1, {"a.py": "x"}))).status_code, 200)
        accepted = await self.post(V03_CONFIG, t1_observation(1))
        self.assertEqual(accepted.status_code, 200)
        record = accepted.json()["observation"]
        self.assertEqual((record["conversation"]["adopted_items"], record["progress"]["version"]), (["a"], "progress-v3"))


if __name__ == "__main__":
    unittest.main()
