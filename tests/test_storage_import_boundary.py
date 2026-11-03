import unittest

from storage.import_run import _model_name, upsert_session
from storage.import_utils import observation_input, verify_project
from storage.safety import assert_safe_storage_json


class CursorStub:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), tuple(params)))

    def fetchone(self):
        return self.row


class SequenceCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), tuple(params)))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class StorageImportBoundaryTests(unittest.TestCase):
    def test_raw_import_rejects_read_only_project(self):
        cursor = CursorStub((True,))
        with self.assertRaisesRegex(ValueError, "읽기 전용"):
            verify_project(cursor, 3)

    def test_raw_import_accepts_writable_project(self):
        cursor = CursorStub((False,))
        verify_project(cursor, 7)
        self.assertIn("read_only", cursor.executed[0][0])


    def test_model_object_is_reduced_to_text_identifier(self):
        self.assertEqual(_model_name({"name": "model-x", "other": 1}), "model-x")
        self.assertEqual(_model_name({"model": "model-y"}), "model-y")
        with self.assertRaises(ValueError):
            _model_name({"temperature": 0.2})

    def test_raw_reimport_cannot_change_existing_scenario_identity(self):
        cursor = SequenceCursor([("raw-run", 99)])
        values = {
            "status": "ended",
            "termination_reason": "done",
            "phase": None,
            "guardrail_mode": "observe",
            "model": "model-x",
            "steps_reached": 1,
            "total_tokens": 10,
            "first_stop_step": None,
            "started_at": None,
            "ended_at": None,
            "execution_config": {},
            "session_data": {},
        }
        with self.assertRaisesRegex(ValueError, "identity"):
            upsert_session(cursor, "same-session", 42, values)
        self.assertEqual(len(cursor.executed), 1)
        self.assertIn("FOR UPDATE", cursor.executed[0][0])

    def test_observation_input_keeps_structured_judge_fields_but_not_computed_results(self):
        raw = {
            "step_id": 1,
            "agent_id": "developer",
            "conversation": {"open_issue_ids": ["x"]},
            "progress": {"state": "stagnant"},
            "criteria": {"decision": "CONTINUE"},
        }
        result = observation_input(raw)
        self.assertEqual(result["conversation"], {"open_issue_ids": ["x"]})
        self.assertNotIn("progress", result)
        self.assertNotIn("criteria", result)
        assert_safe_storage_json(result, "observation_data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
