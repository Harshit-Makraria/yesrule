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
        approvals_needed=req.approvals_needed,
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
    """Record one person's answer. A deny ends it; approvals count until approvals_needed distinct people agree."""
    row = db.get(RequestRow, request_id)
    if row is None:
        raise DecisionError("request not found")
    if row.status != "pending":
        raise DecisionError(f"request already {row.status}")  # first final decision wins
    now = utcnow()
    if now > _as_utc(row.expires_at):
        row.status = "expired"
        row.decided_at = now
        append_audit(db, "expired", {"id": row.id})
        db.commit()
        raise DecisionError("request expired")
    earlier = db.scalars(select(DecisionRow).where(DecisionRow.request_id == row.id,
                                                   DecisionRow.human.is_(True))).all()
    if any(d.decided_by == by for d in earlier):
        raise DecisionError(f"{by} already answered this request")

    latency = (now - _as_utc(row.created_at)).total_seconds() * 1000
    db.add(DecisionRow(request_id=row.id, decided_by=by, approved=approved, human=True, note=note,
                       channel=channel, latency_ms=latency, created_at=now))
    approvals = sum(1 for d in earlier if d.approved) + (1 if approved else 0)
    if not approved:
        row.status, row.decided_at = "denied", now
    elif approvals >= row.approvals_needed:
        row.status, row.decided_at = "approved", now
    append_audit(db, "decision", {"id": row.id, "approved": approved, "by": by, "channel": channel,
                                  "status": row.status})
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


# --- read models ----------------------------------------------------------

def approvals_so_far(db: Session, request_id: str) -> int:
    return len(db.scalars(select(DecisionRow).where(DecisionRow.request_id == request_id,
                                                    DecisionRow.human.is_(True),
                                                    DecisionRow.approved.is_(True))).all())


def receipt(db: Session, row: RequestRow) -> dict[str, Any] | None:
    """Why an automatic decision happened: the rule, the evidence behind it, and who accepted it."""
    if not row.rule_id:
        return None
    rule = db.get(RuleRow, row.rule_id)
    if rule is None:
        return None
    return {"rule": rule.id, "description": rule.description, "conditions": rule.conditions,
            "evidence": rule.evidence, "accepted_by": rule.accepted_by}


def request_summary(r: RequestRow) -> dict[str, Any]:
    p = r.payload
    return {"id": r.id, "agent": r.agent, "platform": r.platform, "action": r.action, "status": r.status,
            "risk": r.risk_score, "risk_band": r.risk_band, "client": r.client,
            "amount": (p.get("amount") or {}).get("value"), "reason": r.verdict_reason, "rule_id": r.rule_id,
            "created_at": _as_utc(r.created_at).isoformat(), "expires_at": _as_utc(r.expires_at).isoformat()}


def request_detail(db: Session, row: RequestRow) -> dict[str, Any]:
    decisions = db.scalars(select(DecisionRow).where(DecisionRow.request_id == row.id)
                           .order_by(DecisionRow.id)).all()
    return request_summary(row) | {
        "payload": row.payload, "risk_reasons": row.risk_reasons, "receipt": receipt(db, row),
        "approvals_needed": row.approvals_needed,
        "decisions": [{"by": d.decided_by, "approved": d.approved, "human": d.human, "channel": d.channel,
                       "note": d.note, "latency_ms": d.latency_ms,
                       "at": _as_utc(d.created_at).isoformat()} for d in decisions],
    }


def rule_dict(r: RuleRow) -> dict[str, Any]:
    return {"id": r.id, "description": r.description, "status": r.status, "effect": r.effect,
            "conditions": r.conditions, "evidence": r.evidence, "fire_count": r.fire_count,
            "accepted_by": r.accepted_by}


# --- drift watch ------------------------------------------------------------

def flag_auto_decision(db: Session, request_id: str, by: str, note: str | None) -> dict[str, Any]:
    """A person says an automatic approval was wrong: record it as a human denial and pause the rule."""
    row = db.get(RequestRow, request_id)
    if row is None:
        raise DecisionError("request not found")
    if row.status not in {"auto_approved", "auto_denied"} or not row.rule_id:
        raise DecisionError("only automatic decisions can be flagged")
    db.add(DecisionRow(request_id=row.id, decided_by=by, approved=False, human=True, note=note or "flagged",
                       channel="flag", created_at=utcnow()))
    rule = db.get(RuleRow, row.rule_id)
    paused = False
    if rule and rule.status == "active":
        rule.status = "paused"
        paused = True
    row.status = "flagged"
    append_audit(db, "flagged", {"id": row.id, "rule": row.rule_id, "by": by, "rule_paused": paused})
    db.commit()
    return {"id": row.id, "rule": row.rule_id, "rule_paused": paused}


def backtest_rule(db: Session, rule_id: str) -> dict[str, Any]:
    from yesrule.core.miner import backtest

    row = db.get(RuleRow, rule_id)
    if row is None:
        raise DecisionError("rule not found")
    history = human_history(db)
    probe = Rule(row.id, _conds(row.conditions), Effect(row.effect), RuleStatus.ACTIVE)
    result = backtest(probe, history)
    return {"rule": rule_id, "history_size": len(history), "would_auto_approve": result.would_auto_approve,
            "matched_past_denials": result.matched_past_denials, "passed": result.passed}


# --- hard lines -------------------------------------------------------------

VALID_OPS = {"eq", "ne", "lte", "gte", "in", "contains"}


def add_hard_line(db: Session, line_id: str, description: str, conditions: list[dict[str, Any]]) -> HardLineRow:
    if not conditions:
        raise ValueError("a hard line needs at least one condition")
    for c in conditions:
        if not {"field", "op", "value"} <= c.keys() or c["op"] not in VALID_OPS:
            raise ValueError(f"bad condition {c}")
    row = db.get(HardLineRow, line_id) or HardLineRow(id=line_id)
    row.description, row.conditions = description, conditions
    db.add(row)
    append_audit(db, "hard_line_set", {"id": line_id, "conditions": conditions})
    db.commit()
    return row


def delete_hard_line(db: Session, line_id: str) -> None:
    row = db.get(HardLineRow, line_id)
    if row:
        db.delete(row)
        append_audit(db, "hard_line_deleted", {"id": line_id})
        db.commit()


# --- audit, insights, reports -------------------------------------------------

def audit_entries(db: Session, limit: int = 200) -> list[dict[str, Any]]:
    rows = db.scalars(select(AuditRow).order_by(AuditRow.seq.desc()).limit(min(limit, 5000))).all()
    return [{"seq": r.seq, "event": r.event, "data": r.data, "at": r.created_at, "hash": r.hash} for r in rows]


def insights(db: Session) -> dict[str, Any]:
    reqs = db.scalars(select(RequestRow)).all()
    decisions = db.scalars(select(DecisionRow).where(DecisionRow.human.is_(True))).all()
    by_status: dict[str, int] = {}
    for r in reqs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    auto = by_status.get("auto_approved", 0) + by_status.get("auto_denied", 0)
    latencies = sorted(d.latency_ms for d in decisions if d.latency_ms is not None)
    median = latencies[len(latencies) // 2] if latencies else None
    agents: dict[str, dict[str, int]] = {}
    for r in reqs:
        a = agents.setdefault(r.agent, {"requests": 0, "denied": 0, "auto": 0})
        a["requests"] += 1
        a["denied"] += r.status in {"denied", "auto_denied", "flagged"}
        a["auto"] += r.status.startswith("auto_")
    rules = db.scalars(select(RuleRow)).all()
    return {
        "total_requests": len(reqs), "by_status": by_status,
        "automation_rate": round(auto / len(reqs), 3) if reqs else 0.0,
        "human_decisions": len(decisions), "median_response_ms": median,
        "minutes_saved_estimate": round(auto * 0.5, 1),  # ~30 seconds of attention per avoided prompt
        "agents": agents,
        "rules": {"active": sum(r.status == "active" for r in rules),
                  "proposed": sum(r.status == "proposed" for r in rules),
                  "paused": sum(r.status == "paused" for r in rules)},
    }


def client_report(db: Session, client: str, month: str | None = None) -> dict[str, Any]:
    """Monthly report an agency can send its client: what the agents did and who approved it."""
    reqs = [r for r in db.scalars(select(RequestRow).where(RequestRow.client == client))
            if month is None or _as_utc(r.created_at).strftime("%Y-%m") == month]
    total_amount = sum((r.payload.get("amount") or {}).get("value", 0) for r in reqs
                       if r.status in {"approved", "auto_approved"})
    ok, _, _ = verify_audit(db)
    return {
        "client": client, "month": month, "requests": len(reqs),
        "approved_by_person": sum(r.status == "approved" for r in reqs),
        "approved_by_rule": sum(r.status == "auto_approved" for r in reqs),
        "denied": sum(r.status in {"denied", "auto_denied"} for r in reqs),
        "expired": sum(r.status == "expired" for r in reqs),
        "approved_amount": total_amount, "audit_chain_ok": ok,
        "items": [request_summary(r) for r in reqs],
    }
