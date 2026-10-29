"""Opt-in durable-first PostgreSQL -> Redis metadata adapter.

This adapter does NOT modify any existing storage.live public function or the
legacy proxy/JSON session store. Backends may deliberately opt in after they
have verified caller authorization and agreed on the chosen display rule.

All durable writes happen in storage.live first. Cache errors are warnings only.
A cache miss is rehydrated using *committed live PostgreSQL facts*, never by
pretending to start another session. The Redis result is display-only and must
never determine whether the proxy blocks, ends, or resumes an agent execution.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from storage import live
from storage.db import get_connection
from storage.redis_state import RedisLiveStateStore

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_live_snapshot(session_id: str, selected_rule_id: str | None = None) -> dict[str, Any] | None:
    """Consistent, sanitized snapshot from committed PostgreSQL live records.

    The session row's FOR SHARE lock is compatible with reads and serializes
    this read against storage.live's FOR UPDATE guarded child writes and end.
    PostgreSQL does not store raw text in the selected columns.
    This function does NOT check the caller's project/account authorization;
    the backend must authenticate and authorize session access first.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT status, guardrail_mode, ended_at
                   FROM sessions WHERE id = %s AND source = 'live' FOR SHARE""",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            status, mode, ended_at = row
            if status not in ("active", "ended") or mode not in ("observe", "block"):
                raise ValueError("Unsupported durable live state")
            cur.execute("SELECT COALESCE(MAX(step), 0) FROM observations WHERE session_id = %s", (session_id,))
            step = cur.fetchone()[0]
            decision, stagnant_run = None, None
            if selected_rule_id is not None and step > 0:
                cur.execute(
                    """SELECT decision, stagnant_run FROM judgements
                       WHERE session_id = %s AND step = %s AND rule_id = %s""",
                    (session_id, step, selected_rule_id),
                )
                judgement = cur.fetchone()
                if judgement is not None:
                    decision, stagnant_run = judgement
    if status == "ended" and ended_at is None:
        raise ValueError("Durable ended session missing ended_at")
    return {
        "schema_version": 1,
        "session_id": session_id,
        "status": status,
        "mode": mode,
        "step": step,
        "last_decision": decision,
        "stagnant_run": stagnant_run,
        "updated_at": _now(),
        "ended_at": (ended_at.isoformat() if hasattr(ended_at, "isoformat") else str(ended_at))
                    if status == "ended" else None,
    }


class RedisLiveAdapter:
    """Opt-in replacement *at a backend call site*, not a global patch.

    The backend must pass exactly one ``selected_rule_id`` display policy to
    RedisLiveStateStore. Leaving it unset stores only status/step metadata.
    For an async API, call these synchronous methods via a worker thread.
    """

    def __init__(self, cache: RedisLiveStateStore) -> None:
        self.cache = cache

    def _refresh_cache(self, session_id: str) -> None:
        try:
            self.cache.reconcile_from_reader(
                session_id,
                lambda: read_live_snapshot(session_id, self.cache.selected_rule_id),
            )
        except Exception:
            # This happens after a successful DB commit. Do not turn a durable
            # success into a 500 or leak URL, credentials or query data.
            logger.warning("Optional Redis refresh failed; durable result preserved")

    def _persist_then_refresh(self, fn, session_id: str, *args, **kwargs):
        result = fn(*args, **kwargs)  # May raise: PostgreSQL failures MUST propagate.
        self._refresh_cache(session_id)
        return result  # Unmodified backend/Storage response shape.

    def start_live_session(self, project_id, session_id, scenario_key, scenario_hash,
                           mode, model, execution_config):
        return self._persist_then_refresh(
            live.start_live_session, session_id,
            project_id, session_id, scenario_key, scenario_hash, mode, model, execution_config,
        )

    def add_observation(self, session_id, step, agent_id, observation_data):
        return self._persist_then_refresh(
            live.add_observation, session_id, session_id, step, agent_id, observation_data,
        )

    def add_judgement(self, session_id, step, agent_id, decision, rule_id,
                      progress_state, stagnant_run, reason, judgement_ns, result_data):
        return self._persist_then_refresh(
            live.add_judgement, session_id,
            session_id, step, agent_id, decision, rule_id, progress_state,
            stagnant_run, reason, judgement_ns, result_data,
        )

    def add_llm_call(self, session_id, call_index, step, agent_id, prompt_tokens,
                     completion_tokens, reasoning_tokens, latency_ms, status_code,
                     retry_count=None, tool_call_count=None):
        # No Redis metadata depends on the LLM call; leave it PostgreSQL-only.
        return live.add_llm_call(
            session_id, call_index, step, agent_id, prompt_tokens, completion_tokens,
            reasoning_tokens, latency_ms, status_code, retry_count, tool_call_count,
        )

    def end_live_session(self, session_id, termination_reason, steps_reached,
                         total_tokens, first_stop_step):
        return self._persist_then_refresh(
            live.end_live_session, session_id, session_id, termination_reason,
            steps_reached, total_tokens, first_stop_step,
        )

    def get_session_progress(self, session_id, after_step):
        # Preserve the existing step-cursor limitation and return shape.
        return live.get_session_progress(session_id, after_step)

    def get_state(self, session_id: str) -> dict[str, Any] | None:
        """Best-effort cache read; on miss/Redis outage return durable snapshot.

        This endpoint must be protected by backend authorization. Do not use
        the returned last_decision as the proxy's historical STOP decision.
        """
        try:
            cached = self.cache.get_session(session_id)
            if cached is not None:
                return cached
        except Exception:
            logger.warning("Optional Redis read unavailable; using durable state")
        try:
            # WATCH must precede the PostgreSQL read; a conflicting Redis
            # update/deletion forces a *new* durable snapshot on retry.
            return self.cache.reconcile_from_reader(
                session_id,
                lambda: read_live_snapshot(session_id, self.cache.selected_rule_id),
            )
        except Exception:
            logger.warning("Optional Redis rebuild unavailable; using durable state")
            return read_live_snapshot(session_id, self.cache.selected_rule_id)

    def get_authoritative_state(self, session_id: str) -> dict[str, Any] | None:
        """Always query PostgreSQL when a decision needs durable state."""
        return read_live_snapshot(session_id, self.cache.selected_rule_id)
