"""Session persistence boundary; replace repository for Redis in a later phase."""
import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException
from criteria_policy import VERSION as CRITERIA_VERSION, pin_criteria

logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def empty_meta():
    return dict.fromkeys(("model", "temperature", "seed", "max_tokens", "scenario_id",
                          "run_index", "framework_version", "started_at", "ended_at",
                          "termination_reason", "criteria_version", "criteria_parameters", "criteria_sha256",
                          "upstream"))


@dataclass
class Session:
    session_id: str
    turns: list = field(default_factory=list)
    status: str = "active"
    persistent: bool = True
    meta: dict = field(default_factory=empty_meta)
    observations: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def record(self):
        return {"session_id": self.session_id, "status": self.status,
                "meta": self.meta, "turns": self.turns, "observations": self.observations}


class SessionRepository(Protocol):
    def create(self, record: dict) -> None: ...
    def load(self, session_id: str) -> dict | None: ...
    def save(self, record: dict) -> None: ...
    def active_ids(self) -> set[str]: ...


class JsonSessionRepository:
    """Single-worker local backend. create is exclusive; save replaces atomically."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def create(self, record):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / f"{record['session_id']}.json").open("x", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

    def load(self, session_id):
        try:
            with (self.directory / f"{session_id}.json").open(encoding="utf-8") as f:
                record = json.load(f)
        except FileNotFoundError:
            return None
        if not isinstance(record, dict) or record.get("session_id") != session_id:
            raise ValueError("Invalid session identity")
        # Read the immediately preceding S1 format without touching old fixtures.
        if "status" not in record and type(record.get("closed")) is bool:
            record["status"] = "ended" if record["closed"] else "active"
        if record.get("status") not in ("active", "ended"):
            raise ValueError("Invalid session status")
        turns = record.get("turns")
        if not isinstance(turns, list) or any(
            not isinstance(t, dict) or t.get("turn") != n
            for n, t in enumerate(turns, 1)
        ):
            raise ValueError("Invalid turn sequence")
        return record

    def save(self, record):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             suffix=".tmp", delete=False) as f:
                temporary = f.name
                json.dump(record, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.directory / f"{record['session_id']}.json")
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def active_ids(self):
        return {p.stem for p in self.directory.glob("*.json")
                if (record := self.load(p.stem)) and record["status"] == "active"}


class SessionStore:
    def __init__(self, repository: SessionRepository, criteria_version=CRITERIA_VERSION, upstream=None,
                 criteria_parameters=None, guardrail_mode="observe"):
        self.repository = repository
        self.guardrail_mode = guardrail_mode
        self.criteria_parameters = criteria_parameters
        self.criteria_pin = pin_criteria(criteria_version, criteria_parameters)
        self.upstream = upstream
        self.sessions = {}

    def start(self, session_id, registration=None):
        if session_id in self.sessions:
            raise HTTPException(409, "Session key already used; use a new key")
        session = Session(session_id)
        session.meta["started_at"] = utc_now()
        session.meta["upstream"] = self.upstream
        # Fixed per session: a later restart with another configuration does not change how it is treated.
        session.meta["guardrail_mode"] = self.guardrail_mode
        session.meta.update(pin_criteria(self.criteria_pin["criteria_version"], self.criteria_parameters))
        if registration is not None:
            # DM-35: registered once at session start and never changed; absent for unregistered sessions.
            session.meta["registration"] = registration
        try:
            self.repository.create(session.record())
        except FileExistsError:
            raise HTTPException(409, "Session file already exists; use a new key") from None
        except OSError:
            logger.warning("Session log creation failed; forwarding remains enabled", exc_info=True)
            session.persistent = False
        self.sessions[session_id] = session
        return session

    def get(self, session_id):
        if session_id in self.sessions:
            return self.sessions[session_id]
        try:
            record = self.repository.load(session_id)
        except (ValueError, TypeError):
            raise HTTPException(409, "Invalid existing session file; preserved for inspection") from None
        except OSError:
            logger.warning("Session recovery unavailable; forwarding without disk writes", exc_info=True)
            session = Session(session_id, persistent=False)
            self.sessions[session_id] = session
            return session
        if record is None:
            return None
        session = Session(session_id, turns=record["turns"], status=record["status"],
                          meta={**empty_meta(), **record.get("meta", {})},
                          observations=record.get("observations", []))
        self.sessions[session_id] = session
        if session.status == "active":
            logger.warning("Recovered unfinished session %s at turn %s", session_id, len(session.turns))
        return session

    def get_or_start(self, session_id):
        session = self.get(session_id)
        if session is None:
            session = self.start(session_id)
        if session.status == "ended":
            raise HTTPException(409, "Session is ended; use a new key")
        return session

    def save(self, session):
        if session.persistent:
            try:
                self.repository.save(session.record())
                return True
            except Exception:
                logger.warning("Session log save failed; forwarding remains enabled", exc_info=True)
        return False

    def end(self, session, reason=None):
        if session.status != "ended":
            session.meta["ended_at"] = utc_now()
            session.meta["termination_reason"] = reason
        session.status = "ended"
        self.save(session)

    def active_count(self):
        active = self.repository.active_ids()
        for key, session in self.sessions.items():
            if session.status == "active":
                active.add(key)
            else:
                active.discard(key)
        return len(active)
