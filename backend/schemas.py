"""Public session metadata; raw configuration and model text are omitted."""

from datetime import datetime

from pydantic import BaseModel


class ProjectResponse(BaseModel):
    id: int
    name: str
    mode: str
    rule_id: str
    created_at: datetime


class SessionDetailResponse(BaseModel):
    id: str
    scenario_id: int
    status: str
    termination_reason: str | None
    phase: str | None
    guardrail_mode: str | None
    model: str | None
    steps_reached: int | None
    total_tokens: int | None
    first_stop_step: int | None
    started_at: datetime
    ended_at: datetime | None


class SessionListResponse(BaseModel):
    items: list[SessionDetailResponse]
    total: int
    limit: int
    offset: int
