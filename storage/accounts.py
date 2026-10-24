"""Account/project/API-key persistence boundary.

Intent
------
This module stores *already verified* account identity and project ownership
metadata.  It does NOT perform Google OAuth/token verification itself; the
Backend/auth layer must verify Google identity and the allow-list decision
before calling ``upsert_user_from_google``.

Security contract
-----------------
- Raw Guardrail API keys are returned only at issue time; PostgreSQL stores
  SHA-256 + prefix, never the raw key.
- Provider API keys/credentials are never persisted here.
- ``provider`` is a semantic provider choice; ``upstream_url`` is the resolved
  routing endpoint.
- User-owned project operations must enforce ownership and hide other users'
  resources as not-found.
- Model/user text, prompts, responses, narratives, and reasoning text do not
  belong in account/auth metadata.

See ``storage/README.md`` for the complete maintainer/AI handoff contract.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import re
import socket
from typing import Any

import psycopg
from urllib.parse import parse_qsl, urlsplit

from psycopg.types.json import Jsonb

from storage.db import get_connection
from storage.safety import assert_no_secrets, assert_safe_storage_json


VALID_PROJECT_MODES = {"observe", "block"}

# Provider/upstream split
# -----------------------
# projects.provider is the user-facing semantic choice (kmu/groq/openai/custom).
# projects.upstream_url is the resolved routing endpoint consumed by the proxy.
# Keeping upstream_url preserves the existing proxy/service contract while users
# no longer need to understand or type provider URLs for normal providers.
# Provider credentials/API keys are NEVER stored here.
DEFAULT_RULE_ID = os.getenv("GUARDRAIL_DEFAULT_RULE_ID", "deadlock-v0.3")
DEFAULT_PROVIDER_ENV = "GUARDRAIL_DEFAULT_PROVIDER"
DEFAULT_UPSTREAM_URL_ENV = "GUARDRAIL_DEFAULT_UPSTREAM_URL"  # legacy/custom fallback
PROVIDER_URL_ENV_PREFIX = "GUARDRAIL_PROVIDER_"
CUSTOM_PROVIDER_ENABLED_ENV = "GUARDRAIL_ALLOW_CUSTOM_PROVIDER"
_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

# Public providers have stable OpenAI-compatible base URLs.  KMU intentionally
# has no hard-coded address because the school endpoint is deployment-specific.
_BUILTIN_PROVIDER_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
}

_CREDENTIAL_QUERY_KEYS = {
    "key",
    "token",
    "secret",
    "auth",
    "authorization",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "client_secret",
    "subscription_key",
    "x_api_key",
}


def _normalize_provider(provider: str) -> str:
    value = (provider or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(value):
        raise ValueError("provider must use lowercase letters, numbers, '_' or '-'")
    return value


def _validate_upstream_url(value: str, label: str = "upstream URL") -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        raise ValueError(f"{label} is required")
    assert_no_secrets(value, label)

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not contain credentials")
    if parsed.fragment:
        # Fragments are not sent to the upstream HTTP server and have no routing
        # value here. Reject them so credentials cannot be hidden in persistent
        # URL metadata such as #api_key=... .
        raise ValueError(f"{label} must not contain a URL fragment")

    # Unknown/custom provider keys may not match one of our literal secret
    # patterns. Block credential-shaped query parameter names as well so a URL
    # such as ?api_key=<new-format-key> can never become persistent metadata.
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.strip().lower().replace("-", "_")
        if (
            normalized in _CREDENTIAL_QUERY_KEYS
            or normalized.endswith("_key")
            or normalized.endswith("_token")
            or normalized.endswith("_secret")
        ):
            raise ValueError(f"{label} must not contain credential query parameters")
    return value


def _provider_url_env_name(provider: str) -> str:
    return f"{PROVIDER_URL_ENV_PREFIX}{provider.upper().replace('-', '_')}_URL"


def _custom_provider_enabled() -> bool:
    """Return whether server configuration explicitly enables custom endpoints."""
    return os.getenv(CUSTOM_PROVIDER_ENABLED_ENV, "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _require_custom_provider_enabled() -> None:
    if not _custom_provider_enabled():
        raise RuntimeError(
            f"custom provider is disabled; set {CUSTOM_PROVIDER_ENABLED_ENV}=1 on the server to enable it"
        )


def _validate_public_custom_target(value: str, label: str = "custom upstream URL") -> str:
    """Validate a custom provider endpoint against SSRF-prone network targets.

    This is a configuration-time admission check.  It requires the custom
    provider feature flag and rejects any literal or DNS-resolved address that
    is not globally routable (including loopback, private, link-local,
    unspecified, multicast, and reserved ranges).

    The proxy/network layer should still enforce outbound protections at
    request time to cover redirects and DNS rebinding after configuration.
    """
    _require_custom_provider_enabled()
    clean = _validate_upstream_url(value, label)
    parsed = urlsplit(clean)
    host = parsed.hostname
    if not host:
        raise ValueError(f"{label} must include a hostname")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} contains an invalid port") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        addresses.add(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"{label} hostname must resolve") from exc
        for info in infos:
            raw = info[4][0].split("%", 1)[0]
            try:
                addresses.add(ipaddress.ip_address(raw))
            except ValueError:
                raise ValueError(f"{label} hostname resolved to an invalid address") from None

    if not addresses:
        raise ValueError(f"{label} hostname must resolve")
    if any(not address.is_global for address in addresses):
        raise ValueError(
            f"{label} must resolve only to public addresses; loopback/private/link-local targets are forbidden"
        )
    return clean


def _resolve_provider_upstream(provider: str, upstream_url: str | None = None) -> tuple[str, str]:
    """Resolve a provider choice to the concrete proxy routing URL.

    Named providers get their endpoint from server configuration (or a stable
    built-in public endpoint).  Only provider='custom' accepts a caller-supplied
    URL.  This keeps endpoint plumbing separate from the user's provider choice.
    """
    provider = _normalize_provider(provider)

    if upstream_url is not None:
        if provider != "custom":
            raise ValueError("upstream_url may be supplied only for provider='custom'")
        return provider, _validate_public_custom_target(upstream_url, "custom upstream URL")

    configured = os.getenv(_provider_url_env_name(provider), "").strip()
    if configured:
        if provider == "custom":
            return provider, _validate_public_custom_target(
                configured, "custom upstream URL"
            )
        return provider, _validate_upstream_url(configured, f"{provider} upstream URL")

    builtin = _BUILTIN_PROVIDER_URLS.get(provider)
    if builtin:
        return provider, builtin

    if provider == "custom":
        raise RuntimeError("custom provider requires an explicit upstream_url")

    env_name = _provider_url_env_name(provider)
    raise RuntimeError(f"{env_name} must be configured for provider '{provider}'")


def _get_default_provider_config() -> tuple[str, str]:
    """Return (provider, upstream_url) for create_project().

    New deployments should set GUARDRAIL_DEFAULT_PROVIDER.  The old
    GUARDRAIL_DEFAULT_UPSTREAM_URL remains as a compatibility fallback and is
    interpreted as provider='custom'; this avoids breaking existing deployments.
    """
    provider = os.getenv(DEFAULT_PROVIDER_ENV, "").strip()
    if provider:
        return _resolve_provider_upstream(provider)

    legacy_url = os.getenv(DEFAULT_UPSTREAM_URL_ENV, "").strip()
    if legacy_url:
        return "custom", _validate_public_custom_target(
            legacy_url, "default upstream URL"
        )

    raise RuntimeError(
        "GUARDRAIL_DEFAULT_PROVIDER (preferred) or GUARDRAIL_DEFAULT_UPSTREAM_URL "
        "must be configured before creating a project"
    )


def _get_default_upstream_url() -> str:
    """Compatibility helper retained for existing callers/tests."""
    return _get_default_provider_config()[1]


def _normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not value:
        raise ValueError("email is required")
    return value


def _validate_mode(mode: str) -> str:
    value = (mode or "").strip().lower()
    if value not in VALID_PROJECT_MODES:
        raise ValueError("mode must be 'observe' or 'block'")
    return value


def _validate_user_id(user_id: int) -> int:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise ValueError("user_id must be a positive integer")
    return user_id


def _row_dict(cursor, row):
    if row is None:
        return None
    names = [column.name for column in cursor.description]
    return dict(zip(names, row))


def _rows_dict(cursor):
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]



def _require_active_account_cursor(cursor, user_id: int, *, lock: bool = False) -> None:
    """Allow normal service operations only for an active account.

    Mutating operations pass ``lock=True`` so the user row is held with
    ``FOR SHARE`` until the transaction ends. Account deletion/purge uses
    ``FOR UPDATE`` on the same row, which serializes the state transition
    before any project/key write can commit after a completed withdrawal.
    """
    user_id = _validate_user_id(user_id)
    lock_clause = " FOR SHARE" if lock else ""

    cursor.execute(
        f"""
        SELECT account_status
        FROM users
        WHERE id = %s{lock_clause}
        """,
        (user_id,),
    )
    row = cursor.fetchone()

    if row is None:
        raise LookupError("user not found")

    if row[0] != "active":
        raise RuntimeError("account is pending deletion")




def _record_auth_event_cursor(cursor, kind: str, user_id: int | None, detail: Any) -> None:
    if not kind or not str(kind).strip():
        raise ValueError("kind is required")

    clean_kind = str(kind).strip()
    safe_detail = detail if detail is not None else {}

    # auth_events is still a Storage persistence boundary.  A caller must not
    # accidentally turn the audit log into a place that stores raw API keys,
    # provider credentials, prompts, responses, or reasoning text.
    assert_no_secrets(clean_kind, "auth event kind")
    assert_safe_storage_json(safe_detail, "auth event detail")

    cursor.execute(
        """
        INSERT INTO auth_events (kind, user_id, detail)
        VALUES (%s, %s, %s)
        """,
        (clean_kind, user_id, Jsonb(safe_detail)),
    )


def record_auth_event(kind, user_id, detail):
    """Record an authentication/account audit event."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            _record_auth_event_cursor(cursor, kind, user_id, detail)


def upsert_user_from_google(google_sub, email, name):
    """Create/update a Google-authenticated user and refresh last_login_at."""
    google_sub = (google_sub or "").strip()
    if not google_sub:
        raise ValueError("google_sub is required")

    email = _normalize_email(email)
    clean_name = name.strip() if isinstance(name, str) else name

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (google_sub, email, name, last_login_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (google_sub)
                DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    last_login_at = CURRENT_TIMESTAMP
                RETURNING
                    id,
                    google_sub,
                    email,
                    name,
                    created_at,
                    last_login_at,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at
                """,
                (google_sub, email, clean_name),
            )
            user = _row_dict(cursor, cursor.fetchone())
            _record_auth_event_cursor(
                cursor,
                "google_login",
                user["id"],
                {"provider": "google"},
            )
            return user



def get_account_status(user_id):
    """Return account deletion state without exposing unrelated account data."""
    user_id = _validate_user_id(user_id)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )

            account = _row_dict(cursor, cursor.fetchone())
            if account is None:
                raise LookupError("user not found")

            return account


def request_account_deletion(user_id):
    """Start the 30-day deletion grace period and revoke all owned API keys.

    Repeating the request does not extend deletion_due_at.
    """
    user_id = _validate_user_id(user_id)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Serialize deletion/restore requests for this account.
            cursor.execute(
                """
                SELECT
                    id,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at
                FROM users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )

            account = _row_dict(cursor, cursor.fetchone())
            if account is None:
                raise LookupError("user not found")

            already_pending = account["account_status"] == "pending_deletion"

            if account["account_status"] == "active":
                cursor.execute(
                    """
                    UPDATE users
                    SET
                        account_status = 'pending_deletion',
                        deletion_requested_at = CURRENT_TIMESTAMP,
                        deletion_due_at = CURRENT_TIMESTAMP + INTERVAL '30 days'
                    WHERE id = %s
                    RETURNING
                        id,
                        account_status,
                        deletion_requested_at,
                        deletion_due_at
                    """,
                    (user_id,),
                )
                account = _row_dict(cursor, cursor.fetchone())

            elif account["account_status"] != "pending_deletion":
                raise RuntimeError("unsupported account status")

            # A withdrawal request immediately disables every Guardrail API key
            # belonging to the user's projects.
            cursor.execute(
                """
                UPDATE api_keys AS k
                SET revoked_at = COALESCE(k.revoked_at, CURRENT_TIMESTAMP)
                FROM projects AS p
                WHERE p.id = k.project_id
                  AND p.owner_user_id = %s
                  AND k.revoked_at IS NULL
                RETURNING k.id
                """,
                (user_id,),
            )

            revoked_key_count = len(cursor.fetchall())

            if not already_pending:
                _record_auth_event_cursor(
                    cursor,
                    "account_deletion_requested",
                    user_id,
                    {"revoked_api_key_count": revoked_key_count},
                )

            account["already_pending"] = already_pending
            account["revoked_api_key_count"] = revoked_key_count
            return account


def restore_account(user_id):
    """Restore an account only while its 30-day grace period is still open.

    Previously revoked API keys remain revoked.
    """
    user_id = _validate_user_id(user_id)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at
                FROM users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )

            account = _row_dict(cursor, cursor.fetchone())
            if account is None:
                raise LookupError("user not found")

            if account["account_status"] == "active":
                account["already_active"] = True
                return account

            if account["account_status"] != "pending_deletion":
                raise RuntimeError("unsupported account status")

            cursor.execute(
                """
                UPDATE users
                SET
                    account_status = 'active',
                    deletion_requested_at = NULL,
                    deletion_due_at = NULL
                WHERE id = %s
                  AND account_status = 'pending_deletion'
                  AND CURRENT_TIMESTAMP < deletion_due_at
                RETURNING
                    id,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at
                """,
                (user_id,),
            )

            restored = _row_dict(cursor, cursor.fetchone())

            if restored is None:
                raise RuntimeError("account deletion grace period has expired")

            _record_auth_event_cursor(
                cursor,
                "account_restored",
                user_id,
                {},
            )

            restored["already_active"] = False
            return restored



def preview_account_purge(user_id):
    """Return what a final account purge would delete without deleting anything."""
    user_id = _validate_user_id(user_id)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    email,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at,
                    (
                        deletion_due_at IS NOT NULL
                        AND CURRENT_TIMESTAMP >= deletion_due_at
                    ) AS deletion_due
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )

            user = _row_dict(cursor, cursor.fetchone())
            if user is None:
                raise LookupError("user not found")

            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE owner_user_id = %s
                ORDER BY id
                """,
                (user_id,),
            )
            project_ids = [row[0] for row in cursor.fetchall()]

            cursor.execute(
                """
                WITH owned_projects AS (
                    SELECT id
                    FROM projects
                    WHERE owner_user_id = %s
                ),
                owned_scenarios AS (
                    SELECT s.id
                    FROM scenarios AS s
                    JOIN owned_projects AS p
                      ON p.id = s.project_id
                ),
                owned_sessions AS (
                    SELECT s.id
                    FROM sessions AS s
                    JOIN owned_scenarios AS sc
                      ON sc.id = s.scenario_id
                )
                SELECT
                    (SELECT COUNT(*) FROM owned_projects) AS projects,
                    (
                        SELECT COUNT(*)
                        FROM api_keys AS k
                        JOIN owned_projects AS p
                          ON p.id = k.project_id
                    ) AS api_keys,
                    (SELECT COUNT(*) FROM owned_scenarios) AS scenarios,
                    (SELECT COUNT(*) FROM owned_sessions) AS sessions,
                    (
                        SELECT COUNT(*)
                        FROM observations AS o
                        JOIN owned_sessions AS s
                          ON s.id = o.session_id
                    ) AS observations,
                    (
                        SELECT COUNT(*)
                        FROM judgements AS j
                        JOIN owned_sessions AS s
                          ON s.id = j.session_id
                    ) AS judgements,
                    (
                        SELECT COUNT(*)
                        FROM llm_calls AS l
                        JOIN owned_sessions AS s
                          ON s.id = l.session_id
                    ) AS llm_calls,
                    (
                        SELECT COUNT(*)
                        FROM auth_events AS a
                        WHERE a.user_id = %s
                           OR (
                               a.user_id IS NULL
                               AND LOWER(a.detail ->> 'email') = LOWER(%s)
                           )
                    ) AS auth_events,
                    (
                        SELECT COUNT(*)
                        FROM allowed_emails AS ae
                        WHERE LOWER(ae.email) = LOWER(%s)
                    ) AS allowed_emails
                """,
                (
                    user_id,
                    user_id,
                    user["email"],
                    user["email"],
                ),
            )

            counts = _row_dict(cursor, cursor.fetchone())

            return {
                "user_id": user["id"],
                "account_status": user["account_status"],
                "deletion_requested_at": user["deletion_requested_at"],
                "deletion_due_at": user["deletion_due_at"],
                "deletion_due": bool(user["deletion_due"]),
                "project_ids": project_ids,
                "counts": counts,
            }



def purge_account(user_id):
    """Permanently delete one account whose 30-day grace period has expired.

    All user-owned project/runtime data and identifiable account metadata are
    removed in one transaction. The canonical demo project must never be owned
    by a user or included in this purge.
    """
    user_id = _validate_user_id(user_id)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Serialize purge against restore/deletion-state changes.
            cursor.execute(
                """
                SELECT
                    id,
                    email,
                    account_status,
                    deletion_requested_at,
                    deletion_due_at
                FROM users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )

            user = _row_dict(cursor, cursor.fetchone())
            if user is None:
                raise LookupError("user not found")

            if user["account_status"] != "pending_deletion":
                raise RuntimeError("account is not pending deletion")

            # PostgreSQL server time is the authority.
            cursor.execute(
                """
                SELECT CURRENT_TIMESTAMP >= %s
                """,
                (user["deletion_due_at"],),
            )
            if not bool(cursor.fetchone()[0]):
                raise RuntimeError("account deletion grace period has not expired")

            # Lock all owned projects so their ownership/runtime tree cannot change
            # while the purge is selecting and deleting its descendants.
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE owner_user_id = %s
                ORDER BY id
                FOR UPDATE
                """,
                (user_id,),
            )
            project_ids = [row[0] for row in cursor.fetchall()]

            # Lock owned sessions before deleting child rows. This serializes purge
            # against live observation/judgement/LLM-call writers.
            cursor.execute(
                """
                SELECT s.id
                FROM sessions AS s
                JOIN scenarios AS sc
                  ON sc.id = s.scenario_id
                JOIN projects AS p
                  ON p.id = sc.project_id
                WHERE p.owner_user_id = %s
                ORDER BY s.id
                FOR UPDATE OF s
                """,
                (user_id,),
            )
            cursor.fetchall()

            deleted = {}

            cursor.execute(
                """
                DELETE FROM llm_calls AS l
                USING sessions AS s,
                      scenarios AS sc,
                      projects AS p
                WHERE l.session_id = s.id
                  AND s.scenario_id = sc.id
                  AND sc.project_id = p.id
                  AND p.owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["llm_calls"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM judgements AS j
                USING sessions AS s,
                      scenarios AS sc,
                      projects AS p
                WHERE j.session_id = s.id
                  AND s.scenario_id = sc.id
                  AND sc.project_id = p.id
                  AND p.owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["judgements"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM observations AS o
                USING sessions AS s,
                      scenarios AS sc,
                      projects AS p
                WHERE o.session_id = s.id
                  AND s.scenario_id = sc.id
                  AND sc.project_id = p.id
                  AND p.owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["observations"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM sessions AS s
                USING scenarios AS sc,
                      projects AS p
                WHERE s.scenario_id = sc.id
                  AND sc.project_id = p.id
                  AND p.owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["sessions"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM scenarios AS sc
                USING projects AS p
                WHERE sc.project_id = p.id
                  AND p.owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["scenarios"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM api_keys AS k
                USING projects AS p
                WHERE k.project_id = p.id
                  AND p.owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["api_keys"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM projects
                WHERE owner_user_id = %s
                """,
                (user_id,),
            )
            deleted["projects"] = cursor.rowcount

            # Remove identifiable audit records. user_id-linked records belong to
            # this account; user-less allow-list events are matched structurally
            # through detail.email rather than broad JSON/text searching.
            cursor.execute(
                """
                DELETE FROM auth_events
                WHERE user_id = %s
                   OR (
                       user_id IS NULL
                       AND LOWER(detail ->> 'email') = LOWER(%s)
                   )
                """,
                (user_id, user["email"]),
            )
            deleted["auth_events"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM allowed_emails
                WHERE LOWER(email) = LOWER(%s)
                """,
                (user["email"],),
            )
            deleted["allowed_emails"] = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            deleted["users"] = cursor.rowcount

            if deleted["users"] != 1:
                raise RuntimeError("account purge failed to delete exactly one user")

            return {
                "user_id": user_id,
                "project_ids": project_ids,
                "deleted": deleted,
            }



def purge_due_accounts(limit=100):
    """Purge accounts whose deletion grace period has expired.

    Each account is purged in its own transaction through purge_account().
    A failure for one account does not roll back successful purges for others.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")

    # Candidate discovery is intentionally separate from deletion.
    # purge_account() locks and re-validates every user before deleting.
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE account_status = 'pending_deletion'
                  AND deletion_due_at IS NOT NULL
                  AND CURRENT_TIMESTAMP >= deletion_due_at
                ORDER BY deletion_due_at, id
                LIMIT %s
                """,
                (limit,),
            )
            user_ids = [row[0] for row in cursor.fetchall()]

    purged = []
    failed = []

    for user_id in user_ids:
        try:
            result = purge_account(user_id)
            purged.append(result)
        except (LookupError, RuntimeError) as exc:
            # Another request may have restored/deleted this user after candidate
            # discovery. Keep each account independent and report the failure.
            failed.append(
                {
                    "user_id": user_id,
                    "error": str(exc),
                }
            )
        except psycopg.Error as exc:
            # One user's FK/constraint/lock failure must not abort the whole
            # maintenance batch. Do not expose the database error text because it
            # may contain connection or schema details. purge_account() owns its
            # transaction, so a failed user's partial deletes are rolled back.
            failed.append(
                {
                    "user_id": user_id,
                    "error": "database error during account purge",
                    "error_type": type(exc).__name__,
                }
            )

    return {
        "candidate_count": len(user_ids),
        "purged_count": len(purged),
        "failed_count": len(failed),
        "purged": purged,
        "failed": failed,
    }




def is_email_allowed(email):
    """Return whether an email is present in the case-insensitive allow-list."""
    email = _normalize_email(email)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM allowed_emails
                    WHERE LOWER(email) = LOWER(%s)
                )
                """,
                (email,),
            )
            return bool(cursor.fetchone()[0])


def allow_email(email):
    """Add an email to the allow-list. Re-adding it is harmless."""
    email = _normalize_email(email)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO allowed_emails (email)
                VALUES (%s)
                ON CONFLICT DO NOTHING
                """,
                (email,),
            )
            _record_auth_event_cursor(
                cursor,
                "allow_email",
                None,
                {"email": email},
            )


def remove_email(email):
    """Remove an email from the allow-list. Missing rows are harmless."""
    email = _normalize_email(email)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM allowed_emails
                WHERE LOWER(email) = LOWER(%s)
                """,
                (email,),
            )
            _record_auth_event_cursor(
                cursor,
                "remove_email",
                None,
                {"email": email},
            )


def list_allowed_emails():
    """Return the allow-list without exposing unrelated account data."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT email, created_at
                FROM allowed_emails
                ORDER BY LOWER(email), created_at
                """
            )
            return _rows_dict(cursor)







def create_project(owner_user_id, name, mode):
    """Create a user-owned Guardrail project."""
    if isinstance(owner_user_id, bool) or not isinstance(owner_user_id, int) or owner_user_id < 1:
        raise ValueError("owner_user_id must be a positive integer")

    mode = _validate_mode(mode)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("project name is required")
    assert_no_secrets(clean_name, "project name")
    provider, upstream_url = _get_default_provider_config()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, owner_user_id, lock=True)

            cursor.execute(
                """
                INSERT INTO projects (
                    name,
                    mode,
                    rule_id,
                    provider,
                    upstream_url,
                    owner_user_id,
                    read_only
                )
                VALUES (%s, %s, %s, %s, %s, %s, FALSE)
                RETURNING
                    id, name, mode, rule_id, provider, upstream_url,
                    owner_user_id, read_only, created_at
                """,
                (
                    clean_name,
                    mode,
                    DEFAULT_RULE_ID,
                    provider,
                    upstream_url,
                    owner_user_id,
                ),
            )
            project = _row_dict(cursor, cursor.fetchone())
            _record_auth_event_cursor(
                cursor,
                "project_created",
                owner_user_id,
                {"project_id": project["id"], "mode": mode, "provider": provider},
            )
            return project


def list_projects(user_id):
    """Return the user's projects plus system-owned read-only demo projects."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, user_id)
            cursor.execute(
                """
                SELECT
                    id, name, mode, rule_id, provider, upstream_url,
                    owner_user_id, read_only, created_at
                FROM projects
                WHERE owner_user_id = %s
                   OR (owner_user_id IS NULL AND read_only = TRUE)
                ORDER BY read_only DESC, id
                """,
                (user_id,),
            )
            return _rows_dict(cursor)


def _owned_project(cursor, project_id, user_id):
    cursor.execute(
        """
        SELECT
            id, name, mode, rule_id, upstream_url,
            owner_user_id, read_only, created_at
        FROM projects
        WHERE id = %s
          AND owner_user_id = %s
          AND read_only = FALSE
        """,
        (project_id, user_id),
    )
    return _row_dict(cursor, cursor.fetchone())


def set_project_mode(project_id, user_id, mode):
    """Change a project mode only when the caller owns that writable project."""
    mode = _validate_mode(mode)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, user_id, lock=True)
            project = _owned_project(cursor, project_id, user_id)
            if project is None:
                # Deliberately do not distinguish "not found" from "not yours".
                raise LookupError("project not found")

            cursor.execute(
                """
                UPDATE projects
                SET mode = %s
                WHERE id = %s
                """,
                (mode, project_id),
            )
            _record_auth_event_cursor(
                cursor,
                "project_mode_changed",
                user_id,
                {"project_id": project_id, "mode": mode},
            )


def set_project_provider(project_id, user_id, provider, upstream_url=None):
    """Change a project's LLM provider while preserving proxy compatibility.

    provider is the user-facing choice. upstream_url is resolved automatically
    for named providers and stored as the concrete proxy routing endpoint.
    Only provider='custom' accepts an explicit upstream_url.
    """
    provider, resolved_url = _resolve_provider_upstream(provider, upstream_url)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, user_id, lock=True)
            project = _owned_project(cursor, project_id, user_id)
            if project is None:
                # Same information-hiding rule as the other project mutators.
                raise LookupError("project not found")

            cursor.execute(
                """
                UPDATE projects
                SET provider = %s, upstream_url = %s
                WHERE id = %s
                RETURNING
                    id, name, mode, rule_id, provider, upstream_url,
                    owner_user_id, read_only, created_at
                """,
                (provider, resolved_url, project_id),
            )
            updated = _row_dict(cursor, cursor.fetchone())
            _record_auth_event_cursor(
                cursor,
                "project_provider_changed",
                user_id,
                {"project_id": project_id, "provider": provider},
            )
            return updated


def _api_key_digest(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _raw_key_prefix(raw_key: str) -> str | None:
    if not isinstance(raw_key, str) or not raw_key.startswith("gk_"):
        return None

    parts = raw_key.split("_", 2)
    if len(parts) != 3 or len(parts[1]) != 8 or not parts[2]:
        return None

    return parts[1]


def issue_api_key(project_id, user_id, name):
    """Issue a key once; only its SHA-256 hash and 8-char prefix are stored."""
    clean_name = name.strip() if isinstance(name, str) else name
    assert_no_secrets(clean_name, "api key name")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, user_id, lock=True)

            project = _owned_project(cursor, project_id, user_id)
            if project is None:
                raise LookupError("project not found")

            # token_hex(4) -> 8 display chars.
            # token_urlsafe(32) is generated from 32 random bytes.
            prefix = secrets.token_hex(4)
            raw_key = f"gk_{prefix}_{secrets.token_urlsafe(32)}"
            digest = _api_key_digest(raw_key)

            cursor.execute(
                """
                INSERT INTO api_keys (
                    project_id,
                    key_hash,
                    key_prefix,
                    name
                )
                VALUES (%s, %s, %s, %s)
                RETURNING
                    id, project_id, key_prefix, name,
                    created_at, last_used_at, revoked_at
                """,
                (project_id, digest, prefix, clean_name),
            )
            info = _row_dict(cursor, cursor.fetchone())
            info["revoked"] = info["revoked_at"] is not None

            _record_auth_event_cursor(
                cursor,
                "api_key_issued",
                user_id,
                {
                    "project_id": project_id,
                    "key_id": info["id"],
                    "key_prefix": prefix,
                    "name": clean_name,
                },
            )

            # raw_key is intentionally returned only here and never persisted.
            return raw_key, info


def list_api_keys(project_id, user_id):
    """List safe key metadata for an owned project; never return raw/hash values."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, user_id)
            project = _owned_project(cursor, project_id, user_id)
            if project is None:
                raise LookupError("project not found")

            cursor.execute(
                """
                SELECT
                    id, project_id, key_prefix, name,
                    created_at, last_used_at, revoked_at,
                    (revoked_at IS NOT NULL) AS revoked
                FROM api_keys
                WHERE project_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (project_id,),
            )
            return _rows_dict(cursor)


def revoke_api_key(key_id, user_id):
    """Revoke a key only when it belongs to one of the caller's projects."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            _require_active_account_cursor(cursor, user_id, lock=True)
            cursor.execute(
                """
                SELECT k.id, k.project_id
                FROM api_keys k
                JOIN projects p ON p.id = k.project_id
                WHERE k.id = %s
                  AND p.owner_user_id = %s
                  AND p.read_only = FALSE
                """,
                (key_id, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                # Deliberately do not distinguish "not found" from "not yours".
                raise LookupError("api key not found")

            project_id = row[1]
            cursor.execute(
                """
                UPDATE api_keys
                SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                WHERE id = %s
                """,
                (key_id,),
            )
            _record_auth_event_cursor(
                cursor,
                "api_key_revoked",
                user_id,
                {"project_id": project_id, "key_id": key_id},
            )


def verify_api_key(raw_key):
    """Return the project for a valid active key, otherwise None.

    Candidate lookup uses the non-secret 8-character prefix. The full SHA-256
    digest comparison is done with hmac.compare_digest() for constant-time
    equality testing.
    """
    prefix = _raw_key_prefix(raw_key)
    if prefix is None:
        return None

    digest = _api_key_digest(raw_key)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    k.id AS key_id,
                    k.key_hash,
                    k.revoked_at,
                    p.id,
                    p.name,
                    p.mode,
                    p.rule_id,
                    p.upstream_url,
                    p.owner_user_id,
                    p.read_only,
                    p.created_at
                FROM api_keys k
                JOIN projects p ON p.id = k.project_id
                LEFT JOIN users u ON u.id = p.owner_user_id
                WHERE k.key_prefix = %s
                  AND (p.owner_user_id IS NULL OR u.account_status = 'active')
                ORDER BY k.id
                """,
                (prefix,),
            )
            candidates = cursor.fetchall()

            for row in candidates:
                stored_digest = row[1]
                if not hmac.compare_digest(stored_digest, digest):
                    continue

                if row[2] is not None:
                    return None

                key_id = row[0]
                cursor.execute(
                    """
                    UPDATE api_keys
                    SET last_used_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND revoked_at IS NULL
                    RETURNING last_used_at
                    """,
                    (key_id,),
                )
                # A concurrent revoke may have committed after the candidate
                # SELECT. The conditional UPDATE is the final authority: if it
                # updated nothing, the key is no longer valid.
                if cursor.fetchone() is None:
                    return None

                return {
                    "id": row[3],
                    "name": row[4],
                    "mode": row[5],
                    "rule_id": row[6],
                    "upstream_url": row[7],
                    "owner_user_id": row[8],
                    "read_only": row[9],
                    "created_at": row[10],
                }

            return None
