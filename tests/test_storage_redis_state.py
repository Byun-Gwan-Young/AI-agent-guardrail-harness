"""Offline Redis-state tests (no server/credentials necessary)."""
import json
import unittest
from unittest.mock import patch

from storage.redis_state import RedisLiveStateStore, WatchError


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.queued = []
        self.in_multi = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def watch(self, key):
        self.watched = key

    def get(self, key):
        return self.client.get(key)

    def multi(self):
        self.in_multi = True

    def set(self, key, value, *, ex=None, nx=False):
        assert self.in_multi
        self.queued.append((key, value, ex, nx))

    def execute(self):
        if self.client.fail_watch:
            self.client.fail_watch -= 1
            raise WatchError("simulated concurrent change")
        for key, value, ex, nx in self.queued:
            self.client.set(key, value, ex=ex, nx=nx)
        return [True] * len(self.queued)


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}
        self.fail_watch = 0

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        self.ttls[key] = ex
        return True

    def pipeline(self):
        return FakePipeline(self)


class RedisStateTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.state = RedisLiveStateStore(self.redis, ttl_seconds=60)

    def test_create_read_steps_judge_end(self):
        start = self.state.start_session("test-1", "observe")
        self.assertEqual((start["step"], start["status"]), (0, "active"))
        self.assertEqual(self.state.get_session("test-1"), start)
        self.assertEqual(self.state.record_step("test-1", 1)["step"], 1)
        state = self.state.record_judgement("test-1", 1, "CONTINUE", stagnant_run=0)
        self.assertEqual((state["last_decision"], state["stagnant_run"]), ("CONTINUE", 0))
        self.assertEqual(self.state.record_judgement("test-1", 1, "CONTINUE", stagnant_run=0), state)
        state2 = self.state.record_step("test-1", 2)
        self.assertEqual((state2["last_decision"], state2["stagnant_run"]), (None, None))
        ended = self.state.end_session("test-1")
        self.assertEqual(ended["status"], "ended")
        self.assertTrue(ended["ended_at"])
        self.assertEqual(self.state.end_session("test-1"), ended)
        self.assertEqual(self.redis.ttls[self.state._key("test-1")], 60)

    def test_duplicate_start_rejected_without_overwrite(self):
        original = self.state.start_session("same", "block")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.state.start_session("same", "observe")
        self.assertEqual(self.state.get_session("same"), original)

    def test_missing_or_expired_never_recreated_by_update(self):
        self.assertIsNone(self.state.get_session("missing"))
        with self.assertRaises(LookupError):
            self.state.record_step("missing", 1)
        self.state.start_session("expired", "observe")
        self.redis.data.pop(self.state._key("expired"))
        with self.assertRaises(LookupError):
            self.state.end_session("expired")

    def test_step_and_judgement_guards(self):
        self.state.start_session("t", "observe")
        with self.assertRaises(ValueError):
            self.state.record_step("t", True)
        with self.assertRaises(ValueError):
            self.state.record_step("t", 0)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 1, "STOP")
        self.state.record_step("t", 3)
        self.state.record_step("t", 3)
        self.assertEqual(self.state.record_step("t", 2)["step"], 3)
        self.state.record_judgement("t", 3, "STOP", stagnant_run=3)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 3, "CONTINUE", stagnant_run=3)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 3, "STOP", stagnant_run=2)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 3, "STOP", stagnant_run=True)
        self.state.end_session("t")
        with self.assertRaises(ValueError):
            self.state.record_step("t", 4)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 3, "STOP", stagnant_run=3)

    def test_reject_bad_ids_modes_decisions_and_ttl(self):
        for sid in ("../escape", "has space", "", "a" * 129, None, True):
            with self.subTest(sid=sid), self.assertRaises(ValueError):
                self.state.start_session(sid, "observe")
        for mode in ("warn", None, [], {}):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.state.start_session("t", mode)
        for ttl in (0, True, -1, 2_592_001):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                RedisLiveStateStore(self.redis, ttl_seconds=ttl)
        self.state.start_session("t", "observe")
        self.state.record_step("t", 1)
        for decision in ("whole sentence", "", "x" * 65, None, []):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                self.state.record_judgement("t", 1, decision)

    def test_never_persist_raw_or_credential_like_data(self):
        self.state.start_session("t", "block")
        self.state.record_step("t", 1)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 1, "gsk_abcdefgh1234567890")
        # Rejected value does not mutate Redis.
        self.assertIsNone(self.state.get_session("t")["last_decision"])
        self.assertEqual(set(json.loads(self.redis.get(self.state._key("t")))),
                         {"schema_version", "session_id", "status", "mode", "step",
                          "last_decision", "stagnant_run", "updated_at", "ended_at"})

    def test_late_observation_keeps_latest_state(self):
        self.state.start_session("t", "observe")
        self.state.record_step("t", 3)
        self.state.record_judgement("t", 3, "STOP", stagnant_run=3)
        before = self.state.get_session("t")
        self.assertEqual(self.state.record_step("t", 2), before)
        self.assertEqual(self.state.get_session("t"), before)

    def test_late_judgement_skipped_without_reverting_current_step(self):
        self.state.start_session("t", "observe")
        self.state.record_step("t", 1)
        self.state.record_step("t", 2)
        before = self.state.get_session("t")
        after = self.state.record_judgement("t", 1, "STOP", stagnant_run=3)
        self.assertEqual(after, before)
        self.assertEqual(self.state.get_session("t"), before)
        self.assertIsNone(after["last_decision"])

    def test_explicit_display_rule_selection(self):
        state = RedisLiveStateStore(self.redis, ttl_seconds=60,
                                    selected_rule_id="termination_failure")
        state.start_session("t", "observe")
        state.record_step("t", 2)
        with self.assertRaisesRegex(ValueError, "rule_id required"):
            state.record_judgement("t", 2, "CONTINUE")
        before = state.get_session("t")
        ignored = state.record_judgement("t", 2, "STOP", rule_id="other_rule")
        self.assertEqual(ignored, before)
        recorded = state.record_judgement("t", 2, "CONTINUE", stagnant_run=0,
                                           rule_id="termination_failure")
        self.assertEqual(recorded["last_decision"], "CONTINUE")
        self.assertEqual(state.record_judgement("t", 2, "STOP", rule_id="other_rule"), recorded)
        self.assertEqual(state.record_judgement("t", 2, "CONTINUE", stagnant_run=0,
                                                rule_id="termination_failure"), recorded)

    def test_invalid_rule_ids_rejected(self):
        with self.assertRaises(ValueError):
            RedisLiveStateStore(self.redis, selected_rule_id="raw rule text")
        self.state.start_session("t", "observe")
        self.state.record_step("t", 1)
        with self.assertRaises(ValueError):
            self.state.record_judgement("t", 1, "CONTINUE", rule_id="bad rule")

    def test_retries_watch_conflict_and_bounded_failure(self):
        self.state.start_session("t", "observe")
        self.redis.fail_watch = 2
        self.assertEqual(self.state.record_step("t", 1)["step"], 1)
        self.redis.fail_watch = 5
        with self.assertRaises(RuntimeError):
            self.state.record_step("t", 2)
        self.assertEqual(self.state.get_session("t")["step"], 1)

    def test_corrupt_value_rejected_without_value_disclosure(self):
        self.redis.data[self.state._key("t")] = '{"content":"secret"}'
        with self.assertRaisesRegex(ValueError, "Invalid Redis live state"):
            self.state.get_session("t")
        self.redis.data[self.state._key("t")] = "not-json"
        with self.assertRaises(ValueError):
            self.state.get_session("t")
        self.state.start_session("ok", "block")
        key = self.state._key("ok")
        payload = json.loads(self.redis.data[key])
        payload["status"] = []
        self.redis.data[key] = json.dumps(payload)
        with self.assertRaises(ValueError):
            self.state.get_session("ok")


if __name__ == "__main__":
    unittest.main()
