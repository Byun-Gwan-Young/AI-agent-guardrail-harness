"""Offline capture of every upstream request of a scenario-v1 run (A-1-v4, protocol v10), for byte comparison (C-17-4).

The fixture tests/fixtures/c17-4-v1-requests.json was written by this module at 7ef2e5c, before the T1 runner work:
    venv/bin/python -B tests/v1_request_capture.py --write tests/fixtures/c17-4-v1-requests.json
The test (tests/test_dialogue_runner.py) runs the same capture on the current code and compares bytes.
"""
import argparse
import asyncio
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
A1V4 = ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml"
CONFIG = ROOT / "guardrail-deadlock-v0.2-kmu.yaml"
STEPS = 4


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def capture(steps=STEPS):
    """Upstream request bodies, in order, of an offline A-1-v4 run (tool round, early text, final call per step)."""
    import experiments.run_scenario as runner
    from artifact_hook import capture_artifact
    from experiments.step_execution import PROTOCOL_V10
    from proxy import create_app
    from scenario_schema import load_scenario
    import test_harness_facts as facts
    scenario = load_scenario(A1V4).model_copy(deep=True)
    scenario.termination.max_steps = steps
    responses = [r for _ in range(steps) for r in facts.step_responses()]
    requests = []

    def upstream(request):
        requests.append(json.loads(request.content))
        return responses.pop(0)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        app = create_app(root / "logs", transport=httpx.MockTransport(upstream), config_path=CONFIG)
        real_client = httpx.AsyncClient

        class OfflineClient(real_client):
            def __init__(self, *a, **kw):
                kw.setdefault("transport", httpx.ASGITransport(app=app))
                super().__init__(*a, **kw)

        def acceptance(work):
            artifact = capture_artifact(work.root, scenario.monitored_paths,
                                        test_suite_id=scenario.success_criteria.test_suite.test_suite_id)
            artifact.update(test_pass_count=7, test_total_count=16)
            return {"summary": {"passed": 7, "tests": 16}, "gate": {"machine_success": False},
                    "artifact": artifact, "error": None}
        args = SimpleNamespace(scenario=A1V4, run_index=1, temperature=0.0, output_root=root / "runs",
                               no_context_buffer=False, context_buffer_messages=12, seed_probe=None,
                               proxy_url="http://mock", collection_policy=facts.INDEPENDENT,
                               output_contract=facts.V2, runner_protocol=PROTOCOL_V10, api_key_env="KMU_API_KEY",
                               phase=None, dataset_run=False)
        clean = {"git_commit": "0" * 40, "git_dirty": False, "git_state_status": "measured", "git_state_reason": None}
        with mock.patch.object(runner, "load_scenario", return_value=scenario), \
                mock.patch.object(runner.Workspace, "acceptance", acceptance), \
                mock.patch.object(runner, "git_state", return_value=clean), \
                mock.patch("httpx.AsyncClient", OfflineClient), mock.patch.dict("os.environ", {"KMU_API_KEY": "fake"}), \
                contextlib.redirect_stdout(io.StringIO()):
            code = await runner.run(args)
        summary = json.loads(next((root / "runs").iterdir()).joinpath("summary.json").read_text(encoding="utf-8"))
    return {"exit_code": code, "termination_reason": summary["termination_reason"], "requests": requests}


def record(result):
    first = result["requests"][0]
    return {"scenario": A1V4.relative_to(ROOT).as_posix(), "config": CONFIG.name, "steps": STEPS,
            "exit_code": result["exit_code"], "termination_reason": result["termination_reason"],
            "request_count": len(result["requests"]),
            "first_request_messages": first["messages"],
            "first_request_messages_sha256": hashlib.sha256(canonical(first["messages"]).encode()).hexdigest(),
            "request_body_sha256": [hashlib.sha256(canonical(r).encode()).hexdigest() for r in result["requests"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, required=True)
    args = parser.parse_args()
    value = record(asyncio.run(capture()))
    args.write.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in value.items() if k != "first_request_messages"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
