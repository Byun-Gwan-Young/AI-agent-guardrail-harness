import copy
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from progress_signal import calculate_progress, histories_by_agent
from proxy import create_app
from session_store import JsonSessionRepository, SessionStore
from test_progress_signal import snapshot


def obs(step, agent="A", **kwargs):
    return {**snapshot(step, **kwargs), "agent_id": agent}


def calc(history, current):
    return calculate_progress(history, current, version="progress-v2")


class RoleProgressTests(unittest.TestCase):
    def test_a_b_a_compares_only_a(self):
        a, b, current = obs(1, issues=["a"]), obs(2, "B", issues=["b"]), obs(3, issues=["a"])
        result = calc([a, b], current)
        self.assertEqual(result["state"], "stagnant")
        self.assertEqual(result["comparison_step_id"], a["step_id"])
        self.assertEqual(result["history_step_ids"], [a["step_id"]])
        self.assertEqual(result["events"], [])

    def test_other_role_does_not_supply_recurrence_or_seen_info(self):
        a = obs(1, proposal=100, issues=["a"], info=["a"], file="a")
        b = obs(2, "B", proposal=200, issues=["b"], info=["b"], file="b")
        current = obs(3, proposal=200, issues=["b"], info=["b"], file="b")
        result = calc([a, b], current)
        self.assertEqual(result["state"], "progress")
        for flag in ("oscillation", "reopen", "revert"):
            self.assertEqual(result["flags"][flag], [])
        self.assertEqual(result["metrics"]["conversation.new_info_ratio"]["value"], 1.0)

    def test_same_role_recurrence_reopen_and_revert_survive(self):
        a = obs(1, proposal=100, issues=["a"], file="a")
        b = obs(2, "B", proposal=999, issues=["b"], file="b")
        middle = obs(3, proposal=200, issues=[], file="c")
        result = calc([a, b, middle], obs(4, proposal=100, issues=["a"], file="a"))
        self.assertEqual(result["state"], "oscillating")
        for flag in ("oscillation", "reopen", "revert"):
            self.assertTrue(result["flags"][flag])

    def test_first_observation_for_each_role_is_baseline(self):
        self.assertEqual(calc([obs(1)], obs(2, "B"))["state"], "baseline")

    def test_first_empty_or_partial_observation_preserves_legacy_rule(self):
        empty = obs(2, "B"); empty["conversation"] = None; empty["artifact"] = None
        self.assertEqual(calc([obs(1)], empty)["state"], "unmeasured")
        partial = copy.deepcopy(empty)
        partial["conversation"] = {"source_kind": "structured", "open_issue_ids": []}
        self.assertEqual(calc([obs(1)], partial)["state"], "baseline")

    def test_missing_own_observation_is_not_skipped(self):
        a = obs(1); missing = obs(3); missing["conversation"] = None; missing["artifact"] = None
        result = calc([a, obs(2, "B"), missing, obs(4, "B")], obs(5))
        self.assertEqual(result["comparison_step_id"], missing["step_id"])
        self.assertEqual(result["state"], "unmeasured")
        self.assertEqual(result["history_step_ids"], [a["step_id"], missing["step_id"]])

    def test_other_role_missing_does_not_replace_own_baseline(self):
        missing = obs(2, "B"); missing["conversation"] = None; missing["artifact"] = None
        self.assertEqual(calc([obs(1), missing], obs(3))["state"], "stagnant")

    def test_missing_identity_never_uses_global_fallback(self):
        for identity in (None, ""):
            current = obs(2); current["agent_id"] = identity
            self.assertEqual(calc([obs(1)], current)["state"], "unmeasured")
        unknown = obs(1); unknown.pop("agent_id")
        self.assertEqual(calc([unknown], obs(2))["state"], "baseline")

    def test_one_role_matches_v1_except_version_and_comparison_metadata(self):
        history = [obs(1), obs(2, proposal=800)]
        current = obs(3)
        result = calc(history, current)
        for key in ("comparison_step_id", "history_step_ids"):
            result.pop(key)
        result["version"] = "progress-v1"
        self.assertEqual(result, calculate_progress(history, current))

    def test_source_metric_suite_scope_changes_keep_existing_rules(self):
        baseline = obs(1)
        for change in ("source", "metric", "suite", "scope"):
            current = obs(3)
            if change == "source": current["conversation"]["source_kind"] = "extracted"
            if change == "metric": current["progress_metric"]["conversation"] = ["new_info_ratio"]
            if change == "suite": current["artifact"]["test_suite_id"] = "different"
            if change == "scope": current["artifact"]["files_scope_id"] = "different"
            with self.subTest(change=change):
                self.assertEqual(calc([baseline, obs(2, "B")], current)["state"], "unmeasured")

    def test_null_info_and_progress_precedence_unchanged(self):
        baseline, current = obs(1), obs(3)
        current["conversation"]["info_items"] = None
        self.assertEqual(calc([baseline, obs(2, "B")], current)["state"], "unmeasured")
        current["conversation"]["open_issue_ids"] = ["new"]
        result = calc([baseline, obs(2, "B")], current)
        self.assertEqual(result["state"], "progress")
        self.assertFalse(result["coverage_complete"])

    def test_shared_artifact_change_visible_to_multiple_roles(self):
        history = [obs(1, file="old"), obs(2, "B", file="old")]
        changed = obs(3, file="new")
        self.assertEqual(calc(history, changed)["state"], "progress")
        self.assertEqual(calc(history + [changed], obs(4, "B", file="new"))["state"], "progress")

    def test_derived_index_references_originals_without_mutation(self):
        history = [obs(1), obs(2, "B")]; original = copy.deepcopy(history)
        index = histories_by_agent(history)
        self.assertIs(index["A"][0], history[0])
        current = obs(3); before = copy.deepcopy(current)
        calc(history, current)
        self.assertEqual(history, original); self.assertEqual(current, before)

    def test_restart_rebuilds_same_role_history(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonSessionRepository(directory)
            store = SessionStore(repository); session = store.start("roles")
            session.observations = [obs(1), obs(2, "B")]; store.save(session)
            before = calc(session.observations, obs(3))
            restored = SessionStore(repository).get("roles")
            self.assertEqual(calc(restored.observations, obs(3)), before)


class RoleObservationAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_identity_is_idempotent_and_changed_identity_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, httpx.MockTransport(lambda r: httpx.Response(200,
                json={"choices":[{"message":{"content":"ok"}}]})))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                headers = {"X-Guardrail-Session": "roles"}
                await c.post("/v1/chat/completions", json={"messages":[]}, headers=headers)
                body = obs(1)
                first = await c.post("/sessions/observations", json=body, headers=headers)
                duplicate = await c.post("/sessions/observations", json=body, headers=headers)
                self.assertEqual(first.status_code, 200)
                self.assertTrue(duplicate.json()["duplicate"])
                self.assertEqual(len(app.state.store.get("roles").observations), 1)
                body["agent_id"] = "B"
                self.assertEqual((await c.post("/sessions/observations", json=body, headers=headers)).status_code, 409)
