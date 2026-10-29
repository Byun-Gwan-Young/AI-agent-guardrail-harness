"""B1/I1 regressions. The real-Redis case is explicitly opt-in and writes only temporary keys."""
from __future__ import annotations

import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from storage.redis_adapter import RedisLiveAdapter
from storage.redis_state import RedisLiveStateStore
from test_storage_redis_state import FakeRedis


def snap(step, *, status="active", decision=None, sid="b1-session"):
    return {
        "schema_version": 1,
        "session_id": sid,
        "status": status,
        "mode": "observe",
        "step": step,
        "last_decision": decision,
        "stagnant_run": 0 if decision is not None else None,
        "updated_at": "2026-10-29T00:00:00+00:00",
        "ended_at": "2026-10-29T00:01:00+00:00" if status == "ended" else None,
    }


class RedisB1OfflineTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.cache = RedisLiveStateStore(
            self.redis, prefix="guardrail:test:b1", selected_rule_id="rule-A", ttl_seconds=60
        )
        self.adapter = RedisLiveAdapter(self.cache)

    def test_watch_conflict_forces_fresh_database_read_after_key_loss(self):
        calls = []

        def reader():
            calls.append(1)
            if len(calls) == 1:
                # Simulates a different writer changing and expiring the key
                # after this transaction began watching it.
                self.redis.fail_watch = 1
                return snap(2)
            return snap(10, status="ended")

        result = self.cache.reconcile_from_reader("b1-session", reader)
        self.assertEqual(len(calls), 2)
        self.assertEqual((result["status"], result["step"]), ("ended", 10))
        self.assertEqual(self.cache.get_session("b1-session")["status"], "ended")

    def test_get_state_does_not_reuse_outdated_read_on_watch_conflict(self):
        self.redis.fail_watch = 1
        with patch("storage.redis_adapter.read_live_snapshot", side_effect=[
            snap(2), snap(10, status="ended")
        ]) as reader:
            result = self.adapter.get_state("b1-session")
        self.assertEqual(reader.call_count, 2)
        self.assertEqual((result["status"], result["step"]), ("ended", 10))

    def test_refresh_cache_does_not_reuse_outdated_read_on_watch_conflict(self):
        self.redis.fail_watch = 1
        with patch("storage.redis_adapter.read_live_snapshot", side_effect=[
            snap(2), snap(10, status="ended")
        ]) as reader:
            self.adapter._refresh_cache("b1-session")
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(self.cache.get_session("b1-session")["status"], "ended")

    def test_selected_rules_use_disjoint_redis_keys_and_verdicts(self):
        a = self.cache
        b = RedisLiveStateStore(self.redis, prefix=a.prefix, selected_rule_id="rule-B")
        unselected = RedisLiveStateStore(self.redis, prefix=a.prefix)
        self.assertNotEqual(a._key("b1-session"), b._key("b1-session"))
        self.assertNotEqual(a._key("b1-session"), unselected._key("b1-session"))
        a.reconcile_snapshot(snap(2, decision="CONTINUE"))
        self.assertIsNone(b.get_session("b1-session"))
        b.reconcile_snapshot(snap(2, decision="STOP"))
        self.assertEqual(a.get_session("b1-session")["last_decision"], "CONTINUE")
        self.assertEqual(b.get_session("b1-session")["last_decision"], "STOP")
        self.assertIsNone(unselected.get_session("b1-session"))


@unittest.skipUnless(os.getenv("GUARDRAIL_REDIS_TEST_URL"),
                     "Opt-in real Redis test needs GUARDRAIL_REDIS_TEST_URL")
class RedisB1RealTests(unittest.TestCase):
    def test_real_redis_key_removed_after_fresh_end_forces_reread(self):
        # PostgreSQL reader is simulated here; WATCH and set/delete use Redis.
        from storage.redis_client import get_redis_client

        url = os.environ["GUARDRAIL_REDIS_TEST_URL"]
        clients = [get_redis_client(url), get_redis_client(url)]
        prefix = "guardrail:redis-b1-test:" + uuid.uuid4().hex
        stores = [RedisLiveStateStore(c, prefix=prefix, selected_rule_id="rule-A", ttl_seconds=30)
                  for c in clients]
        sid = "b1-session"
        key = stores[0]._key(sid)
        stale_read = Event()
        continue_reader = Event()
        committed = [snap(2)]
        reads = []

        def reader():
            result = committed[0]
            reads.append(result["step"])
            if len(reads) == 1:
                stale_read.set()
                if not continue_reader.wait(5):
                    raise TimeoutError("Test writer did not resume reader")
            return result

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(stores[0].reconcile_from_reader, sid, reader)
                self.assertTrue(stale_read.wait(5))
                committed[0] = snap(10, status="ended")
                stores[1].reconcile_snapshot(committed[0])
                clients[1].delete(key)  # Simulate TTL expiry/cache loss.
                continue_reader.set()
                result = future.result(timeout=10)
            self.assertGreaterEqual(len(reads), 2)
            self.assertEqual((result["status"], result["step"]), ("ended", 10))
            self.assertEqual(stores[1].get_session(sid)["status"], "ended")
        finally:
            continue_reader.set()
            clients[0].delete(key)


if __name__ == "__main__":
    unittest.main()
