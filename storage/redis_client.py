"""Opt-in Redis connection for *local* live-session metadata.

No server is started by importing this module. Redis is a separate service;
GUARDRAIL_REDIS_URL can override the loopback-only development default.
"""

from __future__ import annotations

import os


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


def get_redis_client(url: str | None = None):
    """Return a redis-py client; connect lazily on its first command.

    Never print/log the URL: deployments may configure Redis credentials there.
    """
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("Redis Python client missing: install storage requirements") from exc

    effective_url = url if url is not None else os.environ.get("GUARDRAIL_REDIS_URL", DEFAULT_REDIS_URL)
    if not isinstance(effective_url, str) or not effective_url.strip():
        raise ValueError("GUARDRAIL_REDIS_URL must be a nonempty Redis URL")
    return redis.Redis.from_url(
        effective_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
