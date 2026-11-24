"""HTTP API. Adapters (Claude Code hook, n8n node, MCP, SDK) talk to these endpoints."""


from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from yesrule import service
from yesrule.core.miner import MinerSettings
from yesrule.core.models import ApprovalRequest
from yesrule.core.rules import RuleStatus
from yesrule.db import RequestRow, RuleRow, make_session_factory


class DecisionIn(BaseModel):
    approved: bool
    by: str = "owner"
    note: str | None = None
    channel: str | None = "web"


class RequestOut(BaseModel):
    id: str
    status: str
    risk_score: int
    risk_band: str
    risk_reasons: list[Any]
    reason: str
    rule_id: str | None
    receipt: dict[str, Any] | None = None


def create_app(database_url: str | None = None) -> FastAPI:
    factory = make_session_factory(database_url)
    app = FastAPI(title="Yesrule", version="0.1.0",
                  description="Approval layer for AI agents that learns rules from your decisions.")

    def db() -> Iterator[Session]:
        with factory() as session:
            yield session

    DB = Annotated[Session, Depends(db)]

    def out(row: RequestRow, session: Session) -> RequestOut:
        receipt = None
        if row.rule_id:
            rule = session.get(RuleRow, row.rule_id)
            if rule:
                receipt = {"rule": rule.id, "description": rule.description, "evidence": rule.evidence,
                           "accepted_by": rule.accepted_by}
        return RequestOut(id=row.id, status=row.status, risk_score=row.risk_score, risk_band=row.risk_band,
                          risk_reasons=row.risk_reasons, reason=row.verdict_reason, rule_id=row.rule_id,
                          receipt=receipt)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/requests", response_model=RequestOut, status_code=201)
    def create(req: ApprovalRequest, session: DB) -> RequestOut:
        return out(service.create_request(session, req), session)

    @app.get("/v1/requests/{request_id}", response_model=RequestOut)
    def get(request_id: str, session: DB) -> RequestOut:
        service.expire_overdue(session)
        row = session.get(RequestRow, request_id)
        if row is None:
            raise HTTPException(404, "request not found")
        return out(row, session)

    @app.get("/v1/requests")
    def list_requests(session: DB, status: str | None = None) -> list[dict[str, Any]]:
        service.expire_overdue(session)
        q = select(RequestRow).order_by(RequestRow.created_at.desc()).limit(200)
        if status:
            q = q.where(RequestRow.status == status)
        return [{"id": r.id, "agent": r.agent, "action": r.action, "status": r.status, "risk": r.risk_score,
                 "client": r.client, "created_at": r.created_at.isoformat()} for r in session.scalars(q)]

    @app.post("/v1/requests/{request_id}/decision", response_model=RequestOut)
    def decision(request_id: str, body: DecisionIn, session: DB) -> RequestOut:
        try:
            row = service.record_decision(session, request_id, approved=body.approved, by=body.by,
                                          note=body.note, channel=body.channel)
        except service.DecisionError as e:
            raise HTTPException(409, str(e)) from e
        return out(row, session)

    @app.get("/v1/rules")
    def rules(session: DB) -> list[dict[str, Any]]:
        return [{"id": r.id, "description": r.description, "status": r.status, "effect": r.effect,
                 "conditions": r.conditions, "evidence": r.evidence, "fire_count": r.fire_count}
                for r in session.scalars(select(RuleRow))]

    @app.post("/v1/rules/mine")
    def mine_rules(session: DB, min_confidence: float = 0.90) -> list[dict[str, Any]]:
        created = service.propose_rules(session, MinerSettings(min_confidence=min_confidence))
        return [{"id": r.id, "description": r.description, "evidence": r.evidence} for r in created]

    @app.post("/v1/rules/{rule_id}/{action}")
    def rule_action(rule_id: str, action: str, session: DB, by: str = "owner") -> dict[str, str]:
        status = {"accept": RuleStatus.ACTIVE, "pause": RuleStatus.PAUSED, "dismiss": RuleStatus.EXPIRED}.get(action)
        if status is None:
            raise HTTPException(400, "action must be accept, pause or dismiss")
        try:
            row = service.set_rule_status(session, rule_id, status, by)
        except service.DecisionError as e:
            raise HTTPException(404, str(e)) from e
        return {"id": row.id, "status": row.status}

    @app.get("/v1/audit/verify")
    def audit_verify(session: DB) -> dict[str, Any]:
        ok, bad, count = service.verify_audit(session)
        return {"ok": ok, "first_bad_seq": bad, "entries": count}

    return app


app = create_app()
