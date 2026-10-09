
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from storage import live


class FakeCursor:
    def __init__(self, state):
        self.state = state
        self._rows = []
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _set(self, columns, rows):
        class Col:
            def __init__(self, name):
                self.name = name
        self.description = [Col(c) for c in columns]
        self._rows = list(rows)

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        now = datetime.now(timezone.utc)

        # projects
        if q.startswith("SELECT id, mode, read_only, provider FROM projects WHERE id = %s"):
            p = self.state["projects"].get(params[0])
            self._set(
                ["id", "mode", "read_only", "provider"],
                [] if not p else [(p["id"], p["mode"], p["read_only"], p["provider"])],
            )
            return

        # scenarios identity
        if q.startswith("SELECT id FROM scenarios WHERE project_id = %s"):
            project_id, scenario_key, scenario_hash = params
            rows = [
                (s["id"],)
                for s in self.state["scenarios"].values()
                if s["project_id"] == project_id
                and s["scenario_key"] == scenario_key
                and s["scenario_hash"] == scenario_hash
            ]
            self._set(["id"], rows)
            return

        # insert live session
        if q.startswith("INSERT INTO sessions ( id, scenario_id, status, guardrail_mode"):
            (
                session_id, scenario_id, mode, model, execution_config, session_data
            ) = params
            if session_id in self.state["sessions"]:
                self._set(["id", "started_at"], [])
                return
            row = {
                "id": session_id,
                "scenario_id": scenario_id,
                "status": "active",
                "guardrail_mode": mode,
                "model": model,
                "execution_config": execution_config.obj if hasattr(execution_config, "obj") else execution_config,
                "session_data": session_data.obj if hasattr(session_data, "obj") else session_data,
                "validity": "not_counted",
                "source": "live",
                "started_at": now,
                "ended_at": None,
                "termination_reason": None,
                "steps_reached": None,
                "total_tokens": None,
                "first_stop_step": None,
            }
            self.state["sessions"][session_id] = row
            self._set(["id", "started_at"], [(session_id, now)])
            return

        # select existing session full identity
        if q.startswith("SELECT id, scenario_id, status, guardrail_mode, model, execution_config, session_data, source, started_at FROM sessions WHERE id = %s"):
            s = self.state["sessions"].get(params[0])
            cols = ["id","scenario_id","status","guardrail_mode","model","execution_config","session_data","source","started_at"]
            rows = [] if not s else [tuple(s[c] for c in cols)]
            self._set(cols, rows)
            return

        # require live session
        if q.startswith("SELECT id, status, source FROM sessions WHERE id = %s"):
            s = self.state["sessions"].get(params[0])
            self._set(
                ["id", "status", "source"],
                [] if not s else [(s["id"], s["status"], s["source"])],
            )
            return

        # insert observation
        if q.startswith("INSERT INTO observations ( session_id, step, agent_id, observed_at, observation_data"):
            session_id, step, agent_id, observation_data = params
            key = (session_id, step)
            if key in self.state["observations"]:
                self._set(["id", "observed_at"], [])
                return
            oid = self.state["next_obs_id"]; self.state["next_obs_id"] += 1
            data = observation_data.obj if hasattr(observation_data, "obj") else observation_data
            row = {
                "id": oid, "session_id": session_id, "step": step, "agent_id": agent_id,
                "observed_at": now, "observation_data": data,
            }
            self.state["observations"][key] = row
            self._set(["id", "observed_at"], [(oid, now)])
            return

        if q.startswith("SELECT id, agent_id, observed_at, observation_data FROM observations WHERE session_id = %s AND step = %s"):
            row = self.state["observations"].get(tuple(params))
            cols = ["id","agent_id","observed_at","observation_data"]
            self._set(cols, [] if not row else [tuple(row[c] for c in cols)])
            return

        # judgement requires the same observation/agent for the step
        if q.startswith("SELECT agent_id FROM observations WHERE session_id = %s AND step = %s"):
            row = self.state["observations"].get(tuple(params))
            self._set(["agent_id"], [] if row is None else [(row["agent_id"],)])
            return

        # insert judgement
        if q.startswith("INSERT INTO judgements ( session_id, step, agent_id, observed_at, decision, rule_id"):
            (
                session_id, step, agent_id, decision, rule_id, rule_hash,
                progress_state, progress_version, stagnant_run, reason, judgement_ns, result_data
            ) = params
            key = (session_id, step, rule_id)
            if key in self.state["judgements"]:
                self._set(["id", "observed_at"], [])
                return
            jid = self.state["next_j_id"]; self.state["next_j_id"] += 1
            data = result_data.obj if hasattr(result_data, "obj") else result_data
            row = {
                "id": jid, "session_id": session_id, "step": step, "agent_id": agent_id,
                "observed_at": now, "decision": decision, "rule_id": rule_id,
                "rule_hash": rule_hash, "progress_state": progress_state,
                "progress_version": progress_version, "stagnant_run": stagnant_run,
                "reason": reason, "judgement_ns": judgement_ns, "result_data": data,
            }
            self.state["judgements"][key] = row
            self._set(["id", "observed_at"], [(jid, now)])
            return

        if q.startswith("SELECT id, agent_id, observed_at, decision, rule_hash, progress_state"):
            session_id, step, rule_id = params
            row = self.state["judgements"].get((session_id, step, rule_id))
            cols = [
                "id","agent_id","observed_at","decision","rule_hash","progress_state",
                "progress_version","stagnant_run","reason","judgement_ns","result_data"
            ]
            self._set(cols, [] if not row else [tuple(row[c] for c in cols)])
            return

        # insert llm call
        if q.startswith("INSERT INTO llm_calls ( session_id, call_index, step, agent_id"):
            (
                session_id, call_index, step, agent_id, prompt_tokens,
                completion_tokens, reasoning_tokens, latency_ms, status_code,
                retry_count, tool_call_count
            ) = params
            key = (session_id, call_index)
            if key in self.state["llm_calls"]:
                self._set(["id"], [])
                return
            lid = self.state["next_llm_id"]; self.state["next_llm_id"] += 1
            self.state["llm_calls"][key] = {
                "id": lid, "session_id": session_id, "call_index": call_index,
                "step": step, "agent_id": agent_id, "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens, "reasoning_tokens": reasoning_tokens,
                "latency_ms": latency_ms, "status_code": status_code,
                "retry_count": retry_count, "tool_call_count": tool_call_count,
            }
            self._set(["id"], [(lid,)])
            return

        if q.startswith("SELECT id, step, agent_id, prompt_tokens, completion_tokens, reasoning_tokens"):
            row = self.state["llm_calls"].get(tuple(params))
            cols = [
                "id","step","agent_id","prompt_tokens","completion_tokens",
                "reasoning_tokens","latency_ms","status_code","retry_count","tool_call_count"
            ]
            self._set(cols, [] if not row else [tuple(row[c] for c in cols)])
            return

        # end session select
        if q.startswith("SELECT status, termination_reason, steps_reached, total_tokens, first_stop_step, ended_at FROM sessions"):
            s = self.state["sessions"].get(params[0])
            cols = ["status","termination_reason","steps_reached","total_tokens","first_stop_step","ended_at"]
            self._set(cols, [] if not s or s["source"] != "live" else [tuple(s[c] for c in cols)])
            return

        if q.startswith("UPDATE sessions SET status = 'ended'"):
            termination_reason, steps_reached, total_tokens, first_stop_step, session_id = params
            s = self.state["sessions"][session_id]
            s.update({
                "status": "ended",
                "termination_reason": termination_reason,
                "steps_reached": steps_reached,
                "total_tokens": total_tokens,
                "first_stop_step": first_stop_step,
                "ended_at": now,
            })
            self._set(["ended_at"], [(now,)])
            return

        # progress observations
        if q.startswith("SELECT step, agent_id, observed_at, observation_data FROM observations WHERE session_id = %s"):
            session_id, after_step = params
            rows = [
                r for r in self.state["observations"].values()
                if r["session_id"] == session_id and r["step"] > after_step
            ]
            rows.sort(key=lambda r: (r["step"], r["id"]))
            cols = ["step","agent_id","observed_at","observation_data"]
            self._set(cols, [tuple(r[c] for c in cols) for r in rows])
            return

        if q.startswith("SELECT step, agent_id, observed_at, decision, rule_id, rule_hash"):
            session_id, after_step = params
            rows = [
                r for r in self.state["judgements"].values()
                if r["session_id"] == session_id and r["step"] > after_step
            ]
            rows.sort(key=lambda r: (r["step"], r["id"]))
            cols = [
                "step","agent_id","observed_at","decision","rule_id","rule_hash",
                "progress_state","progress_version","stagnant_run","reason",
                "judgement_ns","result_data"
            ]
            self._set(cols, [tuple(r[c] for c in cols) for r in rows])
            return

        raise AssertionError(f"Unexpected SQL:\n{q}")

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows = self._rows
        self._rows = []
        return rows


class FakeConnection:
    def __init__(self, state):
        self.state = state
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def cursor(self): return FakeCursor(self.state)


class LiveOfflineTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "projects": {
                1: {"id": 1, "mode": "observe", "read_only": False, "provider": "groq"},
                2: {"id": 2, "mode": "observe", "read_only": True, "provider": "custom"},
            },
            "scenarios": {
                10: {
                    "id": 10, "project_id": 1, "scenario_key": "S-1",
                    "scenario_hash": "abc123",
                }
            },
            "sessions": {},
            "observations": {},
            "judgements": {},
            "llm_calls": {},
            "next_obs_id": 1,
            "next_j_id": 1,
            "next_llm_id": 1,
        }
        self.patcher = patch(
            "storage.live.get_connection",
            side_effect=lambda: FakeConnection(self.state),
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def start(self, session_id="live-1"):
        return live.start_live_session(
            1, session_id, "S-1", "abc123", "observe", "model-x",
            {"temperature": 0.2},
        )

    def test_start_session_and_exact_retry(self):
        first = self.start()
        second = self.start()
        self.assertEqual(first["id"], "live-1")
        self.assertEqual(second["id"], "live-1")
        self.assertEqual(len(self.state["sessions"]), 1)
        self.assertEqual(self.state["sessions"]["live-1"]["source"], "live")

    def test_start_session_conflicting_retry_is_rejected(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "different live-session data"):
            live.start_live_session(
                1, "live-1", "S-1", "abc123", "observe", "model-y",
                {"temperature": 0.2},
            )

    def test_start_rejects_mode_that_disagrees_with_project(self):
        with self.assertRaisesRegex(ValueError, "mode does not match project mode"):
            live.start_live_session(
                1, "live-mode-mismatch", "S-1", "abc123", "block", "model-x", {}
            )

    def test_start_requires_existing_scenario_and_writable_project(self):
        with self.assertRaisesRegex(LookupError, "scenario not found"):
            live.start_live_session(
                1, "x", "MISSING", "nope", "observe", "m", {}
            )
        with self.assertRaisesRegex(LookupError, "project not found"):
            live.start_live_session(
                2, "x", "S-1", "abc123", "observe", "m", {}
            )

    def test_observation_exact_retry_and_conflict(self):
        self.start()
        data = {"changed_paths": ["a.py"], "tests_passed": 3}
        first = live.add_observation("live-1", 1, "developer", data)
        second = live.add_observation("live-1", 1, "developer", data)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.state["observations"]), 1)

        with self.assertRaisesRegex(ValueError, "different data"):
            live.add_observation(
                "live-1", 1, "developer",
                {"changed_paths": ["b.py"], "tests_passed": 3},
            )

    def test_judgement_extracts_versions_and_is_idempotent(self):
        self.start()
        live.add_observation(
            "live-1", 1, "developer", {"tests_passed": 3, "tests_total": 3}
        )
        result = {
            "progress": {"version": "progress-v3", "state": "stagnant"},
            "criteria": {
                "criteria_sha256": "hash-123",
                "decision": "STOP",
            },
        }
        first = live.add_judgement(
            "live-1", 1, "developer", "STOP", "deadlock-v0.3",
            "stagnant", 3, "no progress", 12345, result,
        )
        second = live.add_judgement(
            "live-1", 1, "developer", "STOP", "deadlock-v0.3",
            "stagnant", 3, "no progress", 12345, result,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["rule_hash"], "hash-123")
        self.assertEqual(first["progress_version"], "progress-v3")

        conflicting_result = {
            "progress": {"version": "progress-v3", "state": "stagnant"},
            "criteria": {
                "criteria_sha256": "hash-123",
                "decision": "STOP",
            },
        }
        with self.assertRaisesRegex(ValueError, "different data"):
            live.add_judgement(
                "live-1", 1, "developer", "STOP", "deadlock-v0.3",
                "stagnant", 3, "changed", 12345, conflicting_result,
            )

    def test_llm_call_exact_retry_and_conflict(self):
        self.start()
        first = live.add_llm_call(
            "live-1", 1, 1, "developer",
            100, 20, 5, 12.5, 200, 0, 0,
        )
        second = live.add_llm_call(
            "live-1", 1, 1, "developer",
            100, 20, 5, 12.5, 200, 0, 0,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.state["llm_calls"]), 1)

        with self.assertRaisesRegex(ValueError, "different data"):
            live.add_llm_call(
                "live-1", 1, 1, "developer",
                999, 20, 5, 12.5, 200, 0, 0,
            )

    def test_end_allows_zero_steps_and_exact_retry(self):
        self.start()
        first = live.end_live_session("live-1", "startup_error", 0, 0, None)
        ended_at = first["ended_at"]
        second = live.end_live_session("live-1", "startup_error", 0, 0, None)
        self.assertEqual(second["ended_at"], ended_at)

        with self.assertRaisesRegex(ValueError, "already ended with different data"):
            live.end_live_session("live-1", "other", 0, 0, None)

    def test_writes_after_end_are_rejected(self):
        self.start()
        live.end_live_session("live-1", "done", 1, 10, None)

        with self.assertRaisesRegex(ValueError, "not active"):
            live.add_observation("live-1", 2, "developer", {"tests_passed": 1})
        with self.assertRaisesRegex(ValueError, "not active"):
            live.add_judgement(
                "live-1", 2, "developer", "CONTINUE", "deadlock-v0.3",
                "progress", 0, "ok", 1, {"progress": {}, "criteria": {}},
            )
        with self.assertRaisesRegex(ValueError, "not active"):
            live.add_llm_call("live-1", 2, 2, "developer", 1, 1, 0, 1.0, 200)

    def test_forbidden_text_and_secret_fields_are_rejected(self):
        self.start()

        with self.assertRaisesRegex(ValueError, "저장 금지"):
            live.add_observation(
                "live-1", 1, "developer",
                {"content": "raw model text"},
            )

        with self.assertRaisesRegex(ValueError, "저장 금지"):
            live.add_observation(
                "live-1", 1, "developer",
                {"api_key": "gsk_" + "A" * 30},
            )

        with self.assertRaisesRegex(ValueError, "비밀값"):
            live.add_judgement(
                "live-1", 1, "developer", "STOP", "deadlock-v0.3",
                "stagnant", 3, "gk_12345678_" + "A" * 32, 10,
                {"progress": {}, "criteria": {}},
            )

    def test_get_progress_returns_only_after_step(self):
        self.start()
        for step in (1, 2, 3):
            live.add_observation(
                "live-1", step, "developer",
                {"changed_paths": [f"{step}.py"]},
            )
            live.add_judgement(
                "live-1", step, "developer", "CONTINUE", "deadlock-v0.3",
                "progress", 0, f"step-{step}", step * 100,
                {"progress": {"version": "v3"}, "criteria": {}},
            )

        progress = live.get_session_progress("live-1", 1)
        self.assertEqual([r["step"] for r in progress["observations"]], [2, 3])
        self.assertEqual([r["step"] for r in progress["judgements"]], [2, 3])

    def test_get_progress_after_end_is_still_readable(self):
        self.start()
        live.add_observation("live-1", 1, "developer", {"tests_passed": 1})
        live.end_live_session("live-1", "done", 1, 10, None)
        progress = live.get_session_progress("live-1", 0)
        self.assertEqual(len(progress["observations"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
