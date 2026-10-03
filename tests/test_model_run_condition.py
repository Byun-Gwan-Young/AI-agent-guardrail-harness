"""C-17-7 part 1: the model is a run condition (DM-25, D-32) and the manifest names the condition group, offline.

--model is sent for the run instead of the scenario's model; without it nothing changes (the scenario-v1 requests
stay byte-identical to the C-17-4 capture, checked in tests/test_dialogue_runner.py). conditions.json records the
model sent and where it came from, and the manifest's condition group separates runs whose conditions differ.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments.run_scenario import MODEL_RULE, run_model
from scenario_schema import load_scenario
from t1_harness import DELIVERABLE, report, run_t1
from tools import analyze_session
import v1_request_capture as capture

ROOT = Path(__file__).resolve().parents[1]
GPT = "accounts/fireworks/models/gpt-oss-120b"
OTHER = "claude-sonnet-5"
FIXED = {"turn_order": "fixed"}
LOOKUP = {1: ("lookup_order", {"order_id": "A-100"})}


class RunModelTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(capture.A1V4)

    def test_default_is_the_scenario_model(self):
        name, record = run_model(self.scenario, SimpleNamespace())
        self.assertEqual(name, GPT)
        self.assertEqual(record, {"rule": MODEL_RULE, "name": GPT, "source": "scenario", "scenario_model": GPT})

    def test_run_condition_replaces_the_model_and_keeps_the_scenario_model_on_record(self):
        name, record = run_model(self.scenario, SimpleNamespace(model=OTHER))
        self.assertEqual(name, OTHER)
        self.assertEqual((record["name"], record["source"], record["scenario_model"]), (OTHER, "run_condition", GPT))
        # Naming the scenario's own model is still a stated run condition.
        self.assertEqual(run_model(self.scenario, SimpleNamespace(model=GPT))[1]["source"], "run_condition")

    def test_blank_or_padded_model_is_refused(self):
        for value in ("", "   ", " claude-sonnet-5", "claude-sonnet-5\n"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "--model"):
                run_model(self.scenario, SimpleNamespace(model=value))


class ArtifactPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_is_the_only_request_difference_and_is_recorded(self):
        default = await capture.capture()
        other = await capture.offline_run(capture.A1V4, capture.CONFIG, capture.STEPS, model=OTHER)
        self.assertEqual(len(default["requests"]), len(other["requests"]))
        self.assertEqual({d for a, b in zip(default["requests"], other["requests"])
                          for d in capture.differences(a, b)}, {".model"})
        self.assertEqual({r["model"] for r in other["requests"]}, {OTHER})
        self.assertEqual(other["conditions"]["model"],
                         {"rule": MODEL_RULE, "name": OTHER, "source": "run_condition", "scenario_model": GPT})
        self.assertEqual(other["conditions"]["scenario"]["model"], GPT)
        self.assertEqual(default["conditions"]["model"]["source"], "scenario")
        self.assertEqual(default["termination_reason"], other["termination_reason"])


class DialogueManifestTests(unittest.IsolatedAsyncioTestCase):
    async def manifest(self, run):
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            return analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])

    def reports(self):
        return [report("triage"), report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]

    async def test_dialogue_run_sends_the_run_model_and_the_manifest_groups_by_it(self):
        default = await run_t1(self.reports(), tools=LOOKUP, scenario_changes=FIXED, max_steps=2, tests=self)
        other = await run_t1(self.reports(), tools=LOOKUP, scenario_changes=FIXED, max_steps=2, tests=self,
                             model=OTHER)
        self.assertEqual({r["model"] for r in default["requests"]}, {GPT})
        self.assertEqual({r["model"] for r in other["requests"]}, {OTHER})
        self.assertEqual(other["session"]["meta"]["model"], OTHER)
        self.assertEqual((other["conditions"]["model"]["source"], other["conditions"]["model"]["scenario_model"]),
                         ("run_condition", GPT))
        first, second = await self.manifest(default), await self.manifest(other)
        self.assertEqual(second["model"]["name"], OTHER)
        self.assertEqual((second["model"]["source"], second["model"]["scenario_model"],
                          second["model"]["runner_matches_proxy"]), ("run_condition", GPT, True))
        self.assertEqual((first["model"]["source"], first["model"]["runner_matches_proxy"]), ("scenario", True))
        a, b = first["condition"]["group"], second["condition"]["group"]
        self.assertEqual((a["rule"], b["rule"]), ("condition-group-v1", "condition-group-v1"))
        self.assertNotEqual(a["id"], b["id"])
        # C-17-8 added the model's source to the group: a stated run model differs in both.
        self.assertEqual({k for k in a["fields"] if a["fields"][k] != b["fields"][k]}, {"model", "model_source"})
        self.assertEqual((a["fields"]["phase"], a["fields"]["guardrail_mode"], a["fields"]["closed_list_check"],
                          a["fields"]["runner_protocol"]),
                         ("demo", "observe", "provider_strict", "tool-capable-step-v10-final-report-allowlist"))
        self.assertTrue(a["id"].startswith("cg-") and a["id"][3:] == a["sha256"][:12])

    async def test_same_conditions_share_a_group_and_a_closed_list_change_splits_it(self):
        first = await run_t1(self.reports(), tools=LOOKUP, scenario_changes=FIXED, max_steps=2, tests=self)
        second = await run_t1(self.reports(), tools=LOOKUP, scenario_changes=FIXED, max_steps=2, tests=self)
        # The default is provider_strict since DM-55; after_receipt (DM-40) is the other group.
        strict = await run_t1(self.reports(), tools=LOOKUP, scenario_changes=FIXED, max_steps=2, tests=self,
                              closed_list_check="after_receipt")
        groups = [(await self.manifest(r))["condition"]["group"] for r in (first, second, strict)]
        self.assertEqual(groups[0]["id"], groups[1]["id"])
        self.assertNotEqual(groups[0]["id"], groups[2]["id"])
        self.assertEqual({k for k in groups[0]["fields"] if groups[0]["fields"][k] != groups[2]["fields"][k]},
                         {"closed_list_check"})


class ConditionGroupTests(unittest.TestCase):
    def base(self):
        result = {"condition": {"max_steps": 30, "max_llm_calls_per_step": 3}}
        conditions = {"phase": None, "runner_protocol": "p", "collection_policy": "c", "output_contract_version": "v2",
                      "temperature": 0.0, "context_buffer_messages": 12, "requested_seed": None,
                      "reasoning_effort": {"requested": "high", "sent_on": "all_calls", "applied": "unverified"}}
        meta = {"model": GPT, "max_tokens": 16384, "criteria_version": "deadlock-v0.2", "criteria_sha256": "abc",
                "guardrail_mode": "observe",
                "upstream": {"base_url_host": "host", "config_file": "guardrail-deadlock-v0.2-kmu.yaml"}}
        return result, conditions, meta

    def test_values_outside_the_run_conditions_do_not_change_the_group(self):
        result, conditions, meta = self.base()
        group = analyze_session.condition_group(result, conditions, meta)
        changed = copy.deepcopy(conditions)
        changed.update(scenario={"scenario_id": "X"}, run_index=4, git_commit="f" * 40, dataset_run=True,
                       session_id="X-1")
        changed["reasoning_effort"]["applied"] = "probe_indicated"
        self.assertEqual(analyze_session.condition_group(result, changed, meta), group)
        # dialogue_flow and closed_list_check are null outside dialogue tasks and are listed as missing.
        self.assertIn("closed_list_check", group["missing_fields"])
        self.assertEqual(json.loads(json.dumps(group)), group)

    def test_each_run_condition_changes_the_group(self):
        result, conditions, meta = self.base()
        group = analyze_session.condition_group(result, conditions, meta)["id"]
        for target, key, value in (("meta", "model", OTHER), ("meta", "criteria_sha256", "def"),
                                   ("meta", "max_tokens", 2400), ("meta", "guardrail_mode", "block"),
                                   ("conditions", "temperature", 0.3), ("conditions", "runner_protocol", "q"),
                                   ("conditions", "phase", "demo"), ("result", "max_steps", 18)):
            r, c, m = copy.deepcopy((result, conditions, meta))
            {"meta": m, "conditions": c, "result": r["condition"]}[target][key] = value
            with self.subTest(key=key):
                self.assertNotEqual(analyze_session.condition_group(r, c, m)["id"], group)
        r, c, m = copy.deepcopy((result, conditions, meta))
        m["upstream"]["base_url_host"] = "other-host"
        self.assertNotEqual(analyze_session.condition_group(r, c, m)["id"], group)


if __name__ == "__main__":
    unittest.main()
