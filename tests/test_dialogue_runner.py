"""C-17-4 part 1: the scenario-v2 dialogue (T1) run path with the fixed turn order, offline.

Registration sent at session start, output-contract-v3 turns (closed lists checked after receipt or sent strict),
T1 observations from structured fields only, the judge, the tool seam, the demo safeguards on scenario-v2 and
manifest v0.6. The router is part 2 (tests/test_dialogue_router.py); the flows of part 3 are in
tests/test_dialogue_flows.py. Every run here uses the fixed order.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx

from experiments import dialogue_runner as dialogue, dialogue_tools
from experiments.dialogue_contract import for_dialogue_scenario
from experiments.dialogue_runner import SentContract, checked_gate, next_turn, without_enums
from proxy import create_app
from scenario_schema import load_scenario, registration_for
from t1_harness import BLOCK_CONFIG, DELIVERABLE, FIXTURE, PROTOCOL_V10, V02_CONFIG, V3, report, run_t1
from test_harness_facts import ADVICE
from tools import analyze_session

ROOT = Path(__file__).resolve().parents[1]
FIXED = {"turn_order": "fixed"}
LOOKUP = {1: ("lookup_order", {"order_id": "A-100"})}


def conversations(run):
    return [o["conversation"] for o in run["session"]["observations"]]


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(FIXTURE)
        self.contract = for_dialogue_scenario(self.scenario)

    def test_closed_lists_are_sent_only_in_provider_strict_mode(self):
        after, strict = SentContract(self.contract, "after_receipt"), SentContract(self.contract, "provider_strict")
        self.assertEqual(strict.response_format(), self.contract.response_format())
        sent = after.response_format()
        self.assertNotIn('"enum"', json.dumps(sent))
        self.assertTrue(sent["json_schema"]["strict"])
        self.assertEqual(sent["json_schema"]["schema"], without_enums(self.contract.schema()))
        self.assertEqual(sent["json_schema"]["schema"]["required"], self.contract.schema()["required"])
        # Everything else is the contract's own: the closed lists are still checked after receipt.
        self.assertEqual((after.version, after.sha256, after.instructions()),
                         (V3, self.contract.sha256, self.contract.instructions()))
        with self.assertRaises(ValueError) as caught:
            after.parse(json.dumps(report("closed")))
        self.assertEqual(caught.exception.code, "status_not_allowed")
        with self.assertRaises(ValueError):
            SentContract(self.contract, "warn")

    def test_without_enums_keeps_a_property_called_enum(self):
        schema = {"type": "object", "properties": {"enum": {"type": "string", "enum": ["a"]}},
                  "anyOf": [{"enum": [1]}, {"type": "null"}], "required": ["enum"]}
        self.assertEqual(without_enums(schema), {"type": "object", "properties": {"enum": {"type": "string"}},
                                                 "anyOf": [{}, {"type": "null"}], "required": ["enum"]})

    def test_judge_gate_shape(self):
        checked_gate({"machine_success": True, "result": "resolved", "missing": []})
        checked_gate({"machine_success": False, "result": "escalated", "missing": []})
        for bad in ({"machine_success": True, "result": "unfinished", "missing": []},
                    {"machine_success": 1, "result": "resolved", "missing": []},
                    {"machine_success": False, "result": "done", "missing": []},
                    {"machine_success": False, "result": "unfinished", "missing": "x"},
                    {"machine_success": False, "result": "unfinished"}, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                checked_gate(bad)

    def test_fixed_order_is_the_next_role_and_handoff_is_recorded_only(self):
        fixed = self.scenario.model_copy(update={"turn_order": "fixed"})
        for current, value, expected in ((0, report(handoff="shipping"), 1), (2, report(handoff="refund"), 0),
                                         (1, None, 2)):
            with self.subTest(current=current, value=value):
                index, route = next_turn(fixed, current, value)
                self.assertEqual((index, route["rule"], route["fallback_reason"]), (expected, "fixed_order", None))
                self.assertEqual(route["handoff_to"], (value or {}).get("handoff_to"))

    def test_tool_seam_hands_calls_on_and_records_them(self):
        seen = []
        dispatch = dialogue_tools.ToolDispatch({"lookup_order": lambda a, c: seen.append((a, c)) or {"ok": 1},
                                                "read_policy": lambda a, c: 1 / 0}, "inputs")
        dispatch.step_id, dispatch.agent_id = 4, "refund"
        lookup, policy = dispatch.tools(["lookup_order", "read_policy"])
        self.assertEqual((lookup.__name__, policy.__name__), ("lookup_order", "read_policy"))
        self.assertEqual(lookup("A-1"), '{"ok": 1}')
        self.assertEqual(seen, [({"order_id": "A-1"}, {"step_id": 4, "agent_id": "refund", "inputs_dir": "inputs"})])
        with self.assertRaises(ZeroDivisionError):
            policy("refund")
        self.assertEqual([(r["seq"], r["tool"], r["is_error"]) for r in dispatch.records],
                         [(1, "lookup_order", False), (2, "read_policy", True)])
        self.assertIn("ZeroDivisionError", dispatch.records[1]["error"])
        self.assertEqual(dialogue_tools.missing_implementations(self.scenario, {}), ["lookup_order", "read_policy"])
        # C-17-6: every T1 tool has its implementation.
        self.assertEqual(set(dialogue_tools.IMPLEMENTATIONS), set(dialogue_tools.TOOL_VOCABULARY))

    def test_prompt_text_states_facts_only(self):
        agent = self.scenario.agents[1]
        text = dialogue.system_message(agent, list(agent.tools), self.scenario, "SCHEMA")
        added = text[len(agent.system_message):-len("SCHEMA")]
        self.assertTrue(text.startswith(agent.system_message + "\n"))
        for fact in ("For THIS role only these tools are registered: lookup_order, read_policy.",
                     "Files this role can write: none.", "at most 3 model calls"):
            self.assertIn(fact, added)
        # The new sentences (tools, harness facts) carry no advice; the contract sentence is the artifact path's own.
        facts = dialogue_tools.tool_instructions(list(agent.tools)) + dialogue.harness_facts([], 3)
        self.assertIn(facts, added)
        words = set(facts.lower().replace(".", " ").replace(";", " ").replace(",", " ").split())
        self.assertEqual(words & ADVICE, set())
        self.assertTrue(added.endswith("Final response must be one JSON object matching this schema. Report the full "
                                       "shared state, not only this role's issues.\n"))
        self.assertIn("registered: none.", dialogue_tools.tool_instructions([]))


class FixedFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_order_run_registers_observes_judges_and_succeeds(self):
        reports = [report("triage", handoff="shipping", adopted=["ticket"]),
                   report("assigned", handoff="shipping", adopted=["ticket", "owner"]),
                   report("assigned", adopted=["ticket", "owner"]),
                   report("resolved", adopted=["ticket", "owner", "code"], deliverable=DELIVERABLE, declared=True,
                          issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes=FIXED, tests=self)
        summary, steps = run["summary"], run["steps"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["error"]), (0, "success", None))
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "shipping", "intake"])
        self.assertEqual({s["route"]["rule"] for s in steps}, {"fixed_order"})
        self.assertEqual([s["completion_gate"]["result"] for s in steps], ["unfinished"] * 3 + ["resolved"])
        self.assertEqual((summary["criteria_alerts"], summary["final_status"], summary["vocabulary_violations_total"]),
                         ([], "resolved", 0))
        # Registration: sent once, stored by the proxy unchanged, and recorded with its hash.
        conditions, meta = run["conditions"], run["session"]["meta"]
        expected = registration_for(load_scenario(run["out"] / "scenario.yaml"))
        self.assertEqual((conditions["registration"], meta["registration"]), (expected, expected))
        self.assertEqual(conditions["registration_sha256"], dialogue.canonical_sha256(expected))
        self.assertEqual((conditions["output_contract_version"], conditions["runner_protocol"],
                          conditions["closed_list_check"]["mode"], conditions["task_kind"], conditions["turn_order"]),
                         (V3, PROTOCOL_V10, "after_receipt", "dialogue", "fixed"))
        # T1 observations: the verified report's structured fields only; handoff_to recorded in the fixed order too.
        self.assertEqual([(c["status"], c.get("handoff_to"), c["adopted_items"]) for c in conversations(run)],
                         [("triage", "shipping", ["ticket"]), ("assigned", "shipping", ["ticket", "owner"]),
                          ("assigned", None, ["ticket", "owner"]), ("resolved", None, ["ticket", "owner", "code"])])
        observations = run["session"]["observations"]
        self.assertTrue(all(o["extracted_conversation"] is None and o["artifact"] is None for o in observations))
        self.assertEqual([o["issue_report"]["output_contract_version"] for o in observations], [V3] * 4)
        # The tool call was handed to the fake and recorded for the judge.
        self.assertEqual([(r["tool"], r["arguments"], r["step_id"], r["agent_id"]) for r in run["dispatch"]],
                         [("lookup_order", {"order_id": "A-100"}, 1, "intake")])
        self.assertEqual(steps[0]["tool_dispatch_seq"], [1])
        self.assertEqual(conditions["tool_implementations"]["lookup_order"], "t1_harness.fake_lookup")
        # Demo phase: every request carried it and the run folder is under runs/demo/.
        self.assertTrue(all(t["request_params"]["phase"] == "demo" for t in run["session"]["turns"]))
        self.assertEqual(run["out"].parent, run["root"] / "runs" / "demo")
        self.assertEqual(len(run["requests"]), sum(s["llm_calls"] for s in steps))

    async def test_requests_carry_the_contract_and_the_shared_state(self):
        reports = [report("triage", handoff="refund", adopted=["ticket"]),
                   report("resolved", deliverable=DELIVERABLE, issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes=FIXED, max_steps=2, tests=self)
        requests = run["requests"]
        finals = [r for r in requests if "response_format" in r]
        others = [r for r in requests if "response_format" not in r]
        self.assertEqual(len(finals), 2)
        self.assertTrue(all("tools" not in r and r["response_format"]["json_schema"]["strict"] for r in finals))
        self.assertTrue(all('"enum"' not in json.dumps(r["response_format"]) for r in finals))
        self.assertTrue(all(r["reasoning_effort"] == "high" for r in requests))
        self.assertEqual({tuple(t["function"]["name"] for t in r["tools"]) for r in others},
                         {("lookup_order", "read_policy")})
        system = requests[0]["messages"][0]["content"]
        self.assertTrue(system.startswith("당신은 접수 담당입니다."))
        self.assertIn('"enum": ["received", "triage", "assigned", "resolved", "escalated"]', system)
        self.assertIn("Report status as exactly one of", system)
        # The second role sees the first verified report's narrative and v3 state, in its final request too (v10).
        shared = {"agent": "intake", "narrative": "n", "status": "triage", "handoff_to": "refund",
                  "adopted_items": ["ticket"], "deliverable": None}
        context = json.loads(requests[3]["messages"][1]["content"])
        self.assertEqual(context["recent_messages"], [shared])
        self.assertEqual(json.loads(finals[1]["messages"][1]["content"])["observed_records"][0]["recent_messages"],
                         [shared])
        # Step 2 is refund's turn: resolved and judged complete, but only intake declares completion.
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["completion_gate"]["machine_success"]),
                         ("max_steps", True))

    async def test_provider_strict_sends_the_closed_lists(self):
        run = await run_t1([report("triage")], max_steps=1, closed_list_check="provider_strict",
                           scenario_changes=FIXED, tests=self)
        final = next(r for r in run["requests"] if "response_format" in r)
        properties = final["response_format"]["json_schema"]["schema"]["properties"]
        self.assertEqual(properties["status"]["enum"], ["received", "triage", "assigned", "resolved", "escalated"])
        self.assertEqual(properties["handoff_to"]["anyOf"][0]["enum"], ["intake", "refund", "shipping"])
        self.assertTrue(run["conditions"]["closed_list_check"]["enums_sent_to_provider"])

    async def test_resolved_without_the_declaration_or_the_judge_does_not_end(self):
        reports = [report("resolved", deliverable=DELIVERABLE, issues=()),  # nothing looked up yet
                   report("resolved", deliverable=DELIVERABLE, issues=()),  # judge passes, refund cannot declare
                   report("resolved", deliverable=DELIVERABLE, issues=(), declared=True)]  # shipping cannot either
        run = await run_t1(reports, tools={2: ("lookup_order", {"order_id": "A-100"})}, scenario_changes=FIXED,
                           max_steps=3, tests=self)
        gates = [s["completion_gate"] for s in run["steps"]]
        self.assertEqual([g["machine_success"] for g in gates], [False, True, True])
        self.assertEqual(gates[0]["missing"], ["order_id_not_looked_up"])
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")

    async def test_a_declaration_does_not_carry_over_to_another_role(self):
        # DM-45 (C-17-5, replaces the C-17-4 carry-over test): intake declares at step 1 but the judge fails on that
        # report; refund's report passes the judge at step 2 but refund is not the declarer; intake declares again at
        # step 4 and that report passes, so the run succeeds there.
        reports = [report("resolved", deliverable=DELIVERABLE, issues=(), declared=True),
                   report("resolved", deliverable=DELIVERABLE, issues=()),
                   report("resolved", deliverable=DELIVERABLE, issues=()),
                   report("resolved", deliverable=DELIVERABLE, issues=(), declared=True)]
        run = await run_t1(reports, tools={2: ("lookup_order", {"order_id": "A-100"})}, scenario_changes=FIXED,
                           max_steps=5, tests=self)
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 4))
        claims = run["summary"]["completion_claims"]
        self.assertEqual([(c["step_id"], c["agent"], c["accepted"], c["reasons"]) for c in claims],
                         [(1, "intake", False, ["judge_unfinished"]), (2, "refund", False, ["not_declarer", "not_declared"]),
                          (3, "shipping", False, ["not_declarer", "not_declared"]), (4, "intake", True, [])])
        # The first-declaration record for signals (E6) is unchanged (DM-45).
        self.assertEqual(run["session"]["observations"][1]["termination_context"]["declared_step"], 1)


class SafeguardTests(unittest.IsolatedAsyncioTestCase):
    """The demo rules on scenario-v2 dialogue runs, all refused before a run folder or a model call."""

    async def refused(self, pattern, **options):
        changes = {**FIXED, **options.pop("scenario_changes", {})}
        with self.assertRaisesRegex(ValueError, pattern):
            await run_t1([], scenario_changes=changes, tests=self, **options)

    async def test_phase_and_output_root(self):
        await self.refused("--phase demo", phase=None)
        with tempfile.TemporaryDirectory() as directory:
            await self.refused("DM-34", output_root=Path(directory))

    async def test_dataset_run(self):
        await self.refused("cannot be combined", dataset_run=True)
        await self.refused("--dataset-run is refused", dataset_run=True, phase=None)

    async def test_contract_protocol_and_tools(self):
        await self.refused("output-contract-v3", output_contract="output-contract-v2")
        await self.refused("tool-capable-step-v10", runner_protocol="tool-capable-step-v9-reasoning-all-calls")
        await self.refused("Tools without an implementation: lookup_order, read_policy", implementations={})
        await self.refused("reasoning_effort", scenario_changes={"reasoning_effort": None})

    async def test_scenario_v1_refuses_the_dialogue_options(self):
        import experiments.run_scenario as runner
        for options in ({"output_contract": V3}, {"closed_list_check": "after_receipt"}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "scenario-v2 dialogue"):
                await runner.run(SimpleNamespace(scenario=ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml",
                                                 **{"output_contract": "output-contract-v2", **options}))

    async def test_no_run_without_registration(self):
        # A non-demo (v0.2) proxy refuses the registration: the run ends before any model call.
        run = await run_t1([report()], config=V02_CONFIG, scenario_changes=FIXED, tests=self)
        self.assertEqual(run["summary"]["termination_reason"], "runner_error")
        self.assertIn("Proxy refused the session (422)", run["summary"]["error"])
        self.assertIn("registration requires deadlock-v0.3", run["summary"]["error"])
        self.assertEqual((run["requests"], run["steps"]), ([], None))

    async def test_block_proxy_refuses_a_registered_session_without_the_demo_phase(self):
        # DM-32 for a scenario-v2 session start (the runner always sends the demo phase for scenario-v2).
        registration = registration_for(load_scenario(FIXTURE))
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "logs" / "demo", config_path=BLOCK_CONFIG)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                refused = await client.post("/sessions", json={"registration": registration},
                                            headers={"X-Guardrail-Session": "plain"})
                started = await client.post("/sessions", json={"registration": registration},
                                            headers={"X-Guardrail-Session": "demo", "X-Guardrail-Phase": "demo"})
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (409, "block_mode_requires_demo_phase"))
        self.assertEqual((started.status_code, started.json()), (200, {"session_id": "demo", "registered": True}))


class ManifestTests(unittest.IsolatedAsyncioTestCase):
    async def manifest(self, run):
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            analysis = analyze_session.analyse(run["session_id"])
            return analysis, analyze_session.manifest(analysis, "measure", [])

    async def test_manifest_v06_records_registration_contract_violations_and_ending(self):
        reports = [report("triage", handoff="refund"), report("closed"),
                   report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes=FIXED, max_steps=3, tests=self)
        analysis, manifest = await self.manifest(run)
        self.assertEqual(manifest["manifest_version"], "session-manifest-v0.6")
        registration = manifest["registration"]
        self.assertEqual(registration["value"], run["conditions"]["registration"])
        self.assertEqual(registration["sha256"], registration["sha256_recomputed"])
        self.assertTrue(registration["proxy_stored_same"])
        self.assertEqual((manifest["task"]["output_contract_version"], manifest["task"]["turn_order"],
                          manifest["task"]["closed_list_check"]["mode"]), (V3, "fixed", "after_receipt"))
        self.assertEqual((manifest["vocabulary_violations"]["total"], manifest["vocabulary_violations"]["steps"]),
                         (1, [2]))
        # Shipping (step 3) is not the declarer, so the run reaches max_steps.
        self.assertEqual((manifest["run"]["termination_reason"], manifest["judgement"]["normal_session"]),
                         ("max_steps", False))
        self.assertEqual((manifest["condition"]["phase"], manifest["condition"]["guardrail_mode"]), ("demo", "observe"))
        self.assertEqual(manifest["judgement"]["after"]["gate"], run["summary"]["completion_gate"])
        self.assertEqual(analysis["judgement"]["gate_at_end"], run["summary"]["completion_gate"])
        self.assertTrue(analysis["secret_scan"]["clean"])

    async def test_success_manifest_is_a_normal_session(self):
        reports = [report("triage"), report("triage"), report("assigned"),
                   report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes=FIXED, tests=self)
        _, manifest = await self.manifest(run)
        self.assertEqual((manifest["run"]["termination_reason"], manifest["judgement"]["normal_session"]),
                         ("success", True))
        self.assertEqual((manifest["run"]["final_status"], manifest["routing"]["fallbacks"]), ("resolved", []))


if __name__ == "__main__":
    unittest.main()
