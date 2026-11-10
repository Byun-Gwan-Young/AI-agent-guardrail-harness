"""Opt-in real PostgreSQL tests, isolated in a uniquely named test schema.

Set GUARDRAIL_WAYB_TEST=1 and GUARDRAIL_WAYB_TEST_DB_URL to a DISPOSABLE DB.
No GUARDRAIL_DB_URL/.env fallback. Creates and drops only its random schema.
Requires CREATE SCHEMA rights. The original public schema is never selected.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
from threading import Barrier, Event
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from storage import accounts, default_live_scenario as defaults, live, redis_adapter
from storage.redis_adapter import RedisLiveAdapter


@unittest.skipUnless(os.getenv("GUARDRAIL_WAYB_TEST") == "1" and os.getenv("GUARDRAIL_WAYB_TEST_DB_URL"),
                     "Requires GUARDRAIL_WAYB_TEST=1 and a disposable GUARDRAIL_WAYB_TEST_DB_URL")
class DefaultLivePostgresTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ["GUARDRAIL_WAYB_TEST_DB_URL"]
        self.schema = "wayb_test_" + uuid.uuid4().hex
        self.pool = ThreadPoolExecutor(max_workers=6)
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.addCleanup(self.pool.shutdown, wait=True)
        for module in (defaults, accounts, live, redis_adapter):
            p = patch.object(module, "get_connection", self.connect)
            p.start(); self.addCleanup(p.stop)
        with self.connect() as conn:
            conn.execute((Path(__file__).resolve().parents[1] / "storage/schema.sql").read_text(encoding="utf-8"))
            self.user = conn.execute("INSERT INTO users (google_sub,email) VALUES ('owner','owner@example.test') RETURNING id").fetchone()[0]
            self.other = conn.execute("INSERT INTO users (google_sub,email) VALUES ('other','other@example.test') RETURNING id").fetchone()[0]
            self.project = self.new_project(conn, self.user)
            self.project2 = self.new_project(conn, self.user)
            self.other_project = self.new_project(conn, self.other)

    def connect(self, **kwargs):
        return psycopg.connect(self.dsn, options=f"-c search_path={self.schema} -c statement_timeout=8000 -c lock_timeout=5000", **kwargs)

    def cleanup_schema(self):
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def new_project(self, conn, owner, read_only=False):
        return conn.execute("""INSERT INTO projects(name,mode,rule_id,provider,upstream_url,owner_user_id,read_only)
            VALUES ('test','observe','deadlock-v0.3','openai','https://api.openai.com/v1',%s,%s) RETURNING id""",
                            (owner, read_only)).fetchone()[0]

    def ensure(self, project=None, user=None):
        return defaults.ensure_default_live_scenario(self.project if project is None else project,
                                                     user_id=self.user if user is None else user)

    def count(self):
        with self.connect() as conn:
            return conn.execute("SELECT count(*) FROM scenarios").fetchone()[0]

    def start(self, record, sid="test-live", project=None):
        return live.start_live_session(self.project if project is None else project, sid,
                                       record["scenario_key"], record["scenario_hash"], "observe", "test-model", {})

    def wait_blocked(self, pid):
        deadline = time.monotonic() + 3
        with self.connect() as conn:
            while time.monotonic() < deadline:
                if conn.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", (pid,)).fetchone()[0]:
                    return
                time.sleep(.02)
        self.fail("Expected PostgreSQL row-lock wait was not observed")

    def test_create_repeat_other_project_and_live_linkage(self):
        first = self.ensure()
        with self.connect() as conn:
            before = conn.execute("SELECT xmin::text,created_at FROM scenarios WHERE id=%s", (first["scenario_id"],)).fetchone()
        self.assertEqual(first, self.ensure())
        other = self.ensure(self.project2)
        self.assertNotEqual(first["scenario_id"], other["scenario_id"])
        result = self.start(first)
        self.assertEqual((result["scenario_id"], result["source"]), (first["scenario_id"], "live"))
        with self.connect() as conn:
            self.assertEqual(before, conn.execute("SELECT xmin::text,created_at FROM scenarios WHERE id=%s", (first["scenario_id"],)).fetchone())
            row = conn.execute("SELECT sc.project_id,s.validity FROM sessions s JOIN scenarios sc ON s.scenario_id=sc.id WHERE s.id='test-live'").fetchone()
            self.assertEqual(row, (self.project, "not_counted"))

    def test_yaml_new_version_preserves_old_session(self):
        first = self.ensure(); self.start(first)
        raw = defaults.DEFAULT_LIVE_SCENARIO_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "v2.yaml"
            path.write_bytes(raw.replace(b"definition_version: 1", b"definition_version: 2"))
            with patch.object(defaults, "DEFAULT_LIVE_SCENARIO_PATH", path): second = self.ensure()
        self.assertNotEqual(first["scenario_id"], second["scenario_id"])
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.start(first)["scenario_id"], first["scenario_id"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT scenario_id FROM sessions WHERE id='test-live'").fetchone()[0], first["scenario_id"])

    def test_conflicting_definition_is_preserved_and_rejected(self):
        first = self.ensure()
        with self.connect() as conn:
            conn.execute("UPDATE scenarios SET name='corrupted' WHERE id=%s", (first["scenario_id"],))
        with self.assertRaises(ValueError): self.ensure()
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT name FROM scenarios WHERE id=%s", (first["scenario_id"],)).fetchone()[0], "corrupted")

    def test_concurrent_creation_has_one_row_and_one_identity(self):
        gate = Barrier(4)
        def run():
            gate.wait(timeout=5)
            return self.ensure()["scenario_id"]
        futures = [self.pool.submit(run) for _ in range(4)]
        ids = [f.result(timeout=10) for f in futures]
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.count(), 1)

    def test_permissions_readonly_ownerless_and_missing(self):
        with self.connect() as conn:
            readonly = self.new_project(conn, self.user, True)
            ownerless = self.new_project(conn, None)
        for p in (self.other_project, readonly, ownerless, 9_000_000_000):
            with self.subTest(project=p), self.assertRaises(LookupError): self.ensure(p)
        with self.assertRaises(LookupError): self.ensure(user=9_000_000_000)
        self.assertEqual(self.count(), 0)

    def test_withdrawal_first_waits_then_rejects_pending(self):
        ready = Event(); worker_pid = []
        def connect_worker():
            conn = self.connect(); worker_pid.append(conn.info.backend_pid); ready.set(); return conn
        with self.connect() as holder:
            holder.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (self.user,))
            with patch.object(defaults, "get_connection", connect_worker):
                f = self.pool.submit(self.ensure)
                self.assertTrue(ready.wait(3)); self.wait_blocked(worker_pid[0])
                holder.execute("""UPDATE users SET account_status='pending_deletion',
                    deletion_requested_at=CURRENT_TIMESTAMP, deletion_due_at=CURRENT_TIMESTAMP + INTERVAL '30 days'
                    WHERE id=%s""", (self.user,))
                holder.commit()
                with self.assertRaises(RuntimeError): f.result(timeout=8)
        self.assertEqual(self.count(), 0)

    def test_registration_first_holds_user_lock_until_commit(self):
        locked, release, deleting = Event(), Event(), Event()
        deletion_pid = []
        self.addCleanup(release.set)
        @contextmanager
        def pausing_connection():
            with self.connect() as conn:
                class C:
                    @contextmanager
                    def cursor(inner):
                        with conn.cursor() as cur:
                            class Cursor:
                                def execute(inner, query, params):
                                    cur.execute(query, params)
                                    if "SELECT account_status FROM users" in query:
                                        locked.set()
                                        if not release.wait(4): raise TimeoutError("registration test not released")
                                def fetchone(inner): return cur.fetchone()
                            yield Cursor()
                yield C()
        def deletion_connection():
            conn = self.connect(); deletion_pid.append(conn.info.backend_pid); deleting.set(); return conn
        with patch.object(defaults, "get_connection", pausing_connection), patch.object(accounts, "get_connection", deletion_connection):
            f = self.pool.submit(self.ensure)
            try:
                self.assertTrue(locked.wait(3))
                d = self.pool.submit(accounts.request_account_deletion, self.user)
                self.assertTrue(deleting.wait(3)); self.wait_blocked(deletion_pid[0])
            finally:
                release.set()
            self.assertGreater(f.result(timeout=8)["scenario_id"], 0)
            self.assertEqual(d.result(timeout=8)["account_status"], "pending_deletion")
        self.assertEqual(self.count(), 1)
        with self.assertRaises(RuntimeError): self.ensure()

    def test_project_ownership_change_while_waiting_rejects(self):
        ready = Event(); worker_pid = []
        def connect_worker():
            conn = self.connect(); worker_pid.append(conn.info.backend_pid); ready.set(); return conn
        with self.connect() as holder:
            holder.execute("SELECT id FROM projects WHERE id=%s FOR UPDATE", (self.project,))
            with patch.object(defaults, "get_connection", connect_worker):
                f = self.pool.submit(self.ensure)
                self.assertTrue(ready.wait(3)); self.wait_blocked(worker_pid[0])
                holder.execute("UPDATE projects SET owner_user_id=%s WHERE id=%s", (self.other, self.project))
                holder.commit()
                with self.assertRaises(LookupError): f.result(timeout=8)
        self.assertEqual(self.count(), 0)

    def test_sql_failure_after_insert_rolls_back(self):
        @contextmanager
        def failing_connection():
            with self.connect() as conn:
                class C:
                    @contextmanager
                    def cursor(inner):
                        with conn.cursor() as cur:
                            class Cursor:
                                def execute(inner, query, params):
                                    if "SELECT id, schema_version" in query: cur.execute("SELECT 1/0")
                                    cur.execute(query, params)
                                def fetchone(inner): return cur.fetchone()
                            yield Cursor()
                yield C()
        with patch.object(defaults, "get_connection", failing_connection):
            with self.assertRaises(psycopg.Error): self.ensure()
        self.assertEqual(self.count(), 0)

    def test_withdraw_restore_purge_and_other_user_preserved(self):
        first = self.ensure(); self.start(first)
        other = self.ensure(self.other_project, self.other)
        accounts.request_account_deletion(self.user)
        with self.assertRaises(RuntimeError): self.ensure()
        # The new helper must not change the existing exact-start retry policy.
        self.assertEqual(self.start(first)["scenario_id"], first["scenario_id"])
        accounts.restore_account(self.user)
        self.assertEqual(self.ensure(), first)
        accounts.request_account_deletion(self.user)
        with self.connect() as conn:
            conn.execute("""UPDATE users SET deletion_requested_at=CURRENT_TIMESTAMP-INTERVAL '31 days',
                 deletion_due_at=CURRENT_TIMESTAMP-INTERVAL '1 day' WHERE id=%s""", (self.user,))
        accounts.purge_account(self.user)
        with self.assertRaises(LookupError): self.ensure()
        self.assertEqual(self.ensure(self.other_project, self.other), other)

    def test_explicit_scenario_and_adapter_outage_contract(self):
        with self.connect() as conn:
            explicit = conn.execute("""INSERT INTO scenarios(project_id,scenario_key,scenario_hash,schema_version,name,task_kind,config)
                VALUES (%s,'explicit','hash-explicit','scenario-v2','Explicit','dialogue',%s) RETURNING id""",
                                    (self.project, Jsonb({"schema_version": "scenario-v2"}))).fetchone()[0]
        started = self.start({"scenario_key": "explicit", "scenario_hash": "hash-explicit"}, sid="explicit-live")
        self.assertEqual(started["scenario_id"], explicit)
        class OfflineCache:
            selected_rule_id = None
            def reconcile_from_reader(self, *_): raise ConnectionError("simulated Redis outage")
        identity = self.ensure()
        with self.assertLogs("storage.redis_adapter", level="WARNING"):
            result = RedisLiveAdapter(OfflineCache()).start_live_session(
                self.project, "default-adapter", identity["scenario_key"], identity["scenario_hash"],
                "observe", "test-model", {})
        self.assertEqual(result["scenario_id"], identity["scenario_id"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 2)

    @unittest.skipUnless(os.getenv("GUARDRAIL_REDIS_TEST_URL"), "Also requires a disposable GUARDRAIL_REDIS_TEST_URL")
    def test_default_identity_with_real_redis_adapter(self):
        from storage.redis_client import get_redis_client
        from storage.redis_state import RedisLiveStateStore
        client = get_redis_client(os.environ["GUARDRAIL_REDIS_TEST_URL"])
        cache = RedisLiveStateStore(client, prefix="wayb:test:" + uuid.uuid4().hex,
                                    ttl_seconds=30, selected_rule_id="deadlock-v0.3")
        sid = "wayb-live"
        self.addCleanup(client.close)
        self.addCleanup(client.delete, cache._key(sid))
        adapter = RedisLiveAdapter(cache)
        identity = self.ensure()
        started = adapter.start_live_session(self.project, sid, identity["scenario_key"],
                                             identity["scenario_hash"], "observe", "test-model", {})
        self.assertEqual(started["scenario_id"], identity["scenario_id"])
        adapter.add_observation(sid, 1, "agent", {"structured": True})
        self.assertEqual(cache.get_session(sid)["step"], 1)
        client.delete(cache._key(sid))
        self.assertEqual(adapter.get_state(sid)["step"], 1)
        adapter.end_live_session(sid, "completed", 1, 0, None)
        self.assertEqual(cache.get_session(sid)["status"], "ended")


if __name__ == "__main__":
    unittest.main()
