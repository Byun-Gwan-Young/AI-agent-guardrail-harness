"""Offline harness for scenario-v2 artifact (T2/T3) runs (C-17-5): the real runner on the artifact path, an
in-memory proxy, a fake upstream.

The fake upstream answers a request that carries response_format (the step's final call) with the next scripted
report, and any other request with a short text, or with a scripted tool call. The file tools are the runner's own and
act on the copied workspace. Acceptance is replaced by a function of the workspace: the source file's "# PASS=<n>"
line gives the passed count (7 without one) out of 16, so a scripted write changes the measured result.
"""
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from unittest import mock

import httpx
import yaml

from t1_harness import completion

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/scenario-v2-artifact.yaml"
OBSERVE_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu.yaml"
BLOCK_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu-block.yaml"
PROTOCOL_V10 = "tool-capable-step-v10-final-report-allowlist"
V2, V3 = "output-contract-v2", "output-contract-v3"
SOURCE = "src/task_query.py"
TOTAL = 16
# The write gate of a CT-like task (DM-16): the developer waits for the reviewer's approval of SPEC.md.
GATE = {"role": "developer", "requires": "spec_approved", "set_by": "reviewer", "spec_path": "SPEC.md"}


def report(issues=("requirements",), declared=False, approved=None, contract=V3, narrative="n"):
    value = {"narrative": narrative, "open_issue_ids": list(issues), "info_items": None,
             "completion_declared": declared, "unlisted_issues": []}
    return {**value, "spec_approved": approved} if contract == V3 else value


def write(content, path=SOURCE):
    return ("write_file", {"path": path, "content": content})


def source(passed):
    """Source text whose measured pass count is passed (see module docstring)."""
    return f"# PASS={passed}\ndef query_tasks(*args, **kwargs):\n    return []\n"


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


def measured(work):
    """Workspace.acceptance replacement: real artifact capture, the pass count from the source file's marker."""
    from artifact_hook import capture_artifact
    scenario = work.scenario
    text = (work.root / SOURCE).read_text(encoding="utf-8") if (work.root / SOURCE).exists() else ""
    match = re.search(r"^# PASS=(\d+)$", text, re.M)
    passed = int(match.group(1)) if match else 7
    artifact = capture_artifact(work.root, scenario.monitored_paths,
                                test_suite_id=scenario.success_criteria.test_suite.test_suite_id)
    artifact.update(test_pass_count=passed, test_total_count=TOTAL)
    return {"summary": {"passed": passed, "tests": TOTAL}, "gate": {"machine_success": passed == TOTAL},
            "artifact": artifact, "error": None}


def scenario_file(directory, contract=V3, gate=None, max_steps=8, **changes):
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    data.update(output_contract=contract, **changes)
    data["termination"]["max_steps"] = max_steps
    # Optional in scenario-v2; its assumed call range (9-15) would not fit the short test runs.
    data.pop("token_estimate", None)
    if gate is not None:
        data["write_gate"] = gate
    path = Path(directory) / "scenario.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


async def run_t2(reports, *, tools=None, config=OBSERVE_CONFIG, contract=V3, gate=None, max_steps=8,
                 output_contract=None, runner_protocol=PROTOCOL_V10, phase="demo", dataset_run=False,
                 output_root=None, closed_list_check=None, scenario_changes=None, tests=None, scenario_path=None,
                 real_acceptance=False):
    """Returns the run folder files, the proxy log and every upstream request.

    scenario_path runs that scenario file as it is (C-18-1: the DEMO-CL files) instead of a changed copy of FIXTURE;
    real_acceptance keeps the runner's own acceptance run (the scenario's tests in a subprocess, offline).
    """
    import experiments.run_scenario as runner
    from proxy import create_app
    upstream = Upstream(reports, tools)
    root = Path(tests.enterContext(tempfile.TemporaryDirectory()) if tests else tempfile.mkdtemp())
    path = (Path(scenario_path) if scenario_path is not None
            else scenario_file(root, contract, gate, max_steps, **(scenario_changes or {})))
    from pinned_configs import for_model
    # A scenario with run_conditions (DM-57) runs through the real demo configuration.
    sent_model = yaml.safe_load(path.read_text(encoding="utf-8")).get("model")
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
                           output_contract=output_contract or contract, runner_protocol=runner_protocol,
                           api_key_env="KMU_API_KEY", phase=phase, dataset_run=dataset_run,
                           closed_list_check=closed_list_check)
    clean = {"git_commit": "0" * 40, "git_dirty": False, "git_state_status": "measured", "git_state_reason": None}
    stdout = io.StringIO()
    acceptance = runner.Workspace.acceptance if real_acceptance else measured
    with mock.patch.object(runner, "DEMO_OUTPUT_ROOT", demo_root), \
            mock.patch.object(runner, "git_state", return_value=clean), \
            mock.patch.object(runner.Workspace, "acceptance", acceptance), \
            mock.patch("httpx.AsyncClient", OfflineClient), mock.patch.dict("os.environ", {"KMU_API_KEY": "fake"}), \
            contextlib.redirect_stdout(stdout):
        code = await runner.run(args)
    folders = [p for p in demo_root.iterdir()] if demo_root.exists() else []
    out = folders[0] if folders else None
    read = lambda name: (json.loads((out / name).read_text(encoding="utf-8"))
                         if out is not None and (out / name).exists() else None)
    return {"code": code, "root": root, "out": out, "session_id": out.name if out else None,
            "steps": read("steps.json"), "summary": read("summary.json"), "session": read("session.json"),
            "conditions": read("conditions.json"), "requests": upstream.requests, "stdout": stdout.getvalue()}
