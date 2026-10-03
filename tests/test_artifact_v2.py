"""C-17-5 part 1: scenario-v2 artifact tasks (CT, CL, CT-N) run on the unchanged artifact path of the runner.

The contract is the scenario's choice (DM-37), the session is registered (role names and selected metrics only), the
demo safeguards apply as for dialogue tasks, and the DM-37 equivalence: A-1-v4 restated as a scenario-v2 artifact task
sends the same upstream requests as the scenario-v1 run (tests/fixtures/c17-4-v1-requests.json).
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import httpx
import yaml

from experiments.dialogue_contract import for_artifact_scenario
from proxy import create_app
from scenario_schema import ScenarioV2, load_scenario, registration_for
from t2_harness import BLOCK_CONFIG, FIXTURE, SOURCE, V2, V3, report, run_t2, source, write
from tools import analyze_session
import v1_request_capture

ROOT = Path(__file__).resolve().parents[1]
V02_CONFIG = ROOT / "guardrail-deadlock-v0.2-kmu.yaml"
TOOLS = {"read_files": ["read_file"], "write_files": ["write_file", "replace_in_file"], "run_tests": ["run_tests"]}


def restated_a1v4():
    """scenarios/A-1-v4 in the scenario-v2 artifact form, as the fixture should hold it."""
    data = yaml.safe_load((ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml").read_text(encoding="utf-8"))
    for key in ("scenario_revision", "group", "conversation_collection"):
        data.pop(key)
    for agent in data["agents"]:
        agent["tools"] = [t for p in agent.pop("permissions") for t in TOOLS[p]]
    return {**data, "schema_version": "scenario-v2", "task_kind": "artifact", "turn_order": "fixed",
            "criteria_version": "deadlock-v0.3", "output_contract": V2}


class FixtureTests(unittest.TestCase):
    def test_fixture_is_a1v4_restated_with_only_the_id_changed(self):
        fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        expected = restated_a1v4()
        self.assertEqual((fixture.pop("scenario_id"), expected.pop("scenario_id")), ("TEST-T2-v2", "A-1-v4"))
        self.assertEqual(fixture, expected)


class EquivalenceTests(unittest.IsolatedAsyncioTestCase):
    """DM-37: a v2 artifact task without T1 fields makes the same requests as the same v1 scenario (ID aside)."""

    async def test_requests_are_byte_identical_to_the_scenario_v1_run(self):
        expected = json.loads((ROOT / "tests/fixtures/c17-4-v1-requests.json").read_text(encoding="utf-8"))
        v1 = await v1_request_capture.capture()
        v2 = await v1_request_capture.capture_v2()
        record = v1_request_capture.record(v2)
        self.assertEqual((v2["exit_code"], v2["termination_reason"], len(v2["requests"])), (0, "max_steps", 12))
        self.assertEqual(record["request_body_sha256"], expected["request_body_sha256"])
        self.assertEqual(record["first_request_messages_sha256"], expected["first_request_messages_sha256"])
        # The differing fields, reported: none. The scenario ID reaches only headers and the run folder name.
        self.assertEqual([v1_request_capture.differences(a, b) for a, b in zip(v1["requests"], v2["requests"])],
                         [[]] * 12)


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_contract_run_registers_observes_and_records(self):
        run = await run_t2([report(contract=V2)] * 3, contract=V2, max_steps=3, tests=self)
        summary, conditions = run["summary"], run["conditions"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["error"]), (0, "max_steps", None))
        registration = registration_for(load_scenario(FIXTURE))
        self.assertEqual(conditions["registration"], registration)
        self.assertEqual(run["session"]["meta"]["registration"], registration)
        # Role display names and the selected metrics; no dialogue-only values.
        self.assertEqual((registration["role_labels"], registration["status_values"], registration["terminal_statuses"],
                          registration["required_adopted_items"]),
                         ({"planner": "기획", "developer": "개발", "reviewer": "리뷰"}, [], [], None))
        self.assertEqual(registration["progress_metric"], {"conversation": ["open_issues_count"],
                                                           "artifact": ["test_pass_count", "files_changed"]})
        self.assertEqual((conditions["task_kind"], conditions["turn_order"], conditions["output_contract_version"],
                          conditions["phase"], conditions["runner_protocol"]),
                         ("artifact", "fixed", V2, "demo", "tool-capable-step-v10-final-report-allowlist"))
        self.assertIsNone(conditions["contract_sha256"])
        self.assertEqual((summary["task_kind"], summary["output_contract_version"], summary["registration_sha256"]),
                         ("artifact", V2, conditions["registration_sha256"]))
        observations = run["session"]["observations"]
        self.assertEqual([o["criteria"]["criteria_version"] for o in observations], ["deadlock-v0.3"] * 3)
        self.assertEqual(observations[0]["issue_report"]["output_contract_version"], V2)
        # Tools by name keep the order of the permission path (registered-tools.json as for A-1-v4).
        tools = json.loads((run["out"] / "registered-tools.json").read_text(encoding="utf-8"))
        self.assertEqual(tools, {"planner": ["read_file", "write_file", "replace_in_file"],
                                 "developer": ["read_file", "write_file", "replace_in_file", "run_tests"],
                                 "reviewer": ["read_file", "run_tests"]})

    async def test_v3_contract_adds_spec_approved_only(self):
        run = await run_t2([report(approved=None), report(approved=None)], max_steps=2, tests=self)
        finals = [r for r in run["requests"] if "response_format" in r]
        schema = finals[0]["response_format"]["json_schema"]
        self.assertEqual((schema["name"], schema["strict"]), ("state_report_v3_artifact", True))
        self.assertEqual(schema["schema"]["required"], ["narrative", "open_issue_ids", "info_items",
                                                        "completion_declared", "unlisted_issues", "spec_approved"])
        self.assertEqual(schema["schema"]["properties"]["spec_approved"], {"anyOf": [{"type": "boolean"}, {"type": "null"}]})
        system = run["requests"][0]["messages"][0]["content"]
        self.assertIn("spec_approved is null unless the scenario has an approval rule.", system)
        self.assertNotIn("status", schema["schema"]["properties"])
        observations = run["session"]["observations"]
        self.assertEqual(observations[0]["issue_report"]["output_contract_version"], V3)
        contract = for_artifact_scenario(load_scenario(run["out"] / "scenario.yaml"))
        self.assertEqual((run["conditions"]["contract_sha256"], contract.approval), (contract.contract_sha256, None))
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")

    async def test_a_v3_report_without_spec_approved_is_a_shape_error(self):
        run = await run_t2([report(contract=V2), report(contract=V2)], max_steps=2, tests=self)
        self.assertEqual([s["strict_failure"] for s in run["steps"]], ["strict_schema_mismatch"] * 2)
        self.assertEqual(run["summary"]["termination_reason"], "strict_output_failures")

    async def test_file_tools_act_on_the_workspace_and_observations_see_it(self):
        run = await run_t2([report(contract=V2)] * 2, contract=V2, max_steps=2,
                           tools={2: write(source(9))}, tests=self)
        workspace = run["out"] / "workspace" / SOURCE
        self.assertEqual(workspace.read_text(encoding="utf-8"), source(9))
        self.assertEqual([o["artifact"]["test_pass_count"] for o in run["session"]["observations"]], [7, 9])
        self.assertTrue(run["summary"]["fixture_unchanged"])

    async def test_manifest_v06_for_an_artifact_task(self):
        run = await run_t2([report(contract=V2)] * 2, contract=V2, max_steps=2, tests=self)
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            analysis = analyze_session.analyse(run["session_id"])
            manifest = analyze_session.manifest(analysis, "measure", [])
        # C-18-2: the runner records the account label and batch item (None here), so the manifest is v0.7 (v0.6 + run.account_label, run.batch).
        self.assertEqual(manifest["manifest_version"], "session-manifest-v0.7")
        self.assertEqual((manifest["task"]["task_kind"], manifest["task"]["output_contract_version"],
                          manifest["task"]["turn_order"]), ("artifact", V2, "fixed"))
        self.assertTrue(manifest["registration"]["proxy_stored_same"])
        self.assertEqual(manifest["registration"]["sha256"], manifest["registration"]["sha256_recomputed"])
        self.assertEqual(manifest["vocabulary_violations"]["total"], 0)
        # An artifact task keeps the acceptance-test judgement (S-1) of v0.3; no dialogue routing.
        self.assertEqual(manifest["judgement"]["before"], {"tests_passed": 7})
        self.assertEqual(manifest["judgement"]["normal_session"], False)
        self.assertNotIn("routing", manifest)
        self.assertEqual((manifest["condition"]["phase"], manifest["condition"]["guardrail_mode"]), ("demo", "observe"))
        self.assertTrue(analysis["secret_scan"]["clean"])


class SafeguardTests(unittest.IsolatedAsyncioTestCase):
    """The demo rules of dialogue tasks, now on artifact tasks, all refused before a run folder or a model call."""

    async def refused(self, pattern, **options):
        with self.assertRaisesRegex(ValueError, pattern):
            await run_t2([], tests=self, **options)

    async def test_phase_dataset_run_and_output_root(self):
        await self.refused(r"--phase demo \(DM-2, DM-37\)", phase=None)
        await self.refused("cannot be combined", dataset_run=True)
        await self.refused("--dataset-run is refused", dataset_run=True, phase=None)
        with tempfile.TemporaryDirectory() as directory:
            await self.refused("DM-34", output_root=Path(directory))

    async def test_contract_protocol_and_closed_list_check(self):
        await self.refused("run it with --output-contract output-contract-v3", output_contract=V2)
        await self.refused("run it with --output-contract output-contract-v2", contract=V2, output_contract=V3)
        await self.refused("tool-capable-step-v10", runner_protocol="tool-capable-step-v9-reasoning-all-calls")
        await self.refused("--closed-list-check is for scenario-v2 dialogue", closed_list_check="after_receipt")

    async def test_no_run_without_registration(self):
        run = await run_t2([report()], config=V02_CONFIG, tests=self)
        self.assertEqual(run["summary"]["termination_reason"], "runner_error")
        self.assertIn("registration requires deadlock-v0.3", run["summary"]["error"])
        self.assertEqual((run["requests"], run["steps"]), ([], None))

    async def test_block_proxy(self):
        # DM-32: a block proxy refuses a registration without the demo phase; the runner always sends it.
        registration = registration_for(load_scenario(FIXTURE))
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "logs" / "demo", config_path=BLOCK_CONFIG)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                refused = await client.post("/sessions", json={"registration": registration},
                                            headers={"X-Guardrail-Session": "plain"})
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (409, "block_mode_requires_demo_phase"))
        run = await run_t2([report()], config=BLOCK_CONFIG, max_steps=1, tests=self)
        self.assertEqual((run["summary"]["termination_reason"], run["session"]["meta"]["guardrail_mode"]),
                         ("max_steps", "block"))

    def test_schema_rules_for_the_contract_choice(self):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(ScenarioV2.model_validate({**data, "output_contract": V3}).output_contract, V3)
        with self.assertRaisesRegex(ValueError, "DM-37"):
            ScenarioV2.model_validate({k: v for k, v in data.items() if k != "output_contract"})
        dialogue = yaml.safe_load((ROOT / "tests/fixtures/scenario-v2-dialogue.yaml").read_text(encoding="utf-8"))
        self.assertIsNone(ScenarioV2.model_validate(dialogue).output_contract)
        ScenarioV2.model_validate({**dialogue, "output_contract": V3})
        with self.assertRaisesRegex(ValueError, "dialogue task reports output-contract-v3"):
            ScenarioV2.model_validate({**dialogue, "output_contract": V2})


if __name__ == "__main__":
    unittest.main()
