"""Glue between the pure core and the database. The API calls these functions."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from yesrule.core import audit
from yesrule.core.miner import MinerSettings, PastDecision, mine
from yesrule.core.models import ApprovalRequest
from yesrule.core.risk import assess
from yesrule.core.rules import (
    Condition,
    Effect,
    HardLine,
    Outcome,
    Rule,
    RuleStatus,
    decide,
)
from yesrule.db import AuditRow, DecisionRow, HardLineRow, RequestRow, RuleRow, utcnow


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite drops tzinfo


# --- conversion ---------------------------------------------------------

def _conds(raw: list[dict[str, Any]]) -> list[Condition]:
    return [Condition(c["field"], c["op"], c["value"]) for c in raw]


def _raw(conds: list[Condition]) -> list[dict[str, Any]]:
    return [{"field": c.field, "op": c.op, "value": c.value} for c in conds]


def rule_from_row(row: RuleRow) -> Rule:
    return Rule(row.id, _conds(row.conditions), Effect(row.effect), RuleStatus(row.status), row.description, row.evidence)


# --- audit --------------------------------------------------------------

def append_audit(db: Session, event: str, data: dict[str, Any]) -> AuditRow:
    last = db.scalars(select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)).first()
    prev = None if last is None else audit.AuditEntry(last.seq, last.event, last.data, last.created_at, last.prev_hash, last.hash)
    e = audit.make_entry(prev, event, data, utcnow().isoformat())
    row = AuditRow(seq=e.seq, event=e.event, data=e.data, created_at=e.created_at, prev_hash=e.prev_hash, hash=e.hash)
    db.add(row)
    return row


def verify_audit(db: Session) -> tuple[bool, int | None, int]:
    rows = db.scalars(select(AuditRow).order_by(AuditRow.seq)).all()
    entries = [audit.AuditEntry(r.seq, r.event, r.data, r.created_at, r.prev_hash, r.hash) for r in rows]
    ok, bad = audit.verify(entries)
    return ok, bad, len(entries)


# --- requests -----------------------------------------------------------

STATUS_FOR = {Outcome.AUTO_APPROVE: "auto_approved", Outcome.AUTO_DENY: "auto_denied", Outcome.ASK_HUMAN: "pending"}


def create_request(db: Session, req: ApprovalRequest, *, money_limit: float | None = None) -> RequestRow:
    rules = [rule_from_row(r) for r in db.scalars(select(RuleRow)).all()]
    lines = [HardLine(h.id, _conds(h.conditions), h.description) for h in db.scalars(select(HardLineRow)).all()]
    risk = assess(req, money_limit=money_limit)
    verdict = decide(req, risk, rules, lines)
    now = utcnow()

    row = RequestRow(
        id="req_" + secrets.token_hex(8),
        agent=req.agent,
        platform=str(req.platform),
        action=req.action,
        client=req.client,
        payload=req.model_dump(mode="json"),
        risk_score=risk.score,
        risk_band=str(risk.band),
        risk_reasons=[list(r) for r in risk.reasons],
        status=STATUS_FOR[verdict.outcome],
        verdict_reason=verdict.reason,
        rule_id=verdict.rule_id,
        created_at=now,
        expires_at=now + timedelta(seconds=req.timeout_s),
        decided_at=None if verdict.outcome is Outcome.ASK_HUMAN else now,
    )
    db.add(row)
    db.flush()

    if verdict.rule_id:
        rule_row = db.get(RuleRow, verdict.rule_id)
        if rule_row:
            rule_row.fire_count += 1
        db.add(DecisionRow(request_id=row.id, decided_by=f"rule:{verdict.rule_id}",
                           approved=verdict.outcome is Outcome.AUTO_APPROVE, human=False))

    append_audit(db, "request", {"id": row.id, "agent": row.agent, "action": row.action, "risk": risk.score,
                                 "status": row.status, "reason": verdict.reason, "rule": verdict.rule_id})
    db.commit()
    return row


class DecisionError(ValueError):
    pass


def record_decision(db: Session, request_id: str, *, approved: bool, by: str, note: str | None = None,
                    channel: str | None = None) -> RequestRow:
    row = db.get(RequestRow, request_id)
    if row is None:
        raise DecisionError("request not found")
    if row.status != "pending":
        raise DecisionError(f"request already {row.status}")  # decisions are idempotent: first one wins
    now = utcnow()
    if now > _as_utc(row.expires_at):
        row.status = "expired"
        db.commit()
        raise DecisionError("request expired")

    row.status = "approved" if approved else "denied"
    row.decided_at = now
    latency = (now - _as_utc(row.created_at)).total_seconds() * 1000
    db.add(DecisionRow(request_id=row.id, decided_by=by, approved=approved, human=True, note=note,
                       channel=channel, latency_ms=latency, created_at=now))
    append_audit(db, "decision", {"id": row.id, "approved": approved, "by": by, "channel": channel})
    db.commit()
    return row


def expire_overdue(db: Session) -> int:
    now = utcnow()
    pending = db.scalars(select(RequestRow).where(RequestRow.status == "pending")).all()
    count = 0
    for row in pending:
        if _as_utc(row.expires_at) < now:
            row.status = "expired"
            row.decided_at = now
            append_audit(db, "expired", {"id": row.id})
            count += 1
    db.commit()
    return count


# --- rules --------------------------------------------------------------

def human_history(db: Session) -> list[PastDecision]:
    rows = db.execute(
        select(DecisionRow, RequestRow).join(RequestRow, DecisionRow.request_id == RequestRow.id)
        .where(DecisionRow.human.is_(True))
    ).all()
    return [PastDecision(ApprovalRequest.model_validate(r.payload), d.approved, _as_utc(d.created_at)) for d, r in rows]


def propose_rules(db: Session, settings: MinerSettings | None = None) -> list[RuleRow]:
    existing = db.scalars(select(RuleRow)).all()
    known = {tuple(map(str, r.conditions)) for r in existing}
    proposals = mine(human_history(db), settings, next_id=len(existing) + 1)
    created = []
    for p in proposals:
        raw = _raw(p.rule.conditions)
        if tuple(map(str, raw)) in known:
            continue  # same rule already proposed or active
        row = RuleRow(id=p.rule.id, description=p.rule.description, conditions=raw, effect="approve",
                      status="proposed", evidence=p.rule.evidence)
        db.add(row)
        created.append(row)
        append_audit(db, "rule_proposed", {"id": row.id, "evidence": row.evidence})
    db.commit()
    return created


def set_rule_status(db: Session, rule_id: str, status: RuleStatus, by: str) -> RuleRow:
    row = db.get(RuleRow, rule_id)
    if row is None:
        raise DecisionError("rule not found")
    row.status = str(status)
    if status is RuleStatus.ACTIVE:
        row.accepted_by = by
    append_audit(db, f"rule_{status}", {"id": rule_id, "by": by})
    db.commit()
    return row
