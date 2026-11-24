import datetime as dt

import yesrule.service as svc

from .conftest import invoice


def test_two_person_rule(app_client):
    c = app_client
    rid = c.post("/v1/requests", json=invoice(approvals_needed=2)).json()["id"]
    r = c.post(f"/v1/requests/{rid}/decision", json={"approved": True, "by": "a"}).json()
    assert r["status"] == "pending" and r["approvals_so_far"] == 1
    assert c.post(f"/v1/requests/{rid}/decision", json={"approved": True, "by": "a"}).status_code == 409  # same person
    r = c.post(f"/v1/requests/{rid}/decision", json={"approved": True, "by": "b"}).json()
    assert r["status"] == "approved" and r["approvals_so_far"] == 2


def test_one_deny_ends_multi_approval(app_client):
    c = app_client
    rid = c.post("/v1/requests", json=invoice(approvals_needed=3)).json()["id"]
    c.post(f"/v1/requests/{rid}/decision", json={"approved": True, "by": "a"})
    assert c.post(f"/v1/requests/{rid}/decision", json={"approved": False, "by": "b"}).json()["status"] == "denied"


def test_hard_line_always_asks(app_client):
    c = app_client
    assert c.post("/v1/hard-lines", json={"id": "H-1", "description": "never auto for acme",
                                          "conditions": [{"field": "client", "op": "eq", "value": "acme"}]}
                  ).status_code == 201
    assert c.post("/v1/hard-lines", json={"id": "H-2", "conditions": []}).status_code == 400
    assert c.post("/v1/hard-lines", json={"id": "H-3", "conditions": [{"field": "a", "op": "regex", "value": 1}]}
                  ).status_code == 400
    r = c.post("/v1/requests", json=invoice()).json()
    assert r["status"] == "pending" and "never auto for acme" in r["reason"]
    assert [h["id"] for h in c.get("/v1/hard-lines").json()] == ["H-1"]
    c.delete("/v1/hard-lines/H-1")
    assert c.get("/v1/hard-lines").json() == []


def _train(c, monkeypatch, n=40):
    base = dt.datetime(2026, 11, 1, 9, tzinfo=dt.UTC)
    for i in range(n):
        m = base + dt.timedelta(days=i % 4, minutes=i)
        monkeypatch.setattr(svc, "utcnow", lambda m=m: m)
        rid = c.post("/v1/requests", json=invoice(30_000 + i * 100)).json()["id"]
        c.post(f"/v1/requests/{rid}/decision", json={"approved": True, "by": "harshit"})
    monkeypatch.undo()
    rule_id = c.post("/v1/rules/mine").json()[0]["id"]
    c.post(f"/v1/rules/{rule_id}/accept")
    return rule_id


def test_flag_pauses_rule_and_counts_as_denial(app_client, monkeypatch):
    c = app_client
    rule_id = _train(c, monkeypatch)
    rid = c.post("/v1/requests", json=invoice(31_000)).json()["id"]
    assert c.get(f"/v1/requests/{rid}").json()["status"] == "auto_approved"
    r = c.post(f"/v1/requests/{rid}/flag", json={"by": "harshit", "note": "wrong client"}).json()
    assert r["rule_paused"] is True
    rules = {x["id"]: x for x in c.get("/v1/rules").json()}
    assert rules[rule_id]["status"] == "paused"
    assert c.post("/v1/requests", json=invoice(31_000)).json()["status"] == "pending"  # paused rule is inert
    assert c.post("/v1/rules/mine").json() == []  # the denial now blocks re-proposal of the same shape
    assert c.get(f"/v1/rules/{rule_id}/backtest").json()["passed"] is False


def test_cannot_flag_human_decision(app_client):
    c = app_client
    rid = c.post("/v1/requests", json=invoice()).json()["id"]
    assert c.post(f"/v1/requests/{rid}/flag", json={}).status_code == 409


def test_mine_twice_does_not_duplicate(app_client, monkeypatch):
    c = app_client
    _train(c, monkeypatch)
    assert c.post("/v1/rules/mine").json() == []


def test_bad_rule_action_and_unknown_rule(app_client):
    assert app_client.post("/v1/rules/R-1/explode").status_code == 400
    assert app_client.post("/v1/rules/R-404/accept").status_code == 409
    assert app_client.get("/v1/rules/R-404/backtest").status_code == 404


def test_insights_and_client_report(app_client, monkeypatch):
    c = app_client
    _train(c, monkeypatch)
    c.post("/v1/requests", json=invoice(31_000))
    ins = c.get("/v1/insights").json()
    assert ins["total_requests"] == 41 and ins["by_status"]["auto_approved"] == 1
    assert ins["rules"]["active"] == 1 and ins["agents"]["invoice-bot"]["requests"] == 41
    rep = c.get("/v1/reports/client/acme").json()
    assert rep["requests"] == 41 and rep["approved_by_rule"] == 1 and rep["approved_by_person"] == 40
    assert rep["audit_chain_ok"] is True
    assert c.get("/v1/reports/client/acme?month=1999-01").json()["requests"] == 0


def test_validation_rejects_bad_requests(app_client):
    c = app_client
    assert c.post("/v1/requests", json=invoice(-5)).status_code == 422
    assert c.post("/v1/requests", json=invoice(timeout_s=1)).status_code == 422
    assert c.post("/v1/requests", json={"agent": "x"}).status_code == 422
    assert c.post("/v1/requests", json=invoice(platform="fax")).status_code == 422
    assert c.get("/v1/requests/nope").status_code == 404


def test_list_filters_and_audit_listing(app_client):
    c = app_client
    c.post("/v1/requests", json=invoice())
    c.post("/v1/requests", json=invoice(client="other"))
    assert len(c.get("/v1/requests?client=other").json()) == 1
    assert len(c.get("/v1/requests?status=pending").json()) == 2
    events = [e["event"] for e in c.get("/v1/audit").json()]
    assert events == ["request", "request"]


def test_dashboard_served(app_client):
    r = app_client.get("/")
    assert r.status_code == 200 and "Yesrule" in r.text
