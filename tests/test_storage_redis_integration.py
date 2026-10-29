"""Opt-in real Redis test. Set GUARDRAIL_REDIS_TEST_URL to run locally.

Uses a unique key prefix and deletes its own test records on completion.
Never aims this test at the production Redis instance.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
import uuid

from storage.redis_client import get_redis_client
from storage.redis_state import RedisLiveStateStore, WatchError


@unittest.skipUnless(os.environ.get("GUARDRAIL_REDIS_TEST_URL"),
                     "Set GUARDRAIL_REDIS_TEST_URL for an opt-in real Redis integration test")
class RedisRealIntegrationTest(unittest.TestCase):
    def test_real_redis_round_trip_and_separate_instance(self):
        client = get_redis_client(os.environ["GUARDRAIL_REDIS_TEST_URL"])
        self.assertTrue(client.ping())
        prefix = "guardrail:redis-test:" + uuid.uuid4().hex
        name = "test-session"
        key = prefix + ":" + name
        store1 = RedisLiveStateStore(client, prefix=prefix, ttl_seconds=90)
        store2 = RedisLiveStateStore(get_redis_client(os.environ["GUARDRAIL_REDIS_TEST_URL"]),
                                     prefix=prefix, ttl_seconds=90)
        try:
            store1.start_session(name, "observe")
            self.assertEqual(store2.get_session(name)["step"], 0)
            store1.record_step(name, 1)
            store2.record_judgement(name, 1, "CONTINUE", stagnant_run=0)
            result = store1.get_session(name)
            self.assertEqual((result["status"], result["step"], result["last_decision"]),
                             ("active", 1, "CONTINUE"))
            with self.assertRaises(ValueError):
                store1.record_step(name, 0)
            self.assertEqual(store1.end_session(name)["status"], "ended")
            self.assertEqual(store2.get_session(name)["status"], "ended")
            self.assertGreater(client.ttl(key), 0)
        finally:
            client.delete(key)

    def test_atomic_start_with_two_clients(self):
        url = os.environ["GUARDRAIL_REDIS_TEST_URL"]
        prefix = "guardrail:redis-test:" + uuid.uuid4().hex
        key = prefix + ":same"
        clients = [get_redis_client(url) for _ in range(2)]
        stores = [RedisLiveStateStore(c, prefix=prefix, ttl_seconds=30) for c in clients]
        gate = Barrier(2)

        def start(store):
            gate.wait(timeout=5)
            try:
                store.start_session("same", "observe")
                return "created"
            except ValueError as exc:
                self.assertIn("already exists", str(exc))
                return "duplicate"

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(start, store) for store in stores]
                results = [future.result(timeout=10) for future in futures]
            self.assertCountEqual(results, ["created", "duplicate"])
            self.assertEqual(stores[0].get_session("same")["status"], "active")
        finally:
            clients[0].delete(key)

    def test_end_cannot_be_undone_by_concurrent_step(self):
        url = os.environ["GUARDRAIL_REDIS_TEST_URL"]
        prefix = "guardrail:redis-test:" + uuid.uuid4().hex
        key = prefix + ":same"
        stores = [RedisLiveStateStore(get_redis_client(url), prefix=prefix, ttl_seconds=30)
                  for _ in range(2)]
        stores[0].start_session("same", "observe")
        gate = Barrier(2)

        def advance():
            gate.wait(timeout=5)
            try:
                stores[0].record_step("same", 1)
            except ValueError as exc:
                self.assertIn("ended", str(exc))

        def end():
            gate.wait(timeout=5)
            return stores[1].end_session("same")

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                a = executor.submit(advance)
                b = executor.submit(end)
                a.result(timeout=10)
                self.assertEqual(b.result(timeout=10)["status"], "ended")
            self.assertEqual(stores[0].get_session("same")["status"], "ended")
            with self.assertRaises(ValueError):
                stores[1].record_step("same", 2)
        finally:
            stores[0].client.delete(key)

    def test_watch_detects_other_client_write(self):
        url = os.environ["GUARDRAIL_REDIS_TEST_URL"]
        prefix = "guardrail:redis-test:" + uuid.uuid4().hex
        key = prefix + ":same"
        client1, client2 = get_redis_client(url), get_redis_client(url)
        store = RedisLiveStateStore(client2, prefix=prefix, ttl_seconds=30)
        try:
            store.start_session("same", "observe")
            with client1.pipeline() as pipe:
                pipe.watch(key)
                stale_payload = pipe.get(key)
                store.record_step("same", 1)
                pipe.multi()
                pipe.set(key, stale_payload, ex=30)
                with self.assertRaises(WatchError):
                    pipe.execute()
            self.assertEqual(store.get_session("same")["step"], 1)
        finally:
            client1.delete(key)

    def test_expiry_is_cache_miss_not_recreated_by_update(self):
        url = os.environ["GUARDRAIL_REDIS_TEST_URL"]
        prefix = "guardrail:redis-test:" + uuid.uuid4().hex
        client = get_redis_client(url)
        store = RedisLiveStateStore(client, prefix=prefix, ttl_seconds=1)
        key = prefix + ":short"
        try:
            store.start_session("short", "observe")
            time.sleep(1.3)
            self.assertIsNone(store.get_session("short"))
            with self.assertRaises(LookupError):
                store.record_step("short", 1)
        finally:
            client.delete(key)


if __name__ == "__main__":
    unittest.main()
