import sys
import unittest
from unittest.mock import patch

import storage.accounts as accounts
import storage.safety as safety
import storage.__main__ as storage_main


class _Cursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))


class _Connection:
    def __init__(self):
        self.cursor_obj = _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


class AccountsHardeningTests(unittest.TestCase):
    def test_default_upstream_is_provider_neutral_and_required(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            old = os.environ.pop(accounts.DEFAULT_UPSTREAM_URL_ENV, None)
            try:
                with self.assertRaisesRegex(RuntimeError, "GUARDRAIL_DEFAULT_UPSTREAM_URL"):
                    accounts._get_default_upstream_url()
            finally:
                if old is not None:
                    os.environ[accounts.DEFAULT_UPSTREAM_URL_ENV] = old

    def test_default_upstream_comes_from_runtime_environment(self):
        import os
        with patch.dict(
            os.environ,
            {accounts.DEFAULT_UPSTREAM_URL_ENV: "  https://provider.example.invalid/v1  "},
            clear=False,
        ):
            self.assertEqual(
                accounts._get_default_upstream_url(),
                "https://provider.example.invalid/v1",
            )

    def test_default_provider_resolves_known_provider_without_user_url(self):
        import os
        env = {accounts.DEFAULT_PROVIDER_ENV: "groq"}
        with patch.dict(os.environ, env, clear=False):
            old_legacy = os.environ.pop(accounts.DEFAULT_UPSTREAM_URL_ENV, None)
            try:
                provider, url = accounts._get_default_provider_config()
            finally:
                if old_legacy is not None:
                    os.environ[accounts.DEFAULT_UPSTREAM_URL_ENV] = old_legacy
        self.assertEqual(provider, "groq")
        self.assertEqual(url, "https://api.groq.com/openai/v1")

    def test_kmu_provider_uses_deployment_environment_url(self):
        import os
        with patch.dict(
            os.environ,
            {
                accounts.DEFAULT_PROVIDER_ENV: "kmu",
                "GUARDRAIL_PROVIDER_KMU_URL": "https://kmu.example.invalid/v1",
            },
            clear=False,
        ):
            provider, url = accounts._get_default_provider_config()
        self.assertEqual((provider, url), ("kmu", "https://kmu.example.invalid/v1"))

    def test_custom_provider_requires_explicit_url(self):
        with self.assertRaises(RuntimeError):
            accounts._resolve_provider_upstream("custom")
        self.assertEqual(
            accounts._resolve_provider_upstream("custom", "https://custom.example.invalid/v1"),
            ("custom", "https://custom.example.invalid/v1"),
        )

    def test_named_provider_rejects_user_supplied_url_override(self):
        with self.assertRaises(ValueError):
            accounts._resolve_provider_upstream("openai", "https://evil.example.invalid/v1")

    def test_upstream_url_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            accounts._validate_upstream_url("https://user:pass@example.invalid/v1")


    def test_upstream_url_rejects_credential_query_parameter(self):
        with self.assertRaisesRegex(ValueError, "credential query parameters"):
            accounts._validate_upstream_url(
                "https://provider.example.invalid/v1?api_key=unknown-format-secret"
            )

    def test_upstream_url_allows_noncredential_query_parameter(self):
        self.assertEqual(
            accounts._validate_upstream_url(
                "https://provider.example.invalid/v1?api-version=2026-01-01"
            ),
            "https://provider.example.invalid/v1?api-version=2026-01-01",
        )

    def test_create_project_requires_real_owner(self):
        with patch("storage.accounts.get_connection", side_effect=AssertionError("DB must not open")):
            for bad in (None, 0, -1, True, "1"):
                with self.subTest(owner=bad):
                    with self.assertRaises(ValueError):
                        accounts.create_project(bad, "demo", "observe")

    def test_auth_event_rejects_raw_guardrail_key_before_insert(self):
        raw = "gk_a1b2c3d4_" + ("A" * 44)
        conn = _Connection()
        with patch("storage.accounts.get_connection", return_value=conn):
            with self.assertRaises(ValueError) as cm:
                accounts.record_auth_event("login_rejected", None, {"note": raw})
        self.assertEqual(conn.cursor_obj.executed, [])
        self.assertNotIn(raw, str(cm.exception))

    def test_auth_event_rejects_secret_field_names(self):
        conn = _Connection()
        with patch("storage.accounts.get_connection", return_value=conn):
            with self.assertRaises(ValueError):
                accounts.record_auth_event("oauth", 1, {"access_token": "not-even-a-real-token"})
        self.assertEqual(conn.cursor_obj.executed, [])

    def test_secret_names_are_rejected_before_db_access(self):
        raw = "gsk_" + ("X" * 32)
        with patch("storage.accounts.get_connection", side_effect=AssertionError("DB must not open")):
            with self.assertRaises(ValueError):
                accounts.create_project(1, f"project-{raw}", "observe")
            with self.assertRaises(ValueError):
                accounts.issue_api_key(1, 1, f"key-{raw}")

    def test_safety_recognizes_common_oauth_and_private_key_fields(self):
        found = safety.forbidden_fields({
            "access_token": "x",
            "refresh_token": "y",
            "client_secret": "z",
            "private_key": "p",
        })
        self.assertEqual(
            set(found),
            {"$.access_token", "$.refresh_token", "$.client_secret", "$.private_key"},
        )

    def test_allow_email_cli_subcommand(self):
        with patch.object(sys, "argv", ["storage", "allow-email", "user@example.com"]), \
             patch.object(storage_main, "allow_email") as mocked:
            storage_main.command_line()
        mocked.assert_called_once_with("user@example.com")

    def test_remove_email_cli_subcommand(self):
        with patch.object(sys, "argv", ["storage", "remove-email", "user@example.com"]), \
             patch.object(storage_main, "remove_email") as mocked:
            storage_main.command_line()
        mocked.assert_called_once_with("user@example.com")

    def test_allowed_emails_cli_subcommand(self):
        with patch.object(sys, "argv", ["storage", "allowed-emails"]), \
             patch.object(storage_main, "show_allowed_emails") as mocked:
            storage_main.command_line()
        mocked.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
