import copy
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from deadlock_policy import pin_criteria, evaluate_criteria, progress_version_for
from proxy import create_app
from scenario_schema import load_scenario, Scenario
from test_role_progress import obs, calc

ROOT = Path(__file__).resolve().parents[1]


def record(step, agent, state="stagnant", declaration="none", declared_step=None):
    value = obs(step, agent)
    value["progress"] = {"version":"progress-v2", "state":state}
    value["termination_context"] = {"declaration":declaration, "declared_step":declared_step}
    return value


def evaluate(rows):
    return evaluate_criteria(rows, pin_criteria("deadlock-v0.2"))


class CriteriaV02Tests(unittest.TestCase):
    def test_snapshot_matches_generated_pin_and_global_units(self):
        pin = pin_criteria("deadlock-v0.2")
        self.assertEqual(json.loads((ROOT / "docs/criteria/deadlock-v0.2.json").read_text()), pin)
        parameters = pin["criteria_parameters"]
        for name in ("consecutive_steps", "grace_steps", "missing_review_steps"):
            self.assertEqual(parameters[name + "_unit"], "global_step")
        self.assertEqual(progress_version_for(pin), "progress-v2")

    def test_global_n_after_three_role_baselines(self):
        rows = []
        roles = ["A", "B", "C"]
        for step, agent in enumerate(roles + roles, 1):
            current = obs(step, agent)
            current["progress"] = calc(rows, current)
            current["termination_context"] = {"declaration":"none"}
            rows.append(current)
            decision = evaluate(rows)
            if step < len(roles + roles): self.assertEqual(decision["decision"], "continue")
        self.assertEqual(decision["decision"], "deadlock")
        self.assertEqual(decision["first_deadlock_step"], len(rows))

    def test_grace_counts_global_steps_not_role_visits(self):
        rows = [record(1, "A", "baseline", "declared", 1)]
        for step, agent in enumerate(["B", "C", "A"], 2):
            rows.append(record(step, agent, declaration="declared", declared_step=1))
            result = evaluate(rows)
            if step <= 1 + pin_criteria("deadlock-v0.2")["criteria_parameters"]["grace_steps"]:
                self.assertEqual(result["decision"], "continue")
        self.assertEqual(result["decision"], "termination_failure")

    def test_missing_review_counts_global_steps_and_resets_streak(self):
        rows = [record(1, "A"), record(2, "B")]
        for step, agent in enumerate(["C", "A", "B"], 3):
            rows.append(record(step, agent, "unmeasured"))
        result = evaluate(rows)
        self.assertTrue(result["needs_observation_review"])
        self.assertEqual(result["consecutive_steps"], 0)
        rows.append(record(6, "C"))
        self.assertEqual(evaluate(rows)["decision"], "continue")

    def test_progress_baseline_unknown_reset_global_counter(self):
        for state, disposition in [("progress","none"),("baseline","none"),("stagnant","unknown")]:
            rows = [record(1,"A"), record(2,"B"), record(3,"C",state,disposition), record(4,"A")]
            self.assertEqual(evaluate(rows)["consecutive_steps"], 1)
            self.assertIsNone(evaluate(rows)["first_deadlock_step"])

    def test_hash_mismatch_wrong_progress_and_unknown_pin_abstain(self):
        rows = [record(1,"A"), record(2,"B"), record(3,"C")]
        pin = pin_criteria("deadlock-v0.2"); pin["criteria_sha256"] = "bad"
        self.assertEqual(evaluate_criteria(rows,pin)["decision"], "unmeasured")
        rows[-1]["progress"]["version"] = "progress-v1"
        self.assertEqual(evaluate(rows)["decision"], "unmeasured")

    def test_scenario_accepts_explicit_new_version_without_changing_legacy(self):
        old = load_scenario(ROOT / "scenarios/A-1-ambiguous-task-query.yaml")
        self.assertEqual(old.criteria_version, "deadlock-v0.1")
        value = old.model_dump(); value["criteria_version"] = "deadlock-v0.2"
        self.assertEqual(Scenario.model_validate(value).criteria_version, "deadlock-v0.2")


class V02IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_dispatch_restart_and_old_session_pin_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = root / "config.yaml"
            config.write_text("criteria_version: deadlock-v0.2\n")
            def upstream(r): return httpx.Response(200,json={"choices":[{"message":{"content":"ok"}}]})
            app = create_app(root / "logs", httpx.MockTransport(upstream), config_path=config)
            old = app.state.store.start("old")
            old.meta.update(pin_criteria("deadlock-v0.1")); app.state.store.save(old)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
                headers = {"X-Guardrail-Session":"new"}
                for step, agent in enumerate(["A","B","A"],1):
                    await c.post("/v1/chat/completions",json={"messages":[]},headers=headers)
                    response = await c.post("/sessions/observations",json=obs(step,agent),headers=headers)
                    self.assertEqual(response.status_code,200)
                before = response.json()["observation"]["progress"]
                self.assertEqual(before["version"],"progress-v2")
                self.assertEqual(before["state"],"stagnant")
                self.assertEqual(before["comparison_step_id"],1)
            restarted = create_app(root / "logs", httpx.MockTransport(upstream), config_path=config)
            self.assertEqual(restarted.state.store.get("new").observations[-1]["progress"],before)
            self.assertEqual(progress_version_for(restarted.state.store.get("old").meta),"progress-v1")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url="http://test") as c:
                for session_id, step in [("new",4),("old",1)]:
                    headers = {"X-Guardrail-Session":session_id}
                    await c.post("/v1/chat/completions",json={"messages":[]},headers=headers)
                    body = obs(step,"B")
                    response = await c.post("/sessions/observations",json=body,headers=headers)
                    self.assertEqual(response.status_code,200)
                    progress = response.json()["observation"]["progress"]
                    self.assertEqual(progress["version"],"progress-v2" if session_id == "new" else "progress-v1")
                    if session_id == "new": self.assertEqual(progress["comparison_step_id"],2)
