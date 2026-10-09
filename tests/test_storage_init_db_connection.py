import unittest
from unittest.mock import MagicMock, patch

import psycopg

import storage.init_db as init_db


class _ConnectionContext:
    def __init__(self, connection=None, exc=None):
        self.connection = connection or MagicMock()
        self.exc = exc

    def __enter__(self):
        if self.exc is not None:
            raise self.exc
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


class InitDbConnectionContractTests(unittest.TestCase):
    def test_existing_url_database_does_not_need_postgres_env_or_create_privilege(self):
        with patch("storage.init_db.get_target_database_name", return_value="appdb"), patch(
            "storage.init_db.get_connection",
            return_value=_ConnectionContext(),
        ) as get_connection:
            created = init_db.ensure_database_exists()

        self.assertFalse(created)
        get_connection.assert_called_once_with(autocommit=True)

    def test_missing_database_uses_same_connection_source_with_dbname_override(self):
        missing = psycopg.errors.InvalidCatalogName("database does not exist")
        maintenance = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        maintenance.cursor.return_value.__enter__.return_value = cursor
        maintenance.cursor.return_value.__exit__.return_value = False

        calls = [
            _ConnectionContext(exc=missing),
            _ConnectionContext(connection=maintenance),
        ]

        with patch("storage.init_db.get_target_database_name", return_value="appdb"), patch(
            "storage.init_db.get_connection",
            side_effect=calls,
        ) as get_connection:
            created = init_db.ensure_database_exists()

        self.assertTrue(created)
        self.assertEqual(
            get_connection.call_args_list[0].kwargs,
            {"autocommit": True},
        )
        self.assertEqual(
            get_connection.call_args_list[1].kwargs,
            {"dbname": "postgres", "autocommit": True},
        )
        cursor.execute.assert_any_call(
            "SELECT 1 FROM pg_database WHERE datname = %s;",
            ("appdb",),
        )




    def test_target_connection_operational_error_does_not_imply_missing_database(self):
        target_error = psycopg.OperationalError("connection failed")
        maintenance = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)  # target DB exists
        maintenance.cursor.return_value.__enter__.return_value = cursor
        maintenance.cursor.return_value.__exit__.return_value = False

        calls = [
            _ConnectionContext(exc=target_error),
            _ConnectionContext(connection=maintenance),
        ]

        with patch("storage.init_db.get_target_database_name", return_value="appdb"), patch(
            "storage.init_db.get_connection",
            side_effect=calls,
        ):
            with self.assertRaisesRegex(RuntimeError, "존재하지만 연결에 실패"):
                init_db.ensure_database_exists()

        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any("CREATE DATABASE" in str(stmt) for stmt in statements))

    def test_init_does_not_bootstrap_ownerless_writable_project(self):
        with patch("storage.init_db.initialize_schema") as initialize_schema, patch(
            "storage.init_db.list_projects", return_value=[]
        ), patch("builtins.input", side_effect=AssertionError("init must not prompt for project")):
            init_db.initialize_everything(interactive_project=True)

        initialize_schema.assert_called_once_with()

    def test_legacy_bootstrap_create_project_is_retired(self):
        with self.assertRaisesRegex(RuntimeError, "ownerless project bootstrap is retired"):
            init_db.create_project("legacy", "observe", "deadlock-v0.3", "https://example.invalid")

if __name__ == "__main__":
    unittest.main(verbosity=2)
