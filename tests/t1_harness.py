"""Offline harness for scenario-v2 dialogue (T1) runs (C-17-4): the real runner, an in-memory proxy, a fake upstream.

The fake upstream answers a request that carries response_format (the step's final call) with the next scripted
output-contract-v3 report, and any other request with a short text, or with a scripted tool call. Tools are fakes
injected into experiments.dialogue_tools.IMPLEMENTATIONS unless a test passes the real ones (C-17-6).
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/scenario-v2-dialogue.yaml"
FIXTURES = ROOT / "tests/fixtures"
OBSERVE_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu.yaml"
BLOCK_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu-block.yaml"
V02_CONFIG = ROOT / "guardrail-deadlock-v0.2-kmu.yaml"
PROTOCOL_V10 = "tool-capable-step-v10-final-report-allowlist"
V3 = "output-contract-v3"
DELIVERABLE = {"order_id": "A-100", "handling_code": "PARTIAL_REFUND", "owner": "refund",
               "customer_reply": "부분 환불을 진행합니다."}


def report(status="received", handoff=None, adopted=(), issues=("requirements",), deliverable=None, declared=False,
           narrative="n"):
    return {"narrative": narrative, "open_issue_ids": list(issues), "info_items": None,
            "completion_declared": declared, "unlisted_issues": [], "status": status, "handoff_to": handoff,
            "adopted_items": list(adopted), "deliverable": deliverable, "spec_approved": None}


def completion(content=None, tool=None, arguments=None, turn_id="t"):
    message = {"role": "assistant", "content": content}
    if tool:
        message.update(content=None, tool_calls=[{"id": "call-" + turn_id, "type": "function",
                                                  "function": {"name": tool, "arguments": json.dumps(arguments)}}])
    return httpx.Response(200, json={"id": "fake", "object": "chat.completion", "created": 0, "model": "fake-model",
                                     "choices": [{"index": 0, "finish_reason": "tool_calls" if tool else "stop",
                                                  "message": message}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})


class Upstream:
    """reports: one per step (dict, or raw text for a malformed final). tools: {step: (name, arguments)}."""

    def __init__(self, reports, tools=None):
        self.reports, self.tools, self.requests = list(reports), dict(tools or {}), []
        self.finals, self.tool_steps_done = 0, set()

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        if "response_format" in body:
            self.finals += 1
            item = self.reports.pop(0)
            return completion(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))
        step = self.finals + 1
        if step in self.tools and step not in self.tool_steps_done:
            self.tool_steps_done.add(step)
            name, arguments = self.tools[step]
            return completion(tool=name, arguments=arguments, turn_id=str(step))
        return completion("ok")


def fake_lookup(arguments, context):
    return {"order_id": arguments["order_id"], "status": "delivered_damaged"}


def fake_policy(arguments, context):
    return "policy text for " + arguments["name"]


FAKE_TOOLS = {"lookup_order": fake_lookup, "read_policy": fake_policy}


def scenario_file(directory, **changes):
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if key == "max_steps":
            data["termination"]["max_steps"] = value
        elif value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = Path(directory) / "scenario.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


async def run_t1(reports, *, tools=None, config=OBSERVE_CONFIG, phase="demo", dataset_run=False,
                 closed_list_check=None, output_contract=V3, runner_protocol=PROTOCOL_V10, implementations=None,
                 output_root=None, scenario_changes=None, max_steps=8, tests=None, model=None):
    """Returns the run folder files, the proxy log and every upstream request."""
    import experiments.run_scenario as runner
    import experiments.dialogue_runner as dialogue
    import experiments.dialogue_tools as dialogue_tools
    from proxy import create_app
    upstream = Upstream(reports, tools)
    root = Path(tests.enterContext(tempfile.TemporaryDirectory()) if tests else tempfile.mkdtemp())
    path = scenario_file(root, max_steps=max_steps, **(scenario_changes or {}))
    from pinned_configs import for_model
    # A scenario with run_conditions (DM-57) and no --model runs through the real demo configuration.
    sent_model = model if model is not None else yaml.safe_load(path.read_text(encoding="utf-8")).get("model")
    app = create_app(root / "logs" / "demo", transport=httpx.MockTransport(upstream),
                     config_path=for_model(config, sent_model) if sent_model else config)
    real_client = httpx.AsyncClient

    class OfflineClient(real_client):
        def __init__(self, *a, **kw):
            kw.setdefault("transport", httpx.ASGITransport(app=app))
            super().__init__(*a, **kw)
    demo_root = root / "runs" / "demo"
    args = SimpleNamespace(scenario=path, run_index=1, temperature=None, output_root=output_root,
                           no_context_buffer=False, context_buffer_messages=None, seed_probe=None,
                           proxy_url="http://mock", collection_policy="independent-sources-v1",
                           output_contract=output_contract, runner_protocol=runner_protocol,
                           api_key_env="KMU_API_KEY", phase=phase, dataset_run=dataset_run,
                           closed_list_check=closed_list_check, model=model)
    clean = {"git_commit": "0" * 40, "git_dirty": False, "git_state_status": "measured", "git_state_reason": None}
    stdout = io.StringIO()
    with mock.patch.object(runner, "DEMO_OUTPUT_ROOT", demo_root), \
            mock.patch.object(runner, "git_state", return_value=clean), \
            mock.patch.object(dialogue, "SCENARIO_ROOT", FIXTURES), \
            mock.patch.dict(dialogue_tools.IMPLEMENTATIONS, FAKE_TOOLS if implementations is None else implementations,
                            clear=True), \
            mock.patch("httpx.AsyncClient", OfflineClient), mock.patch.dict("os.environ", {"KMU_API_KEY": "fake"}), \
            contextlib.redirect_stdout(stdout):
        code = await runner.run(args)
    folders = [p for p in demo_root.iterdir()] if demo_root.exists() else []
    out = folders[0] if folders else None
    read = lambda name: (json.loads((out / name).read_text(encoding="utf-8"))
                         if out is not None and (out / name).exists() else None)
    return {"code": code, "root": root, "out": out, "session_id": out.name if out else None,
            "steps": read("steps.json"), "summary": read("summary.json"), "session": read("session.json"),
            "conditions": read("conditions.json"), "dispatch": read("tool-dispatch.json"),
            "requests": upstream.requests, "stdout": stdout.getvalue()}
