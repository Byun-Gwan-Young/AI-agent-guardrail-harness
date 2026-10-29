"""Explicit opt-in real Redis CAS/rehydration tests; no PostgreSQL needed."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import time
import unittest
import uuid

from storage.redis_client import get_redis_client
from storage.redis_state import RedisLiveStateStore


@unittest.skipUnless(os.getenv('GUARDRAIL_REDIS_TEST_URL'),
                     'Opt-in real Redis test requires GUARDRAIL_REDIS_TEST_URL')
class RedisRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        url = os.environ['GUARDRAIL_REDIS_TEST_URL']
        self.clients = [get_redis_client(url) for _ in range(2)]
        self.prefix = 'guardrail:redis-recover-test:' + uuid.uuid4().hex
        self.stores = [RedisLiveStateStore(client, prefix=self.prefix, ttl_seconds=60,
                                          selected_rule_id='deadlock-v0.3')
                       for client in self.clients]
        self.sid = 'test-1'
        self.key = self.stores[0]._key(self.sid)

    def tearDown(self):
        self.clients[0].delete(self.key)

    def snapshot(self, step, *, status='active', decision=None):
        return {'schema_version': 1, 'session_id': self.sid, 'status': status, 'mode': 'observe',
                'step': step, 'last_decision': decision,
                'stagnant_run': 0 if decision else None, 'updated_at': '2026-10-29T00:00:00+00:00',
                'ended_at': '2026-10-29T00:01:00+00:00' if status == 'ended' else None}

    def test_two_clients_cannot_rewind_on_concurrent_cache_rebuild(self):
        gate = Barrier(2)
        def restore(store, step):
            gate.wait(timeout=5)
            return store.reconcile_snapshot(self.snapshot(step))
        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(restore, self.stores[0], 2)
            b = executor.submit(restore, self.stores[1], 10)
            a.result(timeout=10)
            b.result(timeout=10)
        self.assertEqual(self.stores[0].get_session(self.sid)['step'], 10)

    def test_late_active_restore_never_reopens_ended_session(self):
        self.stores[0].reconcile_snapshot(self.snapshot(7, status='ended'))
        self.stores[1].reconcile_snapshot(self.snapshot(6))
        self.assertEqual(self.stores[0].get_session(self.sid)['status'], 'ended')

    def test_expired_key_uses_verified_snapshot_instead_of_new_step_zero(self):
        short = RedisLiveStateStore(self.clients[0], prefix=self.prefix, ttl_seconds=1,
                                    selected_rule_id='deadlock-v0.3')
        short.reconcile_snapshot(self.snapshot(10, decision='CONTINUE'))
        time.sleep(1.3)
        self.assertIsNone(short.get_session(self.sid))
        self.assertEqual(short.reconcile_snapshot(self.snapshot(10, decision='CONTINUE'))['step'], 10)
        self.assertEqual(short.get_session(self.sid)['last_decision'], 'CONTINUE')


if __name__ == '__main__':
    unittest.main()
