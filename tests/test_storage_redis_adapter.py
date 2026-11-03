"""Offline M1/M2 adapter tests: no external PostgreSQL/Redis required."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from storage.redis_adapter import RedisLiveAdapter, read_live_snapshot
from storage.redis_state import RedisLiveStateStore
from test_storage_redis_state import FakeRedis


def snapshot(step=0, status="active", decision=None, mode="observe", sid="test-1"):
    return {
        "schema_version": 1, "session_id": sid, "status": status, "mode": mode,
        "step": step, "last_decision": decision,
        "stagnant_run": 0 if decision is not None else None,
        "updated_at": "2026-10-29T00:00:00+00:00",
        "ended_at": "2026-10-29T00:01:00+00:00" if status == "ended" else None,
    }


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.cache = RedisLiveStateStore(self.redis, ttl_seconds=60, prefix="guardrail:test:adapter",
                                         selected_rule_id="deadlock-v0.3")
        self.adapter = RedisLiveAdapter(self.cache)

    def test_real_dotted_rule_id_is_accepted(self):
        self.assertEqual(self.cache.selected_rule_id, "deadlock-v0.3")
        self.cache.start_session("test-1", "observe")
        self.cache.record_step("test-1", 1)
        self.assertIsNone(self.cache.record_judgement("test-1", 1, "CONTINUE", rule_id="other-rule")["last_decision"])
        self.assertEqual(self.cache.record_judgement("test-1", 1, "CONTINUE", rule_id="deadlock-v0.3")["last_decision"], "CONTINUE")

    def test_cache_restored_from_authoritative_snapshot_not_start(self):
        with patch('storage.redis_adapter.read_live_snapshot', return_value=snapshot(step=10, decision="CONTINUE")):
            self.assertEqual(self.adapter.get_state("test-1")["step"], 10)
        self.assertEqual(self.cache.get_session("test-1")["step"], 10)
        self.assertEqual(self.cache.get_session("test-1")["last_decision"], "CONTINUE")

    def test_late_rebuild_cannot_replace_newer_step(self):
        self.cache.reconcile_snapshot(snapshot(step=10))
        self.cache.reconcile_snapshot(snapshot(step=2, decision="STOP"))
        self.assertEqual(self.cache.get_session("test-1")["step"], 10)
        self.assertIsNone(self.cache.get_session("test-1")["last_decision"])

    def test_stale_active_rebuild_cannot_undo_end(self):
        self.cache.reconcile_snapshot(snapshot(step=10, status="ended"))
        self.cache.reconcile_snapshot(snapshot(step=5))
        self.assertEqual(self.cache.get_session("test-1")["status"], "ended")

    def test_same_step_older_read_does_not_erase_new_judgement(self):
        self.cache.reconcile_snapshot(snapshot(step=3, decision="STOP"))
        self.cache.reconcile_snapshot(snapshot(step=3))
        self.assertEqual(self.cache.get_session("test-1")["last_decision"], "STOP")

    def test_selected_rule_late_judgement_never_rolls_step_back(self):
        self.cache.reconcile_snapshot(snapshot(step=11))
        self.cache.record_judgement("test-1", 10, "STOP", rule_id="deadlock-v0.3")
        self.assertEqual(self.cache.get_session("test-1")["step"], 11)

    def test_cache_miss_deleted_key_restores_verified_ended_state(self):
        with patch('storage.redis_adapter.read_live_snapshot', return_value=snapshot(step=8, status="ended")):
            self.assertEqual(self.adapter.get_state("test-1")["status"], "ended")
        self.assertEqual(self.cache.get_session("test-1")["status"], "ended")
        with self.assertRaises(ValueError):
            self.cache.record_step("test-1", 9)

    def test_redis_failure_does_not_change_successful_postgres_return(self):
        expected = {"id": 33, "session_id": "test-1", "step": 1}
        with patch('storage.redis_adapter.live.add_observation', return_value=expected), \
             patch.object(self.cache, 'reconcile_from_reader', side_effect=ConnectionError('redis down')) as rebuild, \
             self.assertLogs('storage.redis_adapter', level='WARNING') as logs:
            got = self.adapter.add_observation('test-1', 1, 'agent', {"tests_passed": 1})
        self.assertIs(got, expected)
        rebuild.assert_called_once()
        self.assertEqual(rebuild.call_args.args[0], 'test-1')
        self.assertTrue(callable(rebuild.call_args.args[1]))
        self.assertTrue(any('Optional Redis refresh failed' in line for line in logs.output))

    def test_db_failure_propagates_and_redis_not_touched(self):
        with patch('storage.redis_adapter.live.add_observation', side_effect=RuntimeError('db failed')), \
             patch('storage.redis_adapter.read_live_snapshot') as reader:
            with self.assertRaisesRegex(RuntimeError, 'db failed'):
                self.adapter.add_observation('test-1', 1, 'agent', {})
            reader.assert_not_called()

    def test_cache_unavailable_read_falls_back_to_postgres(self):
        with patch.object(self.cache, 'get_session', side_effect=ConnectionError('redis down')) as cache_read, \
             patch.object(self.cache, 'reconcile_from_reader', side_effect=ConnectionError('redis down')) as rebuild, \
             patch('storage.redis_adapter.read_live_snapshot', return_value=snapshot(step=9)) as db_reader, \
             self.assertLogs('storage.redis_adapter', level='WARNING') as logs:
            result = self.adapter.get_state('test-1')
        self.assertEqual(result['step'], 9)
        cache_read.assert_called_once_with('test-1')
        rebuild.assert_called_once()
        self.assertEqual(rebuild.call_args.args[0], 'test-1')
        self.assertTrue(callable(rebuild.call_args.args[1]))
        db_reader.assert_called_once_with('test-1', 'deadlock-v0.3')
        self.assertTrue(any('Optional Redis rebuild unavailable' in line for line in logs.output))

    def test_db_read_failure_after_db_write_does_not_change_write_result(self):
        with patch('storage.redis_adapter.live.end_live_session', return_value={'status': 'ended'}), \
             patch('storage.redis_adapter.read_live_snapshot', side_effect=ConnectionError('db temporarily unavailable')):
            self.assertEqual(self.adapter.end_live_session('test-1', 'done', 0, 0, None), {'status': 'ended'})

    def test_multi_rule_pg_result_selected_by_explicit_rule(self):
        self.cache.reconcile_snapshot(snapshot(step=2, decision='CONTINUE'))
        with patch('storage.redis_adapter.read_live_snapshot', return_value=snapshot(step=2, decision='CONTINUE')) as reader, \
             patch('storage.redis_adapter.live.add_judgement', return_value={'id': 55, 'rule_id': 'other-rule'}):
            saved = self.adapter.add_judgement('test-1', 2, 'agent', 'STOP', 'other-rule', 'progress', 0, None, 1, {})
            self.assertEqual(saved['rule_id'], 'other-rule')
            reader.assert_called_once_with('test-1', 'deadlock-v0.3')
        self.assertEqual(self.cache.get_session('test-1')['last_decision'], 'CONTINUE')

    def test_reconcile_rejects_inconsistent_mode_and_invalid_source_fields(self):
        self.cache.reconcile_snapshot(snapshot(step=1))
        with self.assertRaises(ValueError):
            self.cache.reconcile_snapshot(snapshot(step=3, mode='block'))
        invalid = snapshot(step=2)
        invalid['raw_turns'] = 'must never store'
        with self.assertRaises(ValueError):
            self.cache.reconcile_snapshot(invalid)


class DatabaseSnapshotReaderTests(unittest.TestCase):
    class Cur:
        def __init__(self, rows):
            self.rows = rows
            self.queries = []
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, sql, args):
            self.queries.append((sql, args))
        def fetchone(self):
            return self.rows.pop(0)

    class Conn:
        def __init__(self, cur): self.cur = cur
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def cursor(self): return self.cur

    def test_snapshot_reads_selected_rule_and_locks_session(self):
        cur = self.Cur([('active', 'observe', None), (3,), ('CONTINUE', 2)])
        with patch('storage.redis_adapter.get_connection', return_value=self.Conn(cur)):
            s = read_live_snapshot('test-1', 'deadlock-v0.3')
        self.assertEqual((s['step'], s['last_decision'], s['stagnant_run']), (3, 'CONTINUE', 2))
        self.assertIn('FOR SHARE', cur.queries[0][0])
        self.assertIn("source = 'live'", cur.queries[0][0])
        self.assertEqual(cur.queries[2][1], ('test-1', 3, 'deadlock-v0.3'))

    def test_ended_snapshot_preserves_durable_timestamp(self):
        t = datetime(2026, 10, 29, tzinfo=timezone.utc)
        cur = self.Cur([('ended', 'block', t), (2,)])
        with patch('storage.redis_adapter.get_connection', return_value=self.Conn(cur)):
            s = read_live_snapshot('test-2')
        self.assertEqual(s['ended_at'], t.isoformat())
        self.assertIsNone(s['last_decision'])

    def test_missing_live_session_is_not_recreated(self):
        cur = self.Cur([None])
        with patch('storage.redis_adapter.get_connection', return_value=self.Conn(cur)):
            self.assertIsNone(read_live_snapshot('not-real', 'deadlock-v0.3'))


if __name__ == '__main__':
    unittest.main()
