import hashlib
import unittest
from unittest.mock import patch

import storage.accounts as accounts


class FakeCursor:
    def __init__(self, state):
        self.state = state
        self._rows = []
        self.description = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _set_rows(self, columns, rows):
        class Column:
            def __init__(self, name):
                self.name = name

        self.description = [Column(name) for name in columns]
        self._rows = list(rows)

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        self.rowcount = -1

        if "SELECT id, name, mode, rule_id, upstream_url, owner_user_id, read_only, created_at FROM projects" in q:
            project_id, user_id = params
            p = self.state["projects"].get(project_id)
            if p and p["owner_user_id"] == user_id and not p["read_only"]:
                self._set_rows(
                    ["id", "name", "mode", "rule_id", "upstream_url", "owner_user_id", "read_only", "created_at"],
                    [(
                        p["id"], p["name"], p["mode"], p["rule_id"], p["upstream_url"],
                        p["owner_user_id"], p["read_only"], p["created_at"]
                    )],
                )
            else:
                self._set_rows(
                    ["id", "name", "mode", "rule_id", "upstream_url", "owner_user_id", "read_only", "created_at"],
                    [],
                )
            return

        if q.startswith("INSERT INTO api_keys"):
            project_id, key_hash, key_prefix, name = params
            key_id = self.state["next_key_id"]
            self.state["next_key_id"] += 1
            row = {
                "id": key_id,
                "project_id": project_id,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "name": name,
                "created_at": "created",
                "last_used_at": None,
                "revoked_at": None,
            }
            self.state["api_keys"][key_id] = row
            self._set_rows(
                ["id", "project_id", "key_prefix", "name", "created_at", "last_used_at", "revoked_at"],
                [(
                    row["id"], row["project_id"], row["key_prefix"], row["name"],
                    row["created_at"], row["last_used_at"], row["revoked_at"]
                )],
            )
            return

        if q.startswith("INSERT INTO auth_events"):
            kind, user_id, detail = params
            self.state["auth_events"].append((kind, user_id, detail))
            self._set_rows([], [])
            return

        if "FROM api_keys k JOIN projects p ON p.id = k.project_id WHERE k.key_prefix = %s" in q:
            prefix = params[0]
            rows = []
            for key in self.state["api_keys"].values():
                if key["key_prefix"] != prefix:
                    continue
                p = self.state["projects"][key["project_id"]]
                rows.append((
                    key["id"],
                    key["key_hash"],
                    key["revoked_at"],
                    p["id"],
                    p["name"],
                    p["mode"],
                    p["rule_id"],
                    p["upstream_url"],
                    p["owner_user_id"],
                    p["read_only"],
                    p["created_at"],
                ))
            self._set_rows(
                [
                    "key_id", "key_hash", "revoked_at", "id", "name", "mode",
                    "rule_id", "upstream_url", "owner_user_id", "read_only", "created_at"
                ],
                rows,
            )
            return

        if q.startswith("UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP"):
            key_id = params[0]
            key = self.state["api_keys"][key_id]
            if key["revoked_at"] is None:
                key["last_used_at"] = "used"
                self._set_rows(["last_used_at"], [("used",)])
            else:
                self._set_rows(["last_used_at"], [])
            return

        if "SELECT k.id, k.project_id FROM api_keys k JOIN projects p ON p.id = k.project_id" in q:
            key_id, user_id = params
            key = self.state["api_keys"].get(key_id)
            if key:
                p = self.state["projects"][key["project_id"]]
                if p["owner_user_id"] == user_id and not p["read_only"]:
                    self._set_rows(["id", "project_id"], [(key_id, key["project_id"])])
                    return
            self._set_rows(["id", "project_id"], [])
            return

        if q.startswith("UPDATE api_keys SET revoked_at = COALESCE"):
            key_id = params[0]
            if self.state["api_keys"][key_id]["revoked_at"] is None:
                self.state["api_keys"][key_id]["revoked_at"] = "revoked"
            self._set_rows([], [])
            return

        if q.startswith("UPDATE projects SET mode = %s"):
            mode, project_id = params
            self.state["projects"][project_id]["mode"] = mode
            self._set_rows([], [])
            return

        raise AssertionError(f"Unexpected SQL in fake DB:\n{q}")

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows = self._rows
        self._rows = []
        return rows


class FakeConnection:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.state)


class AccountsOfflineTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "next_key_id": 1,
            "projects": {
                10: {
                    "id": 10,
                    "name": "owned",
                    "mode": "observe",
                    "rule_id": "deadlock-v0.3",
                    "upstream_url": "https://example.invalid",
                    "owner_user_id": 100,
                    "read_only": False,
                    "created_at": "created",
                },
                20: {
                    "id": 20,
                    "name": "other",
                    "mode": "observe",
                    "rule_id": "deadlock-v0.3",
                    "upstream_url": "https://example.invalid",
                    "owner_user_id": 200,
                    "read_only": False,
                    "created_at": "created",
                },
            },
            "api_keys": {},
            "auth_events": [],
        }
        self.connection_patch = patch(
            "storage.accounts.get_connection",
            side_effect=lambda: FakeConnection(self.state),
        )
        self.connection_patch.start()

    def tearDown(self):
        self.connection_patch.stop()

    def test_mode_validation(self):
        self.assertEqual(accounts._validate_mode("observe"), "observe")
        self.assertEqual(accounts._validate_mode("BLOCK"), "block")
        with self.assertRaises(ValueError):
            accounts._validate_mode("warn")

    def test_email_normalization_is_case_insensitive(self):
        self.assertEqual(accounts._normalize_email(" User@Example.COM "), "user@example.com")

    def test_issue_key_returns_raw_once_but_stores_only_hash_and_prefix(self):
        raw, info = accounts.issue_api_key(10, 100, "demo key")

        self.assertTrue(raw.startswith("gk_"))
        parts = raw.split("_", 2)
        self.assertEqual(len(parts[1]), 8)
        self.assertGreaterEqual(len(parts[2]), 32)

        stored = self.state["api_keys"][info["id"]]
        self.assertNotEqual(stored["key_hash"], raw)
        self.assertEqual(stored["key_hash"], hashlib.sha256(raw.encode("utf-8")).hexdigest())
        self.assertEqual(stored["key_prefix"], parts[1])

        # No stored DB value or audit-event string should contain the raw key.
        self.assertNotIn(raw, repr(self.state))

    def test_verify_valid_key_returns_project_and_updates_last_used(self):
        raw, info = accounts.issue_api_key(10, 100, "demo key")

        project = accounts.verify_api_key(raw)

        self.assertIsNotNone(project)
        self.assertEqual(project["id"], 10)
        self.assertEqual(project["name"], "owned")
        self.assertEqual(self.state["api_keys"][info["id"]]["last_used_at"], "used")

    def test_verify_wrong_key_returns_none(self):
        raw, _ = accounts.issue_api_key(10, 100, "demo key")
        prefix = raw.split("_", 2)[1]
        wrong = f"gk_{prefix}_{'x' * 48}"

        self.assertIsNone(accounts.verify_api_key(wrong))

    def test_revoked_key_is_rejected(self):
        raw, info = accounts.issue_api_key(10, 100, "demo key")

        accounts.revoke_api_key(info["id"], 100)

        self.assertIsNone(accounts.verify_api_key(raw))
        self.assertIsNotNone(self.state["api_keys"][info["id"]]["revoked_at"])

    def test_other_users_project_is_treated_as_not_found(self):
        with self.assertRaisesRegex(LookupError, "project not found"):
            accounts.issue_api_key(20, 100, "should fail")

        with self.assertRaisesRegex(LookupError, "project not found"):
            accounts.set_project_mode(20, 100, "block")

    def test_other_users_key_is_treated_as_not_found(self):
        _, info = accounts.issue_api_key(10, 100, "owned key")

        with self.assertRaisesRegex(LookupError, "api key not found"):
            accounts.revoke_api_key(info["id"], 200)

    def test_set_project_mode_for_owner(self):
        accounts.set_project_mode(10, 100, "block")
        self.assertEqual(self.state["projects"][10]["mode"], "block")


if __name__ == "__main__":
    unittest.main()
