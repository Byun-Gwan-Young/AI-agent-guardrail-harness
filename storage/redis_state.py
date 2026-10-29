"""Structured, short-lived Redis metadata for live sessions (opt-in).

NOT a drop-in replacement for proxy.session_store.JsonSessionRepository.
The proxy repository persists full turns including raw request/response text.
Those records must not cross the Storage boundary. This module deliberately
accepts ONLY explicit, bounded fields and does not replay agent execution.

PostgreSQL remains the authoritative, durable record. No proxy/backend writes
are intercepted or mirrored automatically: integration needs a team contract.
All mutations are atomic Redis writes; read/modify/write uses WATCH/MULTI.
A timeout or Redis restart can lose this ephemeral metadata.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from storage.safety import assert_safe_storage_json

try:
    from redis.exceptions import WatchError
except ImportError:  # Allows validation-only/offline unit tests without redis-py.
    class WatchError(Exception):
        pass


_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_DECISION_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
# PostgreSQL rule IDs include dotted versions, e.g. deadlock-v0.3.
_RULE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_PREFIX_RE = re.compile(r"[A-Za-z0-9:_-]{1,96}\Z")
_MODES = frozenset({"observe", "block"})
_STATUSES = frozenset({"active", "ended"})


def _session_id(value: str) -> str:
    # Matches proxy.py X-Guardrail-Session and its generated identifiers.
    if not isinstance(value, str) or not _SESSION_ID_RE.fullmatch(value):
        raise ValueError("session_id must be 1-128 ASCII letters, numbers, _ or -")
    return value


def _step(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("step must be an integer >= 1")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(record: dict[str, Any]) -> str:
    assert_safe_storage_json(record, "redis_live_state")
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode(raw: Any, session_id: str) -> dict[str, Any]:
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Invalid Redis live state") from None
    if (
        not isinstance(record, dict)
        or set(record) != {
            "schema_version", "session_id", "status", "mode", "step",
            "last_decision", "stagnant_run", "updated_at", "ended_at"
        }
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or record["session_id"] != session_id
        or not isinstance(record["status"], str)
        or record["status"] not in _STATUSES
        or not isinstance(record["mode"], str)
        or record["mode"] not in _MODES
        or type(record["step"]) is not int
        or record["step"] < 0
        or (record["last_decision"] is not None and (
            not isinstance(record["last_decision"], str)
            or not _DECISION_RE.fullmatch(record["last_decision"])
        ))
        or (record["stagnant_run"] is not None and (
            type(record["stagnant_run"]) is not int or record["stagnant_run"] < 0
        ))
        or not isinstance(record["updated_at"], str)
        or not record["updated_at"]
        or (record["ended_at"] is not None and not isinstance(record["ended_at"], str))
        or (record["status"] == "active" and record["ended_at"] is not None)
        or (record["status"] == "ended" and not record["ended_at"])
        or (record["last_decision"] is None and record["stagnant_run"] is not None)
        or (record["step"] == 0 and record["last_decision"] is not None)
    ):
        raise ValueError("Invalid Redis live state")
    # Return only the strictly-validated shape; never return arbitrary payloads.
    assert_safe_storage_json(record, "redis_live_state")
    return record


class RedisLiveStateStore:
    """Ephemeral metadata cache; PostgreSQL is still source of truth.

    start_session(): create active state (duplicate is a conflict).
    record_step(): advance the maximum observed step (stale step is a no-op).
    record_judgement(): optionally cache one *selected rule* for current step.
                        Late judgements are explicitly ignored, not rejected.
                        No STOP/blocking decisions may depend on this cache.
    end_session(): mark as ended (idempotent).
    get_session(): inspect state, or None if expired / missing.

    Each successful mutation refreshes the TTL; unchanged retries do not.
    Calls are synchronous; run outside async event loops or in a worker thread.
    Cache miss/expiry is not proof of a new/ended PostgreSQL session.
    When there are multiple judgement rules, select exactly one display rule
    with selected_rule_id and provide rule_id on every judgement call.
    """

    def __init__(self, client: Any, *, ttl_seconds: int = 86400,
                 prefix: str = "guardrail:live:session",
                 selected_rule_id: str | None = None) -> None:
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 2_592_000:
            raise ValueError("ttl_seconds must be between 1 and 2592000")
        if not isinstance(prefix, str) or not _PREFIX_RE.fullmatch(prefix):
            raise ValueError("Invalid Redis key prefix")
        self.client = client
        self.ttl_seconds = ttl_seconds
        if selected_rule_id is not None and (
            not isinstance(selected_rule_id, str) or not _RULE_ID_RE.fullmatch(selected_rule_id)
        ):
            raise ValueError("selected_rule_id must be a short rule identifier")
        self.prefix = prefix
        self.selected_rule_id = selected_rule_id

    def _key(self, session_id: str) -> str:
        # A different display rule must never read another rule's verdict.
        # Rule-less mode keeps its existing key contract for older callers.
        rule_scope = f":rule:{self.selected_rule_id}" if self.selected_rule_id is not None else ""
        return f"{self.prefix}{rule_scope}:{_session_id(session_id)}"

    def start_session(self, session_id: str, mode: str) -> dict[str, Any]:
        key = self._key(session_id)
        if not isinstance(mode, str) or mode not in _MODES:
            raise ValueError("mode must be 'observe' or 'block'")
        record = {
            "schema_version": 1,
            "session_id": session_id,
            "status": "active",
            "mode": mode,
            "step": 0,
            "last_decision": None,
            "stagnant_run": None,
            "updated_at": _utc_now(),
            "ended_at": None,
        }
        if not self.client.set(key, _encode(record), nx=True, ex=self.ttl_seconds):
            raise ValueError("Redis live session already exists")
        return record

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        raw = self.client.get(self._key(session_id))
        return None if raw is None else _decode(raw, session_id)

    def _mutate(self, session_id: str, change: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        """CAS: change mutates a private dict and returns whether anything changed."""
        key = self._key(session_id)
        for _ in range(5):
            try:
                with self.client.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    if raw is None:
                        raise LookupError("Redis live session not found or expired")
                    record = _decode(raw, session_id)
                    if not change(record):
                        return record
                    record["updated_at"] = _utc_now()
                    pipe.multi()
                    pipe.set(key, _encode(record), ex=self.ttl_seconds)
                    pipe.execute()
                    return record
            except WatchError:
                continue
        raise RuntimeError("Concurrent Redis live state update; retry the operation")

    def record_step(self, session_id: str, step: int) -> dict[str, Any]:
        _step(step)

        def change(record: dict[str, Any]) -> bool:
            if record["status"] != "active":
                raise ValueError("Cannot update ended Redis live session")
            if step <= record["step"]:
                # PostgreSQL can accept a late observation for an older step.
                # Do not move the cache backwards or fail after durable commit.
                return False
            record["step"] = step
            record["last_decision"] = None
            record["stagnant_run"] = None
            return True

        return self._mutate(session_id, change)

    def record_judgement(self, session_id: str, step: int, decision: str,
                         *, stagnant_run: int | None = None,
                         rule_id: str | None = None) -> dict[str, Any]:
        """Best-effort display cache, not the PostgreSQL judgement ledger.

        Only judgements for the current observation step are cached. A late
        judgement for an older step is a legitimate no-op. With multiple
        rules, configure selected_rule_id and pass rule_id to filter them.
        The returned state does not say whether a particular event was cached.
        """
        _step(step)
        if not isinstance(decision, str) or not _DECISION_RE.fullmatch(decision):
            raise ValueError("decision must be a short identifier, not text")
        if stagnant_run is not None and (type(stagnant_run) is not int or stagnant_run < 0):
            raise ValueError("stagnant_run must be a nonnegative integer or None")
        if rule_id is not None and (
            not isinstance(rule_id, str) or not _RULE_ID_RE.fullmatch(rule_id)
        ):
            raise ValueError("rule_id must be a short rule identifier")
        if self.selected_rule_id is not None and rule_id is None:
            raise ValueError("rule_id required when selected_rule_id is configured")

        def change(record: dict[str, Any]) -> bool:
            if record["status"] != "active":
                raise ValueError("Cannot judge ended Redis live session")
            if step < record["step"]:
                # PostgreSQL may accept a late judgement after the next step.
                # This cache intentionally shows *current-step* verdicts only.
                return False
            if step > record["step"]:
                raise ValueError("Redis judgement requires an observed step")
            if self.selected_rule_id is not None and rule_id != self.selected_rule_id:
                return False
            if record["last_decision"] is not None:
                if record["last_decision"] != decision or record["stagnant_run"] != stagnant_run:
                    raise ValueError(
                        "Conflicting selected Redis judgement; filter to one display rule"
                    )
                return False
            record["last_decision"] = decision
            record["stagnant_run"] = stagnant_run
            return True

        return self._mutate(session_id, change)

    def end_session(self, session_id: str) -> dict[str, Any]:
        def change(record: dict[str, Any]) -> bool:
            if record["status"] == "ended":
                return False
            record["status"] = "ended"
            record["ended_at"] = _utc_now()
            return True

        return self._mutate(session_id, change)

    def reconcile_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Low-level merge for a caller-supplied snapshot.

        A caller-supplied snapshot can become stale *after Redis key expiry*.
        Do NOT use this method for concurrent PostgreSQL cache recovery; use
        reconcile_from_reader() so the database is re-read under Redis WATCH
        on every retry. Kept for direct snapshot tests/controlled utilities.
        """
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid Redis live snapshot")
        session_id = _session_id(snapshot.get("session_id"))
        _decode(_encode(snapshot), session_id)  # Validate before opening Redis.
        result = self._reconcile_from_reader(session_id, lambda: snapshot)
        assert result is not None
        return result

    def reconcile_from_reader(self, session_id: str,
                              snapshot_reader: Callable[[], dict[str, Any] | None]) -> dict[str, Any] | None:
        """Rebuild using a fresh, authoritative snapshot under Redis WATCH.

        The reader is invoked AFTER WATCH and again for every WatchError.
        If a newer cache write and key expiry/delete occur during a delayed
        read, EXEC fails and a new PostgreSQL snapshot replaces the old one.
        The adapter supplies read_live_snapshot; callers must authenticate
        and authorize before using this API. This remains a display-only cache.
        """
        _session_id(session_id)
        if not callable(snapshot_reader):
            raise TypeError("snapshot_reader must be callable")
        return self._reconcile_from_reader(session_id, snapshot_reader)

    def _reconcile_from_reader(self, session_id: str,
                               snapshot_reader: Callable[[], dict[str, Any] | None]) -> dict[str, Any] | None:
        key = self._key(session_id)
        for _ in range(5):
            try:
                with self.client.pipeline() as pipe:
                    pipe.watch(key)
                    # This MUST be inside WATCH and repeated after a conflict.
                    snapshot = snapshot_reader()
                    if snapshot is None:
                        return None
                    if not isinstance(snapshot, dict):
                        raise ValueError("Invalid Redis live snapshot")
                    candidate = _decode(_encode(snapshot), session_id)
                    raw = pipe.get(key)
                    if raw is None:
                        pipe.multi()
                        pipe.set(key, _encode(candidate), nx=True, ex=self.ttl_seconds)
                        result = pipe.execute()
                        if result[0]:
                            return candidate
                        continue
                    current = _decode(raw, session_id)
                    if current["mode"] != candidate["mode"]:
                        raise ValueError("Redis session mode conflicts with durable state")
                    if current["status"] == "ended":
                        return current
                    if candidate["status"] == "active":
                        if candidate["step"] < current["step"]:
                            return current
                        if candidate["step"] == current["step"]:
                            if candidate["last_decision"] is None:
                                return current
                            if current["last_decision"] is not None:
                                return current
                    if candidate["status"] == "ended" and candidate["step"] < current["step"]:
                        raise ValueError("Durable end snapshot predates cached step")
                    pipe.multi()
                    pipe.set(key, _encode(candidate), ex=self.ttl_seconds)
                    pipe.execute()
                    return candidate
            except WatchError:
                # Do not retry the old candidate: a concurrent writer may
                # have committed a newer PostgreSQL status while this read ran.
                continue
        raise RuntimeError("Concurrent Redis snapshot recovery; retry later")
