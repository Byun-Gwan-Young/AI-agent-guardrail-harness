"""C-17-8 part 1: the C-17-7 decisions DM-54 ② (--dataset-run refuses a model other than the scenario's) and ④ (the
artifact path runs the tool calls of one response one at a time, in the response's order), the proxy pinned to one
model (S-12: one proxy = one condition group) and the condition-group values checked against the guideline list."""
import asyncio
import copy
import functools
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
import yaml

import criteria_freeze
from experiment_config import load_config, pinned_model
from experiments import run_scenario as runner
from experiments.run_scenario import Workspace, enforce_proxy_model, run_model
from experiments.step_execution import PROTOCOL_V10
from pinned_configs import for_model, pinned_copy
from proxy import create_app
from scenario_schema import load_scenario
from t1_harness import DELIVERABLE, report, run_t1
import test_harness_facts as facts
import test_model_run_condition as group_tests
import test_tool_recovery as recovery
from tools import analyze_session
import v1_request_capture as capture

ROOT = Path(__file__).resolve().parents[1]
GPT = "accounts/fireworks/models/gpt-oss-120b"
OTHER = "glm-5.3-flash"
V03_CONFIGS = ("guardrail-deadlock-v0.3-kmu.yaml", "guardrail-deadlock-v0.3-kmu-block.yaml")
UNPINNED = ("guardrail.yaml", "guardrail-deadlock-v0.2.yaml", "guardrail-deadlock-v0.2-kmu.yaml")


class DatasetModelTests(unittest.TestCase):
    """DM-54 ②: a dataset run sends the versioned scenario's model; another one is refused before the run folder."""

    def setUp(self):
        self.scenario = load_scenario(capture.A1V4)

    def test_another_model_is_refused_with_dataset_run(self):
        with self.assertRaisesRegex(ValueError, "--dataset-run sends the scenario model .*DM-54"):
            run_model(self.scenario, SimpleNamespace(model=OTHER, dataset_run=True))

    def test_the_scenario_model_named_or_not_is_accepted(self):
        for args in (SimpleNamespace(dataset_run=True), SimpleNamespace(model=GPT, dataset_run=True),
                     SimpleNamespace(model=OTHER, dataset_run=False)):
            with self.subTest(args=args):
                run_model(self.scenario, args)

    def test_the_runner_refuses_before_any_folder_or_request(self):
        args = SimpleNamespace(scenario=capture.A1V4, run_index=1, temperature=0.0, output_root=None,
                               no_context_buffer=False, context_buffer_messages=12, seed_probe=None,
                               proxy_url="http://mock", collection_policy=facts.INDEPENDENT, output_contract=facts.V2,
                               runner_protocol=PROTOCOL_V10, api_key_env="KMU_API_KEY", phase=None,
                               dataset_run=True, model=OTHER)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(runner, "DEFAULT_OUTPUT_ROOT", Path(directory) / "runs"), \
                mock.patch.dict("os.environ", {"KMU_API_KEY": "fake"}), \
                mock.patch("httpx.AsyncClient", side_effect=AssertionError("no request")):
            with self.assertRaisesRegex(ValueError, "DM-54"):
                asyncio.run(runner.run(args))
            self.assertFalse((Path(directory) / "runs").exists())


def call(name, arguments, number):
    return {"id": "call%d" % number, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def calls_response(*calls):
    message = {"role": "assistant", "content": None, "tool_calls": list(calls)}
    return httpx.Response(200, json={"id": "fake", "object": "chat.completion", "created": 0, "model": "fake-model",
                                     "choices": [{"index": 0, "finish_reason": "tool_calls", "message": message}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})


def slowed(tools):
    """The workspace tools with a write of 'first' made slow, so calls that ran at the same time would overtake it."""
    def slow(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            if "first" in args or kwargs.get("content") == "first":
                time.sleep(0.2)
            return function(*args, **kwargs)
        return wrapper
    return [slow(t) if t.__name__ == "write_file" else t for t in tools]


class InOrderTests(unittest.IsolatedAsyncioTestCase):
    """DM-54 ④ on the artifact path: autogen starts the calls of a response together; they now run in its order."""

    async def test_the_workspace_runs_calls_in_the_given_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SPEC.md").write_text("original", encoding="utf-8")
            agent = SimpleNamespace(permissions=["read_files", "write_files"], writable_paths=["SPEC.md"])
            work = Workspace(None, root)
            raw = slowed(work.tools(agent))
            write, read = (next(t for t in raw if t.__name__ == n) for n in ("write_file", "read_file"))
            # Without the order: the read and the second write overtake the slow first write.
            unordered = await asyncio.gather(asyncio.to_thread(write, "SPEC.md", "first"),
                                             asyncio.to_thread(read, "SPEC.md"),
                                             asyncio.to_thread(write, "SPEC.md", "second"))
            self.assertEqual((unordered[1], (root / "SPEC.md").read_text(encoding="utf-8")), ("original", "first"))
            (root / "SPEC.md").write_text("original", encoding="utf-8")
            with mock.patch.object(work, "tools", lambda a: raw):
                ordered = {t.__name__: t for t in work.ordered_tools(agent)}
            results = await asyncio.gather(ordered["write_file"]("SPEC.md", "first"), ordered["read_file"]("SPEC.md"),
                                           ordered["write_file"]("SPEC.md", "second"),
                                           ordered["read_file"]("SPEC.md"))
            self.assertEqual(results, ["written: SPEC.md", "first", "written: SPEC.md", "second"])
            self.assertEqual((root / "SPEC.md").read_text(encoding="utf-8"), "second")

    async def test_the_tool_schema_is_the_wrapped_function(self):
        from autogen_core.tools import FunctionTool
        agent = SimpleNamespace(permissions=["read_files", "write_files", "run_tests"], writable_paths=["SPEC.md"])
        work = Workspace(None, Path("."))
        for raw, ordered in zip(work.tools(agent), work.ordered_tools(agent)):
            with self.subTest(tool=raw.__name__):
                self.assertEqual(FunctionTool(ordered, description=ordered.__doc__).schema,
                                 FunctionTool(raw, description=raw.__doc__).schema)


class InOrderRunTests(facts.Runner):
    scenario_path = capture.A1V4
    runner_protocol = PROTOCOL_V10

    async def test_a_response_writing_one_file_twice_keeps_the_later_write(self):
        response = calls_response(call("write_file", {"path": "SPEC.md", "content": "first"}, 0),
                                  call("read_file", {"path": "SPEC.md"}, 1),
                                  call("write_file", {"path": "SPEC.md", "content": "second"}, 2),
                                  call("read_file", {"path": "SPEC.md"}, 3))
        original = Workspace.tools
        with mock.patch.object(Workspace, "tools", lambda self, agent: slowed(original(self, agent))):
            run = await self.run_offline([response, recovery.success(), facts.final()], max_steps=1)
        executions = run["steps"][0]["tool_executions"]
        self.assertEqual([(e["tool"], e["is_error"]) for e in executions],
                         [("write_file", False), ("read_file", False), ("write_file", False), ("read_file", False)])
        follow_up = run["upstream_requests"][1]["messages"]
        results = [(m["tool_call_id"], m["content"]) for m in follow_up if m["role"] == "tool"]
        self.assertEqual(results, [("call0", "written: SPEC.md"), ("call1", "first"),
                                   ("call2", "written: SPEC.md"), ("call3", "second")])
        self.assertTrue(all("parallel_tool_calls" not in r for r in run["upstream_requests"]))


class ProxyPinTests(unittest.IsolatedAsyncioTestCase):
    """S-12: a pinned proxy forwards its one model and refuses any other before anything goes upstream."""

    async def asyncSetUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.upstream = []

    def client(self, config):
        def handler(request):
            self.upstream.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        app = create_app(self.directory / "logs", httpx.MockTransport(handler), config_path=config)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(client.aclose)
        return app, client

    def config(self, text):
        path = self.directory / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    async def test_another_model_gets_409_and_nothing_is_sent_or_logged(self):
        app, client = self.client(self.config("criteria_version: deadlock-v0.2\npinned_model: m-1\n"))
        headers = {"X-Guardrail-Session": "s1"}
        refused = await client.post("/v1/chat/completions", json={"model": "m-2", "messages": []}, headers=headers)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual((refused.json()["error"]["code"], refused.json()["error"]["pinned_model"],
                          refused.json()["error"]["requested_model"]), ("model_differs_from_pinned_model", "m-1", "m-2"))
        self.assertEqual(refused.headers["x-should-retry"], "false")
        self.assertEqual((self.upstream, app.state.store.get("s1")), ([], None))
        ok = await client.post("/v1/chat/completions", json={"model": "m-1", "messages": []}, headers=headers)
        self.assertEqual((ok.status_code, len(self.upstream)), (200, 1))
        meta = (await client.get("/log", headers=headers)).json()["meta"]
        self.assertEqual(meta["pinned_model"], {"name": "m-1", "source": "pinned_model"})
        # deadlock-v0.2 rules are fixed in code: no freeze record.
        self.assertNotIn("criteria_freeze", meta)

    async def test_an_unpinned_configuration_forwards_as_before(self):
        _, client = self.client(self.config("criteria_version: deadlock-v0.2\n"))
        headers = {"X-Guardrail-Session": "s1"}
        for model in ("m-1", "m-2"):
            self.assertEqual((await client.post("/v1/chat/completions", json={"model": model, "messages": []},
                                                headers=headers)).status_code, 200)
        meta = (await client.get("/log", headers=headers)).json()["meta"]
        self.assertNotIn("pinned_model", meta)

    async def test_a_demo_session_records_the_v03_freeze(self):
        _, client = self.client(pinned_copy(ROOT / V03_CONFIGS[0], "m-1"))
        headers = {"X-Guardrail-Session": "s1"}
        await client.post("/v1/chat/completions", json={"model": "m-1", "messages": []}, headers=headers)
        meta = (await client.get("/log", headers=headers)).json()["meta"]
        frozen = json.loads((ROOT / "docs/criteria/deadlock-v0.3.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["criteria_freeze"]["implementation_sha256"], frozen["implementation_sha256"])
        self.assertEqual(meta["criteria_freeze"]["explanation_templates_sha256"], frozen["explanation_templates_sha256"])
        self.assertEqual(meta["criteria_freeze"], criteria_freeze.freeze("deadlock-v0.3"))

    def test_a_demo_configuration_must_be_pinned_and_values_are_checked(self):
        data = yaml.safe_load((ROOT / V03_CONFIGS[0]).read_text(encoding="utf-8"))
        data.pop("pinned_model", None)
        data.pop("run_conditions", None)
        unpinned = self.config(yaml.safe_dump(data))
        with self.assertRaisesRegex(ValueError, "deadlock-v0.3 \\(demo\\) proxy needs"):
            create_app(self.directory / "logs" / "demo", config_path=unpinned)
        for bad in (" m", "", 3):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                pinned_model({"pinned_model": bad})

    def test_the_repository_configurations(self):
        demo = {name: pinned_model(load_config(ROOT / name)) for name in V03_CONFIGS}
        # Observe and block proxies of the demo are pinned to the same model; the names are not in code.
        self.assertEqual(len({p["name"] for p in demo.values()}), 1)
        self.assertTrue(all(p is not None for p in demo.values()))
        # The Groq-era configurations and the byte-protected v0.2 gateway configuration stay unpinned (C-17-1).
        for name in UNPINNED:
            with self.subTest(config=name):
                self.assertIsNone(pinned_model(load_config(ROOT / name)))

    def test_the_fixture_copy_differs_only_in_the_pin(self):
        for name in V03_CONFIGS:
            original = load_config(ROOT / name)
            copy_ = load_config(for_model(ROOT / name, "m-1"))
            for data in (original, copy_):
                data.pop("pinned_model", None)
                data.pop("run_conditions", None)
            self.assertEqual(copy_, original)
        self.assertEqual(for_model(ROOT / UNPINNED[2], "m-1"), ROOT / UNPINNED[2])


class RunnerPinTests(unittest.IsolatedAsyncioTestCase):
    def test_the_runner_check(self):
        pin = {"name": "m-1", "source": "pinned_model"}
        self.assertEqual(enforce_proxy_model({"pinned_model": pin}, "m-1", True, "demo"), pin)
        with self.assertRaisesRegex(ValueError, "pinned to m-1; this run would send m-2"):
            enforce_proxy_model({"pinned_model": pin}, "m-2", False, None)
        for dataset_run, phase in ((True, None), (False, "demo")):
            with self.subTest(dataset_run=dataset_run, phase=phase), self.assertRaisesRegex(ValueError, "S-12"):
                enforce_proxy_model({}, "m-1", dataset_run, phase)
        # A verification or debug run through an unpinned (Groq-era) proxy is recorded as before.
        self.assertIsNone(enforce_proxy_model({}, "m-1", False, None))

    async def test_a_proxy_pinned_to_another_model_stops_the_run_before_any_model_call(self):
        # The harness normally re-pins the copy to the fixture's model; here the proxy keeps another model.
        with mock.patch("pinned_configs.for_model", lambda config, model: config):
            run = await capture.offline_run(capture.A1V4_V2, pinned_copy(capture.V03_CONFIG, OTHER), 1, phase="demo")
        self.assertEqual((run["exit_code"], run["termination_reason"], run["requests"]), (1, "runner_error", []))

    async def test_a_matching_pin_is_recorded(self):
        run = await capture.offline_run(capture.A1V4_V2, capture.V03_CONFIG, 1, phase="demo")
        self.assertEqual(run["conditions"]["proxy_pinned_model"], {"name": GPT, "source": "pinned_model"})


class ConditionGroupValueTests(unittest.TestCase):
    """The guideline's list (C-17-8 part 1): model and source, reasoning effort, criteria version and freeze hash,
    protocol, output contract, strict mode, hand-on rule, phase, mode and search settings."""

    def test_each_listed_value_is_in_the_group(self):
        result, conditions, meta = group_tests.ConditionGroupTests.base(None)
        fields = analyze_session.condition_group(result, conditions, meta)["fields"]
        for key in ("model", "model_source", "reasoning_effort", "criteria_version", "criteria_sha256",
                    "criteria_freeze_sha256", "runner_protocol", "output_contract_version", "closed_list_check",
                    "recent_messages_rule", "phase", "guardrail_mode", "search_settings_sha256"):
            self.assertIn(key, fields)

    def test_the_new_values_change_the_group(self):
        result, conditions, meta = group_tests.ConditionGroupTests.base(None)
        group = analyze_session.condition_group(result, conditions, meta)["id"]
        changes = (("conditions", "model", {"source": "run_condition"}), ("meta", "criteria_freeze", {"sha256": "x"}),
                   ("conditions", "recent_messages_rule", "t1-handoff-v1"),
                   ("conditions", "tool_settings", {"web_search": {"max_calls_per_session": 20}}))
        for target, key, value in changes:
            r, c, m = copy.deepcopy((result, conditions, meta))
            {"meta": m, "conditions": c}[target][key] = value
            with self.subTest(key=key):
                self.assertNotEqual(analyze_session.condition_group(r, c, m)["id"], group)


class DialogueGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_dialogue_manifest_carries_the_new_values(self):
        run = await run_t1([report("triage"), report("resolved", deliverable=DELIVERABLE, declared=True, issues=())],
                           tools={1: ("lookup_order", {"order_id": "A-100"})}, scenario_changes={"turn_order": "fixed"},
                           max_steps=2, tests=self)
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            manifest = analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])
        fields = manifest["condition"]["group"]["fields"]
        self.assertEqual((fields["model_source"], fields["recent_messages_rule"], fields["search_settings_sha256"]),
                         ("scenario", "t1-handoff-v1", None))
        self.assertEqual(fields["criteria_freeze_sha256"], criteria_freeze.freeze("deadlock-v0.3")["sha256"])


if __name__ == "__main__":
    unittest.main()
