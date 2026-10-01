"""C-17-1 part 1: deadlock-v0.3 / progress-v3 (DM-10, DM-22). v0.1/v0.2/progress-v1/v2 stay frozen."""
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from criteria_policy import pin_criteria, evaluate_criteria, progress_version_for
from experiment_config import load_config
from progress_schema import Observation
from progress_signal import calculate_progress
from progress_signal_v3 import calculate_progress as calculate_v3
from proxy import create_app
from tools import write_criteria_snapshot as snapshot_tool

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu.yaml"
V02_KMU = ROOT / "guardrail-deadlock-v0.2-kmu.yaml"
ROLES = ["planner", "developer", "reviewer"]
STATUS = ["received", "triage", "assigned", "resolved"]
T1 = ["status_advance", "adopted_items", "new_issue_ids"]
CONTEXT = {"declaration": "none", "declared_step": None, "source_kind": "scenario_rule", "evidence": "test"}


def configured(**changes):
    return pin_criteria("deadlock-v0.3", {**load_config(CONFIG)["criteria_parameters"], **changes})


V02 = pin_criteria("deadlock-v0.2")


def artifact_obs(step, files, passed=7, issues=("a",), agent=None):
    """Schema-valid T2/T3 observation shaped like A-1 (open_issues_count + test_pass_count + files_changed)."""
    return Observation.model_validate({
        "agent_id": agent or ROLES[(step - 1) % 3], "step_id": step, "llm_turns": [step], "progress_source": "both",
        "progress_metric": {"conversation": ["open_issues_count"], "artifact": ["test_pass_count", "files_changed"]},
        "conversation": {"source_kind": "structured", "open_issue_ids": list(issues)},
        "artifact": {"file_hashes": {p: hashlib.sha256(c.encode()).hexdigest() for p, c in files.items()},
                     "files_scope_id": "workspace-v1", "test_pass_count": passed, "test_total_count": 16,
                     "test_suite_id": "suite-v1"},
        "termination_context": CONTEXT}).model_dump()


def series(passes, contents=None):
    """One artifact observation per step: code.py content (default: new every step) and its pass count."""
    contents = contents or [f"v{s}" for s in range(1, len(passes) + 1)]
    return [artifact_obs(s, {"code.py": c}, passed=p) for s, (c, p) in enumerate(zip(contents, passes), 1)]


def dialogue(step, agent=None, status="received", adopted=(), issues=("x",), handoff=None, metrics=T1):
    """T1 observation with the fields of output-contract-v3. The status order is registered, not observed (DM-35)."""
    return {"agent_id": agent or ROLES[(step - 1) % 3], "step_id": step, "llm_turns": [step],
            "progress_source": "conversation", "progress_metric": {"conversation": list(metrics), "artifact": []},
            "conversation": {"source_kind": "structured", "status": status,
                             "adopted_items": list(adopted), "open_issue_ids": list(issues), "handoff_to": handoff},
            "artifact": None, "termination_context": CONTEXT}


def t1_registration(metrics=T1, required=None, role_labels=None, status_labels=None):
    """Session registration (DM-35). Default labels equal the IDs, so sentences read as the IDs did before."""
    roles = ROLES + ["intake", "refund", "shipping"]
    names = status_labels or {}
    return {"registration_version": "session-registration-v1",
            "role_labels": role_labels or {r: r for r in roles},
            "status_values": [{"id": s, "label": names.get(s, s)} for s in STATUS],
            "terminal_statuses": [{"id": "escalated", "label": names.get("escalated", "escalated")}],
            "required_adopted_items": required, "progress_source": "conversation",
            "progress_metric": {"conversation": list(metrics), "artifact": []}}


REG = t1_registration()


def replay(inputs, pin, registration=None):
    history = []
    for raw in inputs:
        if pin["criteria_version"] == "deadlock-v0.3":
            progress = calculate_v3(history, raw, pin["criteria_parameters"], registration)
        else:
            progress = calculate_progress(history, raw, version=pin["criteria_parameters"]["progress_version"])
        record = {**raw, "progress": progress}
        history.append({**record, "criteria": evaluate_criteria(history + [record], pin, registration)})
    return history


def states(rows):
    return [r["progress"]["state"] for r in rows]


def first_stop(rows):
    return rows[-1]["criteria"]["first_deadlock_step"]


class PinTests(unittest.TestCase):
    def test_configured_pin_matches_registered_snapshot(self):
        pin = configured()
        frozen = json.loads((ROOT / "docs/criteria/deadlock-v0.3.json").read_text(encoding="utf-8"))
        self.assertEqual({k: frozen[k] for k in pin}, pin)
        self.assertEqual(frozen, snapshot_tool.snapshot(pin))
        self.assertEqual(progress_version_for(pin), "progress-v3")
        self.assertEqual(pin["criteria_parameters"]["plateau_steps"], 6)
        self.assertEqual(pin["criteria_parameters"]["handoff_record_threshold"], 4)

    def test_config_differs_from_v02_gateway_config_only_in_criteria(self):
        v03, v02 = load_config(CONFIG), load_config(V02_KMU)
        self.assertEqual((v03.pop("criteria_version"), v02.pop("criteria_version")), ("deadlock-v0.3", "deadlock-v0.2"))
        v03.pop("criteria_parameters")
        self.assertNotIn("criteria_parameters", v02)
        self.assertEqual(v03, v02)

    def test_parameters_have_no_code_default(self):
        parameters = load_config(CONFIG)["criteria_parameters"]
        missing = dict(parameters); missing.pop("plateau_steps")
        for bad in (None, {}, missing, {**parameters, "extra": 1}, {**parameters, "progress_version": "progress-v2"},
                    {**parameters, "plateau_steps": True}, {**parameters, "plateau_steps": 0},
                    {**parameters, "handoff_record_threshold": 1}, {**parameters, "t3_global_revert": "yes"},
                    {**parameters, "t1_metrics": ["status_advance", "status_advance"]},
                    {**parameters, "t1_metrics": ["open_issues_count"]},
                    {**parameters, "explanation_version": "explain-v2"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pin_criteria("deadlock-v0.3", bad)
        with self.assertRaises(ValueError):
            pin_criteria("deadlock-v0.2", parameters)

    def test_code_and_templates_match_the_frozen_record(self):
        # C-17-2 refreeze: a later edit of the v0.3 code or of a template fails here until it is refrozen.
        frozen = json.loads((ROOT / "docs/criteria/deadlock-v0.3.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(frozen["implementation_sha256"]), sorted(snapshot_tool.V03_IMPLEMENTATION))
        for name, digest in frozen["implementation_sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        record = json.loads((ROOT / frozen["explanation_record"]).read_text(encoding="utf-8"))
        self.assertEqual(record, snapshot_tool.explanation_record())
        self.assertEqual(record["templates_sha256"], frozen["explanation_templates_sha256"])
        self.assertEqual(snapshot_tool.canonical_sha256({k: v for k, v in record.items() if k != "templates_sha256"}),
                         record["templates_sha256"])

    def test_snapshot_tool_refuses_to_overwrite_without_refreeze(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "deadlock-v0.3.json"
            target.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                snapshot_tool.write(target, "[]\n", refreeze=False)
            before, after = snapshot_tool.write(target, "[]\n", refreeze=True)
            self.assertEqual((before, after), (hashlib.sha256(b"{}\n").hexdigest(), hashlib.sha256(b"[]\n").hexdigest()))
        self.assertEqual(snapshot_tool.snapshot(V02), V02)

    def test_tampered_pin_abstains(self):
        rows = replay([artifact_obs(s, {"a.py": "same"}) for s in range(1, 7)], configured())
        pin = configured(); pin["criteria_sha256"] = "bad"
        self.assertEqual(evaluate_criteria(rows, pin)["decision"], "unmeasured")
        self.assertIsNone(progress_version_for(pin))
        pin = configured(); pin["criteria_parameters"]["plateau_steps"] = 2
        self.assertEqual(evaluate_criteria(rows, pin)["decision"], "unmeasured")

    def test_frozen_legacy_files_are_byte_identical(self):
        expected = json.loads((ROOT / "tests/fixtures/c17-1-protected-files.json").read_text(encoding="utf-8"))
        for path, digest in expected.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)


class T3ArtifactTests(unittest.TestCase):
    def test_global_revert_when_role_history_lacks_the_state(self):
        # demo-deadlock-v0.3.md 4, case 1: reviewer restores step 4's content, which it never saw itself.
        contents = ["s0", "s0", "s0", "s1", "s2", "s1"]
        inputs = [artifact_obs(s, {"code.py": c}) for s, c in enumerate(contents, 1)]
        v02, v03 = replay(inputs, V02), replay(inputs, configured())
        self.assertEqual(v02[5]["progress"]["state"], "progress")
        self.assertEqual(v03[5]["progress"]["state"], "oscillating")
        t3 = v03[5]["progress"]["t3"]
        self.assertEqual((t3["applied"], t3["revert_to_step"], t3["changed_paths"]), ("global_revert", 4, ["code.py"]))
        self.assertEqual(states(v02[:5]), states(v03[:5]))

    def test_global_revert_switch_is_read_from_the_pin(self):
        contents = ["s0", "s0", "s0", "s1", "s2", "s1"]
        inputs = [artifact_obs(s, {"code.py": c}) for s, c in enumerate(contents, 1)]
        rows = replay(inputs, configured(t3_global_revert=False))
        self.assertEqual(rows[5]["progress"]["state"], "progress")
        self.assertTrue(rows[5]["progress"]["t3"]["global_revert"])
        self.assertIsNone(rows[5]["progress"]["t3"]["applied"])

    def test_edits_without_new_pass_count_become_stagnant_after_k(self):
        # Case 2: a new file state every step, pass count stuck at its step-1 maximum.
        inputs = [artifact_obs(s, {"code.py": f"v{s}"}) for s in range(1, 12)]
        v02, v03 = replay(inputs, V02), replay(inputs, configured())
        self.assertIsNone(first_stop(v02))
        parameters = configured()["criteria_parameters"]
        expected = 1 + parameters["plateau_steps"] + parameters["consecutive_steps"]
        self.assertEqual(first_stop(v03), expected)
        self.assertEqual(states(v03)[3:expected], ["progress"] * 4 + ["stagnant"] * 3)
        self.assertEqual(v03[expected - 1]["progress"]["t3"]["applied"], "test_plateau")
        self.assertEqual(v03[expected - 1]["progress"]["t3"]["file_state_changes_since_test_max"], expected - 1)

    def test_plateau_window_is_read_from_the_pin(self):
        inputs = [artifact_obs(s, {"code.py": f"v{s}"}) for s in range(1, 12)]
        self.assertEqual(first_stop(replay(inputs, configured(plateau_steps=2))), 1 + 2 + 3)

    def test_pass_count_increase_is_progress_and_restarts_the_window(self):
        # Case 3: edits with a new maximum stay progress; the K window restarts there.
        def build(n):
            return [artifact_obs(s, {"code.py": f"v{s}"}, passed=8 if s >= 7 else 7) for s in range(1, n + 1)]
        rows = replay(build(15), configured())
        self.assertEqual(rows[6]["progress"]["state"], "progress")
        self.assertEqual(rows[6]["progress"]["t3"]["test_max_step"], 7)
        self.assertIsNone(first_stop(rows))
        self.assertEqual(first_stop(replay(build(16), configured())), 16)

    def test_new_session_maximum_is_counted_as_pass_count_progress(self):
        # DM-28: the only pass-count progress is a count above every earlier count in the session.
        rows = replay(series([7, 7, 7, 10]), configured())
        record = rows[3]["progress"]["pass_count"]
        self.assertEqual((record["role_event"], record["session_max_before"], record["new_session_max"],
                          record["counted_as_progress"]), ("improved", 7, True, True))
        self.assertIn("artifact.test_pass_count", [e["metric"] for e in rows[3]["progress"]["events"]])
        self.assertEqual(rows[3]["progress"]["state"], "progress")

    def test_drop_and_recovery_below_maximum_with_file_change_are_not_progress_after_k(self):
        # DM-28: a file change with a lower pass count is judged like a file-only change, so after the K window
        # it is stagnant. Before DM-28 the per-role 'regressed'/'improved' event kept these steps progress.
        passes = [7, 7, 7] + [10] * 7 + [8, 8, 8, 9]
        v02, v03 = replay(series(passes), V02), replay(series(passes), configured())
        self.assertEqual(states(v03)[10:14], ["stagnant"] * 4)
        self.assertEqual(first_stop(v03), 13)
        self.assertEqual(states(v02)[10:14], ["progress"] * 4)
        self.assertIsNone(first_stop(v02))
        drop, recovery = v03[10]["progress"], v03[13]["progress"]
        self.assertEqual((drop["pass_count"]["role_event"], drop["pass_count"]["counted_as_progress"]),
                         ("regressed", False))
        self.assertEqual((drop["t3"]["applied"], drop["t3"]["steps_since_test_max"]), ("test_plateau", 7))
        self.assertEqual((recovery["pass_count"]["role_event"], recovery["pass_count"]["session_max_before"],
                          recovery["pass_count"]["new_session_max"]), ("improved", 10, False))
        self.assertNotIn("artifact.test_pass_count", [e["metric"] for e in recovery["events"]])

    def test_fix_and_revert_with_pass_count_up_and_down_stops(self):
        # DM-28 reason: files flip between two states and the pass count between 9 and 8. Every step is a
        # global revert once the pass-count events no longer count, so v0.3 stops where v0.2 sees progress.
        contents = ["s0", "s0", "s0", "s1", "s2", "s1", "s2", "s1"]
        passes = [7, 7, 7, 9, 8, 9, 8, 9]
        inputs = series(passes, contents)
        v02, v03 = replay(inputs, V02), replay(inputs, configured())
        self.assertEqual(states(v03)[3:], ["progress", "progress", "oscillating", "oscillating", "oscillating"])
        self.assertEqual(first_stop(v03), 8)
        self.assertEqual(states(v02)[3:], ["progress"] * 5)
        self.assertIsNone(first_stop(v02))
        back = v03[5]["progress"]
        self.assertEqual((back["pass_count"]["role_event"], back["pass_count"]["new_session_max"],
                          back["t3"]["applied"], back["t3"]["revert_to_step"]), ("improved", False, "global_revert", 4))

    def test_drop_inside_the_k_window_stays_progress_through_the_file_change(self):
        # The K = 6 slack absorbs a temporary drop of a legitimate edit (DM-28): the drop itself is not
        # progress, but the file change is, until T3 (a) or (b) applies.
        rows = replay(series([7, 7, 7, 10, 8, 9]), configured())
        self.assertEqual(states(rows)[3:], ["progress"] * 3)
        for row in rows[4:]:
            with self.subTest(step=row["step_id"]):
                self.assertFalse(row["progress"]["pass_count"]["counted_as_progress"])
                self.assertTrue(row["progress"]["t3"]["only_file_change_progress"])
                self.assertIsNone(row["progress"]["t3"]["applied"])

    def test_unchanged_t2_session_matches_v02(self):
        # Case 7: nothing changes (A-1-v4 shape) -> identical decisions.
        inputs = [artifact_obs(s, {"code.py": "same"}) for s in range(1, 10)]
        v02, v03 = replay(inputs, V02), replay(inputs, configured())
        self.assertEqual(states(v02), states(v03))
        self.assertEqual([r["criteria"]["decision"] for r in v02], [r["criteria"]["decision"] for r in v03])
        self.assertEqual(first_stop(v03), 6)


class T1DialogueTests(unittest.TestCase):
    def test_status_forward_same_and_back(self):
        rows = replay([dialogue(1), dialogue(2), dialogue(3), dialogue(4, status="triage"),
                       dialogue(5, status="triage"), dialogue(6, status="received")], configured(), REG)
        self.assertEqual(states(rows), ["baseline"] * 3 + ["progress", "stagnant", "oscillating"])
        self.assertEqual(rows[3]["progress"]["metrics"]["conversation.status_advance"]["value"]["session_max_index"], 0)

    def test_status_order_comes_only_from_the_registration(self):
        # DM-35: without a registered order status_advance is unmeasured; an observed order is not accepted.
        inputs = [dialogue(1), dialogue(2), dialogue(3), dialogue(4, status="triage")]
        rows = replay(inputs, configured())
        self.assertEqual(rows[3]["progress"]["metrics"]["conversation.status_advance"],
                         {"value": None, "status": "unmeasured", "reason": "status order not registered for the session"})
        legacy = [{**i, "conversation": {**i["conversation"], "status_values": STATUS}} for i in inputs]
        self.assertEqual(replay(legacy, configured())[3]["progress"]["metrics"]["conversation.status_advance"]["status"],
                         "unmeasured")
        self.assertEqual(replay(inputs, configured(), REG)[3]["progress"]["state"], "progress")

    def test_status_outside_the_order_is_unmeasured_not_stagnant(self):
        rows = replay([dialogue(1), dialogue(2), dialogue(3), dialogue(4, status="escalated")], configured(), REG)
        self.assertEqual(rows[3]["progress"]["state"], "unmeasured")
        self.assertEqual(rows[3]["criteria"]["decision"], "unmeasured")

    def test_new_adopted_item_is_progress_reorder_is_not(self):
        # Case 5: v0.2 only sees the unchanged issue list.
        inputs = [dialogue(1, adopted=["a"]), dialogue(2, adopted=["a"]), dialogue(3, adopted=["a"]),
                  dialogue(4, adopted=["a", "b"]), dialogue(5, adopted=["b", "a"])]
        rows = replay(inputs, configured(), REG)
        self.assertEqual(states(rows)[3:], ["progress", "stagnant"])
        legacy = [{**i, "progress_metric": {"conversation": ["open_issues_count"], "artifact": []}} for i in inputs]
        self.assertEqual(states(replay(legacy, V02))[3], "stagnant")

    def test_issue_close_is_not_progress_but_new_id_is(self):
        inputs = [dialogue(1, issues=["x", "y"]), dialogue(2, issues=["x", "y"]), dialogue(3, issues=["x", "y"]),
                  dialogue(4, issues=["x"]), dialogue(5, issues=["x", "y"]), dialogue(6, issues=["x", "z"])]
        self.assertEqual(states(replay(inputs, configured(), REG))[3:], ["stagnant", "stagnant", "progress"])

    def test_close_reopen_loop_stops_earlier_than_v02(self):
        # Case 4: v0.2 counts closing as progress; v0.3 does not.
        issues = [["x", "y"]] * 3 + [["x"]] * 3 + [["x", "y"]] * 3
        inputs = [dialogue(s, issues=i) for s, i in enumerate(issues, 1)]
        legacy = [{**i, "progress_metric": {"conversation": ["open_issues_count"], "artifact": []}} for i in inputs]
        self.assertEqual(first_stop(replay(inputs, configured(), REG)), 6)
        self.assertEqual(first_stop(replay(legacy, V02)), 9)

    def test_status_advance_prevents_a_v02_stop(self):
        # Case 6: unchanged issue list, status moves forward every step.
        inputs = [dialogue(s, status=STATUS[max(0, s - 3)]) for s in range(1, 7)]
        legacy = [{**i, "progress_metric": {"conversation": ["open_issues_count"], "artifact": []}} for i in inputs]
        self.assertEqual(first_stop(replay(legacy, V02)), 6)
        rows = replay(inputs, configured(), REG)
        self.assertEqual(states(rows)[3:], ["progress"] * 3)
        self.assertIsNone(first_stop(rows))

    def test_handoff_exchange_is_recorded_but_never_judged(self):
        agents = ["refund", "shipping"] * 3
        inputs = [dialogue(s, agent=a, handoff=agents[s]) for s, a in enumerate(agents[:5], 1)]
        rows = replay(inputs, configured(), REG)
        record = rows[3]["progress"]["handoff"]
        self.assertEqual((record["roles"], record["count"], record["first_step"]), (["refund", "shipping"], 4, 1))
        self.assertTrue(record["at_or_above_threshold"])
        self.assertFalse(rows[2]["progress"]["handoff"]["at_or_above_threshold"])
        silent = replay([{**i, "conversation": {**i["conversation"], "handoff_to": None}} for i in inputs], configured(), REG)
        for pin in (configured(), configured(handoff_record_threshold=2)):
            judged = replay(inputs, pin, REG)
            self.assertEqual([r["criteria"]["decision"] for r in judged], [r["criteria"]["decision"] for r in silent])
            self.assertEqual(states(judged), states(silent))

    def test_handoff_chain_breaks_on_a_third_role(self):
        inputs = [dialogue(1, "refund", handoff="shipping"), dialogue(2, "shipping", handoff="refund"),
                  dialogue(3, "refund", handoff="intake"), dialogue(4, "intake", handoff="refund")]
        rows = replay(inputs, configured(), REG)
        self.assertEqual(rows[1]["progress"]["handoff"]["count"], 2)
        self.assertEqual(rows[2]["progress"]["handoff"]["count"], 1)
        self.assertEqual(rows[3]["progress"]["handoff"]["roles"], ["refund", "intake"])


class ExistingSessionTests(unittest.TestCase):
    """C-16 prediction (demo-deadlock-v0.3.md 5): first STOP 6 / none / 9, and v0.2 records reproduce exactly."""
    SESSIONS = {"A-1-v2-b51f67df2fb9402ba15fccb35c3db53e": 6, "A-1-v3-4a0087756b2641f4b8f9b025c0419f73": None,
                "A-1-v4-e174aafe805b4f59bb62d7c95716b8b7": 9}

    def test_v03_first_stop_matches_prediction_and_v02_is_reproduced(self):
        fields = set(Observation.model_fields)
        for session_id, expected in self.SESSIONS.items():
            with self.subTest(session=session_id):
                log = json.loads((ROOT / "logs" / f"{session_id}.json").read_text(encoding="utf-8"))
                inputs = [{k: v for k, v in o.items() if k in fields} for o in log["observations"]]
                v02 = replay(inputs, log["meta"])
                for stored, again in zip(log["observations"], v02):
                    self.assertEqual(json.dumps(again["progress"], ensure_ascii=False),
                                     json.dumps(stored["progress"], ensure_ascii=False))
                    self.assertEqual(json.dumps(again["criteria"], ensure_ascii=False),
                                     json.dumps(stored["criteria"], ensure_ascii=False))
                self.assertEqual(first_stop(replay(inputs, configured())), expected)


class V03IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_pins_v03_records_judgement_ns_and_survives_restart(self):
        ticks = itertools.count(1000, 250)
        def upstream(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / "logs"
            app = create_app(logs, httpx.MockTransport(upstream), config_path=CONFIG,
                             judgement_clock_ns=lambda: next(ticks))
            headers = {"X-Guardrail-Session": "v03"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                for step in (1, 2, 3):
                    await c.post("/v1/chat/completions", json={"messages": []}, headers=headers)
                    response = await c.post("/sessions/observations", headers=headers,
                                            json=artifact_obs(step, {"code.py": "same"}))
                    self.assertEqual(response.status_code, 200)
                    record = response.json()["observation"]
                    self.assertEqual(record["judgement_ns"], 250)
                    self.assertEqual(record["progress"]["version"], "progress-v3")
                    self.assertEqual(record["criteria"]["criteria_version"], "deadlock-v0.3")
            restarted = create_app(logs, httpx.MockTransport(upstream), config_path=CONFIG,
                                   judgement_clock_ns=lambda: next(ticks))
            meta = restarted.state.store.get("v03").meta
            self.assertEqual({k: meta[k] for k in configured()}, configured())
            self.assertEqual(progress_version_for(meta), "progress-v3")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://test") as c:
                await c.post("/v1/chat/completions", json={"messages": []}, headers=headers)
                response = await c.post("/sessions/observations", headers=headers,
                                        json=artifact_obs(4, {"code.py": "same"}))
                record = response.json()["observation"]
                self.assertEqual((record["progress"]["state"], record["judgement_ns"]), ("stagnant", 250))
                self.assertIsNone(record["progress"]["t3"]["applied"])

    def test_v03_config_without_parameters_and_v02_with_parameters_fail_at_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            for text in ("criteria_version: deadlock-v0.3\n",
                         "criteria_version: deadlock-v0.2\ncriteria_parameters: {}\n"):
                config = Path(directory) / "config.yaml"
                config.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(ValueError):
                    create_app(Path(directory) / "logs", config_path=config)
