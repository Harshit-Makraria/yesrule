"""Database tables (SQLAlchemy 2). SQLite locally, Postgres in production via YESRULE_DATABASE_URL."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RequestRow(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent: Mapped[str] = mapped_column(String(200), index=True)
    platform: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(200))
    client: Mapped[str | None] = mapped_column(String(200), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)  # full ApprovalRequest
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_band: Mapped[str] = mapped_column(String(10))
    risk_reasons: Mapped[list[Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), index=True)  # pending|approved|denied|expired|auto_*
    verdict_reason: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(String(32))
    approvals_needed: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DecisionRow(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    decided_by: Mapped[str] = mapped_column(String(200))  # user name or "rule:R-7" or "timeout"
    approved: Mapped[bool] = mapped_column(Boolean)
    human: Mapped[bool] = mapped_column(Boolean)  # only human decisions train the miner
    note: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[list[Any]] = mapped_column(JSON)
    effect: Mapped[str] = mapped_column(String(10), default="approve")
    status: Mapped[str] = mapped_column(String(10), default="proposed")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    accepted_by: Mapped[str | None] = mapped_column(String(200))
    fire_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HardLineRow(Base):
    __tablename__ = "hard_lines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[list[Any]] = mapped_column(JSON)


class AuditRow(Base):
    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


def make_session_factory(url: str | None = None):
    url = url or os.environ.get("YESRULE_DATABASE_URL", "sqlite:///yesrule.db")
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
