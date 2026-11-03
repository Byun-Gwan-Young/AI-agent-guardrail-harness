"""Storage persistence-boundary safety checks.

This module is intentionally self-contained: Storage should not depend on the
legacy service database layer just to decide whether a JSON value is safe to
persist.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

# Keys that directly carry model/user text or raw provider traffic.
_FORBIDDEN_TEXT_KEYS = {
    "narrative",
    "reasoning_content",
    "thought",
    "thoughts",
    "content",
    "messages",
    "request_body",
    "response_body",
    "upstream_request_body",
    "upstream_response_body",
    "raw_request",
    "raw_response",
}

# Values under these keys are credentials by definition, regardless of format.
_FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "x-api-key",
    "x_api_key",
    "x-guardrail-key",
    "x_guardrail_key",
    "guardrail_key",
    "llm_api_key",
    "provider_key",
    "password",
    "passwd",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "oauth_token",
    "session_token",
    "private_key",
}

_SECRET_PATTERNS = {
    "groq_key": re.compile(r"\bgsk_[A-Za-z0-9_-]{8,}\b"),
    "bearer_value": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}\b", re.IGNORECASE),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "tavily_key": re.compile(r"\btvly-[A-Za-z0-9_-]{8,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "github_token": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    "guardrail_key": re.compile(r"\bgk_[A-Za-z0-9]{8}_[A-Za-z0-9_-]{20,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}

# If one of these environment values is present, treat the literal value as a
# secret too.  The value itself is never included in an exception message.
_SECRET_ENVS = (
    "KMU_API_KEY",
    "TAVILY_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "GUARDRAIL_KEY",
    "POSTGRES_PASSWORD",
    "GUARDRAIL_DB_URL",
)

_SECRET_KEY_SUFFIXES = (
    "_api_key",
    "_apikey",
    "_password",
    "_passwd",
    "_token",
    "_secret",
    "_private_key",
)


def _normalized_key_name(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


def _is_secret_key_name(key: Any) -> bool:
    normalized = _normalized_key_name(key)
    return (
        normalized in {name.replace("-", "_") for name in _FORBIDDEN_SECRET_KEYS}
        or normalized.endswith(_SECRET_KEY_SUFFIXES)
    )


def secret_fields(value: Any, path: str = "$") -> list[str]:
    """Return paths whose field names are credential-shaped.

    This deliberately checks names, not only known secret *values*. Provider or
    deployment credentials can use a previously unseen format, so fields such as
    ``provider_api_key`` or ``POSTGRES_PASSWORD`` must still be rejected.
    """

    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}"
            if _is_secret_key_name(key):
                found.append(here)
            found.extend(secret_fields(item, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(secret_fields(item, f"{path}[{index}]"))
    return found


def forbidden_fields(value: Any, path: str = "$") -> list[str]:
    """Return paths that would persist raw model/user text or credentials.

    A few historic demo metric objects use ``prompt``/``completion`` as token
    counts, so those names are rejected only when they carry non-numeric data.
    ``reasoning`` is likewise allowed only as a numeric token count or null.
    """

    found: list[str] = []

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            here = f"{path}.{key_text}"

            if lowered in _FORBIDDEN_TEXT_KEYS:
                found.append(here)
            elif _is_secret_key_name(key_text):
                found.append(here)
            elif lowered == "reasoning" and not (
                item is None or (isinstance(item, int) and not isinstance(item, bool))
            ):
                found.append(here)
            elif lowered in {"prompt", "completion"} and not (
                item is None or (isinstance(item, (int, float)) and not isinstance(item, bool))
            ):
                found.append(here)

            found.extend(forbidden_fields(item, here))

    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(forbidden_fields(item, f"{path}[{index}]"))

    return found


def secret_hits(value: Any) -> list[str]:
    """Return only secret *types*, never the secret value itself."""

    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    hits = [name for name, pattern in _SECRET_PATTERNS.items() if pattern.search(text)]

    for env_name in _SECRET_ENVS:
        env_value = os.environ.get(env_name)
        if env_value and env_value in text:
            hits.append(f"env:{env_name}")

    # Keep deterministic, duplicate-free messages.
    return sorted(set(hits))


def assert_safe_storage_json(value: Any, label: str) -> None:
    """Reject a JSON-like value that crosses the Storage persistence boundary."""

    fields = forbidden_fields(value)
    if fields:
        preview = fields[:5]
        suffix = "" if len(fields) <= 5 else f" ... (+{len(fields) - 5} more)"
        raise ValueError(
            f"{label}에 저장 금지된 모델/요청/비밀 필드가 있습니다: {preview}{suffix}"
        )

    hits = secret_hits(value)
    if hits:
        raise ValueError(f"{label}에서 비밀값 패턴이 발견되었습니다: {hits}")


def assert_no_secrets(value: Any, label: str) -> None:
    """Reject credential-shaped fields and known/literal secret values.

    Trusted configuration may contain normal task text, so this helper does not
    apply the raw-model-text field ban. It still rejects credential field names
    because unknown provider key formats cannot be detected from value patterns
    alone.
    """

    fields = secret_fields(value)
    if fields:
        preview = fields[:5]
        suffix = "" if len(fields) <= 5 else f" ... (+{len(fields) - 5} more)"
        raise ValueError(f"{label}에 비밀 필드가 있습니다: {preview}{suffix}")

    hits = secret_hits(value)
    if hits:
        raise ValueError(f"{label}에서 비밀값 패턴이 발견되었습니다: {hits}")
