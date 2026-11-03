from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class AccountAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: StrictBool
    csrf_token: str = Field(min_length=1, max_length=256)

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value):
        if not value:
            raise ValueError("Explicit confirmation is required")
        return value
