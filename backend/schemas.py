"""Public session metadata; raw configuration and model text are omitted."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    mode: Literal["observe", "block"] = "observe"
    csrf_token: str = Field(min_length=1, max_length=256)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


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
