"""Typed request format shared by every adapter (Claude Code, n8n, MCP, SDK)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Platform(StrEnum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    N8N = "n8n"
    MCP = "mcp"
    RETELL = "retell"
    VAPI = "vapi"
    SDK = "sdk"


class Environment(StrEnum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    UNKNOWN = "unknown"


class Target(BaseModel):
    type: str = "unknown"
    id: str | None = None


class Money(BaseModel):
    value: float = Field(ge=0)
    currency: str = "INR"


class Recipient(BaseModel):
    id: str
    known: bool = False
    past_count: int = Field(default=0, ge=0)
    external: bool = True  # outside the user's own organisation


class ApprovalRequest(BaseModel):
    """What an agent wants to do. Adapters translate platform events into this."""

    agent: str
    platform: Platform
    action: str  # e.g. "send_email", "bash", "delete_record", "publish"
    target: Target = Field(default_factory=Target)
    amount: Money | None = None
    recipient: Recipient | None = None
    reversible: bool = True
    environment: Environment = Environment.UNKNOWN
    client: str | None = None  # agency client this request belongs to
    context: dict[str, Any] = Field(default_factory=dict)
    fallback: str | None = None  # what the agent does if denied or timed out
    timeout_s: int = Field(default=600, ge=5, le=86_400)
    approvals_needed: int = Field(default=1, ge=1, le=5)  # two-person rule for sensitive actions
