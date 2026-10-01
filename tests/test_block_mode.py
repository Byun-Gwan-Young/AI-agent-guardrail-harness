"""Demo block mode (C-17-2 part 1, DM-7, DM-23; C-17-3 DM-32, DM-34). Offline only: fake upstream, in-memory proxy."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
import deadlock_policy_v03
from experiment_config import load_config
from experiments.step_execution import PROTOCOL_V10, guardrail_stop, perform_step
from experiments import run_scenario
from experiments.run_scenario import enforce_demo_separation, enforce_observe_proxy, output_root_for
from proxy import create_app
from test_criteria_v03 import CONFIG as OBSERVE_CONFIG, artifact_obs
import test_harness_facts as facts
import test_tool_recovery as recovery
from tools import analyze_session

ROOT = Path(__file__).resolve().parents[1]
BLOCK_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu-block.yaml"
A1V4 = ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml"
DEMO = {"X-Guardrail-Phase": "demo"}


def ok(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                     "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})


class ProxyBlockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.upstream = []

    def app(self, config):
        def upstream(request):
            self.upstream.append(json.loads(request.content))
            return ok(request)
        return create_app(Path(self.directory) / "logs", httpx.MockTransport(upstream), config_path=config)

    async def stop_session(self, config, headers, steps=6):
        """Six unchanged artifact steps reach the v0.3 STOP at step 6 (N = 3 after three role baselines)."""
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app(config)), base_url="http://test")
        self.addAsyncCleanup(client.aclose)
        for step in range(1, steps + 1):
            await client.post("/v1/chat/completions", json={"messages": []}, headers=headers)
            response = await client.post("/sessions/observations", headers=headers,
                                         json=artifact_obs(step, {"code.py": "same"}))
        return client, response.json()["observation"]

    async def test_request_after_stop_is_refused_with_403_and_never_forwarded(self):
        headers = {"X-Guardrail-Session": "blocked", **DEMO}
        client, stop = await self.stop_session(BLOCK_CONFIG, headers)
        self.assertEqual(stop["criteria"]["decision"], "deadlock")
        response = await client.post("/v1/chat/completions", json={"messages": [{"content": "next"}]}, headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual((response.headers["x-should-retry"], response.headers["X-Guardrail-Turn"]), ("false", "7"))
        error = response.json()["error"]
        self.assertEqual({k: error[k] for k in ("type", "code", "stop_step", "decision", "criteria_version",
                                                "template_id", "session_id")},
                         {"type": "guardrail_stop", "code": "guardrail_stop", "stop_step": 6, "decision": "deadlock",
                          "criteria_version": "deadlock-v0.3", "template_id": "E1", "session_id": "blocked"})
        # DM-9: the body carries the STOP record's own sentence.
        self.assertEqual(error["message"], stop["criteria"]["explanation"]["text"])
        self.assertEqual(error["criteria_sha256"], stop["criteria"]["criteria_sha256"])
        self.assertEqual(len(self.upstream), 6)
        again = await client.post("/v1/chat/completions", json={"messages": []}, headers=headers)
        self.assertEqual((again.status_code, len(self.upstream)), (403, 6))
        log = (await client.get("/log", headers=headers)).json()
        refused = log["turns"][6:]
        self.assertEqual([(t["turn"], t["forwarded"], t["blocked"], t["status_code"], t["tokens"], t["upstream_ms"])
                          for t in refused], [(7, False, True, 403, 0, 0.0), (8, False, True, 403, 0, 0.0)])
        self.assertIsNone(refused[0]["upstream_request_body"])
        self.assertNotIn("blocked", log["turns"][5])
        block = log["meta"]["guardrail_block"]
        self.assertEqual({k: block[k] for k in ("stop_step", "decision", "blocked_at_step", "first_blocked_turn",
                                                "refused_requests")},
                         {"stop_step": 6, "decision": "deadlock", "blocked_at_step": 7, "first_blocked_turn": 7,
                          "refused_requests": 2})
        self.assertEqual(block["explanation"], stop["criteria"]["explanation"])
        self.assertEqual((log["meta"]["guardrail_mode"], log["meta"]["phase"]), ("block", "demo"))
        # judgement_ns is still recorded in block mode (S-5).
        self.assertTrue(all(isinstance(o["judgement_ns"], int) for o in log["observations"]))
        stored = json.loads((Path(self.directory) / "logs" / "blocked.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["meta"]["guardrail_block"]["refused_requests"], 2)

    async def test_without_demo_phase_a_block_proxy_refuses_with_409(self):
        # DM-32: no silent observe run on the block proxy; nothing is forwarded and no session file is made.
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app(BLOCK_CONFIG)), base_url="http://test")
        self.addAsyncCleanup(client.aclose)
        for phase in (None, "measure"):
            with self.subTest(phase=phase):
                headers = {"X-Guardrail-Session": f"plain-{phase}", **({"X-Guardrail-Phase": phase} if phase else {})}
                for path, body in (("/sessions", None), ("/v1/chat/completions", {"messages": []})):
                    response = await client.post(path, json=body, headers=headers)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.headers["x-should-retry"], "false")
                    error = response.json()["error"]
                    self.assertEqual((error["code"], error["phase"]), ("block_mode_requires_demo_phase", phase))
                    self.assertIn("demo phase 전용", error["message"])
                self.assertEqual((await client.get("/log", headers=headers)).status_code, 404)
        self.assertEqual(self.upstream, [])
        self.assertFalse((Path(self.directory) / "logs").exists() and any((Path(self.directory) / "logs").iterdir()))

    async def test_a_demo_session_on_the_block_proxy_refuses_a_later_request_without_the_phase(self):
        headers = {"X-Guardrail-Session": "mixed", **DEMO}
        client, _ = await self.stop_session(BLOCK_CONFIG, headers, steps=2)
        response = await client.post("/v1/chat/completions", json={"messages": []},
                                     headers={"X-Guardrail-Session": "mixed"})
        self.assertEqual((response.status_code, len(self.upstream)), (409, 2))
        self.assertEqual(len((await client.get("/log", headers=headers)).json()["turns"]), 2)
        started = await client.post("/sessions", headers={"X-Guardrail-Session": "fresh", **DEMO})
        self.assertEqual(started.status_code, 200)

    async def test_observe_proxy_never_refuses_even_for_the_demo_phase(self):
        headers = {"X-Guardrail-Session": "observe", **DEMO}
        client, stop = await self.stop_session(OBSERVE_CONFIG, headers)
        self.assertEqual(stop["criteria"]["decision"], "deadlock")
        response = await client.post("/v1/chat/completions", json={"messages": []}, headers=headers)
        self.assertEqual((response.status_code, len(self.upstream)), (200, 7))
        self.assertEqual((await client.get("/log", headers=headers)).json()["meta"]["guardrail_mode"], "observe")

    async def test_failed_explanation_still_refuses_without_inventing_a_sentence(self):
        headers = {"X-Guardrail-Session": "unexplained", **DEMO}
        with mock.patch.object(deadlock_policy_v03, "explain", side_effect=RuntimeError("boom")):
            client, stop = await self.stop_session(BLOCK_CONFIG, headers)
        self.assertEqual(stop["criteria"]["explanation"]["status"], "failed")
        error = (await client.post("/v1/chat/completions", json={"messages": []}, headers=headers)).json()["error"]
        self.assertEqual((error["message"], error["template_id"], error["stop_step"]), ("guardrail_stop", None, 6))

    async def test_invalid_phase_header_is_rejected(self):
        app = self.app(BLOCK_CONFIG)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/chat/completions", json={"messages": []},
                                         headers={"X-Guardrail-Session": "bad", "X-Guardrail-Phase": "Demo Run"})
        self.assertEqual((response.status_code, self.upstream), (400, []))


class BlockConfigTests(unittest.TestCase):
    def test_block_config_differs_from_the_observe_config_only_in_mode(self):
        block, observe = load_config(BLOCK_CONFIG), load_config(OBSERVE_CONFIG)
        self.assertEqual(block.pop("guardrail_mode"), "block")
        self.assertNotIn("guardrail_mode", observe)
        self.assertEqual(block, observe)

    def test_block_needs_v03_and_mode_values_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            v02 = Path(directory) / "v02-block.yaml"
            v02.write_text("criteria_version: deadlock-v0.2\nguardrail_mode: block\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires criteria_version deadlock-v0.3"):
                create_app(Path(directory) / "logs", config_path=v02)
            other = Path(directory) / "warn.yaml"
            other.write_text("guardrail_mode: warn\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(other)
            observe = Path(directory) / "observe.yaml"
            observe.write_text("criteria_version: deadlock-v0.2\nguardrail_mode: observe\n", encoding="utf-8")
            create_app(Path(directory) / "logs", config_path=observe)

    def test_existing_configs_stay_observe(self):
        for name in ("guardrail.yaml", "guardrail-deadlock-v0.2.yaml", "guardrail-deadlock-v0.2-kmu.yaml",
                     "guardrail-deadlock-v0.3-kmu.yaml"):
            with self.subTest(config=name):
                self.assertNotIn("guardrail_mode", load_config(ROOT / name))


class RunnerSafeguardTests(unittest.TestCase):
    def test_dataset_run_never_carries_the_demo_phase(self):
        enforce_demo_separation(False, "demo")
        enforce_demo_separation(True, None)
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            enforce_demo_separation(True, "demo")
        with self.assertRaises(ValueError):
            enforce_demo_separation(False, "measure")

    def test_dataset_run_is_refused_by_a_block_proxy(self):
        enforce_observe_proxy(True, "observe")
        enforce_observe_proxy(True, None)
        enforce_observe_proxy(False, "block")
        with self.assertRaisesRegex(ValueError, "block-mode proxy"):
            enforce_observe_proxy(True, "block")

    def test_only_the_guardrail_403_is_a_stop(self):
        body = {"message": "문장", "code": "guardrail_stop", "stop_step": 6, "decision": "deadlock",
                "criteria_version": "deadlock-v0.3"}
        for shape in (body, {"error": body}):
            with self.subTest(shape=shape):
                stop = guardrail_stop(SimpleNamespace(status_code=403, body=shape))
                self.assertEqual((stop["message"], stop["stop_step"], stop["decision"]), ("문장", 6, "deadlock"))
        for other in (SimpleNamespace(status_code=403, body={"error": {"code": "forbidden"}}),
                      SimpleNamespace(status_code=400, body={"error": body}), SimpleNamespace(status_code=403, body=None),
                      RuntimeError("no status")):
            with self.subTest(other=other):
                self.assertIsNone(guardrail_stop(other))


class StepBlockTests(unittest.IsolatedAsyncioTestCase):
    """perform_step with the proxy's refusal on the first call: no retry, no recovery, not an abort."""
    asyncSetUp = recovery.RecoveryTests.asyncSetUp
    asyncTearDown = recovery.RecoveryTests.asyncTearDown
    step = recovery.RecoveryTests.step

    async def test_refusal_ends_the_step_as_blocked(self):
        self.responses = [httpx.Response(403, json={"error": {"type": "guardrail_stop", "code": "guardrail_stop",
                                                              "message": "문장", "stop_step": 6, "decision": "deadlock"}},
                                         headers={"x-should-retry": "false"})]
        result = await self.step()
        self.assertEqual(result["blocked"]["stop_step"], 6)
        self.assertEqual((result["failed"], result["abort"], result["error"], result["failure_reasons"]),
                         (True, False, None, ["guardrail_stop"]))
        self.assertEqual((self.budget.used, len(self.requests), self.budget.turns), (1, 1, [1]))

    async def test_other_403_still_aborts_as_before(self):
        self.responses = [httpx.Response(403, json={"error": {"code": "forbidden", "message": "no"}})]
        result = await self.step()
        self.assertIsNone(result["blocked"])
        self.assertTrue(result["abort"])


class BlockRunTests(unittest.IsolatedAsyncioTestCase):
    """The real runner against an in-memory block proxy and a fake upstream (DM-7: demo only)."""

    async def run_offline(self, *, phase="demo", dataset_run=False, config=BLOCK_CONFIG, max_steps=8):
        import experiments.run_scenario as runner
        from artifact_hook import capture_artifact
        from scenario_schema import load_scenario
        scenario = load_scenario(A1V4).model_copy(deep=True)
        scenario.termination.max_steps = max_steps
        scenario.model = "fake-model"
        scenario.criteria_version = "deadlock-v0.3"
        responses = [r for _ in range(max_steps) for r in (recovery.success(), facts.final())]
        upstream_requests = []

        def upstream_handler(request):
            upstream_requests.append(json.loads(request.content))
            return responses.pop(0)
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        app = create_app(root / "logs", transport=httpx.MockTransport(upstream_handler), config_path=config)
        real_client = httpx.AsyncClient

        class OfflineClient(real_client):
            def __init__(self, *a, **kw):
                kw.setdefault("transport", httpx.ASGITransport(app=app))
                super().__init__(*a, **kw)

        def acceptance(work):
            # Unchanged files and 7/16 tests every step: a T2 stall that v0.3 stops at step 6.
            artifact = capture_artifact(work.root, scenario.monitored_paths,
                                        test_suite_id=scenario.success_criteria.test_suite.test_suite_id)
            artifact.update(test_pass_count=7, test_total_count=16)
            return {"summary": {"passed": 7, "tests": 16}, "gate": {"machine_success": False},
                    "artifact": artifact, "error": None}
        # DM-34: the demo root is runs/demo/ of this temporary tree.
        demo_root = root / "runs" / "demo"
        output_root = demo_root if phase == "demo" else root / "runs"
        args = SimpleNamespace(scenario=A1V4, run_index=1, temperature=0.0, output_root=output_root,
                               no_context_buffer=False, context_buffer_messages=12, seed_probe=None,
                               proxy_url="http://mock", collection_policy=facts.INDEPENDENT,
                               output_contract=facts.V2, runner_protocol=PROTOCOL_V10, api_key_env="KMU_API_KEY",
                               phase=phase, dataset_run=dataset_run)
        clean = {"git_commit": "0" * 40, "git_dirty": False, "git_state_status": "measured", "git_state_reason": None}
        with mock.patch.object(runner, "load_scenario", return_value=scenario), \
                mock.patch.object(runner, "DEMO_OUTPUT_ROOT", demo_root), \
                mock.patch.object(runner.Workspace, "acceptance", acceptance), \
                mock.patch.object(runner, "git_state", return_value=clean), \
                mock.patch("httpx.AsyncClient", OfflineClient), mock.patch.dict("os.environ", {"KMU_API_KEY": "fake"}), \
                contextlib.redirect_stdout(io.StringIO()):
            code = await runner.run(args)
        out = next(p for p in output_root.iterdir() if p.name != "demo")
        read = lambda name: json.loads((out / name).read_text(encoding="utf-8")) if (out / name).exists() else None
        return {"code": code, "root": root, "session_id": out.name, "steps": read("steps.json"),
                "summary": read("summary.json"), "session": read("session.json"), "conditions": read("conditions.json"),
                "upstream_requests": upstream_requests}

    async def test_demo_session_ends_with_guardrail_stop_after_the_refused_request(self):
        run = await self.run_offline()
        summary, steps, session = run["summary"], run["steps"], run["session"]
        self.assertEqual((run["code"], summary["termination_reason"], summary["error"]), (0, "guardrail_stop", None))
        self.assertEqual((summary["guardrail_stop"]["stop_step"], summary["guardrail_stop"]["blocked_step"]), (6, 7))
        self.assertEqual(summary["guardrail_stop"]["message"],
                         session["observations"][5]["criteria"]["explanation"]["text"])
        self.assertEqual([s["step_status"] for s in steps], ["completed"] * 6 + ["blocked"])
        blocked = steps[-1]
        self.assertEqual((blocked["llm_calls"], blocked["llm_turns"], blocked["acceptance"]), (1, [13], None))
        self.assertNotIn("observation", blocked)
        self.assertEqual(len(session["observations"]), 6)
        self.assertEqual((len(run["upstream_requests"]), len(session["turns"])), (12, 13))
        self.assertEqual(session["meta"]["termination_reason"], "guardrail_stop")
        self.assertEqual(session["meta"]["guardrail_block"]["refused_requests"], 1)
        # Every turn has usage (the refused one is 0), so the session total is measured.
        self.assertEqual(summary["total_tokens"], sum(t["tokens"] for t in session["turns"]))
        self.assertEqual((run["conditions"]["phase"], run["conditions"]["guardrail_mode"]), ("demo", "block"))
        self.assertTrue(all(t["request_params"]["phase"] == "demo" for t in session["turns"]))

    async def test_manifest_v05_records_the_block_and_leaves_savings_to_observe_sessions(self):
        run = await self.run_offline()
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            analysis = analyze_session.analyse(run["session_id"])
            manifest = analyze_session.manifest(analysis, "measure", [])
        self.assertEqual(manifest["manifest_version"], "session-manifest-v0.5")
        self.assertEqual(manifest["run"]["termination_reason"], "guardrail_stop")
        self.assertEqual((manifest["condition"]["phase"], manifest["condition"]["guardrail_mode"]), ("demo", "block"))
        block = manifest["guardrail"]["block"]
        self.assertEqual({k: block[k] for k in ("stop_step", "blocked_at_step", "first_blocked_turn", "refused_requests",
                                                "refused_turns", "forwarded_turns", "same_text_as_first_stop_record")},
                         {"stop_step": 6, "blocked_at_step": 7, "first_blocked_turn": 13, "refused_requests": 1,
                          "refused_turns": [13], "forwarded_turns": 12, "same_text_as_first_stop_record": True})
        self.assertEqual(block["tokens_used"]["total"], manifest["tokens"]["total"])
        self.assertEqual(manifest["guardrail"]["first_stop_step"], 6)
        savings = manifest["guardrail"]["savings_vs_observe"]
        self.assertEqual((savings["status"], savings["value"], savings["observe_session_ids"]), ("unmeasured", None, None))
        self.assertEqual(savings["blocked_session_total_tokens"], manifest["tokens"]["total"])

    async def test_without_demo_phase_the_block_proxy_refuses_the_session(self):
        # DM-32: the run fails at session start, before any model call, with the proxy's reason.
        run = await self.run_offline(phase=None)
        self.assertEqual(run["summary"]["termination_reason"], "runner_error")
        self.assertIn("Proxy refused the session (409)", run["summary"]["error"])
        self.assertIn("block_mode_requires_demo_phase", run["summary"]["error"])
        self.assertEqual((run["upstream_requests"], run["steps"], run["session"]), ([], None, None))
        self.assertIsNone(run["conditions"]["phase"])

    async def test_without_demo_phase_an_observe_proxy_runs_unblocked(self):
        run = await self.run_offline(phase=None, config=OBSERVE_CONFIG)
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")
        self.assertNotIn("guardrail_stop", run["summary"])
        self.assertEqual((len(run["upstream_requests"]), len(run["steps"])), (16, 8))
        self.assertNotIn("guardrail_block", run["session"]["meta"])
        self.assertEqual((run["conditions"]["phase"], run["conditions"]["guardrail_mode"]), (None, "observe"))

    async def test_dataset_run_with_demo_phase_fails_before_the_run_directory(self):
        import experiments.run_scenario as runner
        output = Path(self.enterContext(tempfile.TemporaryDirectory()))
        args = SimpleNamespace(scenario=A1V4, dataset_run=True, phase="demo", collection_policy=facts.INDEPENDENT,
                               output_contract=facts.V2, runner_protocol=PROTOCOL_V10, run_index=1, temperature=0.0,
                               api_key_env="KMU_API_KEY", output_root=output)
        clean = {"git_commit": "0" * 40, "git_dirty": False, "git_state_status": "measured", "git_state_reason": None}
        with mock.patch.object(runner, "git_state", return_value=clean), \
                mock.patch.dict("os.environ", {"KMU_API_KEY": "fake"}), \
                self.assertRaisesRegex(ValueError, "cannot be combined"):
            await runner.run(args)
        self.assertEqual(list(output.iterdir()), [])

    async def test_dataset_run_through_a_block_proxy_stops_before_any_model_call(self):
        # Refused at session start by DM-32; enforce_observe_proxy remains as a second check (unit test above).
        run = await self.run_offline(phase=None, dataset_run=True)
        self.assertEqual(run["summary"]["termination_reason"], "runner_error")
        self.assertIn("block_mode_requires_demo_phase", run["summary"]["error"])
        self.assertEqual((run["upstream_requests"], run["steps"], run["session"]), ([], None, None))


class DemoOutputRootTests(unittest.TestCase):
    """DM-34: --phase demo writes only under runs/demo/; runs/demo/ holds nothing else (DM-2)."""

    def test_defaults_and_allowed_roots(self):
        demo = run_scenario.DEMO_OUTPUT_ROOT.resolve()
        self.assertEqual(output_root_for("demo", None), demo)
        self.assertEqual(output_root_for(None, None), run_scenario.DEFAULT_OUTPUT_ROOT.resolve())
        self.assertEqual(output_root_for("demo", demo / "cl"), demo / "cl")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(output_root_for(None, Path(directory)), Path(directory).resolve())

    def test_demo_elsewhere_and_non_demo_inside_runs_demo_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "DM-34"):
                output_root_for("demo", Path(directory))
        with self.assertRaisesRegex(ValueError, "DM-34"):
            output_root_for("demo", run_scenario.DEFAULT_OUTPUT_ROOT)
        with self.assertRaisesRegex(ValueError, "reserved for --phase demo"):
            output_root_for(None, run_scenario.DEMO_OUTPUT_ROOT / "x")


if __name__ == "__main__":
    unittest.main()
