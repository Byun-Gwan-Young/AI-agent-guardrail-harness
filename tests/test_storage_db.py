import os
import unittest
from unittest.mock import MagicMock, patch

import storage.db as db


class StorageDbContractTests(unittest.TestCase):
    def _env(self, **values):
        clean = {key: str(value) for key, value in values.items() if value is not None}
        return patch.dict(os.environ, clean, clear=True)

    def test_guardrail_db_url_has_priority_over_postgres_fallback(self):
        with self._env(
            GUARDRAIL_DB_URL="postgresql://server.example/appdb",
            POSTGRES_DB="wrongdb",
            POSTGRES_HOST="wronghost",
            POSTGRES_PASSWORD="wrongpass",
        ), patch("storage.db.psycopg.connect") as connect:
            db.get_connection(autocommit=True)

        connect.assert_called_once_with(
            "postgresql://server.example/appdb",
            autocommit=True,
        )

    def test_url_database_override_preserves_other_dsn_settings(self):
        socket_url = "postgresql:///guardrail_demo?host=/var/run/postgresql"
        with self._env(GUARDRAIL_DB_URL=socket_url), patch(
            "storage.db.psycopg.connect"
        ) as connect:
            db.get_connection(dbname="postgres", autocommit=True)

        connect.assert_called_once_with(
            socket_url,
            autocommit=True,
            dbname="postgres",
        )

    def test_unix_socket_peer_url_needs_no_password(self):
        socket_url = "postgresql:///guardrail_demo?host=/var/run/postgresql"
        with self._env(GUARDRAIL_DB_URL=socket_url), patch(
            "storage.db.psycopg.connect"
        ) as connect:
            db.get_connection()

        args, kwargs = connect.call_args
        self.assertEqual(args, (socket_url,))
        self.assertNotIn("password", kwargs)

    def test_fallback_keeps_existing_local_env_shape(self):
        with self._env(
            POSTGRES_HOST="localhost",
            POSTGRES_PORT="5432",
            POSTGRES_DB="guardrail_agent_v2",
            POSTGRES_USER="postgres",
            POSTGRES_PASSWORD="local-secret",
        ), patch("storage.db.psycopg.connect") as connect:
            db.get_connection()

        connect.assert_called_once_with(
            host="localhost",
            port="5432",
            dbname="guardrail_agent_v2",
            user="postgres",
            password="local-secret",
            autocommit=False,
        )

    def test_fallback_password_is_optional(self):
        with self._env(
            POSTGRES_DB="guardrail_agent_v2",
            POSTGRES_USER="guardrail",
        ), patch("storage.db.psycopg.connect") as connect:
            db.get_connection()

        connect.assert_called_once_with(
            dbname="guardrail_agent_v2",
            user="guardrail",
            autocommit=False,
        )

    def test_blank_guardrail_url_falls_back(self):
        with self._env(
            GUARDRAIL_DB_URL="   ",
            POSTGRES_DB="fallback_db",
        ), patch("storage.db.psycopg.connect") as connect:
            db.get_connection()

        connect.assert_called_once_with(dbname="fallback_db", autocommit=False)

    def test_target_database_name_from_socket_url(self):
        with self._env(
            GUARDRAIL_DB_URL="postgresql:///guardrail_demo?host=/var/run/postgresql"
        ):
            self.assertEqual(db.get_target_database_name(), "guardrail_demo")

    def test_target_database_name_from_postgres_db_fallback(self):
        with self._env(POSTGRES_DB="guardrail_agent_v2"):
            self.assertEqual(db.get_target_database_name(), "guardrail_agent_v2")


    def test_project_auto_selection_ignores_read_only_demo(self):
        conn_ctx = MagicMock()
        cursor = conn_ctx.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(42,)]

        with self._env(), patch("storage.db.get_connection", return_value=conn_ctx):
            self.assertEqual(db.get_project_id(), 42)

        statement = cursor.execute.call_args.args[0]
        self.assertIn("read_only = FALSE", statement)

    def test_project_auto_selection_refuses_when_only_demo_exists(self):
        conn_ctx = MagicMock()
        cursor = conn_ctx.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        with self._env(), patch("storage.db.get_connection", return_value=conn_ctx):
            with self.assertRaisesRegex(RuntimeError, "쓰기 가능한 프로젝트"):
                db.get_project_id()

    def test_missing_database_configuration_has_safe_error(self):
        with self._env():
            with self.assertRaisesRegex(RuntimeError, "GUARDRAIL_DB_URL or POSTGRES_DB"):
                db.get_target_database_name()


if __name__ == "__main__":
    unittest.main(verbosity=2)
