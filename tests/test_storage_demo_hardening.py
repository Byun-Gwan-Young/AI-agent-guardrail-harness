import unittest
from collections import Counter
from unittest.mock import MagicMock, patch

from storage import import_demo
from storage.safety import assert_safe_storage_json


class CursorStub:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), tuple(params)))

    def fetchone(self):
        return self.row


class StorageDemoHardeningTests(unittest.TestCase):
    def test_canonical_demo_payloads_parse_before_db(self):
        payloads = import_demo._prepare_all_demo_payloads()
        self.assertEqual(len(payloads), 115)
        self.assertEqual(len({p["session"]["id"] for p in payloads}), 115)
        self.assertEqual(sum(len(p["judgements"]) for p in payloads), 926)
        self.assertEqual(
            len({
                (p["scenario"]["scenario_key"], p["scenario"]["scenario_hash"])
                for p in payloads
            }),
            15,
        )
        self.assertEqual(
            Counter(p["session"]["validity"] for p in payloads),
            Counter({"valid": 67, "excluded": 30, "not_counted": 18}),
        )
        self.assertEqual(
            Counter(p["session"]["source"] for p in payloads),
            Counter({"demo-record": 115}),
        )
        self.assertEqual(
            Counter(p["scenario"]["schema_version"] for p in payloads),
            Counter({"scenario-v2": 115}),
        )

    def test_storage_safety_allows_numeric_token_metrics(self):
        assert_safe_storage_json(
            {
                "tokens": {
                    "prompt": 100,
                    "completion": 20,
                    "reasoning": 5,
                }
            },
            "metrics",
        )

    def test_storage_safety_rejects_raw_model_text_and_secret(self):
        with self.assertRaises(ValueError):
            assert_safe_storage_json({"messages": [{"role": "user", "content": "x"}]}, "row")
        with self.assertRaises(ValueError):
            assert_safe_storage_json({"prompt": "raw prompt"}, "row")
        with self.assertRaises(ValueError):
            assert_safe_storage_json({"api_key": "gsk_" + "A" * 24}, "row")


    def test_demo_project_lookup_ignores_user_owned_same_name(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [(3, True, None)]

        project_id = import_demo.ensure_demo_project(cursor)
        self.assertEqual(project_id, 3)

        lock_sql = " ".join(cursor.execute.call_args_list[0].args[0].split())
        self.assertIn("pg_advisory_xact_lock", lock_sql)

        select_sql = " ".join(cursor.execute.call_args_list[1].args[0].split())
        self.assertIn("owner_user_id IS NULL", select_sql)

        update_sql = " ".join(cursor.execute.call_args_list[2].args[0].split())
        update_params = cursor.execute.call_args_list[2].args[1]
        self.assertIn("provider = %s", update_sql)
        self.assertIn("custom", update_params)


    def test_incomplete_canonical_demo_source_is_rejected_before_db(self):
        folders = import_demo.demo_folders()
        self.assertEqual(len(folders), import_demo.CANONICAL_DEMO_SESSION_COUNT)
        with patch("storage.import_demo.demo_folders", return_value=folders[:-1]), patch(
            "storage.import_demo.get_connection"
        ) as connect:
            with self.assertRaisesRegex(ValueError, "완전하지"):
                import_demo.import_all_demos()
            connect.assert_not_called()

    def test_empty_bulk_source_never_opens_db_or_prunes(self):
        with patch("storage.import_demo._prepare_all_demo_payloads", return_value=[]), patch(
            "storage.import_demo.get_connection"
        ) as connect:
            with self.assertRaises(FileNotFoundError):
                import_demo.import_all_demos()
            connect.assert_not_called()

    def test_session_id_cannot_move_from_other_source(self):
        cursor = CursorStub(("live", 3))
        with self.assertRaisesRegex(ValueError, "다른 source/project"):
            import_demo._assert_demo_session_identity(cursor, "same-id", 3)

    def test_session_id_cannot_move_from_other_project(self):
        cursor = CursorStub(("demo-record", 999))
        with self.assertRaisesRegex(ValueError, "다른 source/project"):
            import_demo._assert_demo_session_identity(cursor, "same-id", 3)

    def test_same_demo_identity_is_allowed(self):
        cursor = CursorStub(("demo-record", 3))
        import_demo._assert_demo_session_identity(cursor, "same-id", 3)

    def test_replace_children_deletes_all_old_demo_children_first(self):
        cursor = CursorStub()
        rows = [{"step_id": 1}, {"step_id": 2}]
        with patch("storage.import_demo.upsert_demo_judgement") as insert:
            import_demo._replace_demo_children(cursor, "session-1", rows)

        statements = [sql for sql, _ in cursor.executed]
        self.assertEqual(len(statements), 3)
        self.assertTrue(statements[0].startswith("DELETE FROM llm_calls"))
        self.assertTrue(statements[1].startswith("DELETE FROM observations"))
        self.assertTrue(statements[2].startswith("DELETE FROM judgements"))
        self.assertEqual(insert.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
