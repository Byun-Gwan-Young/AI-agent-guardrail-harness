"""Offline tests for the separate Storage metadata contract (no database)."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storage import default_live_scenario as defaults
from storage.import_utils import scenario_payload, sha256_file
from storage import live
from storage.redis_adapter import RedisLiveAdapter
from test_storage_live import FakeConnection as LiveFakeConnection


class FakeConnection:
    """Small strict SQL double; concurrency is tested in real PostgreSQL."""
    def __init__(self, state):
        self.state = state
        self.row = None

    def __enter__(self):
        self.before = copy.deepcopy(self.state["scenarios"])
        return self

    def __exit__(self, kind, *_):
        if kind:
            self.state["scenarios"] = self.before
        return False

    def cursor(self):
        outer = self
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params): outer.execute(sql, params)
            def fetchone(self): return outer.row
        return Cursor()

    def execute(self, sql, params):
        q = " ".join(sql.split())
        self.state["sql"].append(q)
        self.row = None
        if q == "SELECT account_status FROM users WHERE id = %s FOR SHARE":
            status = self.state["users"].get(params[0])
            self.row = (status,) if status is not None else None
        elif q.startswith("SELECT id FROM projects"):
            p = self.state["projects"].get(params[0])
            if p and p == (params[1], False): self.row = (params[0],)
        elif q.startswith("INSERT INTO scenarios"):
            if "DO NOTHING" not in q or "DO UPDATE" in q:
                raise AssertionError("Immutable insert contract violated")
            key = tuple(params[:3])
            if key not in self.state["scenarios"]:
                self.state["scenarios"][key] = (
                    len(self.state["scenarios"]) + 1, *params[3:6], copy.deepcopy(params[6].obj)
                )
        elif q.startswith("SELECT id, schema_version, name, task_kind, config FROM scenarios"):
            if self.state.get("fail_after_insert"):
                raise RuntimeError("injected database failure")
            self.row = self.state["scenarios"].get(tuple(params))
        else:
            raise AssertionError("Unexpected SQL: " + q)


class DefaultLiveScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "default.yaml"
        self.raw = defaults.DEFAULT_LIVE_SCENARIO_PATH.read_bytes()
        self.path.write_bytes(self.raw)
        self.state = {"users": {1: "active", 2: "active", 3: "pending_deletion"},
                      "projects": {11: (1, False), 12: (1, False), 21: (2, False),
                                   31: (3, False), 40: (1, True), 50: (None, False)},
                      "scenarios": {}, "sql": []}
        self.addCleanup(patch.stopall)
        patch.object(defaults, "DEFAULT_LIVE_SCENARIO_PATH", self.path).start()
        self.connect = patch.object(defaults, "get_connection", side_effect=lambda: FakeConnection(self.state)).start()

    def ensure(self, project=11, user=1):
        return defaults.ensure_default_live_scenario(project, user_id=user)

    def test_create_repeat_and_other_project(self):
        first = self.ensure()
        before = copy.deepcopy(self.state["scenarios"])
        self.assertEqual(self.ensure(), first)
        self.assertEqual(self.state["scenarios"], before)
        self.assertNotEqual(self.ensure(12)["scenario_id"], first["scenario_id"])
        self.assertEqual(set(first), {"scenario_id", "scenario_key", "scenario_hash", "schema_version"})

    def test_hash_uses_original_bytes_and_comment_change_creates_version(self):
        first = self.ensure()
        self.assertEqual(first["scenario_hash"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(first["scenario_hash"], sha256_file(self.path))
        self.path.write_bytes(self.raw + b"# new release bytes\n")
        second = self.ensure()
        self.assertNotEqual(first["scenario_id"], second["scenario_id"])
        self.assertEqual(len(self.state["scenarios"]), 2)

    def test_definition_revision_registers_new_version(self):
        first = self.ensure()
        self.path.write_bytes(self.raw.replace(b"definition_version: 1", b"definition_version: 2"))
        self.assertNotEqual(first["scenario_id"], self.ensure()["scenario_id"])

    def test_same_hash_different_definition_never_overwritten(self):
        self.ensure()
        for index, bad in [(1, "scenario-v2"), (2, "changed name"), (3, "dialogue"),
                           (4, {"definition_version": True})]:
            key, original = next(iter(self.state["scenarios"].items()))
            changed = list(original); changed[index] = bad
            self.state["scenarios"][key] = tuple(changed)
            with self.subTest(index=index), self.assertRaises(ValueError): self.ensure()
            self.assertEqual(self.state["scenarios"][key], tuple(changed))
            self.state["scenarios"][key] = original

    def test_config_boolean_is_not_integer_revision(self):
        self.ensure()
        key, row = next(iter(self.state["scenarios"].items()))
        row[4]["definition_version"] = True
        with self.assertRaises(ValueError): self.ensure()

    def test_unowned_missing_read_only_and_ownerless_rejected(self):
        for project in (999, 21, 40, 50):
            with self.subTest(project=project), self.assertRaises(LookupError): self.ensure(project)
        self.assertFalse(self.state["scenarios"])

    def test_pending_and_missing_user_rejected_even_on_repeat(self):
        with self.assertRaises(RuntimeError): self.ensure(31, 3)
        with self.assertRaises(LookupError): self.ensure(11, 999)
        self.ensure()
        self.state["users"][1] = "pending_deletion"
        with self.assertRaises(RuntimeError): self.ensure()
        self.assertEqual(len(self.state["scenarios"]), 1)

    def test_invalid_ids_and_missing_authenticated_identity(self):
        for value in (True, 0, -1, "11", None, 2**63):
            with self.subTest(value=value), self.assertRaises(ValueError): self.ensure(value)
            with self.subTest(user=value), self.assertRaises(ValueError): self.ensure(user=value)
        with self.assertRaises(TypeError): defaults.ensure_default_live_scenario(11)
        self.connect.assert_not_called()

    def test_user_before_project_before_insert(self):
        self.ensure()
        q = self.state["sql"]
        self.assertIn("FROM users", q[0]); self.assertIn("FOR SHARE", q[0])
        self.assertIn("FROM projects", q[1]); self.assertIn("FOR SHARE", q[1])
        self.assertIn("INSERT INTO scenarios", q[2])

    def test_failure_after_insert_rolls_back(self):
        self.state["fail_after_insert"] = True
        with self.assertRaises(RuntimeError): self.ensure()
        self.assertFalse(self.state["scenarios"])

    def test_invalid_yaml_schema_fields_and_raw_text_rejected_before_db(self):
        candidates = [b"[", b"[]", b"", b"\xff", b"x" * 16385,
                      self.raw.replace(b"storage-live-v1", b"scenario-v2"),
                      self.raw.replace(b"task_kind: live", b"task_kind: dialogue"),
                      self.raw.replace(b"definition_version: 1", b"definition_version: true"),
                      self.raw + b"content: raw model text\n",
                      self.raw + b"api_key: not-a-real-key\n",
                      self.raw + b"scenario_id: duplicate\n",
                      self.raw.replace(b"\n", b"\r\n")]
        for raw in candidates:
            self.path.write_bytes(raw)
            with self.subTest(raw=raw[:25]), self.assertRaises(ValueError): self.ensure()
        self.connect.assert_not_called()

    def test_metadata_is_separate_from_experiment_import_contract(self):
        self.assertEqual(self.ensure()["schema_version"], "storage-live-v1")
        run = Path(self.temp.name)
        (run / "scenario.yaml").write_bytes(self.raw)
        with self.assertRaises(ValueError): scenario_payload(run, {})

    def test_existing_explicit_import_payload_keeps_hash_policy(self):
        run = Path(self.temp.name)
        raw = b"schema_version: scenario-v2\nscenario_id: explicit\ntitle: Explicit\ntask_kind: dialogue\n"
        (run / "scenario.yaml").write_bytes(raw)
        payload = scenario_payload(run, {})
        self.assertEqual(payload["scenario_key"], "explicit")
        self.assertEqual(payload["scenario_hash"], hashlib.sha256(raw).hexdigest())

    def live_state(self):
        # Bridge the actual default-registration results into the established
        # live SQL double; no production start/adapter function is mocked.
        return {
            "users": {uid: {"account_status": status} for uid, status in self.state["users"].items()},
            "projects": {pid: {"id": pid, "owner_user_id": owner, "read_only": readonly,
                               "mode": "observe", "provider": "openai"}
                         for pid, (owner, readonly) in self.state["projects"].items()},
            "scenarios": {row[0]: {"id": row[0], "project_id": key[0],
                                    "scenario_key": key[1], "scenario_hash": key[2]}
                          for key, row in self.state["scenarios"].items()},
            "sessions": {},
        }

    def test_returned_identity_starts_live_and_old_reference_survives_upgrade(self):
        first = self.ensure()
        state = self.live_state()
        args = (11, "default-live", first["scenario_key"], first["scenario_hash"], "observe", "test-model", {})
        with patch.object(live, "get_connection", side_effect=lambda: LiveFakeConnection(state)):
            self.assertEqual(live.start_live_session(*args)["scenario_id"], first["scenario_id"])
            self.path.write_bytes(self.raw + b"# another definition release\n")
            second = self.ensure()
            state["scenarios"].update(self.live_state()["scenarios"])
            self.assertEqual(live.start_live_session(*args)["scenario_id"], first["scenario_id"])
        self.assertNotEqual(second["scenario_id"], first["scenario_id"])
        self.assertEqual(state["sessions"]["default-live"]["validity"], "not_counted")
        self.assertEqual(state["scenarios"][first["scenario_id"]]["project_id"], 11)

    def test_withdrawal_between_ensure_and_start_rejects_new_session(self):
        first = self.ensure()
        state = self.live_state(); state["users"][1]["account_status"] = "pending_deletion"
        with patch.object(live, "get_connection", side_effect=lambda: LiveFakeConnection(state)):
            with self.assertRaises(RuntimeError):
                live.start_live_session(11, "default-live", first["scenario_key"], first["scenario_hash"],
                                        "observe", "test-model", {})
        self.assertFalse(state["sessions"])
        self.assertEqual(len(self.state["scenarios"]), 1)

    def test_default_identity_adapter_failure_preserves_live_result(self):
        first = self.ensure(); state = self.live_state()
        class BrokenCache:
            selected_rule_id = None
            def reconcile_from_reader(self, *_): raise ConnectionError("cache offline")
        with patch.object(live, "get_connection", side_effect=lambda: LiveFakeConnection(state)):
            with self.assertLogs("storage.redis_adapter", level="WARNING"):
                result = RedisLiveAdapter(BrokenCache()).start_live_session(
                    11, "default-live", first["scenario_key"], first["scenario_hash"], "observe", "test-model", {})
        self.assertEqual(result["scenario_id"], first["scenario_id"])
        self.assertEqual(state["sessions"]["default-live"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
