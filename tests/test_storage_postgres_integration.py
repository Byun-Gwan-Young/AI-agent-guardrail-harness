"""Conditional real-PostgreSQL integration for the unified Storage contract.

This file never opens PostgreSQL during the normal offline suite because the PM
command explicitly unsets GUARDRAIL_DB_URL.  Set GUARDRAIL_DB_URL deliberately
to exercise account/key + live writers against a disposable/test database.
No provider/network request is made.
"""

from __future__ import annotations

import os
import secrets
import unittest
from unittest.mock import patch

from psycopg.types.json import Jsonb

from storage import accounts, live
from storage.db import get_connection


@unittest.skipUnless(
    os.getenv("GUARDRAIL_DB_URL"),
    "GUARDRAIL_DB_URL is not set; real PostgreSQL integration is opt-in",
)
class StoragePostgresIntegration(unittest.TestCase):
    def setUp(self):
        suffix = secrets.token_hex(6)
        self.email = f"storage-integration-{suffix}@example.com"
        self.google_sub = f"storage-integration-{suffix}"
        self.project_name = f"storage-integration-{suffix}"
        self.scenario_key = f"STORAGE-INTEGRATION-{suffix}"
        self.scenario_hash = secrets.token_hex(32)
        self.session_id = f"storage-integration-{suffix}"
        self.user_id = None
        self.project_id = None
        self.scenario_id = None

    def tearDown(self):
        # Clean by exact generated ids/labels only.  Cleanup is best-effort so a
        # failed assertion does not leave fake integration rows in the test DB.
        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    if self.project_id is not None:
                        cursor.execute(
                            """
                            DELETE FROM llm_calls
                            WHERE session_id IN (
                                SELECT s.id FROM sessions s
                                JOIN scenarios sc ON sc.id = s.scenario_id
                                WHERE sc.project_id = %s
                            )
                            """,
                            (self.project_id,),
                        )
                        cursor.execute(
                            """
                            DELETE FROM judgements
                            WHERE session_id IN (
                                SELECT s.id FROM sessions s
                                JOIN scenarios sc ON sc.id = s.scenario_id
                                WHERE sc.project_id = %s
                            )
                            """,
                            (self.project_id,),
                        )
                        cursor.execute(
                            """
                            DELETE FROM observations
                            WHERE session_id IN (
                                SELECT s.id FROM sessions s
                                JOIN scenarios sc ON sc.id = s.scenario_id
                                WHERE sc.project_id = %s
                            )
                            """,
                            (self.project_id,),
                        )
                        cursor.execute(
                            """
                            DELETE FROM sessions
                            WHERE scenario_id IN (
                                SELECT id FROM scenarios WHERE project_id = %s
                            )
                            """,
                            (self.project_id,),
                        )
                        cursor.execute("DELETE FROM api_keys WHERE project_id = %s", (self.project_id,))
                        cursor.execute("DELETE FROM scenarios WHERE project_id = %s", (self.project_id,))
                        cursor.execute("DELETE FROM projects WHERE id = %s", (self.project_id,))

                    if self.user_id is not None:
                        cursor.execute("DELETE FROM auth_events WHERE user_id = %s", (self.user_id,))
                        cursor.execute("DELETE FROM users WHERE id = %s", (self.user_id,))

                    # allow_email/remove-email events have user_id NULL, so use
                    # the unique fake email in their structured detail.
                    cursor.execute(
                        "DELETE FROM auth_events WHERE detail ->> 'email' = %s",
                        (self.email,),
                    )
                    cursor.execute(
                        "DELETE FROM allowed_emails WHERE LOWER(email) = LOWER(%s)",
                        (self.email,),
                    )
        except Exception:
            # Do not hide the original test failure with cleanup noise.
            pass

    def test_accounts_key_and_live_round_trip(self):
        accounts.allow_email(self.email)
        self.assertTrue(accounts.is_email_allowed(self.email))

        user = accounts.upsert_user_from_google(self.google_sub, self.email, "Integration User")
        self.user_id = user["id"]

        # Provider endpoint is metadata only here; no external provider call is
        # made. Use a known provider so create_project has deterministic config.
        with patch.dict(os.environ, {accounts.DEFAULT_PROVIDER_ENV: "openai"}, clear=False):
            project = accounts.create_project(self.user_id, self.project_name, "observe")
        self.project_id = project["id"]
        self.assertEqual(project["provider"], "openai")

        raw_key, key_info = accounts.issue_api_key(self.project_id, self.user_id, "integration")
        self.assertTrue(raw_key.startswith("gk_"))
        self.assertNotIn("key_hash", key_info)
        verified = accounts.verify_api_key(raw_key)
        self.assertEqual(verified["id"], self.project_id)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO scenarios (
                        project_id, scenario_key, scenario_hash, schema_version,
                        name, task_kind, config
                    )
                    VALUES (%s, %s, %s, 'scenario-v2', %s, 'T3', %s)
                    RETURNING id
                    """,
                    (
                        self.project_id,
                        self.scenario_key,
                        self.scenario_hash,
                        "Storage integration scenario",
                        Jsonb({"schema_version": "scenario-v2", "scenario_id": self.scenario_key}),
                    ),
                )
                self.scenario_id = cursor.fetchone()[0]

        started = live.start_live_session(
            self.project_id,
            self.session_id,
            self.scenario_key,
            self.scenario_hash,
            "observe",
            "integration-model",
            {"temperature": 0},
        )
        self.assertEqual(started["source"], "live")
        self.assertEqual(started["provider"], "openai")

        live.add_observation(
            self.session_id,
            1,
            "developer",
            {"tests_passed": 1, "state": "structured"},
        )
        live.add_judgement(
            self.session_id,
            1,
            "developer",
            "CONTINUE",
            "deadlock-v0.3",
            "progress",
            0,
            "structured progress observed",
            100,
            {
                "progress": {"version": "progress-v3", "state": "progress"},
                "criteria": {"decision": "CONTINUE"},
            },
        )
        live.add_llm_call(
            self.session_id,
            1,
            1,
            "developer",
            10,
            2,
            0,
            12.5,
            200,
            0,
            0,
        )

        progress = live.get_session_progress(self.session_id, 0)
        self.assertEqual(len(progress["observations"]), 1)
        self.assertEqual(len(progress["judgements"]), 1)

        ended = live.end_live_session(self.session_id, "completed", 1, 12, None)
        self.assertEqual(ended["status"], "ended")

        accounts.revoke_api_key(key_info["id"], self.user_id)
        self.assertIsNone(accounts.verify_api_key(raw_key))


if __name__ == "__main__":
    unittest.main(verbosity=2)
