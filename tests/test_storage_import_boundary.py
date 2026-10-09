import unittest

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


class StorageImportBoundaryTests(unittest.TestCase):
    def test_raw_import_rejects_read_only_project(self):
        cursor = CursorStub((True,))
        with self.assertRaisesRegex(ValueError, "읽기 전용"):
            verify_project(cursor, 3)

    def test_raw_import_accepts_writable_project(self):
        cursor = CursorStub((False,))
        verify_project(cursor, 7)
        self.assertIn("read_only", cursor.executed[0][0])

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
