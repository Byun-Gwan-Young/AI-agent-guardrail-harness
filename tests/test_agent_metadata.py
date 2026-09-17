import json
import unittest
from pydantic import ValidationError
from progress_schema import Observation
from experiments.output_contract import output_schema, parse_output
from test_progress_signal import snapshot
import test_tool_recovery as recovery


class AgentMetadataTests(unittest.TestCase):
    def test_optional_legacy_metadata_and_empty_id_validation(self):
        value = snapshot(1)
        self.assertIsNone(value["agent_id"])
        value["agent_id"] = ""
        with self.assertRaises(ValidationError):
            Observation.model_validate(value)

    def test_model_contract_still_rejects_agent_id(self):
        schema = output_schema()
        self.assertNotIn("agent_id", schema["properties"])
        with self.assertRaises(ValueError):
            parse_output(json.dumps(dict(narrative="x", open_issue_ids=[], info_items=[],
                                         completion_declared=False, agent_id="spoof")))


class RunnerMetadataTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline

    async def test_runner_supplies_identity_even_when_output_discarded(self):
        run = await self.run_offline([recovery.unknown400(), recovery.success(), recovery.success(),
                                     recovery.success(), recovery.success()])
        for step in run["steps"]:
            self.assertEqual(step["observation"]["agent_id"], step["agent"])
        self.assertEqual(run["steps"][0]["step_status"], "failed")
        self.assertIsNone(run["steps"][0]["observation"]["artifact"])
        for request in run["upstream_requests"]:
            self.assertNotIn("agent_id", json.dumps(request["messages"]))
            self.assertNotIn("agent_id", json.dumps(request.get("response_format", {})))
