"""End-to-end through HTTP: request → human decisions → rule proposed → accepted → auto-approved with receipt."""

from fastapi.testclient import TestClient
from sqlalchemy import update

from yesrule.api import create_app
from yesrule.db import AuditRow


def client(tmp_path) -> TestClient:
    return TestClient(create_app(f"sqlite:///{tmp_path}/t.db"))


def invoice(amount: float = 42_000) -> dict:
    return {
        "agent": "invoice-bot",
        "platform": "n8n",
        "action": "send_email",
        "target": {"type": "invoice"},
        "amount": {"value": amount, "currency": "INR"},
        "recipient": {"id": "acme@client.com", "known": True, "past_count": 11},
        "reversible": False,
        "environment": "production",
        "client": "acme",
    }


def test_new_request_waits_for_human(tmp_path):
    c = client(tmp_path)
    r = c.post("/v1/requests", json=invoice())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending" and body["risk_band"] == "medium"
    assert body["risk_reasons"]  # always explained


def test_decision_is_first_wins(tmp_path):
    c = client(tmp_path)
    rid = c.post("/v1/requests", json=invoice()).json()["id"]
    assert c.post(f"/v1/requests/{rid}/decision", json={"approved": True}).json()["status"] == "approved"
    assert c.post(f"/v1/requests/{rid}/decision", json={"approved": False}).status_code == 409


def test_full_learning_loop(tmp_path, monkeypatch):
    c = client(tmp_path)
    # Approvals must span 2+ days; shift decision timestamps by patching utcnow per request.
    import datetime as dt

    import yesrule.service as svc

    base = dt.datetime(2026, 11, 1, 9, tzinfo=dt.UTC)
    for i in range(40):
        moment = base + dt.timedelta(days=i % 4, minutes=i)
        monkeypatch.setattr(svc, "utcnow", lambda m=moment: m)
        rid = c.post("/v1/requests", json=invoice(30_000 + i * 100)).json()["id"]
        c.post(f"/v1/requests/{rid}/decision", json={"approved": True, "by": "harshit"})
    monkeypatch.undo()

    proposals = c.post("/v1/rules/mine").json()
    assert len(proposals) == 1
    rule_id = proposals[0]["id"]
    assert proposals[0]["evidence"]["approvals"] == 40

    # Proposed rules do nothing until accepted.
    assert c.post("/v1/requests", json=invoice(32_000)).json()["status"] == "pending"

    assert c.post(f"/v1/rules/{rule_id}/accept?by=harshit").json()["status"] == "active"
    r = c.post("/v1/requests", json=invoice(32_000)).json()
    assert r["status"] == "auto_approved"
    assert r["receipt"]["rule"] == rule_id and r["receipt"]["accepted_by"] == "harshit"

    # Approved amounts were 30,000–33,900, so the rule caps at 33,900: anything above asks a human.
    assert c.post("/v1/requests", json=invoice(35_000)).json()["status"] == "pending"


def test_audit_verify_detects_tampering(tmp_path):
    c = client(tmp_path)
    rid = c.post("/v1/requests", json=invoice()).json()["id"]
    c.post(f"/v1/requests/{rid}/decision", json={"approved": True})
    assert c.get("/v1/audit/verify").json() == {"ok": True, "first_bad_seq": None, "entries": 2}

    # Tamper directly in the database.
    from yesrule.db import make_session_factory

    with make_session_factory(f"sqlite:///{tmp_path}/t.db")() as s:
        s.execute(update(AuditRow).where(AuditRow.seq == 1).values(data={"forged": True}))
        s.commit()
    assert c.get("/v1/audit/verify").json()["ok"] is False


def test_expired_request_cannot_be_approved(tmp_path):
    c = client(tmp_path)
    body = invoice() | {"timeout_s": 5}
    rid = c.post("/v1/requests", json=body).json()["id"]
    import datetime as dt

    import yesrule.service as svc

    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)
    svc_utcnow = svc.utcnow
    svc.utcnow = lambda: later
    try:
        r = c.post(f"/v1/requests/{rid}/decision", json={"approved": True})
    finally:
        svc.utcnow = svc_utcnow
    assert r.status_code == 409 and "expired" in r.json()["detail"]
