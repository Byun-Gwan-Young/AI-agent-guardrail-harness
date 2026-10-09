import inspect
import unittest
from unittest.mock import patch

from storage import live
from tests.test_storage_live import FakeConnection


class LiveHardeningTests(unittest.TestCase):
    """Regression tests for the live-write invariants that matter in production.

    These tests are deliberately offline.  They protect the contract that the
    proxy/backend will consume without requiring a local PostgreSQL instance.
    The separate check_2_5_live_health.py exercises the same public functions
    against PostgreSQL.
    """

    def setUp(self):
        self.state = {
            "projects": {
                1: {
                    "id": 1,
                    "mode": "observe",
                    "read_only": False,
                    "provider": "groq",
                }
            },
            "scenarios": {
                10: {
                    "id": 10,
                    "project_id": 1,
                    "scenario_key": "S-1",
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

    def start(self, session_id="live-hardening"):
        return live.start_live_session(
            1,
            session_id,
            "S-1",
            "abc123",
            "observe",
            "model-x",
            {"temperature": 0.2},
        )

    def test_provider_is_snapshotted_and_retry_keeps_original_provider(self):
        first = self.start()
        self.assertEqual(first["provider"], "groq")
        self.assertEqual(
            self.state["sessions"]["live-hardening"]["session_data"]["provider"],
            "groq",
        )

        # A later project provider switch must not rewrite session history.
        self.state["projects"][1]["provider"] = "openai"
        retry = self.start()
        self.assertEqual(retry["provider"], "groq")
        self.assertEqual(
            self.state["sessions"]["live-hardening"]["session_data"]["provider"],
            "groq",
        )

    def test_exact_start_retry_survives_later_project_mode_change(self):
        first = self.start()
        self.assertEqual(first["guardrail_mode"], "observe")

        # The existing session keeps its original mode snapshot.  A network retry
        # of that same start call should remain idempotent after project settings
        # change; only *new* sessions use the new project mode.
        self.state["projects"][1]["mode"] = "block"
        retry = self.start()
        self.assertEqual(retry["guardrail_mode"], "observe")

    def test_judgement_requires_observation_for_same_step(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "requires an observation"):
            live.add_judgement(
                "live-hardening",
                1,
                "developer",
                "CONTINUE",
                "deadlock-v0.3",
                "progress",
                0,
                "progress observed",
                100,
                {
                    "progress": {"version": "progress-v3", "state": "progress"},
                    "criteria": {"decision": "CONTINUE"},
                },
            )

    def test_nested_decision_must_match_top_level_decision(self):
        self.start()
        live.add_observation("live-hardening", 1, "developer", {"tests_passed": 1})
        with self.assertRaisesRegex(ValueError, "criteria decision"):
            live.add_judgement(
                "live-hardening",
                1,
                "developer",
                "CONTINUE",
                "deadlock-v0.3",
                "progress",
                0,
                "progress observed",
                100,
                {
                    "progress": {"version": "progress-v3", "state": "progress"},
                    "criteria": {"decision": "STOP"},
                },
            )

    def test_nested_progress_state_must_match_top_level_state(self):
        self.start()
        live.add_observation("live-hardening", 1, "developer", {"tests_passed": 1})
        with self.assertRaisesRegex(ValueError, "progress state"):
            live.add_judgement(
                "live-hardening",
                1,
                "developer",
                "CONTINUE",
                "deadlock-v0.3",
                "progress",
                0,
                "progress observed",
                100,
                {
                    "progress": {"version": "progress-v3", "state": "stagnant"},
                    "criteria": {"decision": "CONTINUE"},
                },
            )

    def test_first_stop_step_cannot_exceed_steps_reached(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "cannot exceed steps_reached"):
            live.end_live_session("live-hardening", "guardrail_stop", 2, 10, 3)

    def test_live_writes_and_end_use_session_row_lock(self):
        source = inspect.getsource(live._require_live_session)
        self.assertIn("FOR UPDATE", source)

        for fn in (
            live.add_observation,
            live.add_judgement,
            live.add_llm_call,
            live.end_live_session,
        ):
            fn_source = inspect.getsource(fn)
            self.assertIn("lock=True", fn_source, fn.__name__)

    def test_project_snapshot_is_locked_during_start(self):
        source = inspect.getsource(live._require_writable_project)
        self.assertIn("FOR SHARE", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
