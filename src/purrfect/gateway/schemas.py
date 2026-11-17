"""Public API v1 schemas, separate from Core dataclasses."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Optional for backwards-compatible clients; if provided must match ticket.
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    product_id: str | None = Field(default=None, min_length=1, max_length=128)
    product_version: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_pair(self):
        if not self.message.strip() or (self.product_id is None) != (self.product_version is None):
            raise ValueError("Message required and product fields must be paired")
        return self


class SourceResponse(BaseModel):
    id: str
    source: str
    product_id: str


class ChatResponse(BaseModel):
    session_id: str
    status: str
    message: str
    sources: list[SourceResponse]


class SessionResponse(BaseModel):
    session_id: str
    session_token: str
    expires_at: int
