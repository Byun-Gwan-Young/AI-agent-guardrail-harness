"""Opt-in PostgreSQL+Redis end-to-end test on YOUR disposable/local development DB.

This creates a fake user/project/scenario/session and deletes only that test
identity. It does not touch the canonical demo. NO remote provider is called.
Required explicit opt-in: GUARDRAIL_REDIS_TEST_URL and
GUARDRAIL_REDIS_PG_TEST=1. PostgreSQL uses GUARDRAIL_DB_URL or the local
POSTGRES_* .env fallback. Never use production data or services.
"""
from __future__ import annotations

import os
import secrets
import unittest
from unittest.mock import patch

from psycopg.types.json import Jsonb

from storage import accounts
from storage.db import get_connection
from storage.redis_client import get_redis_client
from storage.redis_state import RedisLiveStateStore
from storage.redis_adapter import RedisLiveAdapter


@unittest.skipUnless(
    os.getenv("GUARDRAIL_REDIS_PG_TEST") == "1"
    and os.getenv("GUARDRAIL_REDIS_TEST_URL"),
    "Explicit opt-in requires GUARDRAIL_REDIS_PG_TEST=1 and a Redis test URL",
)
class RedisPostgresAdapterIntegration(unittest.TestCase):
    def setUp(self):
        suffix = secrets.token_hex(7)
        self.email = f"redis-adapter-{suffix}@example.com"
        self.sub = f"redis-adapter-{suffix}"
        self.scenario_key = f"REDIS-ADAPTER-{suffix}"
        self.scenario_hash = secrets.token_hex(32)
        self.sid = f"redis-adapter-{suffix}"
        self.user_id = None
        self.project_id = None
        self.prefix = f"guardrail:redis-pg-test:{suffix}"
        self.client = get_redis_client(os.environ['GUARDRAIL_REDIS_TEST_URL'])
        self.cache = RedisLiveStateStore(self.client, ttl_seconds=45, prefix=self.prefix,
                                         selected_rule_id="deadlock-v0.3")
        self.adapter = RedisLiveAdapter(self.cache)

    def tearDown(self):
        # Only clean this test's generated Redis namespace and PG IDs.
        try:
            self.client.delete(self.cache._key(self.sid))
        except Exception:
            pass
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if self.project_id is not None:
                        for table in ('llm_calls', 'judgements', 'observations'):
                            cur.execute(
                                f"DELETE FROM {table} WHERE session_id IN "
                                "(SELECT s.id FROM sessions s JOIN scenarios sc "
                                "ON sc.id = s.scenario_id WHERE sc.project_id = %s)",
                                (self.project_id,),
                            )
                        cur.execute('DELETE FROM sessions WHERE scenario_id IN '
                                    '(SELECT id FROM scenarios WHERE project_id = %s)',
                                    (self.project_id,))
                        cur.execute('DELETE FROM api_keys WHERE project_id = %s', (self.project_id,))
                        cur.execute('DELETE FROM scenarios WHERE project_id = %s', (self.project_id,))
                        cur.execute('DELETE FROM projects WHERE id = %s', (self.project_id,))
                    if self.user_id is not None:
                        cur.execute('DELETE FROM auth_events WHERE user_id = %s', (self.user_id,))
                        cur.execute('DELETE FROM users WHERE id = %s', (self.user_id,))
                    cur.execute('DELETE FROM auth_events WHERE detail ->> \'email\' = %s', (self.email,))
                    cur.execute('DELETE FROM allowed_emails WHERE LOWER(email) = LOWER(%s)', (self.email,))
        except Exception:
            pass

    def test_durable_first_late_rules_expiry_outage_and_end(self):
        # Standalone setup. All created rows use this test's unique identity.
        accounts.allow_email(self.email)
        owner = accounts.upsert_user_from_google(self.sub, self.email, 'Redis Test')
        self.user_id = owner['id']
        with patch.dict(os.environ, {accounts.DEFAULT_PROVIDER_ENV: 'openai'}, clear=False):
            project = accounts.create_project(self.user_id, self.scenario_key, 'observe')
        self.project_id = project['id']
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO scenarios
                    (project_id, scenario_key, scenario_hash, schema_version, name, task_kind, config)
                    VALUES (%s, %s, %s, 'scenario-v2', %s, 'T3', %s) RETURNING id""",
                    (self.project_id, self.scenario_key, self.scenario_hash,
                     'Redis adapter integration scenario',
                     Jsonb({'schema_version': 'scenario-v2', 'scenario_id': self.scenario_key})),
                )
                self.assertIsNotNone(cur.fetchone()[0])

        started = self.adapter.start_live_session(
            self.project_id, self.sid, self.scenario_key, self.scenario_hash,
            'observe', 'integration-model', {'temperature': 0},
        )
        self.assertEqual(started['status'], 'active')
        self.assertEqual(self.cache.get_session(self.sid)['step'], 0)

        self.adapter.add_observation(self.sid, 1, 'agent', {'structured': True})
        self.adapter.add_observation(self.sid, 2, 'agent', {'structured': True})
        self.assertEqual(self.cache.get_session(self.sid)['step'], 2)

        # A late judgement is accepted in PostgreSQL, but does not rewind the
        # Redis current-step display. Check an unrelated rule on the same step.
        for step, decision, rule_id in [
            (1, 'CONTINUE', 'deadlock-v0.3'),
            (2, 'STOP', 'other-rule'),
            (2, 'CONTINUE', 'deadlock-v0.3'),
        ]:
            record = self.adapter.add_judgement(
                self.sid, step, 'agent', decision, rule_id, 'progress', 0,
                None, 123, {'progress': {'state': 'progress'},
                            'criteria': {'decision': decision}},
            )
            self.assertEqual(record['rule_id'], rule_id)
        cached = self.cache.get_session(self.sid)
        self.assertEqual((cached['step'], cached['last_decision']), (2, 'CONTINUE'))

        # Cache loss does not start a fresh step-0 live session.
        self.client.delete(self.cache._key(self.sid))
        self.assertEqual(self.adapter.get_state(self.sid)['step'], 2)
        self.assertEqual(self.cache.get_session(self.sid)['last_decision'], 'CONTINUE')

        # Use an intentionally unreachable loopback Redis port: exercise a
        # *real connection refusal*, not merely a mocked cache exception.
        offline_cache = RedisLiveStateStore(
            get_redis_client('redis://127.0.0.1:1/0'),
            ttl_seconds=45, prefix=self.prefix, selected_rule_id='deadlock-v0.3',
        )
        offline_adapter = RedisLiveAdapter(offline_cache)
        result = offline_adapter.end_live_session(self.sid, 'completed', 2, 0, None)
        self.assertEqual(result['status'], 'ended')
        self.assertEqual(offline_adapter.get_state(self.sid)['status'], 'ended')
        # A failed cache write left the old active value; authoritative
        # callers must use PostgreSQL, not trust a stale cached status.
        self.assertEqual(self.adapter.get_authoritative_state(self.sid)['status'], 'ended')
        self.client.delete(self.cache._key(self.sid))
        self.assertEqual(self.adapter.get_state(self.sid)['status'], 'ended')
        self.assertEqual(self.cache.get_session(self.sid)['status'], 'ended')


if __name__ == '__main__':
    unittest.main()
