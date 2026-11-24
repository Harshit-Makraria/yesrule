"""HTTP API. Adapters (Claude Code hook, n8n node, MCP, SDKs, voice agents) talk to these endpoints."""

import logging
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from yesrule import service
from yesrule.channels import (
    Channel,
    SlackChannel,
    TelegramChannel,
    channels_from_env,
    parse_callback,
)
from yesrule.core.miner import MinerSettings
from yesrule.core.models import ApprovalRequest
from yesrule.core.rules import RuleStatus
from yesrule.db import HardLineRow, RequestRow, RuleRow, make_session_factory

log = logging.getLogger("yesrule")


class DecisionIn(BaseModel):
    approved: bool
    by: str = "owner"
    note: str | None = None
    channel: str | None = "web"


class FlagIn(BaseModel):
    by: str = "owner"
    note: str | None = None


class HardLineIn(BaseModel):
    id: str
    description: str = ""
    conditions: list[dict[str, Any]]


class RequestOut(BaseModel):
    id: str
    status: str
    risk_score: int
    risk_band: str
    risk_reasons: list[Any]
    reason: str
    rule_id: str | None
    approvals_needed: int = 1
    approvals_so_far: int = 0
    receipt: dict[str, Any] | None = None


def create_app(database_url: str | None = None, channels: list[Channel] | None = None) -> FastAPI:
    factory = make_session_factory(database_url)
    chans: list[Channel] = channels if channels is not None else channels_from_env()
    app = FastAPI(title="Yesrule", version="0.2.0",
                  description="Approval layer for AI agents that learns rules from your decisions.")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"],
                       allow_headers=["*"])
    app.state.channels = chans

    def db() -> Iterator[Session]:
        with factory() as session:
            yield session

    DB = Annotated[Session, Depends(db)]

    def out(row: RequestRow, session: Session) -> RequestOut:
        return RequestOut(id=row.id, status=row.status, risk_score=row.risk_score, risk_band=row.risk_band,
                          risk_reasons=row.risk_reasons, reason=row.verdict_reason, rule_id=row.rule_id,
                          approvals_needed=row.approvals_needed,
                          approvals_so_far=service.approvals_so_far(session, row.id),
                          receipt=service.receipt(session, row))

    def notify(row: RequestRow) -> None:
        for ch in chans:
            try:
                ch.send(row)
            except Exception:  # a broken channel must never break the agent's request
                log.exception("channel %s failed", ch.name)

    def decide_or_409(session: Session, request_id: str, approved: bool, by: str, channel: str,
                      note: str | None = None) -> RequestRow:
        try:
            return service.record_decision(session, request_id, approved=approved, by=by, note=note,
                                           channel=channel)
        except service.DecisionError as e:
            raise HTTPException(409, str(e)) from e

    # --- requests -------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "channels": [c.name for c in chans]}

    @app.post("/v1/requests", response_model=RequestOut, status_code=201)
    def create(req: ApprovalRequest, session: DB) -> RequestOut:
        row = service.create_request(session, req)
        if row.status == "pending":
            notify(row)
        return out(row, session)

    @app.get("/v1/requests/{request_id}", response_model=RequestOut)
    def get(request_id: str, session: DB) -> RequestOut:
        service.expire_overdue(session)
        row = session.get(RequestRow, request_id)
        if row is None:
            raise HTTPException(404, "request not found")
        return out(row, session)

    @app.get("/v1/requests/{request_id}/detail")
    def detail(request_id: str, session: DB) -> dict[str, Any]:
        row = session.get(RequestRow, request_id)
        if row is None:
            raise HTTPException(404, "request not found")
        return service.request_detail(session, row)

    @app.get("/v1/requests")
    def list_requests(session: DB, status: str | None = None, client: str | None = None,
                      limit: int = 200) -> list[dict[str, Any]]:
        service.expire_overdue(session)
        q = select(RequestRow).order_by(RequestRow.created_at.desc()).limit(min(limit, 1000))
        if status:
            q = q.where(RequestRow.status == status)
        if client:
            q = q.where(RequestRow.client == client)
        return [service.request_summary(r) for r in session.scalars(q)]

    @app.post("/v1/requests/{request_id}/decision", response_model=RequestOut)
    def decision(request_id: str, body: DecisionIn, session: DB) -> RequestOut:
        return out(decide_or_409(session, request_id, body.approved, body.by, body.channel or "web", body.note),
                   session)

    @app.post("/v1/requests/{request_id}/flag")
    def flag(request_id: str, body: FlagIn, session: DB) -> dict[str, Any]:
        """Mark an automatic approval as wrong. The rule that made it is paused (drift watch)."""
        try:
            return service.flag_auto_decision(session, request_id, body.by, body.note)
        except service.DecisionError as e:
            raise HTTPException(409, str(e)) from e

    # --- rules and hard lines ------------------------------------------

    @app.get("/v1/rules")
    def rules(session: DB) -> list[dict[str, Any]]:
        return [service.rule_dict(r) for r in session.scalars(select(RuleRow))]

    @app.post("/v1/rules/mine")
    def mine_rules(session: DB, min_confidence: float = 0.90, min_approvals: int = 10,
                   min_days: int = 2) -> list[dict[str, Any]]:
        settings = MinerSettings(min_approvals=min_approvals, min_days=min_days, min_confidence=min_confidence)
        return [service.rule_dict(r) for r in service.propose_rules(session, settings)]

    @app.get("/v1/rules/{rule_id}/backtest")
    def rule_backtest(rule_id: str, session: DB) -> dict[str, Any]:
        try:
            return service.backtest_rule(session, rule_id)
        except service.DecisionError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/v1/rules/{rule_id}/{action}")
    def rule_action(rule_id: str, action: str, session: DB, by: str = "owner") -> dict[str, str]:
        status = {"accept": RuleStatus.ACTIVE, "pause": RuleStatus.PAUSED, "dismiss": RuleStatus.EXPIRED}.get(action)
        if status is None:
            raise HTTPException(400, "action must be accept, pause or dismiss")
        try:
            row = service.set_rule_status(session, rule_id, status, by)
        except service.DecisionError as e:
            raise HTTPException(409, str(e)) from e
        return {"id": row.id, "status": row.status}

    @app.get("/v1/hard-lines")
    def hard_lines(session: DB) -> list[dict[str, Any]]:
        return [{"id": h.id, "description": h.description, "conditions": h.conditions}
                for h in session.scalars(select(HardLineRow))]

    @app.post("/v1/hard-lines", status_code=201)
    def add_hard_line(body: HardLineIn, session: DB) -> dict[str, str]:
        try:
            service.add_hard_line(session, body.id, body.description, body.conditions)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"id": body.id}

    @app.delete("/v1/hard-lines/{line_id}")
    def delete_hard_line(line_id: str, session: DB) -> dict[str, str]:
        service.delete_hard_line(session, line_id)
        return {"id": line_id, "status": "deleted"}

    # --- audit, insights, reports ---------------------------------------

    @app.get("/v1/audit/verify")
    def audit_verify(session: DB) -> dict[str, Any]:
        ok, bad, count = service.verify_audit(session)
        return {"ok": ok, "first_bad_seq": bad, "entries": count}

    @app.get("/v1/audit")
    def audit_list(session: DB, limit: int = 200) -> list[dict[str, Any]]:
        return service.audit_entries(session, limit)

    @app.get("/v1/insights")
    def insights(session: DB) -> dict[str, Any]:
        return service.insights(session)

    @app.get("/v1/reports/client/{client}")
    def client_report(client: str, session: DB, month: str | None = None) -> dict[str, Any]:
        return service.client_report(session, client, month)

    # --- channel webhooks -----------------------------------------------

    @app.post("/v1/channels/telegram/webhook")
    async def telegram_webhook(request: Request, session: DB,
                               x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None
                               ) -> dict[str, bool]:
        tg = next((c for c in chans if isinstance(c, TelegramChannel)), None)
        if tg is None or not tg.verify(x_telegram_bot_api_secret_token):
            raise HTTPException(401, "bad secret")
        update = await request.json()
        cq = update.get("callback_query")
        if not cq:
            return {"ok": True}
        parsed = parse_callback(cq.get("data", ""))
        if parsed is None:
            return {"ok": True}
        request_id, approved = parsed
        user = (cq.get("from") or {}).get("username") or str((cq.get("from") or {}).get("id", "telegram"))
        try:
            row = service.record_decision(session, request_id, approved=approved, by=user, channel="telegram")
            tg.answer(cq.get("id", ""), f"{row.status}")
        except service.DecisionError as e:
            tg.answer(cq.get("id", ""), str(e))
        return {"ok": True}

    @app.post("/v1/channels/slack/actions")
    async def slack_actions(request: Request, session: DB,
                            x_slack_request_timestamp: Annotated[str | None, Header()] = None,
                            x_slack_signature: Annotated[str | None, Header()] = None) -> dict[str, str]:
        sl = next((c for c in chans if isinstance(c, SlackChannel)), None)
        body = await request.body()
        if sl is None or not sl.verify(x_slack_request_timestamp, body, x_slack_signature):
            raise HTTPException(401, "bad signature")
        form = await request.form()
        parsed = SlackChannel.parse_action(str(form.get("payload", "{}")))
        if parsed is None:
            return {"text": "ignored"}
        request_id, approved, user = parsed
        try:
            row = service.record_decision(session, request_id, approved=approved, by=user, channel="slack")
            return {"text": f"{row.status} by {user}"}
        except service.DecisionError as e:
            return {"text": str(e)}

    return app


app = create_app()
