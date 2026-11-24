"""Import past human decisions so rule learning starts with history instead of from zero.

Accepted input (JSON file):
1. Generic list: [{"action": ..., "approved": true, "decided_at": "2026-10-01T10:00:00Z", "platform": "n8n",
   "agent": ..., "amount": 1200, "currency": "INR", "recipient": "x@y.com", "recipient_known": true,
   "client": "acme", "environment": "production", "reversible": false, "target_type": "invoice", "by": "harshit"}]
2. n8n execution export (list of executions or {"data": [...]}) containing "Send and Wait" / Wait approval
   nodes. A run item with json.data.approved (or json.approved) true/false is counted as one decision.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from yesrule.core.models import ApprovalRequest
from yesrule.core.risk import assess
from yesrule.db import DecisionRow, RequestRow
from yesrule.service import append_audit

APPROVAL_NODE_HINTS = ("sendandwait", "send and wait", "approval", "wait")


def _ts(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(str(v))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalise_generic(item: dict[str, Any]) -> tuple[ApprovalRequest, bool, datetime, str]:
    req: dict[str, Any] = {
        "agent": item.get("agent", "imported"), "platform": item.get("platform", "n8n"), "action": item["action"],
        "target": {"type": item.get("target_type", "unknown"), "id": item.get("target_id")},
        "reversible": item.get("reversible", True), "environment": item.get("environment", "unknown"),
        "client": item.get("client"),
    }
    if item.get("amount") is not None:
        req["amount"] = {"value": float(item["amount"]), "currency": item.get("currency", "INR")}
    if item.get("recipient"):
        req["recipient"] = {"id": item["recipient"], "known": bool(item.get("recipient_known", False))}
    return ApprovalRequest.model_validate(req), bool(item["approved"]), _ts(item["decided_at"]), item.get("by", "import")


def parse_n8n(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ex in executions:
        workflow = (ex.get("workflowData") or {}).get("name") or str(ex.get("workflowId", "n8n-workflow"))
        when = ex.get("stoppedAt") or ex.get("startedAt")
        run_data = (((ex.get("data") or {}).get("resultData") or {}).get("runData")) or {}
        for node_name, runs in run_data.items():
            if not any(h in node_name.lower() for h in APPROVAL_NODE_HINTS):
                continue
            for run in runs or []:
                for branch in ((run.get("data") or {}).get("main") or []):
                    for item in branch or []:
                        j = item.get("json") or {}
                        approved = (j.get("data") or {}).get("approved", j.get("approved"))
                        if isinstance(approved, bool) and when:
                            out.append({"agent": workflow, "platform": "n8n", "action": node_name,
                                        "target_type": "workflow_step", "approved": approved,
                                        "decided_at": when, "client": ex.get("client")})
    return out


def detect_and_parse(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        data = data["data"]
    if not isinstance(data, list):
        raise TypeError("expected a JSON list")
    if data and isinstance(data[0], dict) and "action" in data[0] and "approved" in data[0]:
        return data
    return parse_n8n(data)


def import_decisions(db: Session, items: list[dict[str, Any]]) -> int:
    count = 0
    for item in items:
        req, approved, when, by = normalise_generic(item)
        risk = assess(req)
        row = RequestRow(id="req_" + secrets.token_hex(8), agent=req.agent, platform=str(req.platform),
                         action=req.action, client=req.client, payload=req.model_dump(mode="json"),
                         risk_score=risk.score, risk_band=str(risk.band),
                         risk_reasons=[list(r) for r in risk.reasons],
                         status="approved" if approved else "denied", verdict_reason="imported", rule_id=None,
                         approvals_needed=1, created_at=when, expires_at=when + timedelta(seconds=1),
                         decided_at=when)
        db.add(row)
        db.add(DecisionRow(request_id=row.id, decided_by=by, approved=approved, human=True, channel="import",
                           created_at=when))
        count += 1
    append_audit(db, "import", {"count": count})
    db.commit()
    return count
